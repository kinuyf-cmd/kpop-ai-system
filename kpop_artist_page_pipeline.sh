#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# アーティスト別専用ページ生成パイプライン
# TOP20アーティストの包括的プロフィールページを生成・投稿
#
# 使い方:
#   bash kpop_artist_page_pipeline.sh              # 全アーティスト一括（既存スキップ）
#   bash kpop_artist_page_pipeline.sh --artist bts # 個別指定
#   bash kpop_artist_page_pipeline.sh --dry-run    # テスト実行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/env_loader.sh"

# パイプライン排他ロック
_GLOBAL_PIPELINE_LOCK="/tmp/kpop_pipeline_global.flock"
exec 9>"$_GLOBAL_PIPELINE_LOCK"
if ! flock -n 9; then
  echo "⏭️  他のパイプラインが実行中のため、この起動はスキップします（artist_page）"
  exit 0
fi

# 1日最大投稿数チェック
_DAILY_MAX="${DAILY_POST_LIMIT:-15}"
_TODAY=$(date +%Y-%m-%d)
_KPI_LOG="$SCRIPT_DIR/logs/kpi_posts.jsonl"
_TODAY_COUNT=0
if [[ -f "$_KPI_LOG" ]]; then
  _TODAY_COUNT=$(grep -c "\"date\": \"${_TODAY}\"" "$_KPI_LOG" 2>/dev/null) || _TODAY_COUNT=0
fi
if [[ "$_TODAY_COUNT" -ge "$_DAILY_MAX" ]]; then
  echo "⛔ 本日の投稿上限（${_DAILY_MAX}本）に達しています" >&2
  exit 0
fi

# パイプラインログ
PIPELINE_JSONL="$SCRIPT_DIR/logs/pipeline.jsonl"
mkdir -p "$SCRIPT_DIR/logs"
RUN_ID=$(date '+%Y%m%d_%H%M%S')
TODAY=$(date '+%Y年%m月%d日')

log_step() {
  local step="$1" status="$2" msg="${3:-}"
  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  msg="${msg//\\/\\\\}"
  msg="${msg//\"/\\\"}"
  printf '{"timestamp":"%s","run_id":"%s","pipeline":"artist_page","step":"%s","status":"%s","message":"%s"}\n' \
    "$ts" "$RUN_ID" "$step" "$status" "$msg" >> "$PIPELINE_JSONL"
}

echo "========================================"
echo " アーティスト専用ページ生成パイプライン"
echo " 実行日: $TODAY"
echo " RUN_ID: $RUN_ID"
echo "========================================"

# 引数をそのまま artist_page_generator.py に渡す
ARGS="$@"
if [[ -z "$ARGS" ]]; then
  ARGS="--all --skip-existing"
fi

log_step "start" "ok" "args=$ARGS"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [1] 記事生成・投稿
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "[1/3] アーティスト記事生成..."

python3 "$SCRIPT_DIR/lib/artist_page_generator.py" $ARGS 2>&1 | tee "$SCRIPT_DIR/logs/artist_page_${RUN_ID}.log"
GEN_EXIT=$?

if [[ $GEN_EXIT -ne 0 ]]; then
  echo "❌ 記事生成でエラー (exit: $GEN_EXIT)"
  log_step "generation" "error" "exit_code=$GEN_EXIT"
  exit 1
fi
log_step "generation" "ok"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [2] 生成済み記事のサムネイル一括生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "[2/3] サムネイル生成（投稿済み記事）..."

# 生成ログから今回投稿された記事を抽出してサムネイル生成
POSTED=$(grep "\"status\": \"posted\"" "$SCRIPT_DIR/logs/artist_page_generation.jsonl" 2>/dev/null | \
         python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line.strip())
        ts = d.get('timestamp', '')
        if '${_TODAY}' in ts.replace('-', ''):
            print(d.get('post_id', ''), d.get('url', ''))
    except: pass
" 2>/dev/null)

if [[ -n "$POSTED" ]]; then
  while IFS=' ' read -r post_id post_url; do
    if [[ -n "$post_id" && "$post_id" != "None" ]]; then
      echo "  サムネイル: post_id=$post_id"
      # サムネイルは個別アーティスト記事投稿時に artist_page_generator.py 内で処理済み
      # 追加のサムネイル処理が必要な場合はここに追加
    fi
  done <<< "$POSTED"
else
  echo "  今回新規投稿なし（スキップ）"
fi
log_step "thumbnails" "ok"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [3] インデックス登録
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "[3/3] Google/Bing インデックス登録..."

if [[ -n "$POSTED" ]]; then
  while IFS=' ' read -r post_id post_url; do
    if [[ -n "$post_url" && "$post_url" != "None" ]]; then
      echo "  Google Indexing: $post_url"
      bash "$SCRIPT_DIR/google_metrics/request_index.sh" "$post_url" 2>&1 || echo "  ⚠️ Google インデックススキップ"
      echo "  Bing Submission: $post_url"
      bash "$SCRIPT_DIR/google_metrics/request_bing_index.sh" "$post_url" 2>&1 || echo "  ⚠️ Bing インデックススキップ"
    fi
  done <<< "$POSTED"
else
  echo "  新規投稿なし（スキップ）"
fi
log_step "indexing" "ok"

echo ""
echo "========================================"
echo " ✅ アーティスト専用ページパイプライン完了"
echo " ログ: logs/artist_page_${RUN_ID}.log"
echo "========================================"
log_step "complete" "ok"
