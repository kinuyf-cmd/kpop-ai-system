#!/bin/bash
# ============================================================
# popup_smoke_test.sh — タスク#27 Popup/Event 収集スモークテスト
#
# 役割: popup_event_weekly.sh の収集・投稿結果を検証し、異常を cron.log で
#       grep 可能な形(`[SMOKE-FAIL]`)で明示する。
#
# 検証項目:
#   1. シグナル数(total/popup/event)をログ
#   2. 投稿成功した post_id それぞれについて:
#        - HTTP 200(stg は BASIC 認証必須。/tmp/wp_stg.txt の資格情報を使用)
#        - popup の場合: popup_source_url ACF が入っている(citation-rules §8)
#        - popup の場合: category=popup が紐付いている
#   3. HARD_FAIL / 投稿0件 / HTTP エラー / ACF 欠落 / category 欠落 を
#      `[SMOKE-FAIL] <理由>` で出力
#   4. 結果サマリを smoke_YYYYMMDD.log に出力
#   5. 通知は既存 webhook(失効中でも握りつぶし)。ログは必ず残す。
#
# 引数(任意。weekly.sh から渡される):
#   $1 = signals.json のパス
#   $2 = posted results JSON のパス(popup_event_to_post.py の POST_RESULTS 出力)
#   $3 = 元実行ログ(weekly のログ。HARD_FAIL 検出に grep する)
#
# 引数省略時は当日の標準パスを推測する。
#
# 終了コード: 常に 0(cron を止めない)。失敗は [SMOKE-FAIL] 行と件数で表現。
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATE=$(date '+%Y%m%d')
SIGNAL_DIR="${HOME}/.kpop_recovery/popup_event_signals"
LOG_DIR="${HOME}/.kpop_recovery/popup_event_logs"
SMOKE_LOG="${LOG_DIR}/smoke_${DATE}.log"
STG_BASE="https://stg.kpopjournal.tokyo"
CREDS="/tmp/wp_stg.txt"

SIG_FILE="${1:-${SIGNAL_DIR}/${DATE}.json}"
RESULTS_FILE="${2:-${SIGNAL_DIR}/posted_${DATE}.json}"
SRC_LOG="${3:-${LOG_DIR}/${DATE}.log}"

mkdir -p "$LOG_DIR"

FAILS=0
slog() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$SMOKE_LOG"; }
fail() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [SMOKE-FAIL] $*" | tee -a "$SMOKE_LOG"; FAILS=$((FAILS+1)); }

slog "===== popup_smoke_test.sh 開始 (${DATE}) ====="
slog "signals=${SIG_FILE} results=${RESULTS_FILE} src_log=${SRC_LOG}"

# ─── DB ヘルパ(ACF / category 検証用) ─────────────────
mysql_q() {
  # $1 = SQL。資格情報が無い環境では空を返す(検証は HTTP のみへフォールバック)。
  [[ -f "$CREDS" ]] || { echo ""; return 0; }
  local U P DB
  U=$(grep -oE '^WP_DB_USER=.*'     "$CREDS" | cut -d= -f2-)
  P=$(grep -oE '^WP_DB_PASSWORD=.*' "$CREDS" | cut -d= -f2-)
  DB=$(grep -oE '^WP_DB_NAME=.*'    "$CREDS" | cut -d= -f2-)
  [[ -n "$U" && -n "$DB" ]] || { echo ""; return 0; }
  mysql --default-character-set=utf8mb4 -u "$U" -p"$P" "$DB" -N -e "$1" 2>/dev/null || echo ""
}

# ─── BASIC 認証付き HTTP チェック ──────────────────────
http_code() {
  # $1 = URL → 最終 HTTP コードを返す(リダイレクト追従)
  local url="$1" auth=""
  if [[ -f "$CREDS" ]]; then
    local bu bp
    bu=$(grep -oE '^BASIC_AUTH_USER=.*' "$CREDS" | cut -d= -f2-)
    bp=$(grep -oE '^BASIC_AUTH_PASS=.*' "$CREDS" | cut -d= -f2-)
    [[ -n "$bu" ]] && auth="-u ${bu}:${bp}"
  fi
  # shellcheck disable=SC2086
  curl -sL $auth -o /dev/null -w "%{http_code}" --max-time 25 "$url" 2>/dev/null || echo "000"
}

# ─── 1. シグナル数 ─────────────────────────────────────
if [[ -s "$SIG_FILE" ]]; then
  read -r T_TOTAL T_POPUP T_EVENT < <(python3 - "$SIG_FILE" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    c = d.get("counts", {})
    print(c.get("total", 0), c.get("popup", 0), c.get("event", 0))
except Exception:
    print(0, 0, 0)
PY
)
  slog "シグナル数: total=${T_TOTAL} popup=${T_POPUP} event=${T_EVENT}"
  if [[ "${T_TOTAL:-0}" -eq 0 ]]; then
    fail "シグナル0件(収集が空)"
  fi
else
  fail "シグナルファイル不在 or 空: ${SIG_FILE}"
  T_TOTAL=0; T_POPUP=0; T_EVENT=0
