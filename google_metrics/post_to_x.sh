#!/bin/bash
# ============================================================
# post_to_x.sh - X/Twitter 自動投稿（OAuth 1.0a 正規API版）
#
# Usage:
#   bash $_SCRIPT_DIR/google_metrics/post_to_x.sh "記事タイトル" "記事URL" "persian出力ファイル"
#   bash $_SCRIPT_DIR/google_metrics/post_to_x.sh "記事タイトル" "記事URL"
# ============================================================
set -euo pipefail

# .envから環境変数を読み込み
_SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$_SCRIPT_DIR/.env" ]; then
  set -a; source "$_SCRIPT_DIR/.env"; set +a
fi

# ログファイル
X_LOG="/home/aiuser/kpop-ai-system/logs/x_post.log"
mkdir -p "$(dirname "$X_LOG")"

xlog() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
  echo "$msg" >> "$X_LOG"
  echo "$msg"
}

# dry-run制御: ENABLE_X_POST=1 で本番投稿、未設定/0 でdry-run
DRY_RUN=true
if [ "${ENABLE_X_POST:-0}" = "1" ]; then
  DRY_RUN=false
fi

TITLE="${1:-}"
POST_URL="${2:-}"
PERSIAN_FILE="${3:-}"

if [ -z "$TITLE" ]; then
  xlog "ERROR: タイトルが指定されていません"
  exit 1
fi

if [ ! -f ~/.x_credentials ]; then
  xlog "SKIP: X認証情報未設定（~/.x_credentials が見つかりません）"
  exit 0
fi

xlog "=== X/Twitter 自動投稿開始 ==="
xlog "TITLE: $TITLE"
xlog "URL: $POST_URL"
xlog "PERSIAN_FILE: ${PERSIAN_FILE:-なし}"
xlog "DRY_RUN: $DRY_RUN"

