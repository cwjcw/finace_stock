#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py — 发送与整合入口（真正推送在这里）
- 读取 config.yaml / users.yaml / .env
- 调用 finance_morning.generate_report() 生成 Markdown
- 按渠道发送：方糖 / Telegram / 企业微信
"""

import argparse
import os
from pathlib import Path
from typing import Dict, Tuple

import requests
from finance_morning import (
    BASE_DIR, CONFIG_PATH, USERS_PATH,
    load_yaml, generate_report
)

ENV_PATH = Path("/home/cwj/code/finace_stock/.env")

# ---------- 加载 .env（仅 KEY=VAL 简单格式） ----------
def load_env(path: Path) -> Dict[str, str]:
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if (not s) or s.startswith("#") or ("=" not in s):
                continue
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    # 操作系统环境变量优先（便于临时覆盖）
    env.update({k: os.environ[k] for k in os.environ})
    return env

def get_secret(secrets: dict, envmap: dict, key: str, default: str="") -> str:
    """
    支持 "env:VAR" 从 envmap 取变量；否则用明文
    """
    val = (secrets or {}).get(key, "")
    if isinstance(val, str) and val.startswith("env:"):
        return envmap.get(val.split(":",1)[1].strip(), default)
    return val or default

# ---------- 发送实现 ----------
def push_serverchan(sendkey: str, title: str, markdown: str) -> Tuple[int,str]:
    if not sendkey:
        return (0, "No SendKey")
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    r = requests.post(url, data={"text": title, "desp": markdown}, timeout=12)
    return (r.status_code, r.text)

def push_telegram(bot_token: str, chat_id: str, title: str, markdown: str) -> Tuple[int,str]:
    if not bot_token or not chat_id:
        return (0, "No TG creds")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    text = f"{title}\n\n{markdown}"
    r = requests.post(url, json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True}, timeout=15)
    return (r.status_code, r.text)

def push_wecom(webhook: str, title: str, markdown: str) -> Tuple[int,str]:
    if not webhook:
        return (0, "No WeCom webhook")
    payload = {"msgtype":"markdown","markdown":{"content": f"**{title}**\n\n{markdown}"}}
    r = requests.post(webhook, json=payload, timeout=12)
    return (r.status_code, r.text)

# ---------- 主流程 ----------
def parse_args():
    ap = argparse.ArgumentParser(description="早报发送入口（会真正推送）")
    ap.add_argument("--user", help="只发送给指定用户（users.yaml 的 id）")
    return ap.parse_args()

def main():
    args = parse_args()
    defaults = load_yaml(CONFIG_PATH)
    users_cfg = load_yaml(USERS_PATH)
    envmap    = load_env(ENV_PATH)

    if users_cfg.get("users"):
        users = users_cfg["users"]
        if args.user:
            users = [u for u in users if str(u.get("id","")) == args.user]
            if not users:
                print(f"未找到用户 id='{args.user}'")
                raise SystemExit(2)

        results = []
        for u in users:
            uid   = u.get("id","user")
            uname = u.get("name") or uid
            md, meta = generate_report(u, defaults)
            title = f"每日财经早报 | {meta['gen_time']}"

            ch = (u.get("channel") or "serverchan").lower()
            secrets = u.get("secrets") or {}

            if ch == "serverchan":
                sendkey = get_secret(secrets, envmap, "SCT_SENDKEY", "")
                code, text = push_serverchan(sendkey, title, md)
                print(f"[{uid}:serverchan] resp={code} {str(text)[:200]}...")
                results.append(code)
            elif ch == "telegram":
                token  = get_secret(secrets, envmap, "BOT_TOKEN", "")
                chatid = get_secret(secrets, envmap, "CHAT_ID", "")
                code, text = push_telegram(token, chatid, title, md)
                print(f"[{uid}:telegram] resp={code} {str(text)[:200]}...")
                results.append(code)
            elif ch == "wecom":
                webhook = get_secret(secrets, envmap, "WEBHOOK", "")
                code, text = push_wecom(webhook, title, md)
                print(f"[{uid}:wecom] resp={code} {str(text)[:200]}...")
                results.append(code)
            else:
                print(f"[{uid}] 未知渠道：{ch}（未发送）")

        ok = sum(1 for c in results if int(c) == 200)
        print(f"\nDone. success={ok}/{len(results)}")
    else:
        # 单用户兼容（无 users.yaml）
        u = {"id":"single","name":"single","channel":"serverchan","secrets":{"SCT_SENDKEY":"env:SCT_SENDKEY"}}
        md, meta = generate_report(u, defaults)
        title = f"每日财经早报 | {meta['gen_time']}"
        sendkey = get_secret(u["secrets"], envmap, "SCT_SENDKEY", "")
        code, text = push_serverchan(sendkey, title, md)
        print(f"[single:serverchan] resp={code} {str(text)[:200]}...")

if __name__ == "__main__":
    main()
