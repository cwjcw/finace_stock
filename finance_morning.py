import os, io, math, yaml, pytz, requests, feedparser, pandas as pd
from datetime import datetime
from typing import List, Dict
import akshare as ak

BASE_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
USERS_PATH  = os.path.join(BASE_DIR, "users.yaml")
ENV_PATH    = os.path.join(BASE_DIR, ".env")

# ---------- 工具 ----------
def load_yaml(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def load_env(path: str) -> Dict[str, str]:
    env = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if (not line) or line.startswith("#") or ("=" not in line):
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    # 系统环境变量优先
    env.update({k: os.environ[k] for k in os.environ})
    return env

def pct(x):
    try: return f"{x:.2f}%"
    except: return "-"

def now_str(tzname: str):
    return datetime.now(pytz.timezone(tzname)).strftime("%Y-%m-%d %H:%M")

def get_secret(secrets: dict, envmap: dict, key: str, default: str="") -> str:
    """secrets 里允许写 env:VAR_NAME，从 envmap 取值；也支持明文（不推荐）"""
    val = (secrets or {}).get(key, "")
    if isinstance(val, str) and val.startswith("env:"):
        envkey = val.split(":",1)[1].strip()
        return envmap.get(envkey, default)
    return val or default

# ---------- 数据 ----------
def fetch_index_snapshot():
    """三大指数：上证(000001) 深成(399001) 创业板(399006)"""
    try:
        df = ak.stock_zh_index_spot()
        targets = {"000001": "上证指数", "399001": "深证成指", "399006": "创业板指"}
        out = []
        for code, name in targets.items():
            row = df[df['代码'] == code]
            if not row.empty:
                r = row.iloc[0]
                out.append({
                    "name": name,
                    "price": float(r.get("最新价", math.nan)),
                    "change_pct": float(str(r.get("涨跌幅","0")).replace("%","") or 0.0)
                })
        return out
    except Exception:
        return [{"name":"上证指数","price":math.nan,"change_pct":math.nan},
                {"name":"深证成指","price":math.nan,"change_pct":math.nan},
                {"name":"创业板指","price":math.nan,"change_pct":math.nan}]

def fetch_north_money():
    """北向资金净流入（亿元）"""
    try:
        df = ak.stock_hsgt_north_net_flow_in()
        if df is not None and not df.empty:
            last = df.iloc[-1]
            date = str(last.get("日期") or last.get("date") or "")
            val = last.get("北向资金") or last.get("north_money") or last.get("北向资金净流入")
            try: val = float(val)
            except: val = None
            return {"date": date, "north_net_in": val}
    except Exception:
        pass
    return {"date": "", "north_net_in": None}

def fetch_watchlist(codes: List[str]):
    """自选股快照（从全市场快照中过滤）"""
    try:
        if not codes: return []
        df = ak.stock_zh_a_spot()
        df = df[df["代码"].isin(codes)]
        res = []
        for _, r in df.iterrows():
            try:
                res.append({
                    "code": str(r.get("代码","")),
                    "name": str(r.get("名称","")),
                    "price": float(r.get("最新价", math.nan)),
                    "change_pct": float(str(r.get("涨跌幅","0")).replace("%","") or 0.0)
                })
            except:
                continue
        return sorted(res, key=lambda x: abs(x.get("change_pct") or 0), reverse=True)
    except Exception:
        return []

def fetch_rss(feeds: List[str], limit_per_feed: int = 6):
    items = []
    for url in feeds or []:
        try:
            d = feedparser.parse(url)
            cnt = 0
            for e in d.entries:
                title = getattr(e, "title", "(no title)")
                link = getattr(e, "link", "")
                pub  = getattr(e, "published", getattr(e, "updated", ""))
                items.append({"source": url, "title": title.strip(), "link": link, "time": pub})
                cnt += 1
                if cnt >= limit_per_feed: break
        except:
            continue
    return items

# ---------- 渲染 ----------
def render_markdown(gen_time, idx, north, watchlist, rss_items, username=""):
    s = io.StringIO()
    title_prefix = f"{username}的" if username else ""
    s.write(f"# 📈 {title_prefix}每日财经早报（{gen_time}）\n\n")

    s.write("## 大盘速览\n")
    for x in idx:
        cp = x.get("change_pct")
        arrow = "🔺" if (isinstance(cp,(int,float)) and cp>=0) else "🔻"
        price = f"{x.get('price'):.2f}" if isinstance(x.get('price'),(int,float)) else "-"
        cp_str = pct(cp) if isinstance(cp,(int,float)) else "-"
        s.write(f"- {x['name']}：{price}（{arrow} {cp_str}）\n")
    s.write("\n")

    s.write("## 北向资金\n")
    if north.get("north_net_in") is not None:
        sign = "🔺净流入" if north["north_net_in"] >= 0 else "🔻净流出"
        s.write(f"- {north.get('date','')}: {sign} **{north['north_net_in']:.2f} 亿元**\n\n")
    else:
        s.write("- 数据暂不可用\n\n")

    if watchlist:
        s.write("## 自选股动向\n")
        for r in watchlist:
            cp = r.get("change_pct")
            arrow = "🔺" if (isinstance(cp,(int,float)) and cp>=0) else "🔻"
            price = f"{r.get('price'):.2f}" if isinstance(r.get('price'),(int,float)) else "-"
            cp_str = pct(cp) if isinstance(cp,(int,float)) else "-"
            s.write(f"- {r['name']}({r['code']})：{price}（{arrow} {cp_str}）\n")
        s.write("\n")

    if rss_items:
        s.write("## 新闻速读（精选）\n")
        for it in rss_items:
            t = it["title"].replace("\n"," ").strip()
            s.write(f"- [{t}]({it['link']})\n")
        s.write("\n")

    s.write("> 数据来源：交易所/公开RSS/akshare。仅作信息参考，不构成投资建议。\n")
    return s.getvalue()

# ---------- 推送 ----------
def push_serverchan(sendkey: str, title: str, markdown: str):
    if not sendkey:
        return (0, "No SendKey")
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    data = {"text": title, "desp": markdown}
    r = requests.post(url, data=data, timeout=12)
    return (r.status_code, r.text)

def push_telegram(bot_token: str, chat_id: str, title: str, markdown: str):
    if not bot_token or not chat_id:
        return (0, "No TG creds")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    text = f"{title}\n\n{markdown}"
    r = requests.post(url, json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True})
    return (r.status_code, r.text)

