#!/bin/bash
# qa_test_run.sh — N項目 QA テスト統合ランナー(M9)
#
# 用途:
#   ./qa_test_run.sh                 # unit + regression のみ(E2E は skip)
#   ./qa_test_run.sh --e2e           # unit + regression + E2E(stg接続)
#   ./qa_test_run.sh --suite unit    # unit のみ
#   ./qa_test_run.sh --suite regression
#   ./qa_test_run.sh --suite e2e
#
# ログ:
#   ~/.kpop_recovery/qa_test_log.jsonl  (1行1実行)
#
# qa-test-generator SKILL.md §6 cron 用途:
#   日次 03:00: unit + regression
#   週次 日曜 02:00: 全部(unit + regression + E2E)
#
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 99

QA_LOG_DIR="$HOME/.kpop_recovery"
QA_LOG="$QA_LOG_DIR/qa_test_log.jsonl"
mkdir -p "$QA_LOG_DIR"

TS_ISO="$(date -Iseconds)"
TRIGGER="${QA_TRIGGER:-manual}"
SUITE="all"
E2E=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --e2e)        E2E=1; shift ;;
    --suite)      SUITE="$2"; shift 2 ;;
    --trigger)    TRIGGER="$2"; shift 2 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//' | head -25
      exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# 環境変数で E2E 有効化(コマンドフラグ優先)
if [[ "$E2E" == "1" || "$SUITE" == "e2e" || "$SUITE" == "all" && "${QA_FULL:-0}" == "1" ]]; then
  export KPOP_E2E_ENABLE=1
else
  unset KPOP_E2E_ENABLE
fi

PYTEST_TARGETS=()
case "$SUITE" in
  unit)        PYTEST_TARGETS=(tests/unit) ;;
  regression)  PYTEST_TARGETS=(tests/regression) ;;
  e2e)         PYTEST_TARGETS=(tests/e2e); export KPOP_E2E_ENABLE=1 ;;
  all)         PYTEST_TARGETS=(tests/unit tests/regression) ;;
  *) echo "unknown suite: $SUITE" >&2; exit 2 ;;
esac

START=$(date +%s)
# pytest を実行(JSON レポート風に各テスト結果を集計)
PYTEST_OUT=$(python3 -m pytest "${PYTEST_TARGETS[@]}" --tb=short -q 2>&1)
EXIT=$?
END=$(date +%s)
DUR=$((END - START))

# 集計: pytest の最終行 "N passed, M failed" を抜き出す
SUMMARY=$(echo "$PYTEST_OUT" | tail -1)
PASSED=$(echo "$SUMMARY" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo "0")
FAILED=$(echo "$SUMMARY" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo "0")
SKIPPED=$(echo "$SUMMARY" | grep -oE '[0-9]+ skipped' | grep -oE '[0-9]+' || echo "0")
TOTAL=$((PASSED + FAILED + SKIPPED))

# 失敗テスト名抽出
FAILURES_JSON="[]"
if [[ "$FAILED" -gt 0 ]]; then
  FAILURES=$(echo "$PYTEST_OUT" | grep -E '^FAILED ' | head -20 | sed 's/"/\\"/g' | awk '{printf "{\"test\":\"%s\"},", $0}' | sed 's/,$//')
  FAILURES_JSON="[${FAILURES}]"
fi

# JSONL ログ
LOG_LINE=$(cat <<EOF
{"timestamp":"$TS_ISO","trigger":"$TRIGGER","suite":"$SUITE","e2e_enabled":${KPOP_E2E_ENABLE:-0},"total":$TOTAL,"passed":$PASSED,"failed":$FAILED,"skipped":$SKIPPED,"duration_seconds":$DUR,"exit_code":$EXIT,"failures":$FAILURES_JSON}
EOF
)
echo "$LOG_LINE" >> "$QA_LOG"

# 標準出力サマリ
echo "QA TEST SUMMARY"
echo "  suite     : $SUITE"
echo "  total     : $TOTAL"
echo "  passed    : $PASSED"
echo "  failed    : $FAILED"
echo "  skipped   : $SKIPPED"
echo "  duration  : ${DUR}s"
echo "  exit code : $EXIT"
echo "  log       : $QA_LOG"

# 失敗があれば blue_team_repair.sh に連携(N-4 連携)
if [[ "$FAILED" -gt 0 ]]; then
  if [[ -x "$ROOT/blue_team_repair.sh" ]]; then
    QUEUE_DIR="$HOME/.kpop_recovery/owner_decision_queue"
    mkdir -p "$QUEUE_DIR"
    QUEUE_FILE="$QUEUE_DIR/QA-$(date +%Y%m%d-%H%M%S).json"
    cat > "$QUEUE_FILE" <<EOF2
{
  "id": "QA-$(date +%Y%m%d-%H%M%S)",
  "type": "qa_test_failure",
  "created_at": "$TS_ISO",
  "suite": "$SUITE",
  "failed_count": $FAILED,
  "failures": $FAILURES_JSON,
  "action": "investigate and fix failing tests",
  "blue_team_notified": true
}
EOF2
    echo "  queue     : $QUEUE_FILE"
  fi
fi

# 100% pass が望ましいが、skipped は許容
exit $EXIT
