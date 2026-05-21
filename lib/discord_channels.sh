#!/bin/bash
# ============================================================
# discord_channels.sh - Discord チャネル別Webhook取得
#
# Usage:
#   source lib/discord_channels.sh
#   discord_send "publishing_log" "記事投稿完了" '{"embeds":[...]}'
# ============================================================

DISCORD_CONFIG="${DISCORD_CONFIG:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/config/discord_webhooks.json}"
DISCORD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

get_discord_webhook() {
  local channel="$1"
  if [ -f "$DISCORD_CONFIG" ]; then
    # M11.5.B: config 値が "${DISCORD_WEBHOOK_*}" プレースホルダーなら
    # .env / 環境変数から展開する。未解決なら空を返し誤送信を防ぐ。
    DISCORD_ROOT="$DISCORD_ROOT" python3 -c "
import json, sys, os
root = os.environ.get('DISCORD_ROOT', '.')
env_path = os.path.join(root, '.env')
if os.path.exists(env_path):
    for line in open(env_path):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        k = k.strip()
        if k and k not in os.environ:
            os.environ[k] = v.strip().strip('\"').strip(\"'\")
with open('$DISCORD_CONFIG') as f:
    d = json.load(f)
val = (d.get(sys.argv[1], '') or '').strip()
exp = os.path.expandvars(val)
print('' if exp.startswith('\${') else exp)
" "$channel" 2>/dev/null
  fi
}

discord_send() {
  local channel="$1"
  local fallback_msg="$2"
  local json_payload="$3"

  local url
  url=$(get_discord_webhook "$channel")

  # チャネル別Webhookがなければデフォルトにフォールバック
  if [ -z "$url" ]; then
    url="${DISCORD_WEBHOOK:-}"
    if [ -z "$url" ] && [ -f ~/.kpop_discord_webhook ]; then
      url=$(cat ~/.kpop_discord_webhook | tr -d '[:space:]')
    fi
  fi

  if [ -z "$url" ]; then
    echo "  Discord Webhook未設定 → スキップ"
    return 1
  fi

  # JSONペイロードがあればそれを送信、なければシンプルメッセージ
  if [ -n "$json_payload" ]; then
    curl -s -o /dev/null -w "%{http_code}" \
      -X POST "$url" \
      -H "Content-Type: application/json" \
      -d "$json_payload" 2>/dev/null
  else
    curl -s -o /dev/null -w "%{http_code}" \
      -X POST "$url" \
      -H "Content-Type: application/json" \
      -d "{\"content\": \"$fallback_msg\"}" 2>/dev/null
  fi
}
