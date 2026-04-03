#!/bin/bash
set -e

BASE="$HOME/google_metrics"
LOW_CTR_JSON="$BASE/low_ctr_pages.json"
OUT_FILE="$BASE/title_rewrite_candidates.txt"

python3 "$BASE/find_low_ctr_pages.py" < "$BASE/metrics_yesterday.json" > "$LOW_CTR_JSON"

echo "" > "$OUT_FILE"

COUNT=$(python3 - << 'PY' "$LOW_CTR_JSON"
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)
print(len(data))
PY
)

if [ "$COUNT" -eq 0 ]; then
  echo "改善対象なし" > "$OUT_FILE"
  echo "改善対象なし"
  exit 0
fi

python3 - << 'PY' "$LOW_CTR_JSON" > /tmp/low_ctr_pages_list.txt
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)
for item in data:
    print(item["page"])
PY

while IFS= read -r PAGE; do
  [ -z "$PAGE" ] && continue

  echo "=== $PAGE ===" >> "$OUT_FILE"

  PROMPT=$(cat <<TXT
あなたはK-POPメディアのCTR改善担当です。

以下のページは、検索表示はあるのにCTRが低いページです。
このページのタイトル改善案を3つ出してください。

【ルール】
- クリック率を上げる
- 過度な誇張は禁止
- アーティスト名・数字・イベント名を優先
- SEOも意識する
- 各案は1行で
- 説明不要

対象ページ:
$PAGE
TXT
)

  claude -p "$PROMPT" >> "$OUT_FILE"
  echo "" >> "$OUT_FILE"
done < /tmp/low_ctr_pages_list.txt

echo "$OUT_FILE"
