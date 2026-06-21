#!/bin/bash
# ============================================================
# red_team_scan.sh — M8 L 項目(REDチーム週次自動スキャン)
#
# 役割: red-team-auditor SKILL §4 の非破壊チェックを週次自動実行。
#   1. 公開ディレクトリの危険ファイル露出(.env / .git/ / *.bak)
#   2. HTTP セキュリティヘッダの有無
#   3. SSL 証明書の有効期限(失効30日前 WARNING)
#   4. WordPress / プラグインの既知のバージョン
#   5. robots.txt / noindex / Basic 認証 の状態(stg 隠蔽確認)
#   6. uploads/ 配下に .php / .phtml / .phar 等の実行可能拡張子
#   7. crontab 内の不審スクリプト
#   8. audit スクリプトの SHA256 改ざん検知
#
# 出力:
#   - 検出ログ: ~/.kpop_recovery/red_team_log.jsonl(1検出1行 追記)
#   - サマリ: ~/.kpop_recovery/red_team/report_YYYYMMDD.md
#   - 連携: blue-team-repair が自動読み込み
#
# 起動:
#   bash red_team_scan.sh         # 通常実行
#   DRY_RUN=1 bash red_team_scan.sh   # ログ書き込みなし
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATE=$(date '+%Y%m%d')
TS=$(date '+%Y-%m-%dT%H:%M:%S+09:00')
RT_DIR="${HOME}/.kpop_recovery/red_team"
LOG_FILE="${HOME}/.kpop_recovery/red_team_log.jsonl"
REPORT_FILE="${RT_DIR}/report_${DATE}.md"
DRY_RUN=${DRY_RUN:-0}

mkdir -p "$RT_DIR"

STG_HOST="stg.kpopjournal.tokyo"
PROD_HOST="www.kpopjournal.tokyo"   # セキュリティヘッダ等は公開面(本番)を測る
# Basic auth(stg のみ。本番は別途認証なしを想定)
STG_AUTH_USER="kpopadmin"
STG_AUTH_PASS=""
if [[ -f /tmp/wp_stg.txt ]]; then
  STG_AUTH_PASS=$(grep '^BASIC_AUTH_PASS=' /tmp/wp_stg.txt | sed 's/^[^=]*=//')
fi

# 検出カウンタ
declare -i N_CRITICAL=0 N_HIGH=0 N_MEDIUM=0 N_LOW=0
declare -a FINDINGS=()

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
add_finding() {
  # add_finding SEVERITY CATEGORY MESSAGE EVIDENCE
  local sev="$1" cat="$2" msg="$3" ev="$4"
  case "$sev" in
    CRITICAL) N_CRITICAL=$((N_CRITICAL+1)) ;;
    HIGH)     N_HIGH=$((N_HIGH+1)) ;;
    MEDIUM)   N_MEDIUM=$((N_MEDIUM+1)) ;;
    LOW)      N_LOW=$((N_LOW+1)) ;;
  esac
  FINDINGS+=("$sev|$cat|$msg|$ev")
  if [[ "$DRY_RUN" != "1" ]]; then
    printf '{"ts":"%s","severity":"%s","category":"%s","message":%s,"evidence":%s,"target":"red->blue"}\n' \
      "$TS" "$sev" "$cat" \
      "$(printf '%s' "$msg" | python3 -c 'import sys, json; print(json.dumps(sys.stdin.read()))')" \
      "$(printf '%s' "$ev" | python3 -c 'import sys, json; print(json.dumps(sys.stdin.read()))')" \
      >> "$LOG_FILE"
  fi
  log "[$sev] $cat: $msg"
}

log "===== red_team_scan.sh 開始 (${DATE}, DRY_RUN=${DRY_RUN}) ====="

