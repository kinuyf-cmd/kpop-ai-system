#!/bin/bash
# orchestration_run.sh — M10 P 統合実行(P-1/P-5 マルチエージェント並列+朝バッチ)
#
# orchestration-leader SKILL §6 の1日のフローを実装。
# ai_company/agent_council.sh は記事生成パイプラインの中核として既存稼働中。
# 本スクリプトはそれを含む KPOP 全エージェントの並列起動を統括する。
#
# 用途:
#   ./orchestration_run.sh                    # 全エージェント並列(朝バッチ想定)
#   ./orchestration_run.sh --suite morning    # 朝バッチのみ
#   ./orchestration_run.sh --dry-run          # 実行せず手順表示
#
# orchestration_state.json で各エージェント状態を管理。
# Webhook 通知は webhook_dispatcher.py、Outcomes 採点は outcomes_score.py。
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 99

STATE_FILE="$HOME/.kpop_recovery/orchestration_state.json"
LOG_DIR="$HOME/.kpop_recovery/orchestration_logs"
LOG_FILE="$LOG_DIR/run_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$LOG_DIR"

TS_ISO="$(date -Iseconds)"
SUITE="all"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --suite)  SUITE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//' | head -25; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

log() { echo "[$(date '+%H:%M:%S')] [ORCH] $*" | tee -a "$LOG_FILE"; }

log "Orchestration run START suite=$SUITE dry_run=$DRY_RUN"
START=$(date +%s)

# P-1 Multi-agent 並列実行: バックグラウンドで起動
# 各エージェントは独立した cron で動いているが、ここでは「同期的に1サイクル」走らせる
declare -A AGENT_PIDS=()
declare -A AGENT_STATUS=()

start_agent() {
  local name="$1"; shift
  local cmd="$*"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "  [DRY] would start: $name → $cmd"
    AGENT_STATUS[$name]="dryrun"
    return
  fi
  log "  starting: $name"
  ( $cmd ) >> "$LOG_DIR/${name}_$(date +%Y%m%d).log" 2>&1 &
  AGENT_PIDS[$name]=$!
  AGENT_STATUS[$name]="running"
}

case "$SUITE" in
  morning|all)
    # 朝バッチで並列起動するエージェント群(P-5)
    start_agent "audit_daily"     "bash $ROOT/audit_daily.sh"
    start_agent "kpi_dashboard"   "bash $ROOT/ceo_morning_brief.sh"
    start_agent "qa_unit"         "bash $ROOT/qa_test_run.sh --suite unit --trigger orch"
    start_agent "skill_metrics"   "bash $ROOT/skill_metrics_collect.sh"
    ;;
  weekly)
    start_agent "red_team"        "bash $ROOT/red_team_scan.sh"
    start_agent "blue_team"       "bash $ROOT/blue_team_repair.sh"
    start_agent "qa_full"         "bash $ROOT/qa_test_run.sh --suite all --trigger orch_weekly"
    start_agent "skill_pattern"   "bash $ROOT/skill_pattern_detector.sh"
    start_agent "skill_report"    "bash $ROOT/skill_effect_report.sh"
    ;;
  *) log "unknown suite: $SUITE"; exit 2 ;;
esac

# 並列待機(P-1 並列実行の証跡: 同時刻に複数 PID が稼働)
log "Waiting for ${#AGENT_PIDS[@]} agents to finish (parallel run)"
for name in "${!AGENT_PIDS[@]}"; do
  pid="${AGENT_PIDS[$name]}"
  if wait "$pid"; then
    AGENT_STATUS[$name]="success"
  else
    AGENT_STATUS[$name]="failed"
  fi
  log "  agent finished: $name = ${AGENT_STATUS[$name]}"
done

END=$(date +%s)
DUR=$((END - START))

# orchestration_state.json 更新 — associative array を tsv で渡す
TSV=$(mktemp)
for name in "${!AGENT_STATUS[@]}"; do
  printf "%s\t%s\n" "$name" "${AGENT_STATUS[$name]}" >> "$TSV"
done

python3 - "$STATE_FILE" "$SUITE" "$DUR" "$TSV" <<'PY'
import json, os, sys
from datetime import datetime, timezone, timedelta

state_file = os.path.expanduser(sys.argv[1])
suite      = sys.argv[2]
dur        = int(sys.argv[3])
tsv        = sys.argv[4]

now = datetime.now(timezone(timedelta(hours=9))).isoformat()
if os.path.exists(state_file):
    try:
        state = json.load(open(state_file))
    except json.JSONDecodeError:
        state = {}
else:
    state = {}
state.setdefault("agents", {})
state.setdefault("active_workflows", [])
state.setdefault("pending_decisions", [])
state.setdefault("outcomes_scores", {})

agent_map = {}
if os.path.exists(tsv):
    for line in open(tsv):
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 2 and parts[0]:
            agent_map[parts[0]] = parts[1]

for name, status in agent_map.items():
    state["agents"][name] = {"status": status, "last_run": now, "duration_seconds": dur}

state["last_orchestration_run"] = {
    "timestamp": now, "suite": suite, "duration_seconds": dur, "agent_count": len(agent_map)
}

with open(state_file, "w") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)
print(f"  state file updated: {state_file}")
PY
rm -f "$TSV"

# サマリ
SUCCESS=0; FAILED=0
for s in "${AGENT_STATUS[@]}"; do
  case "$s" in
    success|dryrun) SUCCESS=$((SUCCESS+1)) ;;
    failed) FAILED=$((FAILED+1)) ;;
  esac
done

log "ORCHESTRATION SUMMARY"
log "  suite          : $SUITE"
log "  agents started : ${#AGENT_PIDS[@]} (parallel)"
log "  success        : $SUCCESS"
log "  failed         : $FAILED"
log "  duration       : ${DUR}s"
log "  state          : $STATE_FILE"

# Outcomes 採点呼び出し(P-2)
if [[ -x "$ROOT/outcomes_score.py" ]]; then
  log "  outcomes scoring..."
  python3 "$ROOT/outcomes_score.py" --suite "$SUITE" >> "$LOG_FILE" 2>&1 || log "    (outcomes_score failed, non-blocking)"
fi

# Webhook 通知(P-3)
if [[ -x "$ROOT/webhook_dispatcher.py" ]]; then
  log "  webhook dispatch..."
  python3 "$ROOT/webhook_dispatcher.py" --event orchestration_complete --suite "$SUITE" --success "$SUCCESS" --failed "$FAILED" >> "$LOG_FILE" 2>&1 || log "    (webhook failed, non-blocking)"
fi

# 失敗時 blue_team に連携
if [[ "$FAILED" -gt 0 ]]; then
  log "  ! $FAILED agent(s) failed, queueing for blue_team_repair"
fi

exit $FAILED
