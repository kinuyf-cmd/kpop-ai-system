#!/bin/bash
set -e

BASE="$HOME/google_metrics"
WP_API="https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
WP_USER="${WP_USER:-kpop-bot}"
DISCORD_WEBHOOK="$DISCORD_WEBHOOK"
OUT="$BASE/noindex_candidates.json"
LOG="$BASE/noindex_candidates.log"

echo "" >> "$LOG"
echo "=== $(date '+%Y-%m-%d %H:%M') ===" >> "$LOG"

# スコア計算
SCORES=$(python3 "$BASE/score_articles.py" < "$BASE/metrics_yesterday.json")

# スコア4以下を抽出
python3 - << 'PY' "$SCORES" "$OUT"
import json, sys
data = json.loads(sys.argv[1])
out_path = sys.argv[2]

candidates = [
    d for d in data
    if d.get("total", 0) <= 4
    and d.get("url", "").startswith("http")
]

# 判定ラベル付与
for c in candidates:
    score = c["total"]
    if score <= 1:
        c["action"] = "noindex推奨"
    elif score <= 2:
        c["action"] = "リライト候補"
    else:
        c["action"] = "様子見"

candidates.sort(key=lambda x: x["total"])
json.dump(candidates, open(out_path, "w"), ensure_ascii=False, indent=2)
print(f"{len(candidates)}件の候補を検出")
PY

COUNT=$(python3 -c "import json; d=json.load(open('$OUT')); print(len(d))")
NOINDEX_COUNT=$(python3 -c "import json; d=json.load(open('$OUT')); print(len([x for x in d if x['action']=='noindex推奨']))")

echo "候補: ${COUNT}件 (noindex推奨: ${NOINDEX_COUNT}件)" | tee -a "$LOG"

# Discord報告
REPORT=$(python3 - << 'PY' "$OUT"
import json
data = json.load(open(sys.argv[1]))
import sys

if not data:
    print("負け記事なし ✅")
    sys.exit()

lines = ["⚠️ 負け記事レポート\n"]
for d in data[:10]:
    url = d["url"].replace("https://www.kpopjournal.tokyo","")
    action = d["action"]
    score = d["total"]
    lines.append(f"{action} (score:{score}) {url}")

print("\n".join(lines))
PY
)

curl -s -X POST "$DISCORD_WEBHOOK"   -H "Content-Type: application/json"   -d "$(python3 -c "import json,sys; print(json.dumps({'content': sys.argv[1][:1900]}))" "$REPORT")" > /dev/null

echo "レポート送信完了" | tee -a "$LOG"

# noindex推奨記事にnoindexタグを自動付与（上限3件/日）
python3 - << 'PY' "$OUT" > /tmp/noindex_targets.txt
import json, sys
data = json.load(open(sys.argv[1]))
targets = [d for d in data if d["action"] == "noindex推奨"][:3]
for t in targets:
    slug = t["url"].rstrip("/").split("/")[-1]
    print(slug)
PY

APPLIED=0
while IFS= read -r SLUG; do
  [ -z "$SLUG" ] && continue

  POST=$(curl -s -K "$HOME/.wp_auth" "$WP_API?slug=$SLUG")
  POST_ID=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['id'] if d else '')")
  TITLE=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['title']['rendered'] if d else '')")

  [ -z "$POST_ID" ] && continue

  # AIOSEO経由でnoindexを設定
  RESP=$(curl -s -X POST "$WP_API/$POST_ID"     -K "$HOME/.wp_auth"     -H "Content-Type: application/json"     -d '{"meta":{"_aioseo_robots_default":false,"_aioseo_robots_noindex":true}}')

  echo "noindex設定: $TITLE" | tee -a "$LOG"

  curl -s -X POST "$DISCORD_WEBHOOK"     -H "Content-Type: application/json"     -d "$(python3 -c "import json,sys; print(json.dumps({'content': '🚫 noindex設定: ' + sys.argv[1]}))" "$TITLE")" > /dev/null

  APPLIED=$((APPLIED + 1))
done < /tmp/noindex_targets.txt

echo "noindex適用: ${APPLIED}件" | tee -a "$LOG"
