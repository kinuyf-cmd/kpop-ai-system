#!/usr/bin/env bash
# cron_update_soompi_chart.sh — Soompi Music Chart を自動発見→取得→WP option反映。
#   user cron から無人実行する版(2026-06-04)。wp 書き込みは kpop-wp-rw.sh 経由
#   (sudo NOPASSWD ラッパー)。非破壊: 取得失敗時は既存 option を維持し空にしない。
#   cron 例(毎週月曜 06:30, Soompiの週次更新後): 30 6 * * 1
set -uo pipefail
cd "$(dirname "$0")/../.."
ROOT="$PWD"
JSON="$ROOT/data/soompi_chart_top10.json"
RW=/usr/local/sbin/kpop/kpop-wp-rw.sh
LOG="$ROOT/logs/cron_soompi_chart_update.log"
ts() { date '+%Y-%m-%dT%H:%M:%S'; }

echo "[$(ts)] ===== Soompi Chart 自動更新 開始 =====" >> "$LOG"

# ① 最新チャートURLを自動発見(カテゴリページの記事ID最大=最新)
URL="$(node tools/chart/find_latest_chart.mjs 2>>"$LOG" || true)"
if [ -z "$URL" ]; then
  echo "[$(ts)] [warn] URL自動発見失敗 → 既存JSON維持・option据え置き" >> "$LOG"
  exit 0
fi
echo "[$(ts)] 発見URL: $URL" >> "$LOG"

# ② Top10 を取得して JSON 生成(失敗時は既存維持)
if ! CHART_URL="$URL" node tools/chart/soompi_chart_fetch.mjs >>"$LOG" 2>&1; then
  echo "[$(ts)] [warn] 取得失敗 → 既存JSON維持" >> "$LOG"
  exit 0
fi

# ③ JSON が10件あるか検証してから WP option へ反映(空で上書きしない)
N="$(python3 -c "import json;print(len(json.load(open('$JSON'))['items']))" 2>/dev/null || echo 0)"
if [ "$N" -lt 1 ]; then
  echo "[$(ts)] [FATAL] JSON空/無効($N件) → option更新せず" >> "$LOG"
  exit 1
fi

if sudo -n "$RW" option update kpop_soompi_chart "$(cat "$JSON")" >>"$LOG" 2>&1; then
  TITLE="$(python3 -c "import json;print(json.load(open('$JSON'))['title'])" 2>/dev/null || echo '?')"
  echo "[$(ts)] ✅ option更新成功: $TITLE ($N件)" >> "$LOG"
else
  echo "[$(ts)] [FATAL] option更新失敗(rwラッパー)" >> "$LOG"
  exit 1
fi
echo "[$(ts)] ===== 完了 =====" >> "$LOG"
