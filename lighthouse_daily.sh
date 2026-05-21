#!/bin/bash
# ============================================================
# lighthouse_daily.sh — M4 K-1/K-4 Lighthouse 日次バッチ(5レイアウト)
#
# 役割: stg 5レイアウトに対する Lighthouse 日次計測 + 結果集計。
#   1. top / single / category / artists / footer の5レイアウト
#   2. Performance / Accessibility / Best Practices / SEO の4カテゴリ
#   3. 結果を ~/.kpop_recovery/kpi_logs/lighthouse_YYYYMMDD.json に保存
#   4. 前日との比較で異常値検知(±10ポイント以上 → アラート)
#   5. 異常時は urgent_errors webhook へ通知(失効中はログのみ)
#
# 起動:
#   bash lighthouse_daily.sh                  # 通常実行
#   LH_DRY_RUN=1 bash lighthouse_daily.sh     # ドライラン(通知 skip)
#   LH_LAYOUTS="top,single" bash ...          # サブセット計測
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATE=$(date '+%Y%m%d')
LOG_DIR="${HOME}/.kpop_recovery/kpi_logs"
LH_LOG="${LOG_DIR}/lighthouse_${DATE}.log"
LH_JSON_DIR="${LOG_DIR}/lighthouse_${DATE}"
mkdir -p "$LH_JSON_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LH_LOG"; }
log "===== Lighthouse 日次バッチ 開始: ${DATE} ====="

# stg 認証経由 URL
STG_AUTH="kpopadmin:caSEbIauNSSkMc9173843RAaUNAaaF7k"
declare -A LAYOUTS=(
  [top]="/"
  [single]="/soompi-may-individual-idol-brand-reputation-2026-05/"
  [category]="/category/news/"
  [artists]="/artists/"
  [footer]="/?lhcheck=footer"
)
# 計測対象を環境変数で絞れる
SELECTED="${LH_LAYOUTS:-top,single,category,artists,footer}"

# CHROME_PATH を明示(Lighthouse は puppeteer の Chromium を使う)
export CHROME_PATH="${CHROME_PATH:-/home/aiuser/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome}"

SUMMARY_JSON="${LOG_DIR}/lighthouse_${DATE}_summary.json"
echo "{" > "$SUMMARY_JSON"
echo "  \"date\": \"$DATE\"," >> "$SUMMARY_JSON"
echo "  \"layouts\": {" >> "$SUMMARY_JSON"

FIRST=1
for layout in $(echo "$SELECTED" | tr ',' ' '); do
  path="${LAYOUTS[$layout]:-/}"
  url="https://${STG_AUTH}@stg.kpopjournal.tokyo${path}"
  log "--- ${layout}: ${path} ---"
  OUT="${LH_JSON_DIR}/${layout}.json"
  if npx lighthouse "$url" \
      --output=json --output-path="$OUT" \
      --chrome-flags="--no-sandbox --headless=new --disable-dev-shm-usage" \
      --only-categories=performance,accessibility,best-practices,seo \
      --quiet 2>>"$LH_LOG"; then
    # スコア抽出
    SCORES=$(python3 -c "
import json
d = json.load(open('$OUT'))
cats = d.get('categories', {})
out = {k: int(round(v['score']*100)) if v.get('score') is not None else None for k, v in cats.items()}
import json as J
print(J.dumps(out))
")
    log "  scores: $SCORES"
    [[ $FIRST -eq 1 ]] || echo "    ," >> "$SUMMARY_JSON"
    echo "    \"${layout}\": ${SCORES}" >> "$SUMMARY_JSON"
    FIRST=0
  else
    log "  ❌ Lighthouse 失敗: ${layout}"
    [[ $FIRST -eq 1 ]] || echo "    ," >> "$SUMMARY_JSON"
    echo "    \"${layout}\": {\"error\": \"lighthouse_failed\"}" >> "$SUMMARY_JSON"
    FIRST=0
  fi
done

echo "  }" >> "$SUMMARY_JSON"
echo "}" >> "$SUMMARY_JSON"
log "サマリ JSON: $SUMMARY_JSON"

# ─── 前日比較(±10pt 以上で異常値検知)─────────────────────────────────
YESTERDAY_DATE=$(date -d 'yesterday' '+%Y%m%d' 2>/dev/null || date -v-1d '+%Y%m%d' 2>/dev/null || echo "")
YESTERDAY_SUMMARY="${LOG_DIR}/lighthouse_${YESTERDAY_DATE}_summary.json"
ANOMALIES=""
if [[ -n "$YESTERDAY_DATE" ]] && [[ -f "$YESTERDAY_SUMMARY" ]]; then
  log "--- 前日比較 ($YESTERDAY_DATE) ---"
  ANOMALIES=$(python3 -c "
import json, sys
today = json.load(open('$SUMMARY_JSON'))['layouts']
yest  = json.load(open('$YESTERDAY_SUMMARY'))['layouts']
anomalies = []
for layout, scores in today.items():
    if 'error' in scores: continue
    yscores = yest.get(layout, {})
    for cat, s in scores.items():
        ys = yscores.get(cat)
        if ys is None or s is None: continue
        diff = s - ys
        if abs(diff) >= 10:
            sign = '+' if diff > 0 else ''
            anomalies.append(f'{layout}.{cat}: {ys} → {s} ({sign}{diff})')
print('\n'.join(anomalies))
" 2>/dev/null)
  if [[ -n "$ANOMALIES" ]]; then
    log "🚨 異常値検出:"
    echo "$ANOMALIES" | while read line; do log "    $line"; done
  else
    log "✅ 前日比 異常なし(±10pt以内)"
  fi
else
  log "ℹ️ 前日サマリなし(初回または前日未実行): $YESTERDAY_SUMMARY"
fi

# ─── 異常時 Discord 通知(失効中でも try、ログのみで完走)─────────────
if [[ -n "$ANOMALIES" ]] && [[ "${LH_DRY_RUN:-0}" != "1" ]]; then
  URGENT_WH=$(python3 -c "
import json; print(json.load(open('$SCRIPT_DIR/config/discord_webhooks.json')).get('urgent_errors',''))
" 2>/dev/null)
  if [[ -n "$URGENT_WH" ]]; then
    MSG="🚨 **Lighthouse 異常値検出** [${DATE}]
$(echo "$ANOMALIES" | head -10 | sed 's/^/  - /')

詳細: lighthouse_${DATE}_summary.json"
    AUDIT_MSG="$MSG" AUDIT_WH="$URGENT_WH" python3 -c "
import json, urllib.request, os, sys
try:
    urllib.request.urlopen(urllib.request.Request(os.environ['AUDIT_WH'],
        data=json.dumps({'content': os.environ['AUDIT_MSG'][:1900]}).encode(),
        headers={'Content-Type':'application/json'}, method='POST'), timeout=15)
    print('OK')
except Exception as e:
    print(f'NG: {e}', file=sys.stderr); sys.exit(1)
" >>"$LH_LOG" 2>&1 || log "⚠️ Discord 通知失敗(webhook失効? ログに残し続行)"
  fi
fi

log "===== Lighthouse 日次バッチ 完了 ====="
exit 0
