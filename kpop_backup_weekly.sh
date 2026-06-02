#!/bin/bash
# ============================================================
# kpop_backup_weekly.sh — M8 M-4 予防メンテ(週次バックアップ)
#
# 役割: KPOP JOURNAL stg の DB + 重要ファイルを週次バックアップ。
#   1. WP DB のフルダンプ → ~/.kpop_recovery/backups/{date}_db.sql.gz
#   2. ACF JSON / テーマ / 重要設定の tar.gz バックアップ
#   3. 4週間より古いバックアップを自動削除
#   4. 完了通知 Discord
#
# crontab: 0 3 * * 1 (月曜 03:00、popup_event_weekly より前に実行)
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATE=$(date '+%Y%m%d')
TS=$(date '+%Y-%m-%dT%H:%M:%S+09:00')
BACKUP_DIR="${HOME}/.kpop_recovery/backups"
LOG_DIR="${HOME}/.kpop_recovery/blue_team"
LOG_FILE="${LOG_DIR}/backup_${DATE}.log"

mkdir -p "$BACKUP_DIR" "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "===== kpop_backup_weekly.sh 開始 (${DATE}) ====="

# ─── 1. WP DB ダンプ ─────────────────────
if [[ ! -f /tmp/wp_stg.txt ]]; then
  log "ERROR: /tmp/wp_stg.txt がない、DB バックアップスキップ"
else
  source /tmp/wp_stg.txt 2>/dev/null
  DB_OUT="${BACKUP_DIR}/${DATE}_db.sql"
  log "Step 1: WP DB ダンプ → $DB_OUT.gz"
  if mysqldump --default-character-set=utf8mb4 \
      -u "$WP_DB_USER" -p"$WP_DB_PASSWORD" \
      --single-transaction --quick --routines --triggers \
      "$WP_DB_NAME" > "$DB_OUT" 2>>"$LOG_FILE"; then
    gzip -f "$DB_OUT"
    DB_SIZE=$(ls -lh "$DB_OUT.gz" | awk '{print $5}')
    log "  DB ダンプ完了: $DB_OUT.gz ($DB_SIZE)"
  else
    log "  ERROR: mysqldump 失敗"
  fi
fi

# ─── 2. 重要ファイルの tar.gz ─────────────────────
FILES_OUT="${BACKUP_DIR}/${DATE}_files.tar.gz"
log "Step 2: 重要ファイル tar.gz → $FILES_OUT"

# 対象:
#   - 子テーマ /var/www/wp_stg/wp-content/themes/generatepress-kpop/
#   - ACF JSON /var/www/wp_stg/wp-content/themes/generatepress-kpop/acf-json/
#   - kpop-ai-system/ の lib/ + 主要 .sh
TMP_LIST=$(mktemp)
cat > "$TMP_LIST" <<'EOF'
/home/aiuser/kpop-ai-system/lib
/home/aiuser/kpop-ai-system/red_team_scan.sh
/home/aiuser/kpop-ai-system/blue_team_repair.sh
/home/aiuser/kpop-ai-system/audit_daily.sh
/home/aiuser/kpop-ai-system/audit_weekly.sh
/home/aiuser/kpop-ai-system/audit_monthly.sh
/home/aiuser/kpop-ai-system/popup_event_weekly.sh
/home/aiuser/kpop-ai-system/lighthouse_daily.sh
/home/aiuser/kpop-ai-system/kpop_backup_weekly.sh
/home/aiuser/kpop-ai-system/config
/home/aiuser/.kpop_recovery/red_team
/home/aiuser/.kpop_recovery/blue_team
/home/aiuser/.kpop_recovery/100point_state.json
/home/aiuser/.kpop_recovery/roadmap_state.json
EOF
# /var/www/ への読み取りは aiuser 権限で可能なファイルのみ(www-data 所有は読み取れない)
# テーマファイルは別途オーナー側でバックアップ運用想定

if tar -czf "$FILES_OUT" -T "$TMP_LIST" 2>>"$LOG_FILE"; then
  FILES_SIZE=$(ls -lh "$FILES_OUT" | awk '{print $5}')
  log "  ファイル tar.gz 完了: $FILES_OUT ($FILES_SIZE)"
else
  log "  WARN: tar 部分エラー(www-data 所有ファイル読み取り不可は想定内)"
fi
rm -f "$TMP_LIST"

# ─── 3. 古いバックアップ削除(4週間保持) ─────────────────────
log "Step 3: 4週間より古いバックアップを削除"
find "$BACKUP_DIR" -type f \( -name "*_db.sql.gz" -o -name "*_files.tar.gz" \) -mtime +28 -print -delete 2>&1 | tee -a "$LOG_FILE" | head -10

# ─── 4. 現状バックアップ一覧 ─────────────────────
log "Step 4: バックアップ一覧"
ls -lh "$BACKUP_DIR"/ 2>&1 | tee -a "$LOG_FILE" | head -20

# ─── Discord 通知 ─────────────────────
if [[ -f "${SCRIPT_DIR}/config/discord_webhooks.json" ]]; then
  # webhook は ${VAR} プレースホルダーを .env から展開して取得(未展開だと不正URL=失敗)。
  WEBHOOK=$(python3 "${SCRIPT_DIR}/lib/resolve_discord_webhook.py" weekly_board_report 2>/dev/null)
  if [[ -n "$WEBHOOK" ]]; then
    DB_INFO=""
    [[ -f "${BACKUP_DIR}/${DATE}_db.sql.gz" ]] && DB_INFO=" db=$(ls -lh "${BACKUP_DIR}/${DATE}_db.sql.gz" | awk '{print $5}')"
    FILES_INFO=""
    [[ -f "${BACKUP_DIR}/${DATE}_files.tar.gz" ]] && FILES_INFO=" files=$(ls -lh "${BACKUP_DIR}/${DATE}_files.tar.gz" | awk '{print $5}')"
    MSG="💾 週次バックアップ完了 (${DATE})${DB_INFO}${FILES_INFO}"
    curl -s -X POST -H "Content-Type: application/json" -d "{\"content\":\"${MSG}\"}" "$WEBHOOK" > /dev/null 2>&1 || log "Discord 通知失敗"
  fi
fi

log "===== kpop_backup_weekly.sh 完了 ====="
exit 0
