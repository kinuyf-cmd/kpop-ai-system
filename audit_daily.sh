#!/bin/bash
# ============================================================
# audit_daily.sh — D-a 日次サイト全体監査(M3 段階3.8 残点回収)
#
# 役割: サイト全体の日次品質ヘルスチェック。1日1回 朝5時 cron で起動。
#   1. audit_72h.py --hours 24 で直近24h 記事のパイプライン/GSC/X/サムネ統合監査
#   2. 全公開記事(直近24h)の HTTP 200 + featured_media 整合性チェック
#   3. サマリレポートを daily_ceo_report Discord webhook へ通知
#
# ログ: ~/.kpop_recovery/audit_logs/daily_YYYYMMDD.log
# 通知: config/discord_webhooks.json の "daily_ceo_report"
#
# 使い方:
#   bash audit_daily.sh           # 通常実行(Discord 通知あり)
#   AUDIT_DRY_RUN=1 bash ...      # ドライラン(Discord 通知スキップ)
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATE=$(date '+%Y%m%d')
TS=$(date '+%Y-%m-%d %H:%M:%S')
LOG_DIR="${HOME}/.kpop_recovery/audit_logs"
LOG_FILE="${LOG_DIR}/daily_${DATE}.log"
mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "===== 日次サイト全体監査 開始: ${DATE} ====="

# ─── [1] audit_72h.py を 24h モードで実行 ─────────────────────────────────
log "--- [1] audit_72h.py --hours 24 統合監査 ---"
AUDIT_72H_OUT="${LOG_DIR}/daily_${DATE}_audit72h.txt"
python3 "$SCRIPT_DIR/lib/audit_72h.py" --hours 24 > "$AUDIT_72H_OUT" 2>&1
AUDIT_EXIT=$?
log "audit_72h exit=${AUDIT_EXIT}, output=${AUDIT_72H_OUT} ($(wc -l < "$AUDIT_72H_OUT") lines)"

# 総合スコア抽出(audit_72h レポートから)
OVERALL_SCORE=$(grep -E "総合スコア:" "$AUDIT_72H_OUT" | head -1 | grep -oE "[0-9]+/100" | head -1 || echo "N/A")
GRADE=$(grep -E "総合スコア:" "$AUDIT_72H_OUT" | head -1 | grep -oE "グレード: [A-F]" | sed 's/グレード: //' || echo "?")

# ─── [2] 直近24h 公開記事の HTTP 200 + featured_media 整合性 ──────────────
log "--- [2] 直近24h 公開記事の整合性チェック ---"
CONSISTENCY_OUT="${LOG_DIR}/daily_${DATE}_consistency.json"
python3 - > "$CONSISTENCY_OUT" 2>&1 << 'PY'
import json, urllib.request, datetime, sys

WP = "https://www.kpopjournal.tokyo/wp-json/wp/v2"
cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
results = {"checked": 0, "http_ok": 0, "http_fail": [], "feat_missing": [], "errors": []}

try:
    req = urllib.request.Request(
        f"{WP}/posts?per_page=50&orderby=date&order=desc&status=publish&_fields=id,link,featured_media,date",
        headers={"User-Agent": "kpop-audit-daily/1.0"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        posts = json.loads(resp.read())
except Exception as e:
    results["errors"].append(f"WP API fetch failed: {e}")
    posts = []

for p in posts:
    # 24h 以内の記事のみ
    try:
        pd = datetime.datetime.fromisoformat(p["date"].replace("Z", "+00:00"))
        if pd.tzinfo is None:
            pd = pd.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
        if pd < cutoff:
            continue
    except Exception:
        pass
    results["checked"] += 1
    pid = p["id"]; link = p["link"]; feat = p.get("featured_media", 0)
    # HTTP 200
    try:
        r = urllib.request.Request(link, headers={"User-Agent": "kpop-audit-daily/1.0"})
        with urllib.request.urlopen(r, timeout=10) as resp:
            if 200 <= resp.status < 300:
                results["http_ok"] += 1
            else:
                results["http_fail"].append({"id": pid, "code": resp.status, "url": link})
    except Exception as e:
        results["http_fail"].append({"id": pid, "code": "err", "url": link, "msg": str(e)[:80]})
    # featured_media
    if not feat:
        results["feat_missing"].append({"id": pid, "url": link})

print(json.dumps(results, ensure_ascii=False, indent=2))
PY
CHK=$(cat "$CONSISTENCY_OUT")
CHK_TOTAL=$(echo "$CHK" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('checked',0))" 2>/dev/null || echo "0")
CHK_HTTP_OK=$(echo "$CHK" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('http_ok',0))" 2>/dev/null || echo "0")
CHK_HTTP_FAIL=$(echo "$CHK" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('http_fail',[])))" 2>/dev/null || echo "0")
CHK_FEAT_MISS=$(echo "$CHK" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('feat_missing',[])))" 2>/dev/null || echo "0")
log "整合性: checked=${CHK_TOTAL}, http_ok=${CHK_HTTP_OK}, http_fail=${CHK_HTTP_FAIL}, feat_missing=${CHK_FEAT_MISS}"