# ─── [1] 公開ディレクトリの危険ファイル露出 ─────────────────────
log "--- [1] 危険ファイル公開チェック ---"
for path in ".env" ".git/config" "wp-config.php.bak" "backup.sql" "wp_stg.txt" ".DS_Store"; do
  url="https://${STG_HOST}/${path}"
  http=$(curl -s -u "${STG_AUTH_USER}:${STG_AUTH_PASS}" -o /dev/null -w "%{http_code}" --max-time 10 "$url" || echo "000")
  if [[ "$http" == "200" ]]; then
    add_finding "CRITICAL" "security" "公開ディレクトリに $path が露出" "URL=$url HTTP=200"
  fi
done

# ─── [2] HTTP セキュリティヘッダ ─────────────────────
log "--- [2] HTTP セキュリティヘッダ ---"
# 公開面(本番 www)を測る。stg は Basic 認証(401)でヘッダを読めず偽陽性に
# なるため対象外(2026-05-25: stg 401 を「ヘッダ欠落」と毎週誤検出し queue を
# 偽陽性で埋めていた事案。本番は4ヘッダとも設定済み)。
HEADERS=$(curl -s -I --max-time 10 "https://${PROD_HOST}/" 2>/dev/null || echo "")
for hdr in "Strict-Transport-Security" "X-Content-Type-Options" "X-Frame-Options" "Referrer-Policy"; do
  if ! echo "$HEADERS" | grep -qi "^${hdr}:"; then
    add_finding "MEDIUM" "security" "${hdr} ヘッダが欠落" "${PROD_HOST} /"
  fi
done