# persianファイルから投稿文を抽出
TWEET_TEXT=""
if [ -n "$PERSIAN_FILE" ] && [ -f "$PERSIAN_FILE" ]; then
  TWEET_TEXT=$(python3 -c "
import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()

# パターンA/1/採用推奨のコードブロック内テキストを抽出
patterns = [
    # コードブロック内のパターンA
    r'パターンA[^\n]*\n\`\`\`\n(.*?)\n\`\`\`',
    # パターンA（コードブロックなし）
    r'パターンA[^\n]*\n((?:[^\n]+\n){1,5})',
    # パターン1
    r'(?:パターン1|投稿文1)[^\n]*\n\`\`\`\n(.*?)\n\`\`\`',
    r'(?:パターン1|投稿文1)[^\n]*\n((?:[^\n]+\n){1,5})',
    # 採用推奨
    r'採用推奨[^\n]*\n\`\`\`\n(.*?)\n\`\`\`',
    r'採用推奨[^\n]*\n((?:[^\n]+\n){1,5})',
    # #KPOP含む行を含むブロック
    r'(?:^|\n)([^\n]*(?:#KPOP|#kpop)[^\n]*)',
]
for pat in patterns:
    m = re.search(pat, text, re.DOTALL)
    if m:
        t = m.group(1).strip()
        t = re.sub(r'^[\`\s]+|[\`\s]+$', '', t)
        t = re.sub(r'^[「『]|[」』]$', '', t)
        # 文字数が30以上あれば採用（）
        if len(t) > 30:
            # URLが古い場合は置換
            print(t); sys.exit()
print('')
" "$PERSIAN_FILE" 2>/dev/null || echo "")
fi

# persianから取れなければテンプレートで生成
if [ -z "$TWEET_TEXT" ] || [ ${#TWEET_TEXT} -lt 30 ]; then
  TWEET_TEXT=$(python3 "$_SCRIPT_DIR/lib/x_post_templates.py" "$TITLE" "$POST_URL" --genre default 2>/dev/null || echo "")
fi

# フォールバック
if [ -z "$TWEET_TEXT" ] || [ ${#TWEET_TEXT} -lt 20 ]; then
  TWEET_TEXT="${TITLE}
#KPOP #韓国
${POST_URL}"
fi

# URLが含まれていなければ追加
if [[ -n "$POST_URL" ]] && [[ "$TWEET_TEXT" != *"$POST_URL"* ]]; then
  TWEET_TEXT="${TWEET_TEXT}
${POST_URL}"
fi

# ツイート文ログ
xlog "TWEET_TEXT: $TWEET_TEXT"
xlog "TWEET_LENGTH: ${#TWEET_TEXT}"

# X投稿スコアリング
X_SCORE_JSON=$(python3 $_SCRIPT_DIR/google_metrics/score_x_post.py "$TWEET_TEXT" 2>&1 || echo '{"pass":true,"score":0}')
X_PASS=$(python3 -c "import json,sys; print('YES' if json.loads(sys.argv[1]).get('pass') else 'NO')" "$X_SCORE_JSON" 2>/dev/null || echo "YES")
X_SCORE=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('score',0))" "$X_SCORE_JSON" 2>/dev/null || echo "0")
xlog "SCORE: $X_SCORE (pass=$X_PASS)"

if [ "$X_PASS" != "YES" ]; then
  echo "  ⚠ X投稿スコア低 → テンプレートで再生成"
  TWEET_TEXT=$(python3 "$_SCRIPT_DIR/lib/x_post_templates.py" "$TITLE" "$POST_URL" --genre default 2>/dev/null || echo "")

  if [ -n "$TWEET_TEXT" ] && [ ${#TWEET_TEXT} -ge 20 ]; then
    # URLが含まれていなければ追加
    if [[ -n "$POST_URL" ]] && [[ "$TWEET_TEXT" != *"$POST_URL"* ]]; then
      TWEET_TEXT="${TWEET_TEXT}
${POST_URL}"
    fi
    # 再スコアリング
    X_SCORE_JSON=$(python3 $_SCRIPT_DIR/google_metrics/score_x_post.py "$TWEET_TEXT" 2>/dev/null || echo '{"pass":true,"score":0}')
    X_PASS=$(python3 -c "import json,sys; print('YES' if json.loads(sys.argv[1]).get('pass') else 'NO')" "$X_SCORE_JSON" 2>/dev/null || echo "YES")
    X_SCORE=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('score',0))" "$X_SCORE_JSON" 2>/dev/null || echo "0")
    xlog "RE-SCORE: $X_SCORE (pass=$X_PASS)"
  fi

  if [ "$X_PASS" != "YES" ]; then
    xlog "RESULT: スコア不合格によりスキップ (score=$X_SCORE)"
    exit 0
  fi
fi

xlog "FINAL_TWEET: ${TWEET_TEXT:0:100}..."

if [ "$DRY_RUN" = "true" ]; then
  xlog "RESULT: DRY-RUN（ENABLE_X_POST=1 で有効化）"
  echo "[DRY-RUN] X投稿をスキップしました（ENABLE_X_POST=1 で有効化）"
  echo "  投稿予定文:"
  echo "  $TWEET_TEXT"
  exit 0
fi

xlog "POST: X API呼び出し開始"
POST_OUTPUT=$(python3 $_SCRIPT_DIR/google_metrics/post_to_x.py "$TWEET_TEXT" 2>&1) || {
  xlog "RESULT: X投稿失敗 - $POST_OUTPUT"
  echo "$POST_OUTPUT"
  exit 1
}
echo "$POST_OUTPUT"

# ツイートIDやURLをログに記録
TWEET_ID=$(echo "$POST_OUTPUT" | grep -oP '(?:tweet_id|id)["\s:=]+\K[0-9]+' | head -1 || true)
TWEET_URL=$(echo "$POST_OUTPUT" | grep -oP 'https://x\.com/\S+' | head -1 || true)
if [ -n "$TWEET_URL" ]; then
  xlog "RESULT: 投稿成功 - $TWEET_URL"
elif [ -n "$TWEET_ID" ]; then
  xlog "RESULT: 投稿成功 - tweet_id=$TWEET_ID"
else
  xlog "RESULT: 投稿完了 - $POST_OUTPUT"
fi
