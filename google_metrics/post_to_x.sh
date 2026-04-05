#!/bin/bash
# ============================================================
# post_to_x.sh - X/Twitter 自動投稿（OAuth 1.0a 正規API版）
#
# Usage:
#   bash ~/google_metrics/post_to_x.sh "記事タイトル" "記事URL" "persian出力ファイル"
#   bash ~/google_metrics/post_to_x.sh "記事タイトル" "記事URL"
# ============================================================
set -euo pipefail

# dry-run制御: ENABLE_X_POST=1 で本番投稿、未設定/0 でdry-run
DRY_RUN=true
if [ "${ENABLE_X_POST:-0}" = "1" ]; then
  DRY_RUN=false
fi

TITLE="${1:-}"
POST_URL="${2:-}"
PERSIAN_FILE="${3:-}"

if [ -z "$TITLE" ]; then
  echo "❌ タイトルが指定されていません"
  exit 1
fi

if [ ! -f ~/.x_credentials ]; then
  echo "⚠ X認証情報未設定 → スキップ"
  exit 0
fi

echo "=== X/Twitter 自動投稿 ==="

# persianファイルから投稿文を抽出
TWEET_TEXT=""
if [ -n "$PERSIAN_FILE" ] && [ -f "$PERSIAN_FILE" ]; then
  TWEET_TEXT=$(python3 -c "
import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
patterns = [
    r'(?:パターン1|投稿文1|採用推奨)[：:\s]*\n?(.*?)(?:\n\n|\nパターン|\n投稿文|\n#|\Z)',
    r'(?:^|\n)([^\n]*?(?:#KPOP|#kpop|#韓国)[^\n]*)',
]
for pat in patterns:
    m = re.search(pat, text, re.DOTALL)
    if m:
        t = m.group(1).strip()
        t = re.sub(r'^[「『]|[」』]$', '', t)
        if len(t) > 30:
            print(t); sys.exit()
print('')
" "$PERSIAN_FILE" 2>/dev/null || echo "")
fi

# persianから取れなければarticunoで生成
if [ -z "$TWEET_TEXT" ] || [ ${#TWEET_TEXT} -lt 30 ]; then
  TWEET_TEXT=$(claude --agent articuno -p "
以下のK-POP記事のX/Twitter投稿文を1つだけ作れ。
【ルール】
- 200文字以内
- 冒頭でニュースの核心を伝える（バイラル狙い）
- ハッシュタグ2-4個（#KPOP必須）
- 絵文字1-2個
- 説明・前置き禁止。投稿文のみ出力。

記事タイトル: ${TITLE}
記事URL: ${POST_URL}
" 2>/dev/null || echo "")
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

echo "  投稿文: ${TWEET_TEXT:0:100}..."

if [ "$DRY_RUN" = "true" ]; then
  echo "[DRY-RUN] X投稿をスキップしました（ENABLE_X_POST=1 で有効化）"
  echo "  投稿予定文:"
  echo "  $TWEET_TEXT"
  exit 0
fi

python3 ~/google_metrics/post_to_x.py "$TWEET_TEXT"
