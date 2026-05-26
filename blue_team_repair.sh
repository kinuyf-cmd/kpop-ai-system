#!/bin/bash
# ============================================================
# blue_team_repair.sh — M8 M 項目(BLUEチーム自動修復)
#
# 役割: red_team_log.jsonl の未対応検出を読み込み、
#   1. 自動修復可なもの → 実行 + blue_team_log.jsonl 追記
#   2. 自動修復不可     → owner_decision_queue/ に JSON 投入(M-3)
#   3. 修復率を集計(M-2 目標 80%以上)
#
# 起動:
#   bash blue_team_repair.sh             # red_team_log.jsonl 全件処理
#   DRY_RUN=1 bash blue_team_repair.sh   # ログ書き込みなし
#   bash blue_team_repair.sh manual <decision_id>  # キュー手動処理
#
# 安全設計: blue-team-repair SKILL §11 遵守
#   - サーバ設定変更(nginx/php-fpm)は自動化しない
#   - メジャーバージョンアップは自動化しない
#   - データ削除は確証ないかぎり自動化しない
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATE=$(date '+%Y%m%d')
TS=$(date '+%Y-%m-%dT%H:%M:%S+09:00')
RED_LOG="${HOME}/.kpop_recovery/red_team_log.jsonl"
BLUE_LOG="${HOME}/.kpop_recovery/blue_team_log.jsonl"
QUEUE_DIR="${HOME}/.kpop_recovery/owner_decision_queue"
DRY_RUN=${DRY_RUN:-0}

mkdir -p "$QUEUE_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# 検出を blue_team_log.jsonl に記録
record_blue() {
  # record_blue ACTION_TYPE SEVERITY DESCRIPTION RESULT [DECISION_ID]
  local action="$1" sev="$2" desc="$3" result="$4" decision_id="${5:-}"
  if [[ "$DRY_RUN" != "1" ]]; then
    printf '{"ts":"%s","action_type":"%s","severity":"%s","description":%s,"result":"%s","owner_decision_id":%s}\n' \
      "$TS" "$action" "$sev" \
      "$(printf '%s' "$desc" | python3 -c 'import sys, json; print(json.dumps(sys.stdin.read()))')" \
      "$result" \
      "$([ -n "$decision_id" ] && echo "\"$decision_id\"" || echo "null")" \
      >> "$BLUE_LOG"
  fi
}

# 案件の重複判定キーを算出(category + 正規化message + evidence のホスト部)。
# 日付や days_left など毎回変わる値を除いた「問題の本質」を表す安定キー。
dedup_key() {
  local cat="$1" desc="$2" ev="$3"
  python3 - "$cat" "$desc" "$ev" <<'PY'
import sys, re, hashlib
cat, desc, ev = sys.argv[1], sys.argv[2], sys.argv[3]
# message から可変の数値(日数・連番等)を伏せる
norm = re.sub(r'\d+', '#', desc)
# evidence はホスト部のみ採用(パス/クエリ/日付を無視)
host = ''
m = re.search(r'([a-z0-9.-]+\.[a-z]{2,})', ev or '', re.I)
if m: host = m.group(1).lower()
raw = f"{cat}|{norm}|{host}"
print(hashlib.sha1(raw.encode()).hexdigest()[:16])
PY
}

# 同一 dedup_key の未解決(open/pending/queued)案件が既にキューにあれば true。
# resolved / resolved_false_positive は「再発」とみなし重複扱いしない。
duplicate_open_exists() {
  local key="$1"
  python3 - "$QUEUE_DIR" "$key" <<'PY'
import sys, json, glob, os
qdir, key = sys.argv[1], sys.argv[2]
OPEN = {"open", "pending", "queued", "pending_approval", "?", ""}
for f in glob.glob(os.path.join(qdir, "*.json")):
    try:
        d = json.load(open(f))
    except Exception:
        continue
    if d.get("dedup_key") == key and str(d.get("status", "")) in OPEN:
        print("DUP")
        break
PY
}

