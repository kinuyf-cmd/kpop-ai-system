#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# daily_data_collect.sh - 日次データ収集・KPIログ出力
# データ本部（ミュウツー）管轄
# 毎日 6:00 に実行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SCRIPT_DIR/env_loader.sh"

LOGS_DIR="$SCRIPT_DIR/logs"
TODAY=$(date '+%Y-%m-%d')

mkdir -p "$LOGS_DIR"

echo "=== 日次データ収集 ($TODAY) ==="

# 1. 既存のメトリクス取得（GSC/GA4/AdSense）
echo "[1/4] fetch_yesterday_metrics.py..."
cd "$SCRIPT_DIR"
source .venv/bin/activate 2>/dev/null || true
python3 google_metrics/fetch_yesterday_metrics.py 2>/dev/null || echo "  ⚠ metrics fetch failed"

# 2. 記事別メトリクス取得
echo "[2/4] data_collector.py (7日間)..."
python3 "$SCRIPT_DIR/lib/data_collector.py" 7 2>/dev/null || echo "  ⚠ data collector failed"

# 3. 日次KPIレポート生成
echo "[3/4] KPI daily report..."
python3 "$SCRIPT_DIR/lib/kpi_logger.py" daily "$TODAY" > "$LOGS_DIR/kpi_report_$TODAY.json" 2>/dev/null

# 4. GSC→記事URL紐付け (48h/7d/30d)
echo "[4/6] GSC→記事紐付け..."
python3 "$SCRIPT_DIR/lib/gsc_article_linker.py" 2>/dev/null || echo "  ⚠ GSC article linker failed"

# 5. 統合KPIストア (GSC+GA4+AdSense → kpi_daily.jsonl / kpi_articles.jsonl)
echo "[5/6] 統合KPIストア収集..."
python3 "$SCRIPT_DIR/lib/kpi_store.py" collect 2>/dev/null || echo "  ⚠ KPI store collect failed"

# 6. 異常検知
echo "[6/6] Anomaly check..."
python3 "$SCRIPT_DIR/lib/human_gate.py" health 2>/dev/null || echo "  ⚠ health check failed"

echo "✅ 日次データ収集完了"
