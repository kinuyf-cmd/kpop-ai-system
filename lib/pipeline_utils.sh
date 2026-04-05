#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# pipeline_utils.sh - パイプライン共通ユーティリティ
#
# 提供機能:
# - 強制停止チェック
# - final_post.md 生成（審査レポート分離）
# - post_guard 統合チェック
# - リトライ付きClaude実行
# - リトライ付きWP投稿
# - KPIログ記録
# - 二重投稿防止
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIB_DIR="$SCRIPT_DIR/lib"
REPORTS_DIR="$SCRIPT_DIR/reports"
LOGS_DIR="$SCRIPT_DIR/logs"

# 環境変数読み込み
source "$SCRIPT_DIR/env_loader.sh"

mkdir -p "$REPORTS_DIR" "$LOGS_DIR"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 強制停止チェック
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
check_emergency_stop() {
  if [ -f "$SCRIPT_DIR/EMERGENCY_STOP" ]; then
    echo "🚨 EMERGENCY_STOP is active"
    cat "$SCRIPT_DIR/EMERGENCY_STOP"
    return 1
  fi

  local stop_result
  stop_result=$(python3 "$LIB_DIR/post_guard.py" emergency 2>/dev/null)
  local is_stopped
  is_stopped=$(echo "$stop_result" | python3 -c "import json,sys; print(json.load(sys.stdin).get('stop',False))" 2>/dev/null)

  if [ "$is_stopped" = "True" ]; then
    echo "🚨 Emergency stop triggered by post_guard"
    echo "$stop_result"
    return 1
  fi

  return 0
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# リトライ付きClaudeエージェント実行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_claude_with_retry() {
  local agent="$1"
  local prompt="$2"
  local output_file="$3"
  local max_retries="${4:-2}"
  local fallback_agent="${5:-}"
  local extra_args="${6:-}"

  local attempt=0
  local agents_to_try="$agent"
  [ -n "$fallback_agent" ] && agents_to_try="$agent $fallback_agent"

  for current_agent in $agents_to_try; do
    attempt=0
    while [ "$attempt" -lt "$max_retries" ]; do
      echo "  [attempt $((attempt+1))/$max_retries] Agent: $current_agent"

      if [ -n "$extra_args" ]; then
        claude --dangerously-skip-permissions $extra_args --agent "$current_agent" -p "$prompt" > "$output_file" 2>&1
      else
        claude --dangerously-skip-permissions --agent "$current_agent" -p "$prompt" > "$output_file" 2>&1
      fi

      # 出力検証
      if [ -s "$output_file" ]; then
        # NGフレーズチェック
        local has_ng
        has_ng=$(python3 -c "
import sys
with open(sys.argv[1], encoding='utf-8', errors='replace') as f:
    text = f.read(1000)
ng = ['申し訳ありません','お手伝いできますか','AIとして','言語モデル','質問があります']
print('YES' if any(w in text for w in ng) else 'NO')
" "$output_file" 2>/dev/null)

        if [ "$has_ng" = "NO" ]; then
          echo "  ✓ Agent output OK"
          return 0
        else
          echo "  ⚠ Agent returned NG output"
        fi
      else
        echo "  ⚠ Agent output is empty"
      fi

      attempt=$((attempt + 1))
      if [ "$attempt" -lt "$max_retries" ]; then
        local delay=$((5 * (2 ** attempt)))
        echo "  Waiting ${delay}s before retry..."
        sleep "$delay"
      fi
    done

    if [ "$current_agent" != "$agent" ]; then
      echo "  ⚠ Fallback agent $current_agent also failed"
    elif [ -n "$fallback_agent" ]; then
      echo "  → Trying fallback: $fallback_agent"
    fi
  done

  echo "  ❌ All agents failed for $output_file"
  return 1
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# final_post.md 生成（審査レポート分離の要）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
create_final_post() {
  local source_file="$1"  # 2_checked.md (ジラーチ出力)

  if [ ! -s "$source_file" ]; then
    echo "❌ Source file empty: $source_file"
    return 1
  fi

  # ソースファイルが審査レポートでないことを確認
  local basename
  basename=$(basename "$source_file")
  case "$basename" in
    3_arceus.md|review_log.md|*_review.md|*_score.md)
      echo "🚨 BLOCK: $basename は審査レポートです。final_post.md にコピーできません。"
      python3 "$LIB_DIR/kpi_logger.py" log_error '{"pipeline":"create_final_post","step":"source_check","error_type":"review_report_as_source","message":"'"$basename"'","recoverable":false}' 2>/dev/null
      return 1
      ;;
  esac

  # 審査レポートの内容が混入していないか検証
  local has_review
  has_review=$(python3 -c "
import sys
with open(sys.argv[1], encoding='utf-8', errors='replace') as f:
    text = f.read()
signals = ['エージェント別採点','最終記事品質評価','投稿承認','投稿却下','採点表','スコア:','/50点','/10点','デオキシス:','メタモン:','ジラーチ:','アルセウス:']
found = [s for s in signals if s in text]
print('|'.join(found) if found else 'CLEAN')
" "$source_file" 2>/dev/null)

  if [ "$has_review" != "CLEAN" ]; then
    echo "🚨 BLOCK: 審査レポートの内容が混入: $has_review"
    return 1
  fi

  cp "$source_file" "$REPORTS_DIR/final_post.md"
  echo "✓ final_post.md created from $basename"
  return 0
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# post_guard 全チェック
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_post_guard() {
  local title="$1"
  local slug="$2"
  local article_type="${3:-flow}"

  local result
  result=$(python3 "$LIB_DIR/post_guard.py" full_check "$title" "$slug" "$article_type" 2>/dev/null)

  local allowed
  allowed=$(echo "$result" | python3 -c "import json,sys; print(json.load(sys.stdin).get('allowed',False))" 2>/dev/null)

  echo "$result"

  if [ "$allowed" = "True" ]; then
    return 0
  else
    return 1
  fi
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 投稿実行（post_to_wp.py呼び出し）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
publish_final_post() {
  local slug="$1"
  local category_id="$2"
  local artist_ids="$3"
  local tag_ids="$4"
  local media_id="${5:-0}"
  local article_type="${6:-flow}"
  local status="${7:-publish}"

  local cat_arg=""
  if [ -n "$category_id" ]; then
    cat_arg="$category_id"
    [ -n "$artist_ids" ] && cat_arg="$cat_arg,$artist_ids"
  fi

  local tag_arg=""
  [ -n "$tag_ids" ] && tag_arg="$tag_ids"

  local cmd="python3 $SCRIPT_DIR/post_to_wp.py"
  [ -n "$slug" ] && cmd="$cmd --slug $slug"
  [ -n "$cat_arg" ] && cmd="$cmd --categories $cat_arg"
  [ -n "$tag_arg" ] && cmd="$cmd --tags $tag_arg"
  [ "$media_id" -gt 0 ] 2>/dev/null && cmd="$cmd --media $media_id"
  [ -n "$article_type" ] && cmd="$cmd --type $article_type"
  [ -n "$status" ] && cmd="$cmd --status $status"

  eval "$cmd"
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# KPIログ記録ヘルパー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
log_kpi_post() {
  local json_data="$1"
  python3 "$LIB_DIR/kpi_logger.py" log_post "$json_data" 2>/dev/null
}

log_kpi_error() {
  local json_data="$1"
  python3 "$LIB_DIR/kpi_logger.py" log_error "$json_data" 2>/dev/null
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 投稿後処理（インデックス/X/CTA）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_post_publish_tasks() {
  local post_id="$1"
  local post_url="$2"
  local slug="$3"
  local title="$4"
  local article_type="${5:-flow}"

  echo "=== Post-publish tasks ==="

  # CTA挿入
  echo "  [CTA] Injecting revenue links..."
  bash ~/google_metrics/inject_revenue_links.sh "$post_id" 2>/dev/null || echo "  CTA skip"

  # 内部リンク
  echo "  [Links] Adding internal links..."
  bash ~/google_metrics/add_internal_links.sh "/$slug/" 2>/dev/null || echo "  Links skip"

  # Google Index
  echo "  [Google] Requesting index..."
  local g_attempt=0
  while [ "$g_attempt" -lt 3 ]; do
    bash ~/google_metrics/request_index.sh "$post_url" 2>/dev/null && break
    g_attempt=$((g_attempt + 1))
    [ "$g_attempt" -lt 3 ] && sleep $((3 * g_attempt))
  done

  # Bing Index
  echo "  [Bing] Requesting index..."
  local b_attempt=0
  while [ "$b_attempt" -lt 3 ]; do
    bash ~/google_metrics/request_bing_index.sh "$post_url" 2>/dev/null && break
    b_attempt=$((b_attempt + 1))
    [ "$b_attempt" -lt 3 ] && sleep $((3 * b_attempt))
  done

  echo "  ✓ Post-publish tasks done"
}
