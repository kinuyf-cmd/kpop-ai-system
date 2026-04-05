#!/bin/bash
# ============================================================
# kpop_exit_dashboard.sh - 週次Exit指標ダッシュボード
# 毎週日曜 20:00 JST 実行（cron推奨）
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/env_loader.sh"

TODAY=$(date '+%Y年%m月%d日')
REPORT_DIR=~/monthly_reports
mkdir -p "$REPORT_DIR"

echo "========================================"
echo " Exit指標ダッシュボード: $TODAY"
echo "========================================"

# メトリクス取得
METRICS_TEXT=$(python3 "$SCRIPT_DIR/lib/exit_metrics.py" 2>/dev/null || echo "データ取得失敗")
METRICS_JSON=$(python3 "$SCRIPT_DIR/lib/exit_metrics.py" --json 2>/dev/null || echo '{}')

echo "$METRICS_TEXT"

# レポート保存
REPORT_FILE="$REPORT_DIR/exit_dashboard_$(date '+%Y%m%d').md"
echo "$METRICS_TEXT" > "$REPORT_FILE"
echo "  保存先: $REPORT_FILE"

# Discord通知
source "$SCRIPT_DIR/lib/discord_channels.sh" 2>/dev/null || true
DISCORD_URL=$(get_discord_webhook "weekly_board_report" 2>/dev/null || echo "")
if [ -z "$DISCORD_URL" ]; then
  DISCORD_URL="${DISCORD_WEBHOOK:-}"
fi
if [ -z "$DISCORD_URL" ] && [ -f ~/.kpop_discord_webhook ]; then
  DISCORD_URL=$(cat ~/.kpop_discord_webhook | tr -d '[:space:]')
fi

if [ -n "$DISCORD_URL" ]; then
  SCORE=$(echo "$METRICS_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('exit_readiness',{}).get('score',0))" 2>/dev/null || echo "0")
  GRADE=$(echo "$METRICS_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('exit_readiness',{}).get('grade','?'))" 2>/dev/null || echo "?")
  MRR=$(echo "$METRICS_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(f\"{d.get('mrr',{}).get('current_jpy',0):,}\")" 2>/dev/null || echo "0")
  MRR_GROWTH=$(echo "$METRICS_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('mrr',{}).get('growth_pct',0))" 2>/dev/null || echo "0")
  PV=$(echo "$METRICS_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(f\"{d.get('traffic',{}).get('monthly_pv',0):,}\")" 2>/dev/null || echo "0")
  MARGIN=$(echo "$METRICS_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('financials',{}).get('gross_margin_pct',0))" 2>/dev/null || echo "0")
  AUTO=$(echo "$METRICS_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('operations',{}).get('automation_rate_pct',0))" 2>/dev/null || echo "0")

  # スコアに応じた色
  if [ "$SCORE" -ge 80 ] 2>/dev/null; then
    COLOR=3066993   # 緑
  elif [ "$SCORE" -ge 60 ] 2>/dev/null; then
    COLOR=15105570  # 橙
  elif [ "$SCORE" -ge 40 ] 2>/dev/null; then
    COLOR=16776960  # 黄
  else
    COLOR=15158332  # 赤
  fi

  DISCORD_JSON=$(python3 - <<PYEOF
import json
fields = [
    {"name": "Exit Score", "value": "${SCORE}/100 (${GRADE})", "inline": True},
    {"name": "MRR", "value": "${MRR}円", "inline": True},
    {"name": "MRR成長率", "value": "${MRR_GROWTH}%", "inline": True},
    {"name": "月間PV", "value": "${PV}", "inline": True},
    {"name": "粗利率", "value": "${MARGIN}%", "inline": True},
    {"name": "自動化率", "value": "${AUTO}%", "inline": True},
]
print(json.dumps({
    "embeds": [{
        "title": "📊 Exit Readiness Dashboard | $TODAY",
        "color": $COLOR,
        "fields": fields,
        "footer": {"text": "K-POP AI Company - CFO ミュウツー"}
    }]
}))
PYEOF
)

  curl -s -o /dev/null -w "" \
    -X POST "$DISCORD_URL" \
    -H "Content-Type: application/json" \
    -d "$DISCORD_JSON" 2>/dev/null && echo "  Discord通知送信" || echo "  Discord送信失敗"
else
  echo "  Discord未設定 → スキップ"
fi

echo ""
echo "========================================"
echo " Exit Dashboard 完了"
echo "========================================"
