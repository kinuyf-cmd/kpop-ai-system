#!/bin/bash
set -e

BASE="$HOME/google_metrics"

mkdir -p "$BASE"

# =========================
# meta生成
# =========================
cat > "$BASE/generate_meta_description.sh" << 'SH'
#!/bin/bash
TITLE="$1"
CONTENT="$2"

META=$(claude -p "
あなたはK-POPメディアのSEO担当です。

以下の記事からmeta descriptionを1つ作成してください。

【ルール】
・70〜120文字
・アーティスト名を入れる
・何が分かる記事か明確に
・煽りすぎ禁止
・1行のみ出力

タイトル:
$TITLE

本文:
$CONTENT
" | tail -n 1)

META=$(echo "$META" | tr '\n' ' ' | sed 's/  */ /g')
echo "$META"
SH

chmod +x "$BASE/generate_meta_description.sh"

# =========================
# meta採点
# =========================
cat > "$BASE/score_meta_description.py" << 'PY'
import sys, json

meta = sys.argv[1]
score = 0

if 70 <= len(meta) <= 120:
    score += 4

if any(k in meta for k in ["BTS","BLACKPINK","BIGBANG","IVE","ILLIT","SEVENTEEN","TWICE"]):
    score += 3

if any(k in meta for k in ["まとめ","解説","最新","整理"]):
    score += 2

if any(k in meta for k in ["修正","サマリー","報告"]):
    score -= 3

print(json.dumps({
    "score": score,
    "pass": score >= 6
}))
PY

# =========================
# タイトル＋meta自動更新
# =========================
cat > "$BASE/update_titles_and_meta.sh" << 'SH'
#!/bin/bash
set -e

BASE="$HOME/google_metrics"

WP_API="https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
WP_USER="${WP_USER:-kpop-bot}"
WP_PASS="ここにアプリパスワード"
DISCORD="ここにWebhook"

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
SH

chmod +x "$BASE/update_titles_and_meta.sh"

echo "✅ 完了：meta自動更新セットアップ完了"
