#!/bin/bash
set -e

BASE="$HOME/google_metrics"
WP_API="https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
WP_USER="${WP_USER:-kpop-bot}"
DISCORD_WEBHOOK="$DISCORD_WEBHOOK"
LOCK_FILE="$BASE/strengthen_lock.json"
LOG="$BASE/strengthen_winners.log"
MAX_PER_DAY=5

echo "" >> "$LOG"
echo "=== $(date '+%Y-%m-%d %H:%M') ===" >> "$LOG"

TODAY=$(date '+%Y-%m-%d')

# 今日の処理件数チェック
DONE_TODAY=$(python3 - << 'PY' "$LOCK_FILE" "$TODAY"
import json, sys, os
f = sys.argv[1]; today = sys.argv[2]
if not os.path.exists(f):
    print(0)
else:
    data = json.load(open(f))
    print(data.get(today, {}).get("count", 0))
PY
)

if [ "$DONE_TODAY" -ge "$MAX_PER_DAY" ]; then
  echo "本日の上限($MAX_PER_DAY件)に達しました" | tee -a "$LOG"
  exit 0
fi

# スコア計算
SCORES=$(python3 "$BASE/score_articles.py" < "$BASE/metrics_yesterday.json")

# スコア8以上の記事を抽出
python3 - << 'PY' "$SCORES" > /tmp/winner_pages.txt
import json, sys
data = json.loads(sys.argv[1])
winners = [d for d in data if d.get("total", 0) >= 8 and d.get("url","").startswith("http")]
for w in winners:
    print(w["url"])
PY

COUNT=$(wc -l < /tmp/winner_pages.txt | tr -d ' ')
echo "勝ち記事候補: ${COUNT}件" | tee -a "$LOG"

PROCESSED=0

while IFS= read -r PAGE; do
  [ -z "$PAGE" ] && continue
  [ "$PROCESSED" -ge "$MAX_PER_DAY" ] && break

  SLUG=$(echo "$PAGE" | sed 's|.*/||' | sed 's|/$||')
  POST=$(curl -s -K "$HOME/.wp_auth" "$WP_API?slug=$SLUG")
  POST_ID=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['id'] if d else '')")
  TITLE=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['title']['rendered'] if d else '')")

  [ -z "$POST_ID" ] && continue

  # 同一記事の24時間以内更新チェック
  RECENTLY_UPDATED=$(python3 - << 'PY' "$LOCK_FILE" "$POST_ID"
import json, sys, os
from datetime import datetime, timedelta
f = sys.argv[1]; pid = sys.argv[2]
if not os.path.exists(f):
    print("NO")
else:
    data = json.load(open(f))
    updated = data.get("posts", {}).get(pid)
    if updated:
        last = datetime.fromisoformat(updated)
        if datetime.now() - last < timedelta(hours=24):
            print("YES")
            sys.exit()
print("NO")
PY
)

  if [ "$RECENTLY_UPDATED" = "YES" ]; then
    echo "スキップ（24h以内更新済み）: $TITLE" | tee -a "$LOG"
    continue
  fi

  echo "強化中: $TITLE" | tee -a "$LOG"

  # 収益導線追加
  bash "$BASE/inject_revenue_links.sh" "$POST_ID"

  # 内部リンク追加
  bash "$BASE/add_internal_links.sh" "$PAGE"

  # ロック更新
  python3 - << 'PY' "$LOCK_FILE" "$TODAY" "$POST_ID"
import json, sys, os
from datetime import datetime
f, today, pid = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.load(open(f)) if os.path.exists(f) else {}
data.setdefault(today, {})["count"] = data.get(today, {}).get("count", 0) + 1
data.setdefault("posts", {})[pid] = datetime.now().isoformat()
json.dump(data, open(f, "w"), ensure_ascii=False)
PY

  PROCESSED=$((PROCESSED + 1))
  echo "完了: $TITLE" | tee -a "$LOG"

done < /tmp/winner_pages.txt

echo "勝ち記事強化完了: ${PROCESSED}件" | tee -a "$LOG"
