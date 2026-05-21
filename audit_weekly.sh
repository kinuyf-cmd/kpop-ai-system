#!/bin/bash
# ============================================================
# audit_weekly.sh — D-b 週次サイト全体監査(M3 段階3.8 残点回収)
#
# 役割: 週次の品質トレンドと媒体規約変更の監視。月曜 朝6時 cron で起動。
#   1. audit_72h.py --hours 168 で直近7日の統合監査
#   2. WoW(Week over Week)比較: 直近7日 vs 先週同期間のスコア差分
#   3. 採用5媒体の robots.txt 再取得 + AI bot Disallow 監視
#   4. weekly_board_report Discord webhook へ通知
#
# ログ: ~/.kpop_recovery/audit_logs/weekly_YYYYMMDD.log
# 通知: config/discord_webhooks.json の "weekly_board_report"
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATE=$(date '+%Y%m%d')
TS=$(date '+%Y-%m-%d %H:%M:%S')
LOG_DIR="${HOME}/.kpop_recovery/audit_logs"
LOG_FILE="${LOG_DIR}/weekly_${DATE}.log"
mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "===== 週次サイト全体監査 開始: ${DATE} ====="

# ─── [1] audit_72h.py --hours 168 で直近7日統合監査 ─────────────────────
log "--- [1] audit_72h.py --hours 168(7日)統合監査 ---"
WEEK_OUT="${LOG_DIR}/weekly_${DATE}_audit168h.txt"
python3 "$SCRIPT_DIR/lib/audit_72h.py" --hours 168 > "$WEEK_OUT" 2>&1
log "audit_72h 7d exit=$?, $(wc -l < "$WEEK_OUT") lines"

THIS_SCORE=$(grep -oE "総合スコア: [0-9]+/100" "$WEEK_OUT" | head -1 | grep -oE "[0-9]+" | head -1 || echo "0")
THIS_GRADE=$(grep -E "総合スコア:" "$WEEK_OUT" | head -1 | grep -oE "グレード: [A-F]" | sed 's/グレード: //' || echo "?")

# ─── [2] WoW 比較(先週同期間 = 168h 前から 336h 前)─────────────────────
log "--- [2] WoW 比較(先週: 168-336h 前)---"
# audit_72h は --hours 引数のみで「now-hours から now」なので、過去比較は別途集計が必要
# 簡易実装: 前週ログ(weekly_${YYYYMMDD-7d}.log)から score 抽出
LAST_WEEK_DATE=$(date -d '7 days ago' '+%Y%m%d')
LAST_WEEK_FILE="${LOG_DIR}/weekly_${LAST_WEEK_DATE}_audit168h.txt"
if [[ -f "$LAST_WEEK_FILE" ]]; then
  LAST_SCORE=$(grep -oE "総合スコア: [0-9]+/100" "$LAST_WEEK_FILE" | head -1 | grep -oE "[0-9]+" | head -1 || echo "0")
  DIFF=$((THIS_SCORE - LAST_SCORE))
  log "今週=${THIS_SCORE}, 先週=${LAST_SCORE}, 差分=${DIFF}"
else
  LAST_SCORE="N/A"
  DIFF="initial"
  log "先週ログなし(初回実行): ${LAST_WEEK_FILE}"
fi

# ─── [3] 採用5媒体の robots.txt 再取得 + AI bot Disallow 監視 ───────────
log "--- [3] 採用5媒体 robots.txt + AI bot Disallow 監視 ---"
ROBOTS_OUT="${LOG_DIR}/weekly_${DATE}_robots.json"
python3 - > "$ROBOTS_OUT" 2>&1 << 'PY'
import json, urllib.request

MEDIA = {
    "Soompi":       "https://www.soompi.com/robots.txt",
    "Newsen":       "https://www.newsen.com/robots.txt",
    "PRTIMES":      "https://prtimes.jp/robots.txt",
    "AllKpop":      "https://www.allkpop.com/robots.txt",
    "KoreaHerald":  "https://www.koreaherald.com/robots.txt",
}
# Claude/Anthropic 関連 bot 名(明示 Disallow の検出対象)
AI_BOTS = ["ClaudeBot", "Claude-Web", "anthropic-ai", "GPTBot", "Google-Extended",
           "CCBot", "Applebot-Extended", "PerplexityBot", "Bytespider", "Amazonbot"]
UA = "KpopJournalBot/1.0 (+https://www.kpopjournal.tokyo/about; research)"
report = {}

for name, url in MEDIA.items():
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            txt = resp.read().decode("utf-8", errors="replace")
            code = resp.status
    except Exception as e:
        report[name] = {"status": "fetch_error", "msg": str(e)[:100]}
        continue
    # AI bot 明示 Disallow 検出
    disallows = []
    for bot in AI_BOTS:
        # User-agent: <bot> の直後の Disallow: / を探す
        import re
        pat = rf'User-agent:\s*{re.escape(bot)}[^\n]*\n(?:User-agent:[^\n]*\n)*\s*Disallow:\s*/'
        if re.search(pat, txt, re.IGNORECASE):
            disallows.append(bot)
    report[name] = {
        "status": code,
        "ai_bot_disallows": disallows,
        "size": len(txt),
        "url": url
    }

