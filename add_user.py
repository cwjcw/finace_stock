#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
add_user.py — 为“多用户财经早报系统”添加/更新用户的工具脚本

功能：
- 读取/创建 users.yaml，新增或更新某个用户的配置（时区/渠道/自选股/密钥映射）。
- 在 .env 里追加所需环境变量（占位，不覆盖已有值）。
- 将股票代码统一规范为带前缀（sh/sz）的 6 位格式（如 600519 -> sh600519，000858 -> sz000858）。

用法示例（命令行一次到位）：
  方糖（Server酱）：
    python add_user.py --id eva --name Eva \
      --channel serverchan \
      --timezone Asia/Shanghai \
      --watchlist sh600519 sz000858 sz300750 \
      --sendkey-env SCT_SENDKEY_EVA

  Telegram：
    python add_user.py --id jerry --name Jerry \
      --channel telegram \
      --timezone Europe/London \
      --watchlist sh600036 sz000858 \
      --bot-token-env TG_BOT_TOKEN \
      --chat-id-env TG_CHAT_ID_JERRY

  企业微信机器人：
    python add_user.py --id team --name 团队群 \
      --channel wecom \
      --watchlist sh601318 \
      --webhook-env WECOM_HOOK_TEAM

无参数时进入交互模式，一路按提示输入即可。
"""

import argparse
import os
import re
import sys
import yaml
from pathlib import Path

# === 按你的项目路径设置 ===
BASE = Path("/home/cwj/code/finace_stock")
USERS_YAML = BASE / "users.yaml"
ENV_FILE   = BASE / ".env"


# ---------------- 公共工具 ----------------
def load_users() -> dict:
    """读取 users.yaml，不存在则返回 {'users': []}"""
    if USERS_YAML.exists():
        with open(USERS_YAML, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}
    data.setdefault("users", [])
    return data


def dump_users(data: dict) -> None:
    """写回 users.yaml（保持中文/顺序/缩进友好）"""
    USERS_YAML.parent.mkdir(parents=True, exist_ok=True)
    with open(USERS_YAML, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, indent=2)


def load_env() -> dict:
    """读取 .env 为字典（不解析 export 语法，仅 KEY=VAL）"""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def append_env_if_absent(pairs: list[tuple[str, str]]) -> bool:
    """
    在 .env 末尾追加不存在的变量（占位值），不覆盖已有值。
    pairs: [(KEY, PLACEHOLDER), ...]
    返回：是否有改动
    """
    existing = load_env()
    lines = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    changed = False
    for k, v in pairs:
        if k not in existing:
            lines.append("")
            lines.append(f"# {k} for new user (fill the real value):")
            lines.append(f"{k}={v}")
            changed = True
    if changed:
        ENV_FILE.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        try:
            os.chmod(ENV_FILE, 0o600)
        except Exception:
            pass
    return changed


# ---------------- 代码规范化 ----------------
def normalize_to_prefixed(code_like: str) -> str:
    """
    将任意形态的 A 股代码规范为带前缀格式：
      - 'sh600519' / 'SZ000858' / '600519' / '000858' -> 'sh600519' / 'sz000858'
    规则：
      - 如果已有 sh/sz 前缀，按前缀返回（统一小写）。
      - 否则根据常见号段判定：600/601/603/605/688/689/900 -> 'sh'；其余 -> 'sz'
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
    if x.startswith(("600", "601", "603", "605", "688", "689", "900")):
        return "sh" + x
    return "sz" + x


