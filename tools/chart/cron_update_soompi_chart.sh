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

STREAK="$ROOT/data/.soompi_chart_fail_streak"

notify() {
  # Discord 通知(publishing_log)。失敗しても本処理は止めない。
  local msg="$1"
  local hook
  hook="$(python3 lib/resolve_discord_webhook.py publishing_log 2>/dev/null || true)"
  [ -z "$hook" ] && return 0
  curl -s -H "Content-Type: application/json" \
       -H "User-Agent: KPOP-JOURNAL-Bot/1.0" \
       -d "$(python3 -c "import json,sys;print(json.dumps({'content':sys.argv[1]}))" "$msg")" \
       "$hook" >/dev/null 2>&1 && log "Discord通知済(publishing_log)" || log "[warn] Discord通知失敗"
}

ensure_browser() {
  # 2026-08-23: playwright を更新するとブラウザ実体だけ取り残され、
  # find_latest_chart.mjs が起動できずチャートが8日間止まった(16回連続で
  # 無言 exit 0)。起動前に実体を確認し、無ければ自動で入れ直す。
  node -e "require('playwright').chromium.executablePath()" >/dev/null 2>&1 || return 0
  local exe
  exe="$(node -e "console.log(require('playwright').chromium.executablePath())" 2>/dev/null || true)"
  [ -n "$exe" ] && [ -x "$exe" ] && return 0
  log "[warn] Playwright ブラウザ実体が無い($exe) → 自動インストールを試行"
  # INSTALLATION_COMPLETE マーカーが残っていると、実体が無くても
  # playwright install が「導入済み」と判断してスキップする。先に消す。
  # マーカーは <cache>/<browser>-<rev>/ 直下にある。exe の階層は
  # chrome-linux64/chrome と chrome-headless-shell-linux64/chrome-headless-shell の
  # 2通りあるので、親を遡って INSTALLATION_COMPLETE を持つ階層を探す。
  local dir="$(dirname "$exe")"
  local i=0
  while [ "$i" -lt 4 ] && [ "$dir" != "/" ]; do
    if [ -f "$dir/INSTALLATION_COMPLETE" ]; then
      rm -f "$dir/INSTALLATION_COMPLETE" "$dir/DEPENDENCIES_VALIDATED"
      log "install マーカーを除去: $dir"
      break
    fi
    dir="$(dirname "$dir")"; i=$((i+1))
  done
  # 175MB のダウンロードなので余裕をもたせる。install 自体の戻り値ではなく
  # 「実体が存在するか」で成否を判定する(成功と出て実体が無い事故を防ぐ)。
  timeout 900 npx --yes playwright install chromium >>"$LOG" 2>&1 || true
  exe="$(node -e "console.log(require('playwright').chromium.executablePath())" 2>/dev/null || true)"
  if [ -n "$exe" ] && [ -x "$exe" ]; then
    log "Playwright ブラウザ install 成功(実体を確認)"
  else
    log "[warn] Playwright ブラウザ install 失敗(実体なし) → 今回は据え置き"
    notify "⚠️ Music Chart: Playwright ブラウザの自動復旧に失敗しました。手動で 'npx playwright install chromium' が必要です"
  fi
}

log "===== Soompi Chart 自動更新 チェック開始 ====="
ensure_browser

# ① 最新チャートURLを自動発見(カテゴリページの記事ID最大=最新)
URL="$(node tools/chart/find_latest_chart.mjs 2>>"$LOG" || true)"
if [ -z "$URL" ]; then
  # 失敗を数える。単発は Soompi 側の一時不調もあるので通知しないが、
  # 連続すると「無言で据え置き」のまま何週も古い順位を出し続けるので警告する。
  FAIL_STREAK=$(( $(cat "$STREAK" 2>/dev/null || echo 0) + 1 ))
  echo "$FAIL_STREAK" > "$STREAK"
  log "[warn] URL自動発見失敗(連続${FAIL_STREAK}回) → 既存維持・据え置き"
  if [ "$FAIL_STREAK" -eq 3 ] || [ "$((FAIL_STREAK % 10))" -eq 0 ]; then
    notify "⚠️ Music Chart 自動更新が${FAIL_STREAK}回連続で失敗しています(URL発見不可)。サイトのチャートが古いまま止まっている可能性があります: logs/cron_soompi_chart_update.log"
  fi
  exit 0
fi
rm -f "$STREAK"

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
