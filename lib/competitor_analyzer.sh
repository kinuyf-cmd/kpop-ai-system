#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# competitor_analyzer.sh - 競合ドメイン分析自動化
# SEO本部（ルカリオ/ポリゴンZ）管轄
# 週次cronで実行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SCRIPT_DIR/env_loader.sh"

LOGS_DIR="$SCRIPT_DIR/logs"
TODAY=$(date '+%Y-%m-%d')

mkdir -p "$LOGS_DIR"

echo "=== 競合ドメイン分析 ($TODAY) ==="

# 1. GSCデータからキーワード分析
echo "[1/3] キーワード分析..."
python3 "$SCRIPT_DIR/lib/keyword_classifier.py" analyze > "$LOGS_DIR/competitor_analysis_$TODAY.json" 2>/dev/null

# 2. キーワード戦略提案
echo "[2/3] キーワード戦略提案..."
python3 "$SCRIPT_DIR/lib/keyword_classifier.py" plan > "$LOGS_DIR/keyword_plan_$TODAY.json" 2>/dev/null

# 3. Discord通知
echo "[3/3] Discord通知..."
if [ -f "$LOGS_DIR/keyword_plan_$TODAY.json" ]; then
  SUGGESTIONS=$(python3 -c "
import json
with open('$LOGS_DIR/keyword_plan_$TODAY.json') as f:
    plan = json.load(f)
suggestions = plan.get('suggestions', [])[:5]
lines = []
for s in suggestions:
    lines.append(f\"  {s['type'].upper()}: {s['keyword']} - {s['reason']}\")
print('\n'.join(lines) if lines else '提案なし')
" 2>/dev/null)

  WEBHOOK="${DISCORD_WEBHOOK:-}"
  if [ -n "$WEBHOOK" ]; then
    python3 -c "
import requests, sys
msg = f'📊 **週次SEO分析レポート** ($TODAY)\n\n{sys.argv[1]}'
requests.post(sys.argv[2], json={'content': msg[:1900]}, timeout=10)
" "$SUGGESTIONS" "$WEBHOOK" 2>/dev/null
  fi
fi

echo "✅ 分析完了: $LOGS_DIR/competitor_analysis_$TODAY.json"