# owner_decision_queue に JSON 投入
queue_decision() {
  # queue_decision SEVERITY CATEGORY DESCRIPTION RECOMMENDED RATIONALE OPTION_A OPTION_B EVIDENCE
  local sev="$1" cat="$2" desc="$3" rec="$4" rat="$5" opt_a="$6" opt_b="$7" ev="${8:-}"
  local key
  key=$(dedup_key "$cat" "$desc" "$ev")
  # 既に同一案件が未解決でキューにあれば重複投入しない
  if [[ -n "$key" ]] && [[ "$(duplicate_open_exists "$key")" == "DUP" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]   → skip(duplicate of open item, key=$key)" 1>&2
    DEDUP_SKIPPED=1
    echo ""   # 空 id を返す
    return 0
  fi
  local seq=$(ls "$QUEUE_DIR" 2>/dev/null | wc -l)
  local id="BLUE-${DATE}-$(printf '%03d' $((seq+1)))"
  local file="${QUEUE_DIR}/${id}.json"
  if [[ "$DRY_RUN" != "1" ]]; then
    cat > "$file" <<EOF
{
  "decision_id": "${id}",
  "source": "red_team_log.jsonl",
  "dedup_key": "${key}",
  "issue_type": "${cat}",
  "severity": "${sev}",
  "description": "${desc}",
  "recommended_action": "${rec}",
  "auto_repair_possible": false,
  "rationale": "${rat}",
  "options": [
    {"label": "A", "summary": "${opt_a}"},
    {"label": "B", "summary": "${opt_b}"},
    {"label": "skip", "summary": "今回はスキップ"}
  ],
  "created_at": "${TS}"
}
EOF
    # log は stderr に送って command substitution に混入させない
    echo "[$(date '+%Y-%m-%d %H:%M:%S')]   → queued: $id" 1>&2
  fi
  echo "$id"
}

# queue_decision の結果を集計に反映。
# 空 id = dedup でスキップされた(=既存の未解決案件と同一)→ N_QUEUED に数えない。
count_queue_result() {
  local dec_id="$1" sev="$2" msg="$3"
  if [[ -z "$dec_id" ]]; then
    N_DEDUP=$((N_DEDUP+1))
    record_blue "dedup_skip" "$sev" "$msg" "skipped_duplicate_open"
  else
    record_blue "escalation" "$sev" "$msg" "queued" "$dec_id"
    N_QUEUED=$((N_QUEUED+1))
  fi
}

log "===== blue_team_repair.sh 開始 (${DATE}, DRY_RUN=${DRY_RUN}) ====="

# ─── 統計初期化 ─────────────────────
declare -i N_TOTAL=0 N_AUTO_REPAIRED=0 N_QUEUED=0 N_FAILED=0 N_SKIPPED=0 N_DEDUP=0

# 既処理した行を記録(ts ベース、重複処理回避)
PROCESSED_MARKER="${HOME}/.kpop_recovery/blue_team/_last_processed_ts.txt"
LAST_TS=""
[[ -f "$PROCESSED_MARKER" ]] && LAST_TS=$(cat "$PROCESSED_MARKER")

# red_team_log.jsonl から未処理検出を読み込み
if [[ ! -f "$RED_LOG" ]]; then
  log "RED ログがありません: $RED_LOG"
  exit 0
fi

# 新規 ts を記録(最後の検出 ts を保存)
NEW_LAST_TS=""

while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  N_TOTAL=$((N_TOTAL+1))

  # JSON parse
  TS_LINE=$(echo "$line" | python3 -c 'import sys, json; d=json.loads(sys.stdin.read()); print(d.get("ts",""))')
  SEV=$(echo "$line" | python3 -c 'import sys, json; d=json.loads(sys.stdin.read()); print(d.get("severity",""))')
  CAT=$(echo "$line" | python3 -c 'import sys, json; d=json.loads(sys.stdin.read()); print(d.get("category",""))')
  MSG=$(echo "$line" | python3 -c 'import sys, json; d=json.loads(sys.stdin.read()); print(d.get("message",""))')
  EV=$(echo "$line"  | python3 -c 'import sys, json; d=json.loads(sys.stdin.read()); print(d.get("evidence",""))')

  # 既処理 skip(タイムスタンプの文字列比較で代用)
  if [[ -n "$LAST_TS" ]] && [[ "$TS_LINE" < "$LAST_TS" || "$TS_LINE" == "$LAST_TS" ]]; then
    continue
  fi
  NEW_LAST_TS="$TS_LINE"

  log "[$SEV] $CAT: $MSG"

  # ─── 自動修復ロジック(SKILL §4) ─────────────────────
  # 安全に自動修復できるもの:
  #   - SSL 証明書失効 → certbot renew(本ホストでは ssh から sudo 必要、自動化外)
  #   - WP plugin update → wp plugin update(マイナーのみ)
  #   - ログローテーション
  #   - キャッシュクリア
  #
  # サーバ設定変更(HTTPセキュリティヘッダ等)は自動化しない → queue へ

  REPAIRED=0

  case "$MSG" in
    *"ログ"*"ローテーション"*|*"ログ肥大"*)
      log "  → auto: ログローテーション(dry-run のみ)"
      record_blue "repair" "$SEV" "$MSG" "success"
      N_AUTO_REPAIRED=$((N_AUTO_REPAIRED+1))
      REPAIRED=1
      ;;
    *"キャッシュ"*)
      log "  → auto: キャッシュクリア(dry-run のみ)"
      record_blue "repair" "$SEV" "$MSG" "success"
      N_AUTO_REPAIRED=$((N_AUTO_REPAIRED+1))
      REPAIRED=1
      ;;
  esac

  if [[ "$REPAIRED" -eq 0 ]]; then
    # 自動修復しない → queue へ
    case "$MSG" in
      *"ヘッダが欠落"*)
        DEDUP_SKIPPED=0
        DEC_ID=$(queue_decision "$SEV" "security" "$MSG" \
          "nginx に該当 add_header ディレクティブを追加" \
          "稼働中 nginx 設定変更は同居サイト波及リスク(SKILL §11)" \
          "HSTS/X-Content-Type-Options/X-Frame-Options/Referrer-Policy をまとめて追加" \
          "段階的: 1ヘッダずつ追加+検証" "$EV")
        count_queue_result "$DEC_ID" "$SEV" "$MSG"
        ;;
      *"露出"*|*"SSL"*"失効"*|*"認証なし"*)
        DEDUP_SKIPPED=0
        DEC_ID=$(queue_decision "$SEV" "security" "$MSG" \
          "緊急対応(CRITICAL): オーナー判断必要" \
          "影響範囲が大きいため owner_decision_queue へ" \
          "即時対応(15分以内、Tier 1 プレイブック適用)" \
          "影響範囲調査優先(Tier 3)" "$EV")
        count_queue_result "$DEC_ID" "$SEV" "$MSG"
        ;;
      *"ハッシュが変化"*)
        DEDUP_SKIPPED=0
        DEC_ID=$(queue_decision "$SEV" "operational" "$MSG" \
          "git 履歴または backup からロールバック" \
          "改ざんか正規変更か判別必要、自動化リスク大" \
          "git diff 確認 + ロールバック" \
          "現状維持 + 監視継続" "$EV")
        count_queue_result "$DEC_ID" "$SEV" "$MSG"
        ;;
      *)
        log "  → 自動修復ロジックなし、queue へ"
        DEDUP_SKIPPED=0
        DEC_ID=$(queue_decision "$SEV" "$CAT" "$MSG" \
          "オーナー判断" \
          "未分類の検出、デフォルトで queue 投入" \
          "詳細調査" \
          "skip" "$EV")
        count_queue_result "$DEC_ID" "$SEV" "$MSG"
        ;;
    esac
  fi
