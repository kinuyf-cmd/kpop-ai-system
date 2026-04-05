#!/bin/bash
# 環境変数読み込み（.envまたはホームの実設定から）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
elif [ -f "$HOME/kpop-ai-system/.env" ]; then
  set -a
  source "$HOME/kpop-ai-system/.env"
  set +a
fi

# フォールバック: ホームの直接設定
WP_USER="${WP_USER:-kpop-bot}"
WP_PASS="${WP_PASS:-}"
DISCORD_WEBHOOK="${DISCORD_WEBHOOK:-$(cat ~/.kpop_discord_webhook 2>/dev/null || echo '')}"
