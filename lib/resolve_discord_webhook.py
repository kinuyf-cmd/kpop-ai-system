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
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "discord_webhooks.json"
ENV = ROOT / ".env"

# Discord/Cloudflare は既定の python-urllib UA を error code 1010(HTTP 403)で
# ブロックする。webhook 送信側はこの UA を付けること(1箇所に集約=DRY)。
DISCORD_USER_AGENT = "Mozilla/5.0 (compatible; KpopJournalBot/1.0)"

# 未展開プレースホルダー検出: "${VAR}" / "$VAR" の両形式を弾く。
_UNEXPANDED_RE = re.compile(r"\$\{?\w")
# 正当な webhook URL のみ許可(config 汚染時に任意 URL へ POST しない深層防御)。
_WEBHOOK_PREFIX = "https://discord.com/api/webhooks/"


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
    # 未解決プレースホルダー("${VAR}" / "$VAR")が残存していれば空にして誤送信を防ぐ。
    if not exp or _UNEXPANDED_RE.search(exp):
        return ""
    # 正当な Discord webhook URL でなければ空(config 汚染時の任意 URL POST を防ぐ)。
    if not exp.startswith(_WEBHOOK_PREFIX):
        return ""
    return exp


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(0)
    sys.stdout.write(resolve(sys.argv[1]))
