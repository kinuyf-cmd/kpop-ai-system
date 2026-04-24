#!/bin/bash
# x_404_reply_cleanup.sh — X投稿404 URLリプライの一括削除
#
# 2026-04-24 調査で発見された11件のsoft-404 URLリプライを削除する。
# 原因: パイプラインがX投稿→post_audit→draft化の順序で実行し、
#        draft化後もX URLリプライが残存していた。
#
# 使い方:
#   DRY_RUN=1 bash lib/x_404_reply_cleanup.sh  # プレビュー
#   bash lib/x_404_reply_cleanup.sh             # 実行

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
POSTER="$SCRIPT_DIR/google_metrics/post_to_x.py"
LOG="$SCRIPT_DIR/logs/x_404_cleanup.log"

DRY_RUN="${DRY_RUN:-0}"

log() { echo "[$(date -Iseconds)] $1" | tee -a "$LOG"; }

# 削除対象: reply_tweet_id (URLリプライのみ削除、メインフックは残す)
declare -A REPLY_TWEETS=(
  ["2045747195832648098"]="nct-wish-april-10-ode-love-2026 (post 3333)"
  ["2045996932829757806"]="ファクトチェック結果をまとめます (slug bug)"
  ["2046126118621892683"]="illit-babymonster-2026 (post 3683)"
  ["2046396225969410375"]="kpop-korean-1-2026 (post 3840)"
  ["2046433455043760624"]="twice-3-days-20260421 (post 3850)"
  ["2046456961093513233"]="kpop-bts-seventeen-lesserafim-aespa-4-2026 (post 3854)"
  ["2046487308724236750"]="kpop-9-bts-blackpink-ive-guide-2026 (post 3864)"
  ["2047159670922793453"]="newjeans-2026-20260423 (post 3952)"
  ["2047181974859825385"]="kpop-idol-korean-cosmetics-2-2026 (post 3956)"
  ["2047212466661413279"]="kpop-top10-blackpink-1-2026 (post 3980)"
  ["2047423280789987406"]="2026年04月第17週チャート速報 (Japanese slug)"
)

log "=== X 404 URLリプライ削除開始 (DRY_RUN=$DRY_RUN) ==="
log "対象: ${#REPLY_TWEETS[@]}件"

SUCCESS=0
FAIL=0

for tweet_id in "${!REPLY_TWEETS[@]}"; do
  desc="${REPLY_TWEETS[$tweet_id]}"
  if [ "$DRY_RUN" = "1" ]; then
    log "[DRY] 削除予定: $tweet_id — $desc"
    continue
  fi

  log "削除中: $tweet_id — $desc"
  if python3 "$POSTER" --delete "$tweet_id" 2>&1 | tee -a "$LOG"; then
    SUCCESS=$((SUCCESS + 1))
    log "✅ 削除成功: $tweet_id"
  else
    FAIL=$((FAIL + 1))
    log "❌ 削除失敗: $tweet_id"
  fi
  sleep 2  # Rate limit
done

log "=== 完了: 成功=$SUCCESS 失敗=$FAIL ==="
