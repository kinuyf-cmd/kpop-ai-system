#!/bin/bash
# セッション開始時の概況表示
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

echo "=== K-POP JOURNAL セッション開始 ==="
echo "日時: $(date '+%Y-%m-%d %H:%M')"
echo ""

# 前回セッション学習の確認
if [ -f logs/session_learnings.jsonl ]; then
  LAST=$(tail -1 logs/session_learnings.jsonl 2>/dev/null | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('date','不明'))" 2>/dev/null || echo "不明")
  COUNT=$(wc -l < logs/session_learnings.jsonl 2>/dev/null || echo 0)
  echo "前回セッション: $LAST （累計${COUNT}件の学習記録）"
else
  echo "セッション学習記録: なし（初回）"
fi

echo ""
echo "セッション準備完了"