# ─── [3] SSL 証明書 ─────────────────────
# 公開面(本番)を最優先で測る。stg も併せて確認(両方の失効を取りこぼさない)。
log "--- [3] SSL 証明書有効期限 ---"
for SSL_HOST in "$PROD_HOST" "$STG_HOST"; do
  CERT_END=$(echo | openssl s_client -servername "$SSL_HOST" -connect "${SSL_HOST}:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | sed 's/notAfter=//')
  if [[ -n "$CERT_END" ]]; then
    CERT_EPOCH=$(date -d "$CERT_END" '+%s' 2>/dev/null || echo "0")
    NOW_EPOCH=$(date '+%s')
    DAYS_LEFT=$(( (CERT_EPOCH - NOW_EPOCH) / 86400 ))
    if [[ "$DAYS_LEFT" -lt 30 ]] && [[ "$DAYS_LEFT" -gt 0 ]]; then
      add_finding "HIGH" "security" "SSL 証明書が ${DAYS_LEFT} 日以内に失効 (${SSL_HOST})" "expire=$CERT_END days_left=$DAYS_LEFT"
    elif [[ "$DAYS_LEFT" -le 0 ]]; then
      add_finding "CRITICAL" "security" "SSL 証明書が失効済み (${SSL_HOST})" "expire=$CERT_END"
    else
      log "  SSL OK (${SSL_HOST}): ${DAYS_LEFT} 日残り"
    fi
  else
    log "  SSL: ${SSL_HOST} の証明書を読めず(到達不能?)"
  fi
done

# ─── [4] WP / プラグインバージョン ─────────────────────
log "--- [4] WordPress バージョン ---"
WP_VER=$(curl -s -u "${STG_AUTH_USER}:${STG_AUTH_PASS}" --max-time 10 "https://${STG_HOST}/" | grep -oE 'WordPress [0-9]+\.[0-9]+(\.[0-9]+)?' | head -1 | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' || echo "")
if [[ -n "$WP_VER" ]]; then
  log "  WordPress version: $WP_VER"
  # 6.9 系より古ければ MEDIUM
  WP_MAJOR=$(echo "$WP_VER" | cut -d. -f1)
  WP_MINOR=$(echo "$WP_VER" | cut -d. -f2)
  if [[ "$WP_MAJOR" -lt 6 ]] || { [[ "$WP_MAJOR" -eq 6 ]] && [[ "$WP_MINOR" -lt 8 ]]; }; then
    add_finding "MEDIUM" "security" "WordPress が古いバージョン (${WP_VER})、6.8+ 推奨" "exposed=$WP_VER"
  fi
fi

# ─── [5] robots.txt / noindex / stg 隠蔽 ─────────────────────
log "--- [5] stg 隠蔽状態 ---"
# Basic 認証なしで stg にアクセスできれば認証外れている = LEAK
http_noauth=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "https://${STG_HOST}/" || echo "000")
if [[ "$http_noauth" == "200" ]]; then
  add_finding "HIGH" "security" "stg.kpopjournal.tokyo に Basic 認証なしでアクセス可能(隠蔽漏れ)" "HTTP=$http_noauth"
elif [[ "$http_noauth" != "401" ]]; then
  log "  stg auth status: HTTP=$http_noauth (期待: 401)"
fi
# noindex 確認
ROBOTS=$(curl -s -u "${STG_AUTH_USER}:${STG_AUTH_PASS}" --max-time 10 "https://${STG_HOST}/robots.txt" || echo "")
if echo "$ROBOTS" | grep -qi "Disallow: /"; then
  log "  robots.txt OK: stg は Disallow: / 設定済み"
else
  add_finding "MEDIUM" "security" "stg の robots.txt に Disallow: / がない(検索エンジンに索引されるリスク)" "robots.txt不備"
fi

# ─── [6] uploads/ 内の実行可能拡張子 ─────────────────────
log "--- [6] uploads/ 内の実行可能ファイル ---"
# stg uploads 公開ディレクトリ確認(現状 Basic 認証経由のみアクセス可能なので、認証なしで .php に到達できるか)
UPLOADS_TEST_URL="https://${STG_HOST}/wp-content/uploads/test.php"
http=$(curl -s -u "${STG_AUTH_USER}:${STG_AUTH_PASS}" -o /dev/null -w "%{http_code}" --max-time 10 "$UPLOADS_TEST_URL")
# 200/403 を不審とする(404 = OK)
if [[ "$http" == "200" ]]; then
  add_finding "CRITICAL" "security" "uploads/ に test.php が存在し実行可能" "URL=$UPLOADS_TEST_URL HTTP=200"
fi

# ─── [7] crontab の不審スクリプト ─────────────────────
log "--- [7] crontab 健全性 ---"
# 真の脅威のみを検出する:
#   (1) /tmp /var/tmp 配下のファイルを「実行」している (bash/sh/python 等の直後、またはコマンド位置)
#   (2) curl/wget でDLしたものを shell にパイプしている (remote code execution)
# /tmp/*.lock や /tmp/*_heartbeat 等の lock/heartbeat ファイル「参照」は正常運用なので除外する。
# 検出条件 (いずれか):
#   A) /tmp /var/tmp 配下のファイルを「コマンド位置」で実行
#      = 行頭(cron時刻欄の後)・; && || | ` $( の直後に裸の /tmp パスが来る
#   B) インタプリタ (sh/bash/python) が引数として /tmp 配下を実行
#   C) curl/wget の取得結果を shell にパイプ (remote code execution)
# flock -n /tmp/x.lock や [ -f /tmp/x_heartbeat ] 等の lock/heartbeat 参照は
# /tmp パスが「引数」位置なので A/B いずれにも該当せず除外される。
SUSPICIOUS=$(crontab -l 2>/dev/null | grep -vE '^[[:space:]]*#' \
  | grep -E '([;&|`(]|\$\()[[:space:]]*(/tmp/|/var/tmp/)[^[:space:]]+|(^|[;&|`([:space:]])(ba)?sh[[:space:]]+(/tmp/|/var/tmp/)|python[0-9.]*[[:space:]]+(/tmp/|/var/tmp/)|(curl|wget)[^|]*\|[[:space:]]*(ba)?sh' \
  | head -5)
if [[ -n "$SUSPICIOUS" ]]; then
  add_finding "HIGH" "operational" "crontab に不審なエントリ" "$(echo "$SUSPICIOUS" | head -3)"
fi

# ─── [8] audit スクリプト改ざん検知 ─────────────────────
log "--- [8] audit スクリプト SHA256 変化 ---"
CHECKSUM_FILE="${HOME}/.kpop_recovery/red_team/scripts_sha256.txt"
TARGETS=(
  "${SCRIPT_DIR}/audit_daily.sh"
  "${SCRIPT_DIR}/audit_weekly.sh"
  "${SCRIPT_DIR}/audit_monthly.sh"
  "${SCRIPT_DIR}/lighthouse_daily.sh"
  "${SCRIPT_DIR}/popup_event_weekly.sh"
  "${SCRIPT_DIR}/red_team_scan.sh"
)
if [[ -f "$CHECKSUM_FILE" ]]; then
  # 既存ハッシュと比較
  for t in "${TARGETS[@]}"; do
    if [[ -f "$t" ]]; then
      cur=$(sha256sum "$t" | awk '{print $1}')
      old=$(grep " ${t}$" "$CHECKSUM_FILE" 2>/dev/null | awk '{print $1}')
      if [[ -n "$old" ]] && [[ "$old" != "$cur" ]]; then
        add_finding "HIGH" "operational" "$(basename $t) のハッシュが変化" "old=$old new=$cur"
      fi
    fi
  done
fi
# 現在のハッシュを保存(初回 or 検知後更新)
if [[ "$DRY_RUN" != "1" ]]; then
  : > "$CHECKSUM_FILE"
  for t in "${TARGETS[@]}"; do
    [[ -f "$t" ]] && sha256sum "$t" >> "$CHECKSUM_FILE"
  done
fi

# ─── レポート生成 ─────────────────────
log "===== 検出サマリ: CRITICAL=${N_CRITICAL} HIGH=${N_HIGH} MEDIUM=${N_MEDIUM} LOW=${N_LOW} ====="

if [[ "$DRY_RUN" != "1" ]]; then
  {
    echo "# RED チーム監査レポート [${DATE}]"
    echo ""
    echo "対象: KPOP JOURNAL stg / スキャン種別: 週次自動(非破壊)"
    echo ""
    echo "検出: CRITICAL ${N_CRITICAL} / HIGH ${N_HIGH} / MEDIUM ${N_MEDIUM} / LOW ${N_LOW}"
    echo ""
    for sev in CRITICAL HIGH MEDIUM LOW; do
      icon=""
      case "$sev" in
        CRITICAL) icon="🔴" ;;
        HIGH)     icon="🟠" ;;
        MEDIUM)   icon="🟡" ;;
        LOW)      icon="⚪" ;;
      esac
      header_printed=0
      for f in "${FINDINGS[@]}"; do
        IFS='|' read -r s c m e <<<"$f"
        if [[ "$s" == "$sev" ]]; then
          if [[ "$header_printed" -eq 0 ]]; then
            echo "## ${icon} ${sev}"
            echo ""
            header_printed=1
          fi
          echo "- [${c}] ${m} — 根拠: \`${e}\`"
        fi
      done
      [[ "$header_printed" -eq 1 ]] && echo ""
    done
    echo "→ blue-team-repair 連携: red_team_log.jsonl に $((N_CRITICAL + N_HIGH + N_MEDIUM + N_LOW)) 件追加"
  } > "$REPORT_FILE"
  log "レポート: $REPORT_FILE"
fi

# ─── Discord 通知 ─────────────────────
if [[ "$DRY_RUN" != "1" ]] && [[ -f "${SCRIPT_DIR}/config/discord_webhooks.json" ]]; then
  # webhook は ${VAR} プレースホルダーを .env から展開して取得(未展開だと不正URL=失敗)。
  WEBHOOK=$(python3 "${SCRIPT_DIR}/lib/resolve_discord_webhook.py" weekly_board_report 2>/dev/null)
  if [[ -n "$WEBHOOK" ]]; then
    MSG="🔴 RED チーム週次監査 (${DATE})\\nCRITICAL=${N_CRITICAL} HIGH=${N_HIGH} MEDIUM=${N_MEDIUM} LOW=${N_LOW}"
    curl -s -X POST -H "Content-Type: application/json" -d "{\"content\":\"${MSG}\"}" "$WEBHOOK" > /dev/null 2>&1 || log "Discord 通知失敗(webhook 失効?)"
  fi
fi

log "===== red_team_scan.sh 完了 ====="
exit 0
