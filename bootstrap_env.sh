#!/bin/bash
# bootstrap_env.sh - VPS再構築・再起動後の環境自動復旧
#
# 冪等スクリプト。@reboot cron から呼ばれ、以下を保証する:
#   1. /home/aiuser の所有権（aiuser:aiuser）
#   2. ~/.wp_auth（.env から自動生成）
#   3. ~/.kpop_discord_webhook（.env から自動生成）
#   4. Black weight 日本語フォント（Noto CJK JP Black への symlink）
#
# 失敗項目のみログ出力。正常項目は静粛。
set -u
BASE="/home/aiuser/kpop-ai-system"
HOME_DIR="/home/aiuser"
LOG="$BASE/logs/bootstrap_env.log"
mkdir -p "$BASE/logs" 2>/dev/null || true

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

# --- 1. home 所有権 ---
if [ "$(stat -c '%U' "$HOME_DIR")" != "aiuser" ]; then
  chown aiuser:aiuser "$HOME_DIR" 2>/dev/null && log "FIX home ownership → aiuser:aiuser" \
    || log "WARN chown $HOME_DIR failed（要root）"
fi

# --- 2. .env 読み込み ---
if [ ! -f "$BASE/.env" ]; then
  log "FATAL $BASE/.env がない。復旧不可"; exit 1
fi
set -a; source "$BASE/.env"; set +a

# --- 3. ~/.wp_auth ---
if [ ! -s "$HOME_DIR/.wp_auth" ]; then
  if [ -n "${WP_USER:-}" ] && [ -n "${WP_PASS:-}" ]; then
    TOKEN=$(echo -n "${WP_USER}:${WP_PASS}" | base64 -w0)
    sudo -u aiuser bash -c "cat > $HOME_DIR/.wp_auth <<AUTH
header = \"Authorization: Basic ${TOKEN}\"
AUTH
chmod 600 $HOME_DIR/.wp_auth" && log "FIX ~/.wp_auth 再生成" \
      || log "WARN ~/.wp_auth 作成失敗"
  else
    log "WARN WP_USER/WP_PASS が .env にない"
  fi
fi

# --- 4. ~/.kpop_discord_webhook ---
if [ ! -s "$HOME_DIR/.kpop_discord_webhook" ] && [ -n "${DISCORD_WEBHOOK:-}" ]; then
  sudo -u aiuser bash -c "printf '%s' \"$DISCORD_WEBHOOK\" > $HOME_DIR/.kpop_discord_webhook; chmod 600 $HOME_DIR/.kpop_discord_webhook" \
    && log "FIX ~/.kpop_discord_webhook 再生成" \
    || log "WARN ~/.kpop_discord_webhook 作成失敗"
fi

# --- 4.5. ~/google_metrics シンボリックリンク（fetch_yesterday_metrics.py が ~/google_metrics を参照） ---
if [ ! -e "$HOME_DIR/google_metrics" ]; then
  ln -sfn "$BASE/google_metrics" "$HOME_DIR/google_metrics"
  chown -h aiuser:aiuser "$HOME_DIR/google_metrics"
  log "FIX ~/google_metrics → $BASE/google_metrics"
fi

# --- 5. Black weight 日本語フォント ---
FONT_DIR="$HOME_DIR/.local/share/fonts"
FONT_LINK="$FONT_DIR/NotoSansJP-Black.otf"
FONT_SRC="/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"
if [ ! -e "$FONT_LINK" ] || [ ! -s "$(readlink -f "$FONT_LINK")" ]; then
  if [ ! -f "$FONT_SRC" ]; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y fonts-noto-cjk-extra >/dev/null 2>&1 \
      && log "FIX fonts-noto-cjk-extra インストール"
  fi
  if [ -f "$FONT_SRC" ]; then
    sudo -u aiuser mkdir -p "$FONT_DIR"
    ln -sfn "$FONT_SRC" "$FONT_LINK"
    chown -h aiuser:aiuser "$FONT_LINK" 2>/dev/null
    log "FIX $FONT_LINK → $FONT_SRC"
  else
    log "WARN Noto CJK Black フォントが見つからない"
  fi
fi

log "bootstrap_env.sh 完了"
exit 0
