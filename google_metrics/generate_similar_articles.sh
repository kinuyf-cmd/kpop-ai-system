#!/bin/bash
set -e

BASE="$HOME/google_metrics"
LOCK="$BASE/similar_articles_lock.json"
LOG="$BASE/similar_articles.log"
TODAY=$(date '+%Y-%m-%d')

MAX_PER_DAY=2

echo "" >> "$LOG"
echo "=== $(date '+%Y-%m-%d %H:%M') ===" >> "$LOG"

# 本日上限チェック
DONE=$(python3 -c "
import json, os
f = '$LOCK'
data = json.load(open(f)) if os.path.exists(f) else {}
print(data.get('$TODAY', {}).get('count', 0))
")
[ "$DONE" -ge "$MAX_PER_DAY" ] && echo "上限達成" | tee -a "$LOG" && exit 0

# スコア8以上の勝ち記事を抽出
python3 - << 'PY' "$BASE/score_articles.py" "$BASE/metrics_yesterday.json" > /tmp/winner_topics.txt
import json, sys, subprocess
result = subprocess.run(['python3', sys.argv[1]], stdin=open(sys.argv[2]), capture_output=True, text=True)
data = json.loads(result.stdout)
winners = [d for d in data if d.get("total", 0) >= 8 and d.get("url","").startswith("http")]
for w in winners[:3]:
    slug = w["url"].rstrip("/").split("/")[-1]
    print(slug + "|" + str(w["total"]))
PY

COUNT=$(wc -l < /tmp/winner_topics.txt | tr -d ' ')
echo "勝ち記事: ${COUNT}件" | tee -a "$LOG"

GENERATED=0

while IFS='|' read -r SLUG SCORE; do
  [ -z "$SLUG" ] && continue
  [ "$GENERATED" -ge "$MAX_PER_DAY" ] && break

  # 既に類似記事を生成済みかチェック
  ALREADY=$(python3 -c "
import json, os
f = '$LOCK'
data = json.load(open(f)) if os.path.exists(f) else {}
print('YES' if '$SLUG' in data.get('generated', []) else 'NO')
")
  [ "$ALREADY" = "YES" ] && echo "生成済みスキップ: $SLUG" | tee -a "$LOG" && continue

  # WPから元記事のタイトル取得
  POST=$(curl -s -K "$HOME/.wp_auth"     "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?slug=$SLUG")
  ORIG_TITLE=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['title']['rendered'] if d else '')")
  [ -z "$ORIG_TITLE" ] && continue

  echo "類似記事生成中: $ORIG_TITLE (score:$SCORE)" | tee -a "$LOG"

  # 類似テーマを生成してパイプラインに投入
  TODAY_JP=$(date '+%Y年%m月%d日')

  cd ~ && claude --allowedTools WebSearch --agent deoxys_kpop -p "
今日は${TODAY_JP}です。

以下の「勝ち記事」と同じテーマ領域で、別角度の新しい記事を1本書いてください。

【勝ち記事】
$ORIG_TITLE

【条件】
- 同じテーマだが切り口を変える（例：「使い方」→「比較」→「選び方」）
- SEO検索ボリュームが見込めるキーワードを選ぶ
- 内容が被らない

【出力形式・絶対厳守】
1行目：タイトル文字列のみ
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ
末尾に「※本記事は${TODAY_JP}時点の情報です」を明記
" > reports/0_breaking.md && bash ~/kpop_pipeline.sh 2>&1 | tail -5

  # ロック更新
  python3 - << 'PY' "$LOCK" "$TODAY" "$SLUG"
import json, os
from datetime import datetime
f, today, slug = sys.argv[1], sys.argv[2], sys.argv[3]
import sys
data = json.load(open(f)) if os.path.exists(f) else {}
data.setdefault(today, {})["count"] = data.get(today, {}).get("count", 0) + 1
data.setdefault("generated", []).append(slug)
json.dump(data, open(f, "w"), ensure_ascii=False)
PY

  GENERATED=$((GENERATED + 1))
  echo "完了: $ORIG_TITLE の類似記事" | tee -a "$LOG"

done < /tmp/winner_topics.txt

echo "類似記事生成完了: ${GENERATED}件" | tee -a "$LOG"
