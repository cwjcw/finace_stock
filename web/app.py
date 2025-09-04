# /web/app.py
import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import SQLModel, create_engine, Session, select
from passlib.hash import bcrypt

# 关键：相对路径更稳
THIS_DIR = Path(__file__).resolve().parent            # .../finace_stock/web
PROJECT_ROOT = THIS_DIR.parent                        # .../finace_stock
DB_PATH = THIS_DIR / "app.db"
USERS_YAML = PROJECT_ROOT / "users.yaml"
CONFIG_YAML = PROJECT_ROOT / "config.yaml"

# 包内相对导入（配合 uvicorn web.app:app）
from .models import User, Watch, Rss

app = FastAPI(debug=True)  # 打开调试，若有模板/导入错误，浏览器会显示详细报错
app.mount("/static", StaticFiles(directory=str(THIS_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(THIS_DIR / "templates"))

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

# ---- 初始化 ----
def init_db():
    THIS_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)
init_db()

# ---- 简易会话（演示用）----
SESSION: dict[str, str] = {}  # session_id -> uid

def current_user(request: Request) -> Optional[User]:
    sid = request.cookies.get("sid")
    if not sid or sid not in SESSION:
        return None
    uid = SESSION[sid]
    with Session(engine) as s:
        return s.exec(select(User).where(User.uid == uid)).first()

def login_user(response: Response, uid: str):
    import secrets
    sid = secrets.token_urlsafe(24)
    SESSION[sid] = uid
    response.set_cookie("sid", sid, httponly=True, max_age=7*24*3600, samesite="lax")

def logout_user(response: Response):
    response.delete_cookie("sid")

# ---- 工具 ----
def norm_code(code: str) -> str:
    if not code: return ""
    s = code.strip().lower()
    m = re.search(r"(\d{6})", s)
    if not m: return ""
    x = m.group(1)
    if s.startswith("sh"): return "sh"+x
    if s.startswith("sz"): return "sz"+x
    if x.startswith(("600","601","603","605","688","689","900")): return "sh"+x
    return "sz"+x

def export_users_yaml():
    import yaml, os
    data = {"users": []}
    with Session(engine) as s:
        users = s.exec(select(User)).all()
        for u in users:
            w = s.exec(select(Watch).where(Watch.user_id == u.id)).all()
            r = s.exec(select(Rss).where(Rss.user_id == u.id)).all()
            entry = {
                "id": u.uid,
                "name": u.name,
                "timezone": u.timezone,
                "channel": u.channel,
                "secrets": {},
                "watchlist": [i.code for i in w],
                "rss_feeds": [i.url for i in r],
            }
            if u.channel == "serverchan" and u.sct_sendkey:
                entry["secrets"]["SCT_SENDKEY"] = u.sct_sendkey
            if u.channel == "telegram":
                if u.tg_bot_token: entry["secrets"]["BOT_TOKEN"] = u.tg_bot_token
                if u.tg_chat_id:   entry["secrets"]["CHAT_ID"]   = u.tg_chat_id
            if u.channel == "wecom" and u.wecom_webhook:
                entry["secrets"]["WEBHOOK"] = u.wecom_webhook
            data["users"].append(entry)
    USERS_YAML.write_text(
        __import__("yaml").safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8"
    )
    try:
        os.chmod(USERS_YAML, 0o600)
    except Exception:
        pass

# ---- 基础路由 ----
@app.get("/health")
def health():
    return {"ok": True}

@app.get("/", response_class=HTMLResponse)
def index(request: Request, me: Optional[User] = Depends(current_user)):
    if me:
        return RedirectResponse("/dashboard", 302)
    return RedirectResponse("/login", 302)

# ---- 注册/登录 ----
@app.get("/register", response_class=HTMLResponse)
def register_get(request: Request):
    return templates.TemplateResponse("register.html", {"request": request, "error": ""})

@app.post("/register", response_class=HTMLResponse)
def register_post(
    request: Request,
    uid: str = Form(...),
    name: str = Form(...),
    password: str = Form(...),
):
    uid = uid.strip()
    if not re.fullmatch(r"[a-zA-Z0-9_\-]{2,32}", uid):
        return templates.TemplateResponse("register.html", {"request": request, "error": "ID 仅限2-32位字母数字-_"})
    from sqlmodel import Session, select
    with Session(engine) as s:
        if s.exec(select(User).where(User.uid == uid)).first():
            return templates.TemplateResponse("register.html", {"request": request, "error": "ID 已存在"})
        user = User(uid=uid, name=name.strip() or uid, password_hash=bcrypt.hash(password))
        s.add(user); s.commit()
    resp = RedirectResponse("/dashboard", 302)
    login_user(resp, uid)
    export_users_yaml()
    return resp

@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": ""})

@app.post("/login", response_class=HTMLResponse)
def login_post(request: Request, uid: str = Form(...), password: str = Form(...)):
    from sqlmodel import Session, select
    with Session(engine) as s:
        user = s.exec(select(User).where(User.uid == uid)).first()
        if not user or not bcrypt.verify(password, user.password_hash):
            return templates.TemplateResponse("login.html", {"request": request, "error": "账号或密码错误"})
    resp = RedirectResponse("/dashboard", 302)
    login_user(resp, uid)
    return resp

@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", 302)
    logout_user(resp)
    return resp

# ---- 仪表盘 & 配置 ----
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, me: Optional[User] = Depends(current_user)):
    if not me: return RedirectResponse("/login", 302)
    with Session(engine) as s:
        me = s.exec(select(User).where(User.id == me.id)).first()
        wlist = s.exec(select(Watch).where(Watch.user_id == me.id)).all()
        rss = s.exec(select(Rss).where(Rss.user_id == me.id)).all()
    return templates.TemplateResponse("dashboard.html", {"request": request, "me": me, "wlist": wlist, "rss": rss})