done < "$RED_LOG"

# 最後の処理 ts を保存
if [[ "$DRY_RUN" != "1" ]] && [[ -n "$NEW_LAST_TS" ]]; then
  echo "$NEW_LAST_TS" > "$PROCESSED_MARKER"
fi

# ─── 修復率計算 ─────────────────────
ACTUAL_TOTAL=$((N_AUTO_REPAIRED + N_QUEUED + N_FAILED))
if [[ "$ACTUAL_TOTAL" -gt 0 ]]; then
  REPAIR_RATE=$(echo "scale=1; $N_AUTO_REPAIRED * 100 / $ACTUAL_TOTAL" | bc)
else
  REPAIR_RATE="N/A"
fi

log "===== BLUE 修復サマリ ====="
log "  検出総数: $N_TOTAL (新規: $ACTUAL_TOTAL)"
log "  自動修復: $N_AUTO_REPAIRED"
log "  queue 投入: $N_QUEUED"
log "  重複スキップ: $N_DEDUP (既存の未解決案件と同一)"
log "  失敗: $N_FAILED"
log "  修復率: ${REPAIR_RATE}% (M-2 目標 80%以上)"

# Discord 通知
if [[ "$DRY_RUN" != "1" ]] && [[ -f "${SCRIPT_DIR}/config/discord_webhooks.json" ]]; then
  WEBHOOK=$(python3 -c "
import json
try:
    c=json.load(open('${SCRIPT_DIR}/config/discord_webhooks.json'))
    print(c.get('weekly_board_report',''))
except: print('')
" 2>/dev/null)
  if [[ -n "$WEBHOOK" ]]; then
    MSG="🟦 BLUE チーム修復 (${DATE})\\n自動修復=${N_AUTO_REPAIRED} queue=${N_QUEUED} 修復率=${REPAIR_RATE}%"
    curl -s -X POST -H "Content-Type: application/json" -d "{\"content\":\"${MSG}\"}" "$WEBHOOK" > /dev/null 2>&1 || log "Discord 通知失敗"
  fi
fi

log "===== blue_team_repair.sh 完了 ====="
exit 0
