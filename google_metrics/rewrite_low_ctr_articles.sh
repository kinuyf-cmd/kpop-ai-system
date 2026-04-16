#!/bin/bash
set -e

BASE="$HOME/google_metrics"
METRICS_JSON="$BASE/metrics_yesterday.json"
TMP_LOW="$BASE/low_ctr_pages.json"
TMP_OUT="$BASE/rewrite_low_ctr.log"

WP_API="https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
WP_USER="${WP_USER:-kpop-bot}"
DISCORD_WEBHOOK="$DISCORD_WEBHOOK"

echo "" > "$TMP_OUT"

# 低CTRページ抽出
python3 "$BASE/find_low_ctr_pages.py" < "$METRICS_JSON" > "$TMP_LOW"

COUNT=$(python3 - << 'PY' "$TMP_LOW"
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)
print(len(data))
PY
)

if [ "$COUNT" -eq 0 ]; then
  echo "低CTR改善対象なし" | tee -a "$TMP_OUT"
  exit 0
fi

python3 - << 'PY' "$TMP_LOW" > /tmp/low_ctr_pages_list.txt
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)
for item in data:
    print(item["page"])
PY

while IFS= read -r PAGE; do
  [ -z "$PAGE" ] && continue

  echo "=== PAGE: $PAGE ===" | tee -a "$TMP_OUT"

  SLUG=$(python3 - << 'PY' "$PAGE"
import sys
page = sys.argv[1].strip().rstrip("/")
print(page.split("/")[-1])
PY
)

  POST_JSON=$(curl -s -K "$HOME/.wp_auth" "$WP_API?slug=$SLUG&context=edit")
  POST_ID=$(python3 - << 'PY' "$POST_JSON"
import sys, json
data = json.loads(sys.argv[1])
if isinstance(data, list) and len(data) > 0:
    print(data[0].get("id",""))
else:
    print("")
PY
)

  OLD_TITLE=$(python3 - << 'PY' "$POST_JSON"
import sys, json
data = json.loads(sys.argv[1])
if isinstance(data, list) and len(data) > 0:
    print(data[0].get("title",{}).get("raw","") or data[0].get("title",{}).get("rendered",""))
else:
    print("")
PY
)

  OLD_CONTENT=$(python3 - << 'PY' "$POST_JSON"
import sys, json
data = json.loads(sys.argv[1])
if isinstance(data, list) and len(data) > 0:
    print(data[0].get("content",{}).get("raw","") or data[0].get("content",{}).get("rendered",""))
else:
    print("")
PY
)

  if [ -z "$POST_ID" ] || [ -z "$OLD_TITLE" ] || [ -z "$OLD_CONTENT" ]; then
    echo "投稿取得失敗: $PAGE" | tee -a "$TMP_OUT"
    continue
  fi

  echo "リライト中: $OLD_TITLE" | tee -a "$TMP_OUT"

  # Claudeで本文リライト
  NEW_CONTENT=$(claude -p "
あなたはK-POPメディアのSEOライターです。

以下の記事本文を、エンゲージメントとCTRが向上する形にリライトしてください。

【絶対ルール】
- 修正内容・理由・説明は一切書かない
- 完成HTML本文のみを出力する
- 既存の事実・情報を改ざんしない
- 文字数は元記事と同等以上

【改善ポイント】
- 冒頭3行を「結論 → 注目理由 → 読む価値」で構成する
- H2/H3見出しをクリックしたくなる表現に変える
- 関連コンテンツへ誘導する自然な文章を末尾に追加する

【出力形式】
HTML本文のみ（タイトル不要）

---
タイトル: $OLD_TITLE

本文:
$OLD_CONTENT
")

  if [ -z "$NEW_CONTENT" ]; then
    echo "リライト失敗: $PAGE" | tee -a "$TMP_OUT"
    continue
  fi

  CONTENT_LENGTH=$(echo "$NEW_CONTENT" | wc -c)

  UPDATE_JSON=$(python3 - << 'PY' "$NEW_CONTENT"
import sys, json
print(json.dumps({"content": sys.argv[1]}, ensure_ascii=False))
PY
)

  RESP=$(curl -s -X POST "$WP_API/$POST_ID" \
    -K "$HOME/.wp_auth" \
    -H "Content-Type: application/json" \
    -d "$UPDATE_JSON")

  UPDATED_TITLE=$(python3 - << 'PY' "$RESP"
import sys, json
try:
    data = json.loads(sys.argv[1])
    print(data.get("title",{}).get("rendered",""))
except:
    print("")
PY
)

  if [ -n "$UPDATED_TITLE" ]; then
    echo "リライト成功: $UPDATED_TITLE (${CONTENT_LENGTH}文字)" | tee -a "$TMP_OUT"

    python3 - << PY
import requests, json
webhook = """$DISCORD_WEBHOOK"""
msg = """🛠 本文自動リライト\nページ: $PAGE\nタイトル: $UPDATED_TITLE\n本文文字数: $CONTENT_LENGTH"""
requests.post(webhook, json={"content": msg[:1900]}, timeout=20)
PY

    bash ~/google_metrics/add_internal_links.sh "$PAGE"
  else
    echo "更新失敗: $PAGE" | tee -a "$TMP_OUT"
  fi

done < /tmp/low_ctr_pages_list.txt
