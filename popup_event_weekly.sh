#!/bin/bash
# ============================================================
# popup_event_weekly.sh — M7 段階7.7 週次 Popup/Event 自動収集 cron
#
# 役割:
#   1. lib/popup_event_fetcher.py で PRTIMES + eplus からシグナル取得
#   2. シグナル JSON が出力されたら lib/popup_event_to_post.py で投稿
#   3. ログ + 件数を weekly_board_report webhook(失効中はログのみ)へ通知
#
# 起動:
#   bash popup_event_weekly.sh             # 通常実行
#   DRY_RUN=1 bash popup_event_weekly.sh   # 取得のみ、投稿しない
#
# crontab: 0 4 * * 1  /bin/bash /home/aiuser/kpop-ai-system/popup_event_weekly.sh
# (月曜 4時、audit_weekly.sh と同じ枠で動く)
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATE=$(date '+%Y%m%d')
SIGNAL_DIR="${HOME}/.kpop_recovery/popup_event_signals"
LOG_DIR="${HOME}/.kpop_recovery/popup_event_logs"
LOG_FILE="${LOG_DIR}/${DATE}.log"
RESULTS_FILE="${SIGNAL_DIR}/posted_${DATE}.json"

mkdir -p "$LOG_DIR" "$SIGNAL_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "===== popup_event_weekly.sh 開始 (DRY_RUN=${DRY_RUN:-0}) ====="

# ─── 1. シグナル取得 ───────────────────────────────────
log "Step 1: popup_event_fetcher.py 実行"
if ! python3 "${SCRIPT_DIR}/lib/popup_event_fetcher.py" 2>&1 | tee -a "$LOG_FILE"; then
  log "fetcher 異常終了。中断"
  exit 1
fi

SIG_FILE="${SIGNAL_DIR}/${DATE}.json"
if [[ ! -s "$SIG_FILE" ]]; then
  log "シグナル 0 件のため投稿スキップ(${SIG_FILE} 不在 or 空)"
  log "===== popup_event_weekly.sh 完了 (シグナル無し)====="
  exit 0
fi

# ─── 2. シグナル数 ─────────────────────────────────────
SIG_COUNT=$(python3 -c "import json; d=json.load(open('${SIG_FILE}')); print(d['counts']['total'])" 2>/dev/null || echo "?")
POPUP_COUNT=$(python3 -c "import json; d=json.load(open('${SIG_FILE}')); print(d['counts']['popup'])" 2>/dev/null || echo "?")
EVENT_COUNT=$(python3 -c "import json; d=json.load(open('${SIG_FILE}')); print(d['counts']['event'])" 2>/dev/null || echo "?")
log "Step 2: シグナル取得結果 total=${SIG_COUNT} popup=${POPUP_COUNT} event=${EVENT_COUNT}"

# ─── 3. 投稿 ───────────────────────────────────────────
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  log "Step 3: DRY_RUN=1 のため投稿スキップ"
else
  log "Step 3: popup_event_to_post.py 実行"
  # POST_RESULTS で投稿結果(post_id 一覧)を JSON 出力 → スモークテストが検証に使う
  if ! POST_RESULTS="$RESULTS_FILE" python3 "${SCRIPT_DIR}/lib/popup_event_to_post.py" "$SIG_FILE" 2>&1 | tee -a "$LOG_FILE"; then
    log "投稿スクリプト 異常終了"
    exit 1
  fi
fi

# ─── 4. Discord 通知(weekly_board_report、失効中はログのみ)───
WEBHOOK_URL=$(python3 -c "
import json
try:
    c = json.load(open('${SCRIPT_DIR}/config/discord_webhooks.json'))
    print(c.get('weekly_board_report', ''))
except Exception:
    print('')
" 2>/dev/null)
if [[ -n "$WEBHOOK_URL" ]]; then
  MSG="📅 週次 Popup/Event 自動収集 (${DATE})\\n取得: total=${SIG_COUNT} (popup=${POPUP_COUNT}, event=${EVENT_COUNT})"
  curl -s -X POST -H "Content-Type: application/json" \
    -d "{\"content\": \"${MSG}\"}" \
    "$WEBHOOK_URL" > /dev/null 2>&1 || log "Discord 通知失敗(webhook 失効?)"
fi

# ─── 5. スモークテスト(タスク#27)──────────────────────
# 収集・投稿結果を検証し、異常を [SMOKE-FAIL] で cron.log に明示。
# 専用スクリプトに切り出し済。常に exit 0 なので weekly を止めない。
log "Step 5: popup_smoke_test.sh 実行"
DRY_RUN="${DRY_RUN:-0}" bash "${SCRIPT_DIR}/popup_smoke_test.sh" \
  "$SIG_FILE" "$RESULTS_FILE" "$LOG_FILE" 2>&1 | tee -a "$LOG_FILE" || true

log "===== popup_event_weekly.sh 完了 ====="
exit 0
