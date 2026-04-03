#!/bin/bash
set -e

BASE="$HOME/google_metrics"

WP_API="https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
WP_USER="kpop-bot"
WP_PASS="afX1 yOFd nlrp I751 3XgW zMmM"
DISCORD="https://discord.com/api/webhooks/1489227617373782037/kXg39l1szo4i8IrbgejdIPoug4SDqnFSizbcQB89S0K5JSp8ohSj04Ys_QR0_9xe_9zH"

PAGES=$(python3 "$BASE/find_low_ctr_pages.py" < "$BASE/metrics_yesterday.json" | jq -r '.[].page')

for PAGE in $PAGES; do

SLUG=$(echo "$PAGE" | awk -F/ '{print $NF}')

POST=$(curl -s -u "$WP_USER:$WP_PASS" "$WP_API?slug=$SLUG")

ID=$(echo "$POST" | jq '.[0].id')
TITLE=$(echo "$POST" | jq -r '.[0].title.rendered')
CONTENT=$(echo "$POST" | jq -r '.[0].content.rendered')

[ "$ID" = "null" ] && continue

# ===== タイトル再生成 =====
NEW_TITLE=$(claude -p "
CTRを上げるタイトルを1つ出力

$TITLE
" | tail -n 1)

# ===== meta生成 =====
NEW_META=$(bash "$BASE/generate_meta_description.sh" "$NEW_TITLE" "$CONTENT")

# ===== meta採点 =====
PASS=$(python3 "$BASE/score_meta_description.py" "$NEW_META" | jq -r '.pass')

[ "$PASS" != "true" ] && continue

# ===== 更新 =====
JSON=$(jq -n \
  --arg t "$NEW_TITLE" \
  --arg m "$NEW_META" \
  '{title:$t, meta:{"_aioseo_description":$m}}')

RESP=$(curl -s -X POST "$WP_API/$ID" \
  -u "$WP_USER:$WP_PASS" \
  -H "Content-Type: application/json" \
  -d "$JSON")

# ===== 通知 =====
curl -s -X POST "$DISCORD" \
  -H "Content-Type: application/json" \
  -d "{\"content\":\"✏️タイトル＆meta更新\n$PAGE\n$NEW_TITLE\n$NEW_META\"}"

done
