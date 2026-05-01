#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 週刊ニュースレター配信スクリプト v1.0
# 毎週日曜 10:00 JST に cron から呼び出し
#
# Usage:
#   bash lib/send_newsletter.sh              # 本番配信
#   bash lib/send_newsletter.sh --build-only # HTMLビルドのみ
#   bash lib/send_newsletter.sh --dry-run    # プレビュー
#   bash lib/send_newsletter.sh --test kpopjournal.biz@gmail.com  # テスト配信
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$BASE_DIR/logs/newsletter.log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "━━ ニュースレター配信開始 ━━"

# 引数パース
MODE=""
TEST_EMAIL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --build-only) MODE="--build-only"; shift ;;
    --dry-run)    MODE="--dry-run"; shift ;;
    --test)       TEST_EMAIL="$2"; shift 2 ;;
    *)            shift ;;
  esac
done

# newsletter_credentials チェック
if [[ ! -f "$HOME/.brevo_credentials" && ! -f "$HOME/.newsletter_credentials" ]]; then
  log "⚠️ ~/.brevo_credentials が未設定 — ビルドのみ実行"
  MODE="--build-only"
fi

# 実行
if [[ -n "$TEST_EMAIL" ]]; then
  python3 "$SCRIPT_DIR/newsletter_builder.py" --test-send "$TEST_EMAIL" 2>&1 | tee -a "$LOG_FILE"
elif [[ -n "$MODE" ]]; then
  python3 "$SCRIPT_DIR/newsletter_builder.py" $MODE 2>&1 | tee -a "$LOG_FILE"
else
  python3 "$SCRIPT_DIR/newsletter_builder.py" 2>&1 | tee -a "$LOG_FILE"
fi

EXIT_CODE=${PIPESTATUS[0]}

if [[ $EXIT_CODE -eq 0 ]]; then
  log "✅ ニュースレター処理完了"
else
  log "❌ ニュースレター処理失敗 (exit: $EXIT_CODE)"
fi

log "━━ ニュースレター配信終了 ━━"
exit $EXIT_CODE
