#!/usr/bin/env python3
"""resolve_discord_webhook.py — Discord webhook URL を1チャネル解決して標準出力に返す。

config/discord_webhooks.json はプレースホルダー("${DISCORD_WEBHOOK_*}")を保持し、
実 URL は .env にある(設計: .gitignore 参照)。各 shell スクリプトが素の json.load
で読むと ${VAR} が未展開のまま curl に渡り、Discord で不正 URL=通知失敗になる
(既知バグ: discord-notify-placeholder-not-expanded)。

本ヘルパーは lib/discord_channels.sh::get_discord_webhook と同一ロジックを Python 側に
集約し、全 cron スクリプトが1行で安全に webhook を解決できるようにする。
未解決(プレースホルダーのまま / 未設定)なら空文字を返し、誤送信を防ぐ。

Usage:
    URL=$(python3 lib/resolve_discord_webhook.py urgent_errors)
    [ -n "$URL" ] && curl -s -X POST -H 'Content-Type: application/json' \
        -d "{\"content\":\"...\"}" "$URL"
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "discord_webhooks.json"
ENV = ROOT / ".env"


def _load_dotenv() -> None:
    if not ENV.exists():
        return
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k and k not in os.environ:
            os.environ[k] = v.strip().strip('"').strip("'")


def resolve(channel: str) -> str:
    _load_dotenv()
    try:
        with CONFIG.open() as f:
            d = json.load(f)
    except Exception:
        return ""
    val = (d.get(channel, "") or "").strip()
    exp = os.path.expandvars(val)
    # 未解決プレースホルダー("${...}" が残存)は空にして誤送信を防ぐ
    return "" if exp.startswith("${") or not exp else exp


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(0)
    sys.stdout.write(resolve(sys.argv[1]))