@app.post("/profile")
def update_profile(
    request: Request,
    timezone: str = Form(...),
    channel: str = Form(...),
    sct_sendkey: str = Form(""),
    tg_bot_token: str = Form(""),
    tg_chat_id: str = Form(""),
    wecom_webhook: str = Form(""),
    me: Optional[User] = Depends(current_user)
):
    if not me: return RedirectResponse("/login", 302)
    with Session(engine) as s:
        u = s.exec(select(User).where(User.id == me.id)).first()
        u.timezone = timezone.strip() or u.timezone
        u.channel = channel
        u.sct_sendkey = sct_sendkey.strip() or None
        u.tg_bot_token = tg_bot_token.strip() or None
        u.tg_chat_id = tg_chat_id.strip() or None
        u.wecom_webhook = wecom_webhook.strip() or None
        s.add(u); s.commit()
    export_users_yaml()
    return RedirectResponse("/dashboard", 302)

@app.post("/watch/add")
def add_watch(code: str = Form(...), me: Optional[User] = Depends(current_user)):
    if not me: return RedirectResponse("/login", 302)
    code = norm_code(code)
    if not code: raise HTTPException(400, "无效代码")
    with Session(engine) as s:
        s.add(Watch(user_id=me.id, code=code)); s.commit()
    export_users_yaml()
    return RedirectResponse("/dashboard", 302)

@app.post("/watch/del/{wid}")
def del_watch(wid: int, me: Optional[User] = Depends(current_user)):
    if not me: return RedirectResponse("/login", 302)
    with Session(engine) as s:
        w = s.get(Watch, wid)
        if w and w.user_id == me.id:
            s.delete(w); s.commit()
    export_users_yaml()
    return RedirectResponse("/dashboard", 302)

@app.post("/rss/add")
def add_rss(url: str = Form(...), me: Optional[User] = Depends(current_user)):
    if not me: return RedirectResponse("/login", 302)
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(400, "RSS 必须是 http/https 链接")
    with Session(engine) as s:
        s.add(Rss(user_id=me.id, url=url)); s.commit()
    export_users_yaml()
    return RedirectResponse("/dashboard", 302)

@app.post("/rss/del/{rid}")
def del_rss(rid: int, me: Optional[User] = Depends(current_user)):
    if not me: return RedirectResponse("/login", 302)
    with Session(engine) as s:
        r = s.get(Rss, rid)
        if r and r.user_id == me.id:
            s.delete(r); s.commit()
    export_users_yaml()
    return RedirectResponse("/dashboard", 302)

@app.get("/preview", response_class=HTMLResponse)
def preview(request: Request, me: Optional[User] = Depends(current_user)):
    if not me: return RedirectResponse("/login", 302)
    from finance_morning import load_yaml as fm_load, generate_report
    defaults = fm_load(CONFIG_YAML)
    with Session(engine) as s:
        u = s.exec(select(User).where(User.id == me.id)).first()
        wl = [w.code for w in s.exec(select(Watch).where(Watch.user_id == me.id)).all()]
        rs = [r.url for r in s.exec(select(Rss).where(Rss.user_id == me.id)).all()]
    u_dict = {"id": u.uid, "name": u.name, "timezone": u.timezone, "watchlist": wl, "rss_feeds": rs}
    md, meta = generate_report(u_dict, defaults)
    return templates.TemplateResponse("base.html", {"request": request, "content": f"<pre>{md}</pre>"})