# ---------------- 参数解析 ----------------
def parse_args():
    p = argparse.ArgumentParser(
        description="为多用户财经早报系统添加/更新一个用户"
    )
    p.add_argument("--id", help="用户唯一ID（必填，例如 eva）")
    p.add_argument("--name", help="显示名（默认与 id 相同）")
    p.add_argument("--channel", choices=["serverchan", "telegram", "wecom"],
                   help="推送渠道（serverchan/telegram/wecom），默认 serverchan")
    p.add_argument("--timezone", help="时区（默认继承全局），例如 Asia/Shanghai")
    p.add_argument("--watchlist", nargs="*", help="自选股，支持 600519/sh600519；多只用空格分隔")
    p.add_argument("--rss-feeds", nargs="*", help="仅该用户专属的 RSS（不填则继承全局）")
    # 各渠道的环境变量名字（写入 .env 的键名）
    p.add_argument("--sendkey-env", help="方糖环境变量名，默认 SCT_SENDKEY_<ID大写>")
    p.add_argument("--bot-token-env", help="Telegram Bot Token 变量名，默认 TG_BOT_TOKEN")
    p.add_argument("--chat-id-env", help="Telegram Chat ID 变量名，默认 TG_CHAT_ID_<ID大写>")
    p.add_argument("--webhook-env", help="企业微信 Webhook 变量名，默认 WECOM_HOOK_TEAM")

    args = p.parse_args()

    # 进入交互模式（未提供 --id 时）
    if not args.id:
        print("== 交互模式（亦可用 --id/--channel 等参数免交互）==")
        args.id = input("用户ID（必填，例 eva）：").strip()
        if not args.id:
            print("错误：ID 不能为空")
            sys.exit(1)
        args.name = input(f"显示名（默认 {args.id}）：").strip() or args.id
        ch = input("推送渠道 [serverchan/telegram/wecom]（默认 serverchan）：").strip().lower() or "serverchan"
        if ch not in ("serverchan", "telegram", "wecom"):
            print("错误：渠道无效"); sys.exit(1)
        args.channel = ch
        tz = input("时区（默认继承全局，例 Asia/Shanghai）：").strip()
        args.timezone = tz or None
        wl_raw = input("自选股（空格/逗号分隔，例 sh600519 sz000858）：").replace(",", " ").split()
        args.watchlist = wl_raw or None
        rf_raw = input("专属 RSS（留空则继承全局；多条空格/逗号分隔）：").replace(",", " ").split()
        args.rss_feeds = rf_raw or None

    return args


# ---------------- 主逻辑 ----------------
def main():
    args = parse_args()
    uid = args.id.strip()
    name = (args.name or uid).strip()
    channel = (args.channel or "serverchan").strip().lower()
    tz = args.timezone or None

    # 生成该用户默认的环境变量名
    upper = uid.upper()
    sendkey_env   = args.sendkey_env   or f"SCT_SENDKEY_{upper}"
    bot_token_env = args.bot_token_env or "TG_BOT_TOKEN"
    chat_id_env   = args.chat_id_env   or f"TG_CHAT_ID_{upper}"
    webhook_env   = args.webhook_env   or "WECOM_HOOK_TEAM"

    # 规范化 watchlist
    wl = None
    if args.watchlist is not None:
        wl = []
        for c in args.watchlist:
            norm = normalize_to_prefixed(c)
            if norm:
                wl.append(norm)

    # 组装用户条目（只写明确信息；rss_feeds 不给则继承全局）
    user_entry = {"id": uid, "name": name, "channel": channel}
    if tz:
        user_entry["timezone"] = tz
    if wl is not None:
        user_entry["watchlist"] = wl

    # secrets：按渠道写 env 映射
    secrets = {}
    env_pairs = []  # [(KEY, PLACEHOLDER)]
    if channel == "serverchan":
        secrets["SCT_SENDKEY"] = f"env:{sendkey_env}"
        env_pairs = [(sendkey_env, "")]
    elif channel == "telegram":
        secrets["BOT_TOKEN"] = f"env:{bot_token_env}"
        secrets["CHAT_ID"]   = f"env:{chat_id_env}"
        env_pairs = [(bot_token_env, ""), (chat_id_env, "")]
    elif channel == "wecom":
        secrets["WEBHOOK"] = f"env:{webhook_env}"
        env_pairs = [(webhook_env, "")]
    else:
        print("错误：未知渠道"); sys.exit(1)
    user_entry["secrets"] = secrets

    # 专属 RSS：仅在显式提供时写入；否则继承全局 config.yaml
    if args.rss_feeds is not None:
        user_entry["rss_feeds"] = args.rss_feeds

    # 读取/更新 users.yaml
    data = load_users()
    users = data["users"]
    for i, u in enumerate(users):
        if str(u.get("id", "")) == uid:
            # 更新已有用户（浅合并）
            users[i].update(user_entry)
            break
    else:
        # 追加新用户
        users.append(user_entry)
    dump_users(data)

    # 追加 .env 占位（若不存在）
    changed_env = append_env_if_absent(env_pairs)

    print(f"✅ 用户 '{uid}' 已写入 {USERS_YAML}")
    if changed_env:
        print(f"✅ 已在 {ENV_FILE} 追加环境变量占位：{', '.join(k for k, _ in env_pairs)}")
        print("   请打开 .env 填入真实值后即可生效（定时任务会在下次触发时自动使用）。")
    else:
        print(f"ℹ️ 变量已存在于 {ENV_FILE}，未修改。")

    print("\n👉 立刻测试（示例）：")
    print("   source /home/cwj/code/finace_stock/.venv/bin/activate && python /home/cwj/code/finace_stock/finance_morning.py")


if __name__ == "__main__":
    main()