#!/bin/bash
# run_backup.sh - KPOP JOURNAL 日次/週次バックアップ
#
# 動作:
#   - 毎日 4:00 cron で実行
#   - 日次: WP REST API 経由で posts/pages/categories/tags/media(メタ) を JSON でダンプ
#   - 週次: 日曜実行時は logs/ config/ agents/ lib/ を含む tar.gz フルバックアップ
#   - 90日より古い日次は自動削除、180日より古い週次は自動削除
#   - 失敗しても exit 0 (次の cron を止めない)
#
# 設定:
#   cron: 0 4 * * *   cd ~/kpop-ai-system && bash run_backup.sh >> ~/kpop-ai-system/logs/backup.log 2>&1

set -u
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$SCRIPT_DIR/backups"
DB_DIR="$BACKUP_DIR/db"
WEEKLY_DIR="$BACKUP_DIR/weekly"
LOG_FILE="$SCRIPT_DIR/logs/backup.log"
WP_AUTH="$HOME/.wp_auth"
WP="https://www.kpopjournal.tokyo"

mkdir -p "$DB_DIR" "$WEEKLY_DIR" "$(dirname "$LOG_FILE")"

TS=$(date '+%Y%m%d_%H%M%S')
TODAY=$(date '+%Y-%m-%d')
DOW=$(date '+%u')  # 1=Monday ... 7=Sunday

log() { echo "[$(date -Iseconds)] $*" >> "$LOG_FILE"; }
log "=== backup start (TS=$TS, DOW=$DOW) ==="

fetch() {
  local path="$1" out="$2"
  local tmp
  tmp=$(mktemp)
  if curl -s --max-time 120 "${WP}${path}" -K "$WP_AUTH" -o "$tmp" 2>/dev/null; then
    mv "$tmp" "$out"
    log "  ✓ fetched $path → $(basename "$out") ($(wc -c < "$out") bytes)"
    return 0
  fi
  rm -f "$tmp"
  log "  ✗ fetch failed: $path"
  return 1
}

# --- 日次: コンテンツダンプ ---
DAILY_SUB="$DB_DIR/$TODAY"
mkdir -p "$DAILY_SUB"

# posts (ページング: 最大1000件)
page=1
posts_dump="$DAILY_SUB/posts.jsonl"
: > "$posts_dump"
while [ "$page" -le 20 ]; do
  tmp=$(mktemp)
  if ! curl -s --max-time 120 "${WP}/wp-json/wp/v2/posts?per_page=50&page=${page}&status=publish,draft,private" -K "$WP_AUTH" -o "$tmp"; then
    rm -f "$tmp"; break
  fi
  n=$(python3 -c "import json,sys
try:
    d=json.load(open(sys.argv[1]))
    if isinstance(d,list): print(len(d))
    else: print(0)
except Exception: print(0)" "$tmp")
  if [ "$n" -eq 0 ]; then rm -f "$tmp"; break; fi
  python3 -c "import json,sys
try:
    d=json.load(open(sys.argv[1]))
    for r in d: print(json.dumps(r, ensure_ascii=False))
except Exception: pass" "$tmp" >> "$posts_dump" 2>/dev/null
  rm -f "$tmp"
  if [ "$n" -lt 50 ]; then break; fi
  page=$((page+1))
done
log "  ✓ posts.jsonl: $(wc -l < "$posts_dump") lines"

# categories / tags (single call)
fetch "/wp-json/wp/v2/categories?per_page=100" "$DAILY_SUB/categories.json" || true
fetch "/wp-json/wp/v2/tags?per_page=100"       "$DAILY_SUB/tags.json" || true
fetch "/wp-json/wp/v2/users?per_page=20"       "$DAILY_SUB/users.json" || true

# media メタのみ (source_url等)
fetch "/wp-json/wp/v2/media?per_page=100&orderby=date&order=desc&_fields=id,date,source_url,alt_text,title" "$DAILY_SUB/media_recent.json" || true

# settings系の軽量ダンプ
cp "$SCRIPT_DIR/crontab.txt" "$DAILY_SUB/" 2>/dev/null || true
cp -r "$SCRIPT_DIR/config" "$DAILY_SUB/config" 2>/dev/null || true

# 圧縮
( cd "$DB_DIR" && tar czf "${TODAY}.tar.gz" "$TODAY" && rm -rf "$TODAY" ) && \
  log "  ✓ daily archive: ${TODAY}.tar.gz ($(du -sh "$DB_DIR/${TODAY}.tar.gz" | cut -f1))" || \
  log "  ✗ daily archive failed"

# --- 週次フル (日曜) ---
if [ "$DOW" -eq 7 ]; then
  WEEKLY_FILE="$WEEKLY_DIR/weekly_${TS}.tar.gz"
  # 除外: logs配下の巨大ログ、reports_*、venv、backups自身
  tar czf "$WEEKLY_FILE" \
    --exclude="$SCRIPT_DIR/backups" \
    --exclude="$SCRIPT_DIR/reports_*" \
    --exclude="$SCRIPT_DIR/reports" \
    --exclude="$SCRIPT_DIR/.venv" \
    --exclude="$SCRIPT_DIR/assets/artist_cache" \
    --exclude="$SCRIPT_DIR/diffs" \
    --exclude="$SCRIPT_DIR/logs/*.log" \
    -C "$(dirname "$SCRIPT_DIR")" "$(basename "$SCRIPT_DIR")" \
    2>/dev/null && \
    log "  ✓ weekly archive: $(du -sh "$WEEKLY_FILE" | cut -f1) $WEEKLY_FILE" || \
    log "  ✗ weekly archive failed"
fi

# --- ローテーション ---
# 日次: 90日より古いものを削除
find "$DB_DIR" -name "*.tar.gz" -mtime +90 -delete 2>/dev/null || true
# 週次: 180日より古いものを削除
find "$WEEKLY_DIR" -name "weekly_*.tar.gz" -mtime +180 -delete 2>/dev/null || true

log "=== backup complete ==="
# 失敗しても次のcronを止めないため必ず exit 0
exit 0