print(json.dumps(report, ensure_ascii=False, indent=2))
PY
ROBOTS_OK=0
ROBOTS_NEW_BAN=()
for m in Soompi Newsen PRTIMES AllKpop KoreaHerald; do
  N=$(python3 -c "
import json
try:
    d = json.load(open('$ROBOTS_OUT'))
    info = d.get('$m', {})
    print(','.join(info.get('ai_bot_disallows', [])))
except Exception:
    print('')
" 2>/dev/null)
  if [[ -n "$N" ]]; then
    log "  ⚠️ $m: AI bot Disallow = ${N}"
    ROBOTS_NEW_BAN+=("$m: $N")
  else
    log "  ✅ $m: AI bot Disallow なし"
    ROBOTS_OK=$((ROBOTS_OK+1))
  fi
done

# ─── [4] sanitize_log.jsonl の週次集計 ──────────────────────────────────
log "--- [4] sanitize_output.sh 矯正回数の週次集計 ---"
SANITIZE_LOG="${HOME}/.kpop_recovery/sanitize_log.jsonl"
SANI_CY=0; SANI_CZ=0; SANI_FILES=0
if [[ -f "$SANITIZE_LOG" ]]; then
  WEEK_AGO=$(date -d '7 days ago' '+%s')
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    SANI_CY=$((SANI_CY + $(echo "$line" | python3 -c "
import json,sys
try:
    d=json.loads(sys.stdin.read())
    import datetime
    ts=datetime.datetime.fromisoformat(d['ts']).timestamp()
    if ts >= $WEEK_AGO: print(d.get('n_cy_inline_style',0))
    else: print(0)
except Exception: print(0)
" 2>/dev/null || echo 0)))
    SANI_CZ=$((SANI_CZ + $(echo "$line" | python3 -c "
import json,sys
try:
    d=json.loads(sys.stdin.read())
    import datetime
    ts=datetime.datetime.fromisoformat(d['ts']).timestamp()
    if ts >= $WEEK_AGO: print(d.get('n_cz_table_fix',0))
    else: print(0)
except Exception: print(0)
" 2>/dev/null || echo 0)))
    SANI_FILES=$((SANI_FILES + 1))
  done < <(tail -200 "$SANITIZE_LOG")
fi
log "sanitize 週次: C-Y 矯正=${SANI_CY}, C-Z 矯正=${SANI_CZ}, 対象ファイル=${SANI_FILES}"

# ─── [5] Discord 通知(weekly_board_report)──────────────────────────────
log "--- [5] Discord 通知(weekly_board_report)---"
if [[ "${AUDIT_DRY_RUN:-0}" == "1" ]]; then
  log "🧪 DRY RUN: Discord 通知をスキップ"
else
  WEBHOOK=$(python3 -c "
import json; print(json.load(open('$SCRIPT_DIR/config/discord_webhooks.json')).get('weekly_board_report',''))
" 2>/dev/null)
  if [[ -n "$WEBHOOK" ]]; then
    BAN_LIST=""
    if [[ ${#ROBOTS_NEW_BAN[@]} -gt 0 ]]; then
      BAN_LIST=$(printf '  - %s\n' "${ROBOTS_NEW_BAN[@]}")
    fi
    MSG="📈 **週次サイト全体監査** [${DATE}]
**audit_72h(7日)**: ${THIS_SCORE}/100 (グレード${THIS_GRADE})
**WoW 比較**: 今週 ${THIS_SCORE} vs 先週 ${LAST_SCORE} → 差分 ${DIFF}
**採用5媒体 robots.txt**: AI bot Disallow 監視
  ✅ クリア媒体: ${ROBOTS_OK}/5
${BAN_LIST}
**sanitize 矯正(週次)**: C-Y ${SANI_CY}件, C-Z ${SANI_CZ}件
**ログ**: ${LOG_FILE##*/}"
    AUDIT_MSG="$MSG" AUDIT_WH="$WEBHOOK" python3 -c "
import json, urllib.request, os, sys
try:
    urllib.request.urlopen(urllib.request.Request(os.environ['AUDIT_WH'],
        data=json.dumps({'content': os.environ['AUDIT_MSG'][:1900]}).encode(),
        headers={'Content-Type':'application/json'}, method='POST'), timeout=15)
    print('OK')
except Exception as e:
    print(f'NG: {e}', file=sys.stderr); sys.exit(1)
" >> "$LOG_FILE" 2>&1
    log "Discord weekly_board_report exit=$?"
  else
    log "⚠️ weekly_board_report webhook 未設定"
  fi
fi

# ─── [6] 新規 AI bot Disallow 検出時は urgent_errors にも通知 ───────────
if [[ ${#ROBOTS_NEW_BAN[@]} -gt 0 ]] && [[ "${AUDIT_DRY_RUN:-0}" != "1" ]]; then
  log "--- [6] CRITICAL: AI bot Disallow 検出 → urgent_errors 通知 ---"
  URGENT_WH=$(python3 -c "
import json; print(json.load(open('$SCRIPT_DIR/config/discord_webhooks.json')).get('urgent_errors',''))
" 2>/dev/null)
  if [[ -n "$URGENT_WH" ]]; then
    URG_MSG="🚨 **週次監査 CRITICAL** — 採用媒体で AI bot Disallow を検出
$(printf '  - %s\n' "${ROBOTS_NEW_BAN[@]}")
→ 当該媒体の採用継続可否をオーナーが判断してください。"
    AUDIT_MSG="$URG_MSG" AUDIT_WH="$URGENT_WH" python3 -c "
import json, urllib.request, os
urllib.request.urlopen(urllib.request.Request(os.environ['AUDIT_WH'],
    data=json.dumps({'content': os.environ['AUDIT_MSG'][:1900]}).encode(),
    headers={'Content-Type':'application/json'}, method='POST'), timeout=15)
" 2>>"$LOG_FILE" || log "urgent 通知失敗"
  fi
fi

log "===== 週次監査 完了 ====="
exit 0
