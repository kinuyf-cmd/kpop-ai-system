#!/bin/bash
# ============================================================
# audit_monthly.sh — D-c 月次サイト全体監査(M3 段階3.8 残点回収)
#
# 役割: 月次の品質統計 + KPI 達成状況 + 媒体規約再確認。月初1日 朝7時 cron で起動。
#   1. audit_72h.py --hours 720 で直近30日の統合監査
#   2. KPI 達成状況(M4 と連携、100point_state.json の current_total)
#   3. 採用媒体5件の利用規約ページに HTTP アクセス確認(規約変更検知の足場)
#   4. sanitize_log.jsonl の月次集計
#   5. monthly_board_report Discord webhook へ通知
#
# ログ: ~/.kpop_recovery/audit_logs/monthly_YYYYMM.log
# 通知: config/discord_webhooks.json の "monthly_board_report"
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATE=$(date '+%Y%m')
TS=$(date '+%Y-%m-%d %H:%M:%S')
LOG_DIR="${HOME}/.kpop_recovery/audit_logs"
LOG_FILE="${LOG_DIR}/monthly_${DATE}.log"
mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "===== 月次サイト全体監査 開始: ${DATE} ====="

# ─── [1] audit_72h.py --hours 720(30日)統合監査 ─────────────────────────
log "--- [1] audit_72h.py --hours 720(30日)統合監査 ---"
MONTH_OUT="${LOG_DIR}/monthly_${DATE}_audit720h.txt"
python3 "$SCRIPT_DIR/lib/audit_72h.py" --hours 720 > "$MONTH_OUT" 2>&1
log "audit_72h 30d exit=$?, $(wc -l < "$MONTH_OUT") lines"

MONTH_SCORE=$(grep -oE "総合スコア: [0-9]+/100" "$MONTH_OUT" | head -1 | grep -oE "[0-9]+" || echo "0")
MONTH_GRADE=$(grep -E "総合スコア:" "$MONTH_OUT" | head -1 | grep -oE "グレード: [A-F]" | sed 's/グレード: //' || echo "?")

