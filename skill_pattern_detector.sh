#!/bin/bash
# skill_pattern_detector.sh — O-2 繰り返しタスク検出(M9)
#
# audit/red/blue ログから繰り返しパターンを検出し、
# 「3 回以上同じ操作 = 新 skill 化候補」を出力する。
# Bash 履歴は走査しない(プライバシー回避)。
#
# 検出ソース:
#   - ~/.kpop_recovery/audit_log.jsonl
#   - ~/.kpop_recovery/red_team_log.jsonl
#   - ~/.kpop_recovery/blue_team_log.jsonl
#   - crontab(週次以上の自動化済み = 候補から除外)
#
# 出力:
#   標準出力: 候補一覧
#   ~/.kpop_recovery/skill_candidates_YYYYMMDD.json
set -uo pipefail

LOG_DIR="$HOME/.kpop_recovery"
TS="$(date +%Y%m%d)"
OUT_FILE="$LOG_DIR/skill_candidates_${TS}.json"

# 既に skill 化済みのキーワード(候補から除外)
EXISTING_SKILLS=$(ls "$HOME/.claude/skills/" 2>/dev/null | tr '\n' '|' | sed 's/|$//')

# 関連 jsonl から「action」「type」フィールドを抽出してカウント
TMP=$(mktemp)
trap 'rm -f $TMP' EXIT

for log in "$LOG_DIR/audit_log.jsonl" "$LOG_DIR/red_team_log.jsonl" "$LOG_DIR/blue_team_log.jsonl" "$LOG_DIR/qa_test_log.jsonl" "$LOG_DIR/sanitize_log.jsonl"; do
  [[ ! -f "$log" ]] && continue
  # 単純抽出: "action":"<val>" or "type":"<val>" or "category":"<val>"
  grep -oE '"(action|type|category|suite|trigger)":"[^"]+"' "$log" 2>/dev/null >> "$TMP"
done

# 集計: 3 回以上のキーワードを候補化
CANDIDATES=$(sort "$TMP" | uniq -c | sort -rn | awk '$1 >= 3 {print $0}')

# crontab 自動化済みエントリと突き合わせ
CRONJOBS=$(crontab -l 2>/dev/null | grep -v '^#' | grep -v '^$')

# JSON 出力
echo "{" > "$OUT_FILE"
echo "  \"detected_at\": \"$(date -Iseconds)\"," >> "$OUT_FILE"
echo "  \"candidates\": [" >> "$OUT_FILE"

FIRST=1
COUNT=0
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  freq=$(echo "$line" | awk '{print $1}')
  pattern=$(echo "$line" | sed 's/^ *[0-9]* //')
  # キー名と値を分離
  key=$(echo "$pattern" | sed -E 's/^"([^"]+)":.*/\1/')
  val=$(echo "$pattern" | sed -E 's/^"[^"]+":"([^"]+)"$/\1/')

  # 既存 skill 化済みなら除外
  if [[ -n "$EXISTING_SKILLS" ]] && echo "$val" | grep -qE "^($EXISTING_SKILLS)$"; then
    continue
  fi

  if [[ $FIRST -eq 0 ]]; then
    echo "    ," >> "$OUT_FILE"
  fi
  cat >> "$OUT_FILE" <<EOF
    {
      "pattern_key": "$key",
      "pattern_value": "$val",
      "frequency": $freq,
      "skill_existing": false,
      "rationale": "観測回数 ${freq} (>=3) で繰り返しパターン。新規 skill 化候補。"
    }
EOF
  FIRST=0
  COUNT=$((COUNT + 1))
done <<< "$CANDIDATES"

echo "  ]," >> "$OUT_FILE"
echo "  \"total_candidates\": $COUNT," >> "$OUT_FILE"
echo "  \"sources\": [\"audit_log.jsonl\",\"red_team_log.jsonl\",\"blue_team_log.jsonl\",\"qa_test_log.jsonl\",\"sanitize_log.jsonl\"]," >> "$OUT_FILE"
echo "  \"note\": \"頻度 >=3 のキーワードのみ候補化。既存 skill にカバーされたものは除外。\"" >> "$OUT_FILE"
echo "}" >> "$OUT_FILE"

echo "SKILL PATTERN DETECTOR"
echo "  candidates : $COUNT"
echo "  output     : $OUT_FILE"
[[ $COUNT -gt 0 ]] && head -40 "$OUT_FILE"
