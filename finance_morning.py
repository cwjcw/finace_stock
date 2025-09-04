#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
finance_morning.py — 数据抓取 + 渲染模块（含“测试/预览”，绝不发送）
- 读取 config.yaml / users.yaml
- 抓取：大盘（AkShare + 新浪兜底）、北向、自选股、RSS
- 渲染：输出 Markdown
- CLI（仅测试）：打印并保存到 out/，不发送
"""

import argparse
import io
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import akshare as ak
import feedparser
import pytz
import requests
import yaml

# 路径按你的项目
BASE_DIR = Path("/home/cwj/code/finace_stock").resolve()
CONFIG_PATH = BASE_DIR / "config.yaml"
USERS_PATH  = BASE_DIR / "users.yaml"

# ---------- 基础加载 ----------
def load_yaml(path: Path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}

def pct(x) -> str:
    try:
        return f"{x:.2f}%"
    except Exception:
        return "-"

def now_str(tzname: str) -> str:
    import pytz
    return datetime.now(pytz.timezone(tzname)).strftime("%Y-%m-%d %H:%M")

def normalize_to_prefixed(code_like: str) -> str:
    """
    任意形态 -> 带前缀：sh600519 / sz000858
    """
    if not code_like:
        return ""
    s = str(code_like).strip().lower()
    m = re.search(r"(\d{6})", s)
    if not m:
        return ""
    x = m.group(1)
    if s.startswith("sh"):
        return "sh" + x
    if s.startswith("sz"):
        return "sz" + x
    if x.startswith(("600","601","603","605","688","689","900")):
        return "sh" + x
    return "sz" + x

def pick_user_value(user: dict, defaults: dict, key: str, fallback=None):
    """
    存在就用用户字段（哪怕是空列表/空字符串），否则用全局，最后 fallback
    """
    if key in user:
        return user[key]
    if key in defaults:
        return defaults[key]
    return fallback

# ---------- 大盘（AkShare + 新浪兜底） ----------
def _fetch_index_snapshot_ak() -> List[dict]:
    df = ak.stock_zh_index_spot()
    if df is None or df.empty or ("代码" not in df.columns):
        return []
    df = df.copy()
    df["code6"] = df["代码"].astype(str).str.extract(r"(\d{6})")
    targets = {"000001": "上证指数", "399001": "深证成指", "399006": "创业板指"}
    out = []
    for code6, name in targets.items():
        row = df[df["code6"] == code6]
        if row.empty:
            continue
        r = row.iloc[0]
        try:
            price = float(r.get("最新价", math.nan))
            chg   = float(str(r.get("涨跌幅","0")).replace("%","") or 0.0)
        except Exception:
            price, chg = math.nan, math.nan
        out.append({"name": name, "price": price, "change_pct": chg})
    return out

def _fetch_index_snapshot_sina() -> List[dict]:
    items = [
        ("上证指数", "s_sh000001"),
        ("深证成指", "s_sz399001"),
        ("创业板指", "s_sz399006"),
    ]
    url = "https://hq.sinajs.cn/?list=" + ",".join(code for _, code in items)
    headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=8)
    text = resp.content.decode("gbk", errors="ignore")
    out = []
    for (expected, _), line in zip(items, text.strip().splitlines()):
        m = re.search(r'="([^"]*)"', line)
        if not m:
            continue
        parts = m.group(1).split(",")
        try:
            price = float(parts[1]) if parts[1] else math.nan
            cpct  = float(parts[3].replace("%","")) if len(parts)>3 and parts[3] else math.nan
            out.append({"name": expected, "price": price, "change_pct": cpct})
        except Exception:
            continue
    return out

def fetch_index_snapshot() -> List[dict]:
    try:
        out = _fetch_index_snapshot_ak()
        if len(out) == 3 and all(isinstance(x.get("price"), (int,float)) and not math.isnan(x["price"]) for x in out):
            return out
    except Exception:
        pass
    try:
        return _fetch_index_snapshot_sina()
    except Exception:
        return [
            {"name":"上证指数","price":math.nan,"change_pct":math.nan},
            {"name":"深证成指","price":math.nan,"change_pct":math.nan},
            {"name":"创业板指","price":math.nan,"change_pct":math.nan},
        ]

# ---------- 其它数据 ----------
def fetch_north_money() -> dict:
    try:
        df = ak.stock_hsgt_north_net_flow_in()
        if df is not None and not df.empty:
            last = df.iloc[-1]
            date = str(last.get("日期") or last.get("date") or "")
            val  = last.get("北向资金") or last.get("north_money") or last.get("北向资金净流入")
            try: val = float(val)
            except Exception: val = None
            return {"date": date, "north_net_in": val}
    except Exception:
        pass
    return {"date": "", "north_net_in": None}

def fetch_watchlist(codes: List[str]) -> List[dict]:
    try:
        if codes is None:
            return []
        want = {normalize_to_prefixed(c) for c in codes if c}
        if not want:
            return []
        df = ak.stock_zh_a_spot()
        if df is None or df.empty or ("代码" not in df.columns):
            return []
        df = df.copy()
        df["code6"]     = df["代码"].astype(str).str.extract(r"(\d{6})")
        df["code_pref"] = df["code6"].apply(normalize_to_prefixed)
        df = df[df["code_pref"].isin(want)]
        res = []
        for _, r in df.iterrows():
            try:
                res.append({
                    "code":  str(r.get("code_pref","")),
                    "name":  str(r.get("名称","")),
                    "price": float(r.get("最新价", math.nan)),
                    "change_pct": float(str(r.get("涨跌幅","0")).replace("%","") or 0.0),
                })
            except Exception:
                continue
        return sorted(res, key=lambda x: abs(x.get("change_pct") or 0), reverse=True)
    except Exception:
        return []

def fetch_rss(feeds: List[str], limit_per_feed: int = 6) -> List[dict]:
    items = []
    for url in feeds or []:
        try:
            d = feedparser.parse(url)
            cnt = 0
            for e in d.entries:
                title = getattr(e, "title", "(no title)")
                link  = getattr(e, "link",  "")
                pub   = getattr(e, "published", getattr(e, "updated", ""))
                items.append({"source": url, "title": title.strip(), "link": link, "time": pub})
                cnt += 1
                if cnt >= limit_per_feed: break
        except Exception:
            continue
    return items

# ---------- 渲染 ----------
def render_markdown(gen_time: str, idx, north, watchlist, rss_items, username: str="") -> str:
    s = io.StringIO()
    pre = f"{username}的" if username else ""
    s.write(f"# 📈 {pre}每日财经早报（{gen_time}）\n\n")

    s.write("## 大盘速览\n")
    for x in idx:
        cp = x.get("change_pct")
        arrow  = "🔺" if (isinstance(cp,(int,float)) and cp>=0) else "🔻"
        price  = f"{x.get('price'):.2f}" if isinstance(x.get("price"),(int,float)) else "-"
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
            arrow  = "🔺" if (isinstance(cp,(int,float)) and cp>=0) else "🔻"
            price  = f"{r.get('price'):.2f}" if isinstance(r.get("price"),(int,float)) else "-"
            cp_str = pct(cp) if isinstance(cp,(int,float)) else "-"
            s.write(f"- {r['name']}({r['code']})：{price}（{arrow} {cp_str}）\n")
        s.write("\n")

    if rss_items:
        s.write("## 新闻速读（精选）\n")
        for it in rss_items:
            t = it["title"].replace("\n"," ").strip()
            s.write(f"- [{t}]({it['link']})\n")
        s.write("\n")

    s.write("> 数据来源：交易所/公开RSS/akshare/新浪。仅作信息参考，不构成投资建议。\n")
    return s.getvalue()

# ---------- 生成报告（主暴露函数） ----------
def generate_report(user: dict, defaults: dict) -> Tuple[str, dict]:
    """
    返回 (markdown, meta)
    meta 含：gen_time, tzname, watchlist_count 等
    """
    tzname = pick_user_value(user, defaults, "timezone", "Asia/Shanghai")
    wl     = pick_user_value(user, defaults, "watchlist", [])
    feeds  = pick_user_value(user, defaults, "rss_feeds", [])
    rslim  = int(pick_user_value(user, defaults, "rss_limit", 6))

    gen_time = now_str(tzname)
    idx   = fetch_index_snapshot()
    north = fetch_north_money()
    wlist = fetch_watchlist(wl)
    rss   = fetch_rss(feeds, limit_per_feed=rslim)
    md    = render_markdown(gen_time, idx, north, wlist, rss, username=user.get("name") or user.get("id",""))
    meta  = {"gen_time": gen_time, "tz": tzname, "watchlist_count": len(wlist), "rss_count": len(rss)}
    return md, meta

# =================== 仅用于“测试/预览”的 CLI ===================
def _save(out_dir: Path, uid: str, content: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    fn = out_dir / f"{uid}_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    fn.write_text(content, encoding="utf-8")
    return fn

if __name__ == "__main__":
    # 仅测试，不发送
    ap = argparse.ArgumentParser(description="预览/测试（不发送）")
    ap.add_argument("--user", help="只预览指定用户（users.yaml 的 id）")
    ap.add_argument("--out-dir", default=str(BASE_DIR / "out"), help="输出目录")
    args = ap.parse_args()

    defaults = load_yaml(CONFIG_PATH)
    users_cfg = load_yaml(USERS_PATH)
    out_dir = Path(args.out_dir)

    if users_cfg.get("users"):
        users = users_cfg["users"]
        if args.user:
            users = [u for u in users if str(u.get("id","")) == args.user]
            if not users:
                print(f"未找到用户 id='{args.user}'")
                raise SystemExit(2)
        for u in users:
            uid = u.get("id","user")
            md, meta = generate_report(u, defaults)
            print(f"\n===== [PREVIEW] {uid} ({meta['gen_time']}) =====\n")
            print(md)
            fn = _save(out_dir, uid, md)
            print(f"[PREVIEW] 已保存: {fn}")
    else:
        # 单用户兼容（没 users.yaml 也能预览）
        u = {"id":"single","name":"single"}
        md, meta = generate_report(u, defaults)
        print(f"\n===== [PREVIEW] single ({meta['gen_time']}) =====\n")
        print(md)
        fn = _save(out_dir, "single", md)
        print(f"[PREVIEW] 已保存: {fn}")