fi

# ─── 2. 元ログの HARD_FAIL / 異常終了 検出 ─────────────
if [[ -f "$SRC_LOG" ]]; then
  if grep -q "HARD_FAIL" "$SRC_LOG"; then
    fail "実行ログに HARD_FAIL を検出($(grep -c HARD_FAIL "$SRC_LOG") 件)"
  fi
  if grep -qiE "Traceback|異常終了" "$SRC_LOG"; then
    fail "実行ログに Traceback/異常終了 を検出"
  fi
fi

# ─── 3. 投稿結果(post_id)検証 ─────────────────────────
POSTED_N=0
if [[ -s "$RESULTS_FILE" ]]; then
  # post_id<TAB>type を 1 行ずつ取り出す(post_id=0 = 投稿失敗)
  while IFS=$'\t' read -r PID PTYPE; do
    [[ -z "$PID" ]] && continue
    POSTED_N=$((POSTED_N+1))
    if [[ "$PID" == "0" ]]; then
      fail "post_id=0(投稿失敗 / ID 取得失敗) type=${PTYPE}"
      continue
    fi

    # HTTP 200 確認(?p=ID → pretty permalink へ追従)
    CODE=$(http_code "${STG_BASE}/?p=${PID}")
    if [[ "$CODE" != "200" ]]; then
      fail "post ${PID} (${PTYPE}) HTTP=${CODE}(200 以外)"
    else
      slog "post ${PID} (${PTYPE}) HTTP 200 OK"
    fi

    # popup 固有: popup_source_url ACF + category=popup
    if [[ "$PTYPE" == "popup" ]]; then
      SRC_URL=$(mysql_q "SELECT meta_value FROM wp_postmeta WHERE post_id=${PID} AND meta_key='popup_source_url' LIMIT 1;")
      if [[ -z "$SRC_URL" ]]; then
        fail "post ${PID} popup_source_url ACF が空(citation-rules §8 違反)"
      else
        slog "post ${PID} popup_source_url=${SRC_URL}"
      fi
      CAT=$(mysql_q "SELECT t.slug FROM wp_term_relationships tr JOIN wp_term_taxonomy tt ON tr.term_taxonomy_id=tt.term_taxonomy_id JOIN wp_terms t ON tt.term_id=t.term_id WHERE tr.object_id=${PID} AND tt.taxonomy='category' AND t.slug='popup' LIMIT 1;")
      if [[ "$CAT" != "popup" ]]; then
        fail "post ${PID} category=popup が未紐付け"
      fi
    fi
  done < <(python3 - "$RESULTS_FILE" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    for p in d.get("posted", []):
        print(f"{p.get('post_id', 0)}\t{p.get('type', '')}")
except Exception:
    pass
PY
)
  slog "投稿検証対象: ${POSTED_N} 件"
  # popup シグナルがあったのに投稿結果が 0 件なら異常
  if [[ "$POSTED_N" -eq 0 && "${T_POPUP:-0}" -gt 0 ]]; then
    fail "popup シグナル ${T_POPUP} 件あるのに投稿結果が0件"
  fi
else
  # results ファイルが無い = 投稿フェーズが走っていない or 失敗
  if [[ "${T_TOTAL:-0}" -gt 0 && "${DRY_RUN:-0}" != "1" ]]; then
    fail "投稿結果ファイル不在(${RESULTS_FILE})。投稿が行われていない可能性"
  else
    slog "投稿結果ファイル無し(DRY_RUN or シグナル0)。投稿検証スキップ"
  fi
fi

# ─── 4. サマリ + 通知 ──────────────────────────────────
if [[ "$FAILS" -eq 0 ]]; then
  slog "SMOKE-OK: 全検証パス (signals total=${T_TOTAL}, 投稿検証=${POSTED_N})"
else
  slog "SMOKE-RESULT: [SMOKE-FAIL] ${FAILS} 件"
fi

# Discord 通知(urgent_errors、失効中はログのみ。常に exit 0 でロバスト)
if [[ "$FAILS" -gt 0 ]]; then
  WEBHOOK_URL=$(python3 - "$SCRIPT_DIR" <<'PY'
import json, sys
try:
    c = json.load(open(f"{sys.argv[1]}/config/discord_webhooks.json"))
    print(c.get("urgent_errors", "") or c.get("alert_summary", ""))
except Exception:
    print("")
PY
)
  if [[ -n "$WEBHOOK_URL" ]]; then
    MSG="⚠️ Popup スモークテスト失敗 (${DATE}): [SMOKE-FAIL] ${FAILS} 件。詳細: ${SMOKE_LOG}"
    curl -s -X POST -H "Content-Type: application/json" \
      -d "{\"content\": \"${MSG}\"}" "$WEBHOOK_URL" >/dev/null 2>&1 \
      || slog "Discord 通知失敗(webhook 失効?)"
  fi
fi

slog "===== popup_smoke_test.sh 完了 (FAILS=${FAILS}) ====="
slog "サマリ出力: ${SMOKE_LOG}"
exit 0
