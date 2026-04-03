#!/bin/bash

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# K-POP パイプライン通知スクリプト
# 使用法: bash ~/kpop_notify.sh <success|error> <パイプライン名> <メッセージ> [URL]
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STATUS="$1"
PIPELINE="$2"
MESSAGE="$3"
URL="${4:-}"

if [[ "$STATUS" == "success" ]]; then
  ICON="✅"
  TITLE="K-POP ${PIPELINE}パイプライン 完了"
else
  ICON="❌"
  TITLE="K-POP ${PIPELINE}パイプライン エラー"
fi

# macOS デスクトップ通知
osascript -e "display notification \"${MESSAGE}\" with title \"${TITLE}\" subtitle \"$(date '+%H:%M')\"" 2>/dev/null

# LINE Notify（~/.kpop_line_token にトークンを置けば有効）
LINE_TOKEN_FILE=~/.kpop_line_token
if [[ -f "$LINE_TOKEN_FILE" ]]; then
  LINE_TOKEN=$(cat "$LINE_TOKEN_FILE" | tr -d '[:space:]')
  if [[ -n "$LINE_TOKEN" ]]; then
    BODY="${TITLE}"$'\n'"${ICON} ${MESSAGE}"
    [[ -n "$URL" ]] && BODY="${BODY}"$'\n'"URL: ${URL}"
    curl -s -X POST https://notify-api.line.me/api/notify \
      -H "Authorization: Bearer ${LINE_TOKEN}" \
      --data-urlencode "message=${BODY}" > /dev/null 2>&1
  fi
fi

# Discord Webhook（~/.kpop_discord_webhook にURLを置けば有効）
DISCORD_WEBHOOK_FILE=~/.kpop_discord_webhook
if [[ -f "$DISCORD_WEBHOOK_FILE" ]]; then
  DISCORD_URL=$(cat "$DISCORD_WEBHOOK_FILE" | tr -d '[:space:]')
  if [[ -n "$DISCORD_URL" ]]; then
    if [[ "$STATUS" == "success" ]]; then
      COLOR=3066993   # 緑
    else
      COLOR=15158332  # 赤
    fi
    EMBED_DESC="${ICON} ${MESSAGE}"
    [[ -n "$URL" ]] && EMBED_DESC="${EMBED_DESC}\n${URL}"
    DISCORD_JSON=$(python3 -c "
import json, sys
print(json.dumps({'embeds': [{'title': sys.argv[1], 'description': sys.argv[2].replace(chr(92)+'n', chr(10)), 'color': int(sys.argv[3])}]}))
" "$TITLE" "$EMBED_DESC" "$COLOR")
    curl -s -o /dev/null -X POST "$DISCORD_URL" \
      -H "Content-Type: application/json" \
      -d "$DISCORD_JSON" 2>/dev/null
  fi
fi
