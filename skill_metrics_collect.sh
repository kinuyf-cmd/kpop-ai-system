#!/bin/bash
# skill_metrics_collect.sh — O-3 既存 skill の効果計測(M9)
#
# ~/.claude/skills/ 配下の全 skill をスキャンし、
# 各 skill のメタ情報(行数、最終更新、ファイル参照頻度、JSONL ログ件数)を
# skill_metrics.jsonl に追記する。
#
# 用途:
#   ./skill_metrics_collect.sh                 # 全 skill
#   ./skill_metrics_collect.sh <skill_name>    # 指定 skill のみ
#
# 出力: ~/.kpop_recovery/skill_metrics.jsonl(1行1スキル1スナップショット)
set -uo pipefail

SKILLS_DIR="$HOME/.claude/skills"
LOG_DIR="$HOME/.kpop_recovery"
LOG_FILE="$LOG_DIR/skill_metrics.jsonl"
mkdir -p "$LOG_DIR"

TS_ISO="$(date -Iseconds)"

# Skill ごとに集計
TARGET_SKILL="${1:-}"

if [[ -n "$TARGET_SKILL" ]]; then
  SKILL_DIRS=("$SKILLS_DIR/$TARGET_SKILL")
else
  SKILL_DIRS=("$SKILLS_DIR"/*/)
fi

COUNT=0
for d in "${SKILL_DIRS[@]}"; do
  [[ ! -d "$d" ]] && continue
  skill_name=$(basename "$d")
  skill_md="$d/SKILL.md"

  # 基本メタ
  if [[ -f "$skill_md" ]]; then
    line_count=$(wc -l < "$skill_md" | tr -d ' ')
    last_modified=$(date -r "$skill_md" -Iseconds 2>/dev/null || echo "unknown")
    size_bytes=$(stat -c%s "$skill_md" 2>/dev/null || echo 0)
  else
    line_count=0
    last_modified="missing"
    size_bytes=0
  fi

  # ファイル参照頻度(リポジトリ全体での skill 名出現回数)
  ref_count=$(grep -rsl "$skill_name" /home/aiuser/kpop-ai-system 2>/dev/null | wc -l | tr -d ' ')

  # JSONL ログ件数(該当 skill が関連するログがあるか)
  jsonl_log_count=0
  case "$skill_name" in
    "qa-test-generator")    jsonl_log_count=$([ -f "$LOG_DIR/qa_test_log.jsonl" ] && wc -l < "$LOG_DIR/qa_test_log.jsonl" || echo 0) ;;
    "red-team-auditor")     jsonl_log_count=$([ -f "$LOG_DIR/red_team_log.jsonl" ] && wc -l < "$LOG_DIR/red_team_log.jsonl" || echo 0) ;;
    "blue-team-repair")     jsonl_log_count=$([ -f "$LOG_DIR/blue_team_log.jsonl" ] && wc -l < "$LOG_DIR/blue_team_log.jsonl" || echo 0) ;;
    "audit-rules")          jsonl_log_count=$([ -f "$LOG_DIR/audit_log.jsonl" ] && wc -l < "$LOG_DIR/audit_log.jsonl" || echo 0) ;;
    "kpi-dashboard")        jsonl_log_count=$([ -f "$LOG_DIR/kpi_log.jsonl" ] && wc -l < "$LOG_DIR/kpi_log.jsonl" || echo 0) ;;
    "popup-collector")      jsonl_log_count=$(ls "$LOG_DIR/popup_event_signals/" 2>/dev/null | wc -l | tr -d ' ') ;;
    "kpop-citation-article")jsonl_log_count=$([ -f "$LOG_DIR/sanitize_log.jsonl" ] && wc -l < "$LOG_DIR/sanitize_log.jsonl" || echo 0) ;;
    *) jsonl_log_count=0 ;;
  esac

  # JSONL 行(整数値は数値、文字列はクオート)
  line="{\"timestamp\":\"$TS_ISO\",\"skill_name\":\"$skill_name\",\"line_count\":$line_count,\"size_bytes\":$size_bytes,\"last_modified\":\"$last_modified\",\"ref_count\":$ref_count,\"jsonl_log_count\":$jsonl_log_count}"
  echo "$line" >> "$LOG_FILE"
  COUNT=$((COUNT + 1))
done

echo "SKILL METRICS COLLECT"
echo "  collected : $COUNT skills"
echo "  log       : $LOG_FILE"
