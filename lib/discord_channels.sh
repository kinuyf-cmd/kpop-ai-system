#!/bin/bash
# ============================================================
# discord_channels.sh - Discord チャネル別Webhook取得 v2.0
#
# 4チャネル: morning / seo / publish / error
#
# Usage:
#   source lib/discord_channels.sh
#   discord_send "publish" "記事投稿完了" '{"embeds":[...]}'
#   discord_send "error" "パイプライン停止"
# ============================================================

DISCORD_CONFIG="${DISCORD_CONFIG:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/config/discord_webhooks.json}"

get_discord_webhook() {
  local channel="$1"

  # 旧チャネル名→新チャネル名へマッピング
  case "$channel" in
    urgent_errors|alert_summary|sales_monetization) channel="error" ;;
    daily_ceo_report|weekly_board_report|monthly_board_report) channel="morning" ;;
    seo_insights) channel="seo" ;;
    publishing_log) channel="publish" ;;
  esac

  if [ -f "$DISCORD_CONFIG" ]; then
    python3 -c "
import json, sys
with open('$DISCORD_CONFIG') as f:
    d = json.load(f)
print(d.get(sys.argv[1], ''))
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
