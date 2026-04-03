#!/bin/bash
set -e

BASE="$HOME/google_metrics"
METRICS_JSON="$BASE/metrics_yesterday.json"
TMP_LOW="$BASE/low_ctr_pages.json"
TMP_OUT="$BASE/auto_title_updates.log"

WP_API="https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
WP_USER="${WP_USER:-kpop-bot}"
WP_PASS="${WP_PASS}"
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

  # slug 抽出
  SLUG=$(python3 - << 'PY' "$PAGE"
import sys
page = sys.argv[1].strip()
page = page.rstrip("/")
slug = page.split("/")[-1]
print(slug)
PY
)

  # WPから投稿取得
  POST_JSON=$(curl -s -u "$WP_USER:$WP_PASS" "$WP_API?slug=$SLUG")
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
    print(data[0].get("title",{}).get("rendered",""))
else:
    print("")
PY
)

  if [ -z "$POST_ID" ] || [ -z "$OLD_TITLE" ]; then
    echo "投稿取得失敗: $PAGE" | tee -a "$TMP_OUT"
    continue
  fi

  # 新タイトル生成
  NEW_TITLE=$(claude -p "
あなたはK-POPメディアのCTR改善担当です。

以下の既存タイトルを、SEOを維持しつつCTRが上がる形に改善してください。

【ルール】
- タイトル案を内部で3案考え、最も強い1案だけ出力
- アーティスト名・数字・イベント名を優先
- 過度な誇張禁止
- 24〜38文字目安
- 説明禁止
- 1行だけ出力

既存タイトル:
$OLD_TITLE
" | tail -n 1)

  if [ -z "$NEW_TITLE" ]; then
    echo "新タイトル生成失敗: $PAGE" | tee -a "$TMP_OUT"
    continue
  fi

  # 新タイトル採点
  SCORE_JSON=$(python3 "$BASE/score_title_ctr.py" "$NEW_TITLE")
  PASS=$(python3 - << 'PY' "$SCORE_JSON"
import sys, json
data = json.loads(sys.argv[1])
print("YES" if data.get("pass") else "NO")
PY
)
  SCORE=$(python3 - << 'PY' "$SCORE_JSON"
import sys, json
data = json.loads(sys.argv[1])
print(data.get("score",0))
PY
)

  # 同一タイトル回避
  if [ "$OLD_TITLE" = "$NEW_TITLE" ]; then
    echo "同一タイトルのためスキップ: $OLD_TITLE" | tee -a "$TMP_OUT"
    continue
  fi

  # スコア条件
  if [ "$PASS" != "YES" ]; then
    echo "新タイトル弱いのでスキップ: $NEW_TITLE (score=$SCORE)" | tee -a "$TMP_OUT"
    continue
  fi

  # バックアップ保存
  echo "POST_ID=$POST_ID" >> "$TMP_OUT"
  echo "OLD_TITLE=$OLD_TITLE" >> "$TMP_OUT"
  echo "NEW_TITLE=$NEW_TITLE" >> "$TMP_OUT"

  UPDATE_JSON=$(python3 - << 'PY' "$NEW_TITLE"
import sys, json
print(json.dumps({"title": sys.argv[1]}, ensure_ascii=False))
PY
)

  RESP=$(curl -s -X POST "$WP_API/$POST_ID" \
    -u "$WP_USER:$WP_PASS" \
    -H "Content-Type: application/json" \
    -d "$UPDATE_JSON")

  UPDATED=$(python3 - << 'PY' "$RESP"
import sys, json
try:
    data = json.loads(sys.argv[1])
    print(data.get("title",{}).get("rendered",""))
except Exception:
    print("")
PY
)

  if [ -n "$UPDATED" ]; then
    echo "更新成功: $OLD_TITLE -> $UPDATED" | tee -a "$TMP_OUT"

    python3 - << PY
import requests, json
webhook = """$DISCORD_WEBHOOK"""
msg = """✏️ タイトル自動更新\nページ: $PAGE\n旧: $OLD_TITLE\n新: $UPDATED\nスコア: $SCORE"""
requests.post(webhook, json={"content": msg[:1900]}, timeout=20)
PY
  else
    echo "更新失敗: $PAGE" | tee -a "$TMP_OUT"
  fi

done < /tmp/low_ctr_pages_list.txt
