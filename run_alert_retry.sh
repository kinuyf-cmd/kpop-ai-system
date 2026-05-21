#!/usr/bin/env bash
# run_alert_retry.sh — Discord通知キュー再送スクリプト
# CEO: ミュウツー / オーナー: 人間（閲覧専用）
#
# 役割:
#   logs/alert_queue.jsonl の pending 通知を再送する。
#   discord_notifier.py が送信失敗した通知が積まれているキューを処理する。
#
# 使い方:
#   bash run_alert_retry.sh           # 再送実行
#   bash run_alert_retry.sh --status  # キュー状態の表示のみ（送信しない）
#
# cron 例 (5分ごと):
#   */5 * * * * /home/aiuser/kpop-ai-system/run_alert_retry.sh --cron >> /home/aiuser/kpop-ai-system/logs/retry.log 2>&1

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/.venv/bin/activate"
[[ -f "$VENV" ]] && source "$VENV"
[[ -f "$SCRIPT_DIR/env_loader.sh" ]] && source "$SCRIPT_DIR/env_loader.sh" 2>/dev/null || true

MODE="${1:-}"

# ── --status: キュー状態の表示のみ ──
if [[ "$MODE" == "--status" ]]; then
  echo "=== アラートキュー状態 ==="
  python3 -c "
from lib.alert_queue import queue_status
s = queue_status()
print(f'  total:            {s[\"total\"]}件')
print(f'  pending:          {s[\"pending\"]}件')
print(f'  sent:             {s[\"sent\"]}件')
print(f'  permanent_failed: {s[\"permanent_failed\"]}件')
print(f'  CRITICAL_pending: {s[\"critical_pending\"]}件')
if s['critical_pending'] > 0:
    print()
    print('  ⚠️  CRITICAL通知がpendingです。run_alert_retry.sh を実行してください。')
"
  exit 0
fi

# ── cron モード: サイレント実行 ──
if [[ "$MODE" == "--cron" ]]; then
  RETRY_JSON=$(python3 "$SCRIPT_DIR/lib/alert_queue.py" --retry 2>&1 | tail -1)
  # pendingが残っていればログに出力
  PENDING=$(echo "$RETRY_JSON" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    r = d.get('queue_retry', d)
    print(r.get('pending', '?'))
except: print('?')
" 2>/dev/null || echo "?")
  if [[ "$PENDING" != "0" && "$PENDING" != "?" ]]; then
    echo "[retry] $(date '+%H:%M:%S') pending残=${PENDING}件"
  fi
  exit 0
fi

# ── 通常実行 ──
echo "========================================"
echo " K-POP Journal AI Company"
echo " アラートキュー再送システム"
echo " 実行: $(date '+%Y-%m-%d %H:%M:%S JST')"
echo "========================================"
echo ""

# キュー状態確認
echo "[PRE] キュー状態確認..."
python3 -c "
from lib.alert_queue import queue_status
s = queue_status()
print(f'  pending: {s[\"pending\"]}件 / total: {s[\"total\"]}件 / CRITICAL_pending: {s[\"critical_pending\"]}件')
"

echo ""
echo "[RETRY] pending 通知を再送..."
RETRY_JSON=$(python3 "$SCRIPT_DIR/lib/alert_queue.py" --retry 2>&1 | tee /dev/stderr | tail -1)

# サマリー抽出
RETRY_SENT=$(echo "$RETRY_JSON"    | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); r=d.get('queue_retry',d); print(r.get('sent',0))"             2>/dev/null || echo "?")
RETRY_FAIL=$(echo "$RETRY_JSON"    | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); r=d.get('queue_retry',d); print(r.get('failed',0))"            2>/dev/null || echo "?")
RETRY_PEND=$(echo "$RETRY_JSON"    | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); r=d.get('queue_retry',d); print(r.get('pending',0))"           2>/dev/null || echo "?")
RETRY_PERM=$(echo "$RETRY_JSON"    | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); r=d.get('queue_retry',d); print(r.get('permanent_failed',0))"  2>/dev/null || echo "?")

echo ""
echo "========================================"
echo "✅ 完了: $(date '+%H:%M:%S')"
echo ""
echo "  📬 再送サマリー:"
echo "     送信成功:     ${RETRY_SENT}件"
echo "     失敗(再試行): ${RETRY_FAIL}件"
echo "     pending残:    ${RETRY_PEND}件"
echo "     永続失敗:     ${RETRY_PERM}件"
[[ "$RETRY_PERM" != "0" && "$RETRY_PERM" != "?" ]] && \
  echo "     ⚠️  永続失敗があります。logs/alert_retry_history.jsonl を確認してください。"
echo "========================================"
