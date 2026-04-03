#!/bin/bash
set -e

WP_API="https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
WP_USER="${WP_USER:-kpop-bot}"
WP_PASS="${WP_PASS}"
DISCORD_WEBHOOK="$DISCORD_WEBHOOK"

TARGET_PAGE="$1"

if [ -z "$TARGET_PAGE" ]; then
  echo "使い方: bash add_monetization_links.sh /slug/"
  exit 1
fi

# =========================
# slug抽出
# =========================
SLUG=$(echo "$TARGET_PAGE" | awk -F/ '{print $NF}')

POST=$(curl -s -u "$WP_USER:$WP_PASS" "$WP_API?slug=$SLUG")

POST_ID=$(echo "$POST" | jq '.[0].id')
TITLE=$(echo "$POST" | jq -r '.[0].title.rendered')
CONTENT=$(echo "$POST" | jq -r '.[0].content.rendered')

[ "$POST_ID" = "null" ] && exit 1

# =========================
# 収益記事候補
# =========================
MONEY_PAGES=(
"/abema-free-view-method/"
"/spotify-vs-apple-music/"
"/kpop-live-ticket-guide/"
"/kpop-streaming-howto/"
)

# ランダムで2つ選ぶ
M1=${MONEY_PAGES[$RANDOM % ${#MONEY_PAGES[@]}]}
M2=${MONEY_PAGES[$RANDOM % ${#MONEY_PAGES[@]}]}

# =========================
# CTA生成
# =========================
CTA=$(cat <<HTML
<div style="border:2px solid #ff4d6d;padding:16px;margin:24px 0;border-radius:10px;background:#fff5f7;">
<strong>📌 今すぐチェック</strong><br>
<a href="https://www.kpopjournal.tokyo$M1">▶ 関連情報はこちら</a><br><br>
<a href="https://www.kpopjournal.tokyo$M2">▶ さらに詳しく見る</a>
</div>
HTML
)

# =========================
# 既存CTAチェック
# =========================
HAS_CTA=$(echo "$CONTENT" | grep -c "今すぐチェック" || true)

if [ "$HAS_CTA" -gt 0 ]; then
  echo "CTAあり → スキップ"
  exit 0
fi

# =========================
# 挿入位置（本文末尾）
# =========================
NEW_CONTENT=$(python3 - << 'PY' "$CONTENT" "$CTA"
import sys
print(sys.argv[1] + "\n\n" + sys.argv[2])
PY
)

# =========================
# WP更新
# =========================
JSON=$(jq -n \
  --arg c "$NEW_CONTENT" \
  '{content:$c}')

RESP=$(curl -s -X POST "$WP_API/$POST_ID" \
  -u "$WP_USER:$WP_PASS" \
  -H "Content-Type: application/json" \
  -d "$JSON")

# =========================
# 通知
# =========================
curl -s -X POST "$DISCORD_WEBHOOK" \
  -H "Content-Type: application/json" \
  -d "{\"content\":\"💰 収益導線追加\n$TARGET_PAGE\"}"

echo "完了: $TARGET_PAGE"
