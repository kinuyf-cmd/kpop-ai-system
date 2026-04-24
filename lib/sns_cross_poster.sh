#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SNS クロスポスト統合スクリプト v1.0
# 記事公開後にX/Instagram/LINE/Webプッシュへ自動配信
#
# Usage:
#   bash lib/sns_cross_poster.sh --title "タイトル" --url "記事URL" \
#     --category breaking --image "https://...thumbnail.jpg"
#
#   bash lib/sns_cross_poster.sh --title "..." --url "..." --dry-run
#
# パイプライン連携:
#   kpop_pipeline.sh の WP投稿成功後に自動呼び出し
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
SNS_CONFIG="$BASE_DIR/config/sns_config.json"
LOG_FILE="$BASE_DIR/logs/sns_cross_post.log"

# ── 引数パース ──
TITLE=""
URL=""
CATEGORY="default"
IMAGE=""
DRY_RUN=0
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --title)    TITLE="$2"; shift 2 ;;
    --url)      URL="$2"; shift 2 ;;
    --category) CATEGORY="$2"; shift 2 ;;
    --image)    IMAGE="$2"; shift 2 ;;
    --dry-run)  DRY_RUN=1; shift ;;
    --force)    FORCE=1; shift ;;
    *)          shift ;;
  esac
done

if [[ -z "$TITLE" || -z "$URL" ]]; then
  echo "Usage: bash lib/sns_cross_poster.sh --title '...' --url '...' --category breaking --image '...'"
  exit 1
fi

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "━━ SNSクロスポスト開始 ━━"
log "  タイトル: $TITLE"
log "  URL: $URL"
log "  カテゴリ: $CATEGORY"
log "  画像: ${IMAGE:-なし}"
[[ $DRY_RUN -eq 1 ]] && log "  [DRY-RUN モード]"

# ── 設定読み込み ──
get_channels() {
  local cat="$1"
  if command -v python3 &>/dev/null; then
    python3 -c "
import json
c = json.load(open('$SNS_CONFIG'))
ch = c.get('cross_post',{}).get('channels_by_category',{})
print(' '.join(ch.get('$cat', ch.get('default', ['x']))))
" 2>/dev/null || echo "x"
  else
    echo "x"
  fi
}

DELAY=$(python3 -c "
import json
c = json.load(open('$SNS_CONFIG'))
print(c.get('cross_post',{}).get('delay_between_channels_sec', 30))
" 2>/dev/null || echo "30")

CHANNELS=$(get_channels "$CATEGORY")
log "  配信チャネル: $CHANNELS"

DRY_FLAG=""
[[ $DRY_RUN -eq 1 ]] && DRY_FLAG="--dry-run"

FORCE_FLAG=""
[[ $FORCE -eq 1 ]] && FORCE_FLAG="--force"

RESULTS=()
ERRORS=0

for ch in $CHANNELS; do
  log "--- $ch ---"

  case "$ch" in
    x)
      # X投稿は既存の post_to_x.sh が担当（パイプライン内で別途実行）
      log "  X投稿: パイプラインの既存フローで処理済み（スキップ）"
      RESULTS+=("x:skip")
      ;;

    instagram)
      # Instagram設定チェック
      IG_ENABLED=$(python3 -c "import json; c=json.load(open('$SNS_CONFIG')); print(c.get('instagram',{}).get('enabled', False))" 2>/dev/null || echo "False")
      if [[ "$IG_ENABLED" != "True" ]]; then
        log "  Instagram: 無効（config/sns_config.json で enabled: true に設定）"
        RESULTS+=("instagram:disabled")
      elif [[ -z "$IMAGE" ]]; then
        log "  Instagram: 画像URLなし（スキップ）"
        RESULTS+=("instagram:no_image")
      else
        if python3 "$SCRIPT_DIR/post_to_instagram.py" \
          --title "$TITLE" --url "$URL" --image "$IMAGE" \
          --category "$CATEGORY" $DRY_FLAG 2>&1 | tee -a "$LOG_FILE"; then
          RESULTS+=("instagram:ok")
        else
          log "  ⚠️ Instagram投稿失敗（非致命的）"
          RESULTS+=("instagram:error")
          ((ERRORS++)) || true
        fi
      fi
      ;;

    line)
      LINE_ENABLED=$(python3 -c "import json; c=json.load(open('$SNS_CONFIG')); print(c.get('line',{}).get('enabled', False))" 2>/dev/null || echo "False")
      if [[ "$LINE_ENABLED" != "True" ]]; then
        log "  LINE: 無効（config/sns_config.json で enabled: true に設定）"
        RESULTS+=("line:disabled")
      else
        IMG_FLAG=""
        [[ -n "$IMAGE" ]] && IMG_FLAG="--image $IMAGE"
        if python3 "$SCRIPT_DIR/line_push_notifier.py" \
          --title "$TITLE" --url "$URL" --category "$CATEGORY" \
          $IMG_FLAG $DRY_FLAG $FORCE_FLAG 2>&1 | tee -a "$LOG_FILE"; then
          RESULTS+=("line:ok")
        else
          log "  ⚠️ LINE配信失敗（非致命的）"
          RESULTS+=("line:error")
          ((ERRORS++)) || true
        fi
      fi
      ;;

    webpush)
      WP_ENABLED=$(python3 -c "import json; c=json.load(open('$SNS_CONFIG')); print(c.get('webpush',{}).get('enabled', False))" 2>/dev/null || echo "False")
      if [[ "$WP_ENABLED" != "True" ]]; then
        log "  Webプッシュ: 無効（config/sns_config.json で enabled: true に設定）"
        RESULTS+=("webpush:disabled")
      else
        IMG_FLAG=""
        [[ -n "$IMAGE" ]] && IMG_FLAG="--image $IMAGE"
        if python3 "$SCRIPT_DIR/webpush_notifier.py" \
          --title "$TITLE" --url "$URL" --category "$CATEGORY" \
          $IMG_FLAG $DRY_FLAG $FORCE_FLAG 2>&1 | tee -a "$LOG_FILE"; then
          RESULTS+=("webpush:ok")
        else
          log "  ⚠️ Webプッシュ失敗（非致命的）"
          RESULTS+=("webpush:error")
          ((ERRORS++)) || true
        fi
      fi
      ;;

    *)
      log "  未知のチャネル: $ch（スキップ）"
      RESULTS+=("$ch:unknown")
      ;;
  esac

  # チャネル間のディレイ（最後以外）
  if [[ "$ch" != "${CHANNELS##* }" && $DRY_RUN -eq 0 ]]; then
    log "  ⏳ ${DELAY}秒待機..."
    sleep "$DELAY"
  fi
done

log "━━ SNSクロスポスト完了 ━━"
log "  結果: ${RESULTS[*]}"
[[ $ERRORS -gt 0 ]] && log "  ⚠️ ${ERRORS}件のエラーあり（非致命的）"

exit 0