def push_wecom(webhook: str, title: str, markdown: str):
    if not webhook:
        return (0, "No WeCom webhook")
    payload = {"msgtype":"markdown","markdown":{"content": f"**{title}**\n\n{markdown}"}}
    r = requests.post(webhook, json=payload, timeout=12)
    return (r.status_code, r.text)

# ---------- 主流程（单用户或多用户） ----------
def run_for_user(u: dict, defaults: dict, envmap: dict):
    uname   = u.get("name") or u.get("id","")
    tzname  = u.get("timezone") or defaults.get("timezone","Asia/Shanghai")
    wl      = u.get("watchlist") or defaults.get("watchlist",[])
    feeds   = u.get("rss_feeds") if u.get("rss_feeds") else defaults.get("rss_feeds",[])
    rss_lim = int(defaults.get("rss_limit", 6))

    gen_time = now_str(tzname)
    idx   = fetch_index_snapshot()
    north = fetch_north_money()
    wlist = fetch_watchlist(wl)
    rss   = fetch_rss(feeds, limit_per_feed=rss_lim)
    md    = render_markdown(gen_time, idx, north, wlist, rss, username=uname)
    title = f"每日财经早报 | {gen_time}"

    ch = (u.get("channel") or "serverchan").lower()
    secrets = u.get("secrets") or {}

    if ch == "serverchan":
        sendkey = get_secret(secrets, envmap, "SCT_SENDKEY", "")
        return ("serverchan", *push_serverchan(sendkey, title, md))
    elif ch == "telegram":
        token  = get_secret(secrets, envmap, "BOT_TOKEN", "")
        chatid = get_secret(secrets, envmap, "CHAT_ID", "")
        return ("telegram", *push_telegram(token, chatid, title, md))
    elif ch == "wecom":
        hook = get_secret(secrets, envmap, "WEBHOOK", "")
        return ("wecom", *push_wecom(hook, title, md))
    else:
        print(f"[{uname}] 未知推送渠道：{ch}\n")
        print(md)
        return (ch, 0, "Unknown channel, printed to stdout")

def main():
    defaults = load_yaml(CONFIG_PATH)
    users_cfg = load_yaml(USERS_PATH)
    envmap = load_env(ENV_PATH)

    if users_cfg.get("users"):
        results = []
        for u in users_cfg["users"]:
            ch, code, text = run_for_user(u, defaults, envmap)
            uid = u.get("id","")
            print(f"[{uid}:{ch}] resp={code} {text[:200]}...")
            results.append((uid, ch, code))
        ok = sum(1 for _,_,c in results if int(c) == 200)
        print(f"\nDone. success={ok}/{len(results)}")
    else:
        # 兼容：没有 users.yaml 时走单用户方糖（读环境变量 SCT_SENDKEY）
        gen_time = now_str(defaults.get("timezone","Asia/Shanghai"))
        idx   = fetch_index_snapshot()
        north = fetch_north_money()
        wlist = fetch_watchlist(defaults.get("watchlist",[]))
        rss   = fetch_rss(defaults.get("rss_feeds",[]), limit_per_feed=int(defaults.get("rss_limit",6)))
        md    = render_markdown(gen_time, idx, north, wlist, rss)
        title = f"每日财经早报 | {gen_time}"
        sendkey = os.getenv("SCT_SENDKEY","").strip() or load_env(ENV_PATH).get("SCT_SENDKEY","")
        if sendkey:
            code, text = push_serverchan(sendkey, title, md)
            print(f"[single:serverchan] resp={code} {text[:200]}...")
        else:
            print(md)
            print("\n[未配置 SendKey，已输出到控制台]")

if __name__ == "__main__":
    main()
