#!/usr/bin/env bash
# update_soompi_chart.sh — Soompi K-Pop Music Chart Top10 を取得し WP option に取り込む。
#   ① Node(playwright)で .current-rank から top10抽出 → data/soompi_chart_top10.json
#   ② wp option update kpop_soompi_chart に JSON を格納(PHP shortcode が読む)
#   最新週のURLは CHART_URL で指定可(未指定なら自動発見を試行→失敗時は前回JSONを維持)。
#   Soompiは週次更新。cron 例: 0 6 * * 1(毎週月曜)。owner 実行(wpはwww-data)。
#   実行: sudo bash tools/chart/update_soompi_chart.sh [CHART_URL]
set -uo pipefail
cd "$(dirname "$0")/../.."
ROOT="$PWD"
JSON="$ROOT/data/soompi_chart_top10.json"
URL="${1:-${CHART_URL:-}}"

echo "================ Soompi Chart Top10 取得 ================"
# URL未指定なら自動発見を試行
if [ -z "$URL" ]; then
  URL="$(node tools/chart/find_latest_chart.mjs 2>/dev/null || true)"
  [ -n "$URL" ] && echo "  自動発見URL: $URL" || echo "  [warn] 自動発見失敗 → 既存JSON維持 or CHART_URL指定要"
fi

if [ -n "$URL" ]; then
  if CHART_URL="$URL" node tools/chart/soompi_chart_fetch.mjs 2>&1 | tail -12; then
    echo "  ✅ 取得成功"
  else
    echo "  [warn] 取得失敗 → 既存JSON維持(空にしない)"
  fi
fi

# ② WP option に取り込み(www-data の wp)
if [ -f "$JSON" ] && [ "$(python3 -c "import json;print(len(json.load(open('$JSON'))['items']))" 2>/dev/null || echo 0)" -ge 1 ]; then
  # wp option update は値が長いので --format=json で stdin から
  sudo -u www-data wp --path=/var/www/wp_stg option update kpop_soompi_chart "$(cat "$JSON")" 2>&1 | head -2
  echo "  ✅ wp_option kpop_soompi_chart 更新"
  echo "  現在の格納件数: $(sudo -u www-data wp --path=/var/www/wp_stg option get kpop_soompi_chart --format=json 2>/dev/null | python3 -c "import json,sys;print(len(json.load(sys.stdin)['items']))" 2>/dev/null || echo '?')"
else
  echo "  [FATAL] JSONが空/無効 → option更新せず(古いデータ維持)"
fi
echo "================ 完了 ================"
