#!/bin/bash
# run_dashboard_refresh.sh
# 日中2時間おきダッシュボード更新スクリプト
# 09:00 / 11:00 / 13:00 / 15:00 / 17:00 / 19:00 / 21:00 JST (および 03:00 深夜フル更新)
#
# 動作:
#   1. flock で多重起動防止
#   2. intraday KPI スナップショット追記 (kpi_dashboard_builder.py)
#   3. generate_dashboard.py でHTML生成
#   4. lib/deploy_dashboard.py でWordPressへデプロイ
#   5. 成功/失敗を logs/dashboard_refresh.log に記録

set -euo pipefail

BASE_DIR="/home/aiuser/kpop-ai-system"
LOCK_FILE="/tmp/dashboard_refresh.lock"
LOG_FILE="${BASE_DIR}/logs/dashboard_refresh.log"
VENV="${BASE_DIR}/.venv/bin/activate"

cd "${BASE_DIR}"

# ─── ログ出力関数 ───
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S JST')] $*" | tee -a "${LOG_FILE}"
}

# ─── flock で多重起動防止 (タイムアウト60秒) ───
exec 200>"${LOCK_FILE}"
if ! flock -w 60 200; then
    log "ERROR: 多重起動防止 — 他のdashboard_refreshが実行中のため終了 (lock timeout)"
    exit 1
fi

log "=== dashboard_refresh 開始 ==="

# ─── Python仮想環境を有効化 ───
if [ -f "${VENV}" ]; then
    source "${VENV}"
fi
export PATH="/home/aiuser/.local/bin:${PATH}"

# ─── フェーズ1: intraday スナップショット追記 ───
log "フェーズ1: intraday KPI スナップショット追記..."
if python3 -c "
import sys
sys.path.insert(0, '${BASE_DIR}/lib')
from kpi_dashboard_builder import build_kpi_sections, append_intraday_snapshot, collect_daily_actuals, get_daily_targets, save_monthly_snapshot, collect_monthly_actuals, get_monthly_targets, project_month_end
from datetime import datetime

daily_targets = get_daily_targets()
daily_actuals = collect_daily_actuals()
monthly_targets = get_monthly_targets()
monthly_actuals = collect_monthly_actuals()

append_intraday_snapshot(daily_actuals, daily_targets)

from datetime import datetime as _dt
today_date = _dt.now()
projections = {}
for k in ['posts', 'x_posts', 'index_requests', 'rewrites', 'win_articles', 'ctr_actions']:
    projections[k] = project_month_end(monthly_actuals.get(k, 0), today_date)
save_monthly_snapshot(monthly_actuals, monthly_targets, projections)
print('intraday snapshot OK')
" >> "${LOG_FILE}" 2>&1; then
    log "フェーズ1: OK — intraday スナップ追記完了"
else
    log "WARNING フェーズ1: intraday スナップ追記でエラー (exit=$?) — 続行します"
fi

# ─── フェーズ2: ダッシュボードHTML生成 ───
log "フェーズ2: generate_dashboard.py 実行..."
if python3 "${BASE_DIR}/generate_dashboard.py" >> "${LOG_FILE}" 2>&1; then
    log "フェーズ2: OK — dashboard generated"
else
    EXIT_CODE=$?
    log "ERROR フェーズ2: generate_dashboard.py 失敗 (exit=${EXIT_CODE})"
    exit "${EXIT_CODE}"
fi

# ─── フェーズ3: WordPressへデプロイ ───
log "フェーズ3: lib/deploy_dashboard.py 実行..."
if python3 "${BASE_DIR}/lib/deploy_dashboard.py" >> "${LOG_FILE}" 2>&1; then
    log "フェーズ3: OK — dashboard deployed"
else
    EXIT_CODE=$?
    log "ERROR フェーズ3: deploy_dashboard.py 失敗 (exit=${EXIT_CODE})"
    exit "${EXIT_CODE}"
fi

log "=== dashboard_refresh 完了 ==="
