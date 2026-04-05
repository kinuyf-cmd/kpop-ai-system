#!/bin/bash
# ============================================================
# kpop_category_health.sh - 週次カテゴリ健全性レポート
# 毎週月曜 8:00 JST 実行（cron推奨）
#
# Usage:
#   bash ~/kpop-ai-system/kpop_category_health.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/env_loader.sh"

TODAY=$(date '+%Y年%m月%d日')
REPORT_DIR=~/monthly_reports
mkdir -p "$REPORT_DIR"

echo "========================================"
echo " カテゴリ健全性レポート: $TODAY"
echo "========================================"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [1] カテゴリ分析
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "=== [1] カテゴリ別パフォーマンス ==="
ANALYSIS=$(python3 "$SCRIPT_DIR/lib/category_analyzer.py" analyze 2>/dev/null || echo "分析データなし")
echo "$ANALYSIS"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [2] 不採算カテゴリ検出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "=== [2] 不採算カテゴリ警告 ==="
WARNINGS=$(python3 "$SCRIPT_DIR/lib/category_analyzer.py" unprofitable 2>/dev/null || echo "")
WARNINGS_JSON=$(python3 "$SCRIPT_DIR/lib/category_analyzer.py" unprofitable --json 2>/dev/null || echo "[]")
WARNING_COUNT=$(echo "$WARNINGS_JSON" | python3 -c "import json,sys; print(len(json.loads(sys.stdin.read())))" 2>/dev/null || echo "0")
echo "$WARNINGS"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [3] 最適化提案
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "=== [3] 最適化提案 ==="
SUGGESTIONS=$(python3 "$SCRIPT_DIR/lib/category_analyzer.py" optimize 2>/dev/null || echo "提案なし")
echo "$SUGGESTIONS"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [4] レポート保存
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REPORT_FILE="$REPORT_DIR/category_health_$(date '+%Y%m%d').md"
cat > "$REPORT_FILE" << REPORT
# カテゴリ健全性レポート: $TODAY

## パフォーマンス分析
$ANALYSIS

## 不採算カテゴリ警告
$WARNINGS

## 最適化提案
$SUGGESTIONS
REPORT

echo ""
echo "  保存先: $REPORT_FILE"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [5] Discord通知
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "=== [5] Discord通知 ==="

DISCORD_URL="${DISCORD_WEBHOOK:-}"
if [ -z "$DISCORD_URL" ] && [ -f ~/.kpop_discord_webhook ]; then
  DISCORD_URL=$(cat ~/.kpop_discord_webhook | tr -d '[:space:]')
fi

if [ -n "$DISCORD_URL" ]; then
  # 不採算警告の有無で色を変える
  if [ "$WARNING_COUNT" -gt 0 ] 2>/dev/null; then
    COLOR=15158332  # 赤
    STATUS="$WARNING_COUNT 件の警告"
  else
    COLOR=3066993  # 緑
    STATUS="問題なし"
  fi

  # 分析結果を1024文字に制限
  ANALYSIS_SHORT=$(echo "$ANALYSIS" | head -20 | head -c 1024)
  WARNINGS_SHORT=$(echo "$WARNINGS" | head -c 1024)
  SUGGESTIONS_SHORT=$(echo "$SUGGESTIONS" | head -c 1024)

  DISCORD_JSON=$(python3 - <<PYEOF
import json
fields = [
    {"name": "Status", "value": "$STATUS", "inline": True},
    {"name": "Warning Count", "value": "$WARNING_COUNT", "inline": True},
]
analysis = """$ANALYSIS_SHORT"""
warnings = """$WARNINGS_SHORT"""
suggestions = """$SUGGESTIONS_SHORT"""

if analysis.strip():
    fields.append({"name": "📊 カテゴリ分析", "value": analysis[:1024], "inline": False})
if warnings.strip():
    fields.append({"name": "⚠ 不採算警告", "value": warnings[:1024], "inline": False})
if suggestions.strip():
    fields.append({"name": "💡 最適化提案", "value": suggestions[:1024], "inline": False})

print(json.dumps({
    "embeds": [{
        "title": "📊 週次カテゴリ健全性レポート | $TODAY",
        "color": $COLOR,
        "fields": fields,
        "footer": {"text": "K-POP AI Company - ポリゴンZ"}
    }]
}))
PYEOF
)

  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$DISCORD_URL" \
    -H "Content-Type: application/json" \
    -d "$DISCORD_JSON")

  if [ "$HTTP_CODE" = "204" ]; then
    echo "  Discord通知送信"
  else
    echo "  Discord送信失敗 (HTTP ${HTTP_CODE})"
  fi
else
  echo "  Discord Webhook未設定 → スキップ"
fi

echo ""
echo "========================================"
echo " カテゴリ健全性レポート完了"
echo "========================================"