# ─── [3] Discord 通知(daily_ceo_report)──────────────────────────────────
log "--- [3] Discord 通知(daily_ceo_report)---"
if [[ "${AUDIT_DRY_RUN:-0}" == "1" ]]; then
  log "🧪 DRY RUN: Discord 通知をスキップ"
else
  WEBHOOK=$(cd "$SCRIPT_DIR" && python3 -c "
import json, sys
from pathlib import Path
sys.path.insert(0, '$SCRIPT_DIR')
from lib.discord_notifier import _expand_webhook
cfg = Path('$SCRIPT_DIR/config/discord_webhooks.json')
if cfg.exists():
    d = json.loads(cfg.read_text())
    print(_expand_webhook(d.get('daily_ceo_report', '')))
" 2>/dev/null)
  if [[ -n "$WEBHOOK" ]]; then
    # 通知本文を組み立て
    MSG="📊 **日次サイト全体監査** [${DATE}]
**audit_72h(24h)**: ${OVERALL_SCORE} (グレード${GRADE})
**直近24h 公開記事**: ${CHK_TOTAL}件
  ✅ HTTP 200: ${CHK_HTTP_OK}件
  ❌ HTTP失敗: ${CHK_HTTP_FAIL}件
  ⚠️ サムネ未設定: ${CHK_FEAT_MISS}件
**ログ**: ${LOG_FILE##*/}"
    AUDIT_MSG="$MSG" AUDIT_WH="$WEBHOOK" python3 -c "
import json, urllib.request, urllib.error, sys, os
msg = os.environ.get('AUDIT_MSG', '')
webhook = os.environ.get('AUDIT_WH', '')
try:
    payload = json.dumps({'content': msg[:1900]}).encode()
    req = urllib.request.Request(webhook, data=payload,
        headers={'Content-Type': 'application/json'}, method='POST')
    urllib.request.urlopen(req, timeout=15)
    print('OK')
except Exception as e:
    print(f'NG: {e}', file=sys.stderr)
    sys.exit(1)
" >> "$LOG_FILE" 2>&1
    AUDIT_NOTIFY_EXIT=$?
    log "Discord notify exit=${AUDIT_NOTIFY_EXIT}"
  else
    log "⚠️ daily_ceo_report webhook 未設定"
  fi
fi

# ─── [4] CRITICAL があれば urgent_errors にも通知 ─────────────────────────
if [[ "$CHK_HTTP_FAIL" -gt 0 ]] && [[ "${AUDIT_DRY_RUN:-0}" != "1" ]]; then
  log "--- [4] CRITICAL 通知(HTTP失敗 ${CHK_HTTP_FAIL}件)---"
  URGENT_WH=$(cd "$SCRIPT_DIR" && python3 -c "
import json, sys
sys.path.insert(0, '$SCRIPT_DIR')
from lib.discord_notifier import _expand_webhook
print(_expand_webhook(json.load(open('$SCRIPT_DIR/config/discord_webhooks.json')).get('urgent_errors','')))
" 2>/dev/null)
  if [[ -n "$URGENT_WH" ]]; then
    URG_MSG="🚨 **日次監査 CRITICAL** — HTTP 失敗 ${CHK_HTTP_FAIL}件
詳細: ${CONSISTENCY_OUT##*/}
ログ: ${LOG_FILE##*/}"
    AUDIT_MSG="$URG_MSG" AUDIT_WH="$URGENT_WH" python3 -c "
import json, urllib.request, os
msg = os.environ['AUDIT_MSG']; wh = os.environ['AUDIT_WH']
urllib.request.urlopen(urllib.request.Request(wh,
    data=json.dumps({'content': msg[:1900]}).encode(),
    headers={'Content-Type':'application/json'}, method='POST'), timeout=15)
" 2>>"$LOG_FILE" || log "urgent_errors 通知失敗"
  fi
fi

log "===== 日次監査 完了 ====="
exit 0
