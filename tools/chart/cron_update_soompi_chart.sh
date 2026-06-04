#!/usr/bin/env bash
# cron_update_soompi_chart.sh — Soompi Music Chart を自動発見→取得→WP option反映。
#   user cron から無人実行(2026-06-04)。wp 書き込みは kpop-wp-rw.sh 経由。
#   冪等: 既に取り込み済みの週URLなら取得・更新・通知を全てスキップ(無駄打ち無し)。
#   新しい週を取り込んだ時だけ option 更新 + Discord 通知(publishing_log)。
#   非破壊: 取得失敗時は既存 option を維持し空にしない。
#   cron 例(週末の公開を翌週まで待たないよう、土日含め朝晩2回チェック):
#     30 7,19 * * 6,0,1   # 土日月の 07:30/19:30
set -uo pipefail
cd "$(dirname "$0")/../.."
ROOT="$PWD"
JSON="$ROOT/data/soompi_chart_top10.json"
RW=/usr/local/sbin/kpop/kpop-wp-rw.sh
LOG="$ROOT/logs/cron_soompi_chart_update.log"
ts() { date '+%Y-%m-%dT%H:%M:%S'; }
log() { echo "[$(ts)] $*" >> "$LOG"; }

log "===== Soompi Chart 自動更新 チェック開始 ====="

# ① 最新チャートURLを自動発見(カテゴリページの記事ID最大=最新)
URL="$(node tools/chart/find_latest_chart.mjs 2>>"$LOG" || true)"
if [ -z "$URL" ]; then
  log "[warn] URL自動発見失敗 → 既存維持・据え置き"
  exit 0
fi

# ② 冪等チェック: 既存JSONのURLと同じなら何もしない(無駄な取得・更新・通知を回避)
CUR_URL="$(python3 -c "import json;print(json.load(open('$JSON')).get('url',''))" 2>/dev/null || echo '')"
if [ "$URL" = "$CUR_URL" ]; then
  log "最新週は取り込み済み($URL) → スキップ"
  exit 0
fi
log "新しい週を検出: $URL (前回: ${CUR_URL:-なし})"

# ③ Top10 を取得して JSON 生成(失敗時は既存維持)
if ! CHART_URL="$URL" node tools/chart/soompi_chart_fetch.mjs >>"$LOG" 2>&1; then
  log "[warn] 取得失敗 → 既存JSON維持"
  exit 0
fi

# ④ JSON が10件あるか検証してから WP option へ反映(空で上書きしない)
N="$(python3 -c "import json;print(len(json.load(open('$JSON'))['items']))" 2>/dev/null || echo 0)"
if [ "$N" -lt 1 ]; then
  log "[FATAL] JSON空/無効($N件) → option更新せず"
  exit 1
fi

if sudo -n "$RW" option update kpop_soompi_chart "$(cat "$JSON")" >>"$LOG" 2>&1; then
  TITLE="$(python3 -c "import json;print(json.load(open('$JSON'))['title'])" 2>/dev/null || echo '?')"
  TOP1="$(python3 -c "import json;d=json.load(open('$JSON'))['items'][0];print(d['rank'],d['song'],'-',d['artist'])" 2>/dev/null || echo '?')"
  log "✅ option更新成功: $TITLE ($N件) / 1位: $TOP1"
  # ⑤ 新しい週を取り込んだ時のみ Discord 通知(publishing_log)
  HOOK="$(python3 lib/resolve_discord_webhook.py publishing_log 2>/dev/null || true)"
  if [ -n "$HOOK" ]; then
    MSG="🎵 Music Chart 更新: ${TITLE} / 1位 ${TOP1}"
    curl -s -H "Content-Type: application/json" \
         -H "User-Agent: KPOP-JOURNAL-Bot/1.0" \
         -d "$(python3 -c "import json,sys;print(json.dumps({'content':sys.argv[1]}))" "$MSG")" \
         "$HOOK" >/dev/null 2>&1 && log "Discord通知済(publishing_log)" || log "[warn] Discord通知失敗"
  fi
else
  log "[FATAL] option更新失敗(rwラッパー)"
  exit 1
fi
log "===== 完了 ====="
