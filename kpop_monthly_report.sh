#!/bin/bash
# ============================================================
# kpop_monthly_report.sh - 月次経営レポート
# 毎月1日 10:00 JST 実行（cron推奨）
#
# Usage:
#   bash ~/kpop-ai-system/kpop_monthly_report.sh           # 前月分
#   bash ~/kpop-ai-system/kpop_monthly_report.sh 2026-03   # 指定月
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/env_loader.sh"

# 対象月の決定
if [ -n "${1:-}" ]; then
  TARGET_MONTH="$1"
else
  # 前月
  TARGET_MONTH=$(python3 -c "
from datetime import datetime
now = datetime.now()
m = now.month - 1 if now.month > 1 else 12
y = now.year if now.month > 1 else now.year - 1
print(f'{y}-{m:02d}')
")
fi

TODAY=$(date '+%Y年%m月%d日')
REPORT_DIR=~/monthly_reports
mkdir -p "$REPORT_DIR"

echo "========================================"
echo " 月次経営レポート: ${TARGET_MONTH}"
echo " 生成日: $TODAY"
echo "========================================"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [1] メトリクス集計
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "=== [1] メトリクス集計 ==="

METRICS_JSON=$(python3 "$SCRIPT_DIR/lib/monthly_metrics_aggregator.py" "$TARGET_MONTH" --json 2>/dev/null || echo '{}')
METRICS_TEXT=$(python3 "$SCRIPT_DIR/lib/monthly_metrics_aggregator.py" "$TARGET_MONTH" 2>/dev/null || echo "集計データなし")

echo "$METRICS_TEXT"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [2] Claude によるエグゼクティブサマリ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "=== [2] エグゼクティブサマリ生成 ==="

# 経営目標を取得
TARGETS=$(python3 -c "
import json
from pathlib import Path
rc = Path('$SCRIPT_DIR/config/revenue_config.json')
if rc.exists():
    c = json.loads(rc.read_text())
    t = c.get('daily_targets', {})
    print(f'月次目標（参考）: Month1={t.get(\"month_1\",\"N/A\")}円/日, Month3={t.get(\"month_3\",\"N/A\")}円/日, Month6={t.get(\"month_6\",\"N/A\")}円/日, Month12={t.get(\"month_12\",\"N/A\")}円/日')
else:
    print('目標データなし')
" 2>/dev/null || echo "")

EXEC_SUMMARY=$(claude -p "
あなたはK-POPメディア企業のCFO（ミュウツー）です。
以下の月次データをもとに、経営会議向けエグゼクティブサマリを生成せよ。

【対象月】${TARGET_MONTH}

【メトリクスデータ】
${METRICS_TEXT}

【経営目標】
${TARGETS}

【出力要件】
1. 月次総括（3行以内）
2. 重要KPIハイライト（投稿数・PV・収益・コストの要点）
3. 前月比コメント（データがあれば。なければ『初月のため前月比なし』）
4. カテゴリ別所見（好調/不調カテゴリ）
5. トークンコスト評価（削減余地の有無）
6. 来月の注力提案（2-3点）
7. リスク・懸念事項

簡潔・実用的に。経営者が1分で把握できる形式で。
" 2>/dev/null || echo "エグゼクティブサマリ生成失敗")

echo "$EXEC_SUMMARY"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [3] レポート保存
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REPORT_FILE="$REPORT_DIR/${TARGET_MONTH}_monthly.md"
cat > "$REPORT_FILE" << REPORT
# 月次経営レポート: ${TARGET_MONTH}
生成日: ${TODAY}

## メトリクス
${METRICS_TEXT}

## エグゼクティブサマリ
${EXEC_SUMMARY}
REPORT

echo ""
echo "  保存先: $REPORT_FILE"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [4] Discord通知
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "=== [4] Discord通知 ==="

DISCORD_URL="${DISCORD_WEBHOOK:-}"
if [ -z "$DISCORD_URL" ] && [ -f ~/.kpop_discord_webhook ]; then
  DISCORD_URL=$(cat ~/.kpop_discord_webhook | tr -d '[:space:]')
fi

if [ -n "$DISCORD_URL" ]; then
  # メトリクスから主要数値を抽出
  TOTAL_POSTS=$(echo "$METRICS_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('posts',{}).get('total',0))" 2>/dev/null || echo "0")
  TOTAL_PV=$(echo "$METRICS_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(f\"{d.get('traffic',{}).get('total_pv',0):,}\")" 2>/dev/null || echo "0")
  REVENUE=$(echo "$METRICS_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(f\"{d.get('revenue',{}).get('total_jpy',0):,.0f}\")" 2>/dev/null || echo "0")
  TOKEN_COST=$(echo "$METRICS_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(f\"{d.get('tokens',{}).get('cost_jpy',0):.0f}\")" 2>/dev/null || echo "0")
  PROFIT=$(echo "$METRICS_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(f\"{d.get('cost_vs_revenue',{}).get('profit_jpy',0):,.0f}\")" 2>/dev/null || echo "0")
  ROI=$(echo "$METRICS_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('cost_vs_revenue',{}).get('roi',0))" 2>/dev/null || echo "0")

  # サマリを1024文字に制限
  SUMMARY_SHORT=$(echo "$EXEC_SUMMARY" | head -c 1024)

  DISCORD_JSON=$(python3 - <<PYEOF
import json
fields = [
    {"name": "📝 投稿数", "value": "$TOTAL_POSTS 本", "inline": True},
    {"name": "👀 総PV", "value": "$TOTAL_PV", "inline": True},
    {"name": "💰 売上", "value": "${REVENUE}円", "inline": True},
    {"name": "🔧 トークンコスト", "value": "${TOKEN_COST}円", "inline": True},
    {"name": "📈 粗利", "value": "${PROFIT}円", "inline": True},
    {"name": "📊 ROI", "value": "${ROI}%", "inline": True},
]
summary = """$SUMMARY_SHORT"""
if summary.strip():
    fields.append({"name": "📋 エグゼクティブサマリ", "value": summary[:1024], "inline": False})

print(json.dumps({
    "embeds": [{
        "title": "📊 月次経営レポート | $TARGET_MONTH",
        "color": 3447003,
        "fields": fields,
        "footer": {"text": "K-POP AI Company - CFO ミュウツー"}
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
echo " 月次経営レポート完了: ${TARGET_MONTH}"
echo " 保存先: $REPORT_FILE"
echo "========================================"