# ─── [2] 100point_state.json の KPI 達成状況 ────────────────────────────
log "--- [2] 100point 採点状況 ---"
KPI_TOTAL=$(python3 -c "
import json
try:
    d = json.load(open('${HOME}/.kpop_recovery/100point_state.json'))
    print(d.get('current_total', 0))
except Exception:
    print(0)
" 2>/dev/null)
KPI_MAX=$(python3 -c "
import json
try:
    d = json.load(open('${HOME}/.kpop_recovery/100point_state.json'))
    print(d.get('total_max', 63))
except Exception:
    print(63)
" 2>/dev/null)
KPI_PCT=$(python3 -c "print(f'{int(${KPI_TOTAL}*100/${KPI_MAX})}')" 2>/dev/null || echo "0")
log "100point: ${KPI_TOTAL}/${KPI_MAX} (${KPI_PCT}%)"

# ─── [3] 採用5媒体の利用規約ページ HTTP 到達性 ─────────────────────────
log "--- [3] 採用5媒体 利用規約 HTTP 到達性 ---"
TERMS_OUT="${LOG_DIR}/monthly_${DATE}_terms.json"
python3 - > "$TERMS_OUT" 2>&1 << 'PY'
import json, urllib.request

UA = "KpopJournalBot/1.0 (+https://www.kpopjournal.tokyo/about; research)"
TERMS_URLS = {
    "Soompi_copyright":      "https://www.soompi.com/copyright",
    "Soompi_terms":          "https://www.soompi.com/terms",
    "Newsen_root":           "https://www.newsen.com/",
    "PRTIMES_terms":         "https://prtimes.jp/main/html/policy.html",
    "AllKpop_terms":         "https://www.allkpop.com/terms",
    "KoreaHerald_terms":     "https://www.koreaherald.com/help/userPolicy",
}
report = {}
for name, url in TERMS_URLS.items():
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            report[name] = {"status": resp.status, "size": len(resp.read())}
    except Exception as e:
        report[name] = {"status": "err", "msg": str(e)[:100]}
print(json.dumps(report, ensure_ascii=False, indent=2))
PY
TERMS_OK=$(python3 -c "
import json
try:
    d = json.load(open('$TERMS_OUT'))
    ok = sum(1 for v in d.values() if isinstance(v.get('status'), int) and 200 <= v['status'] < 400)
    print(ok)
except Exception:
    print(0)
" 2>/dev/null)
TERMS_TOTAL=$(python3 -c "
import json
print(len(json.load(open('$TERMS_OUT'))))
" 2>/dev/null || echo "0")
log "利用規約到達性: ${TERMS_OK}/${TERMS_TOTAL}"

# ─── [4] sanitize_log.jsonl 月次集計 ────────────────────────────────────
log "--- [4] sanitize_output 矯正回数の月次集計 ---"
SANITIZE_LOG="${HOME}/.kpop_recovery/sanitize_log.jsonl"
if [[ -f "$SANITIZE_LOG" ]]; then
  MONTH_AGO=$(date -d '30 days ago' '+%s')
  read SANI_CY SANI_CZ SANI_FILES <<< $(python3 -c "
import json
from datetime import datetime
cy=cz=files=0
month_ago = ${MONTH_AGO}
with open('$SANITIZE_LOG') as f:
    for line in f:
        try:
            d = json.loads(line)
            ts = datetime.fromisoformat(d['ts']).timestamp()
            if ts >= month_ago:
                cy += d.get('n_cy_inline_style', 0)
                cz += d.get('n_cz_table_fix', 0)
                files += 1
        except Exception:
            pass
print(cy, cz, files)
" 2>/dev/null)
  log "sanitize 月次: C-Y 矯正=${SANI_CY:-0}, C-Z 矯正=${SANI_CZ:-0}, 対象ファイル=${SANI_FILES:-0}"
else
  SANI_CY=0; SANI_CZ=0; SANI_FILES=0
  log "sanitize_log.jsonl なし"
fi

# ─── [5] media_copy_policy.json の更新候補リスト出力(オーナー判断用) ───
log "--- [5] media_copy_policy.json の unknown リスト ---"
POLICY_FILE="${HOME}/.kpop_recovery/media_copy_policy.json"
UNKNOWN_LIST=""
if [[ -f "$POLICY_FILE" ]]; then
  UNKNOWN_LIST=$(python3 -c "
import json
try:
    d = json.load(open('$POLICY_FILE'))
    names = [k for k, v in d.items() if not k.startswith('_') and v.get('copy_allowed') == 'unknown']
    print(','.join(names))
except Exception:
    print('')
" 2>/dev/null)
fi
log "copy_allowed=unknown: ${UNKNOWN_LIST:-(none / file 未生成)}"

# ─── [6] Discord 通知(monthly_board_report)─────────────────────────────
log "--- [6] Discord 通知(monthly_board_report)---"
if [[ "${AUDIT_DRY_RUN:-0}" == "1" ]]; then
  log "🧪 DRY RUN: Discord 通知をスキップ"
else
  # webhook は ${VAR} プレースホルダーを .env から展開して取得(未展開だと不正URL=失敗)。
  WEBHOOK=$(python3 "$SCRIPT_DIR/lib/resolve_discord_webhook.py" monthly_board_report 2>/dev/null)
  if [[ -n "$WEBHOOK" ]]; then
    MSG="📊 **月次サイト全体監査** [${DATE}]
**audit_72h(30日)**: ${MONTH_SCORE}/100 (グレード${MONTH_GRADE})
**100point 達成度**: ${KPI_TOTAL}/${KPI_MAX} (${KPI_PCT}%)
**採用5媒体 利用規約到達性**: ${TERMS_OK}/${TERMS_TOTAL}
**sanitize 矯正(月次)**: C-Y ${SANI_CY:-0}件, C-Z ${SANI_CZ:-0}件 / 対象${SANI_FILES:-0}ファイル
**copy_allowed=unknown 媒体**: ${UNKNOWN_LIST:-(なし)}
→ unknown 媒体は当月中にオーナーが利用規約を手動確認、media_copy_policy.json を更新してください
**ログ**: ${LOG_FILE##*/}"
    AUDIT_MSG="$MSG" AUDIT_WH="$WEBHOOK" python3 -c "
import json, urllib.request, os, sys
try:
    urllib.request.urlopen(urllib.request.Request(os.environ['AUDIT_WH'],
        data=json.dumps({'content': os.environ['AUDIT_MSG'][:1900]}).encode(),
        headers={'Content-Type':'application/json',
                 'User-Agent':'Mozilla/5.0 (compatible; KpopJournalBot/1.0)'},
        method='POST'), timeout=15)
    print('OK')
except Exception as e:
    print(f'NG: {e}', file=sys.stderr); sys.exit(1)
" >> "$LOG_FILE" 2>&1
    log "Discord monthly_board_report exit=$?"
  else
    log "⚠️ monthly_board_report webhook 未設定"
  fi
fi

log "===== 月次監査 完了 ====="
exit 0
