#!/usr/bin/env bash
# delete_x_post.sh — WordPress記事削除時にX投稿を同時削除
#
# Usage:
#   bash delete_x_post.sh <wp_post_id>
#   bash delete_x_post.sh <wp_post_id> --tweet-id <tweet_id>  # メタ取得をスキップ
#
# 動作:
#   1. WordPress投稿メタ "_x_tweet_id" からツイートIDを取得
#   2. X API v2 DELETE /2/tweets/:id でツイートを削除
#   3. WordPress投稿をゴミ箱に移動（trash）または完全削除

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env_loader.sh" 2>/dev/null || true
TWEET_DB="$SCRIPT_DIR/logs/tweet_id_db.tsv"

WP_USER="${WP_USER:-}"
WP_PASS="${WP_PASS:-}"
WP_BASE="https://www.kpopjournal.tokyo/wp-json/wp/v2"

POST_ID="${1:-}"
TWEET_ID_ARG=""
FORCE_DELETE_WP=0

# 引数パース
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tweet-id) TWEET_ID_ARG="$2"; shift 2 ;;
    --force)    FORCE_DELETE_WP=1; shift ;;
    *) shift ;;
  esac
done

if [ -z "$POST_ID" ]; then
  echo "Usage: bash delete_x_post.sh <wp_post_id> [--tweet-id <id>] [--force]"
  exit 1
fi

echo "=== X投稿削除 (WP記事ID: $POST_ID) ==="

# ── 1. ツイートID取得 ──
if [ -n "$TWEET_ID_ARG" ]; then
  TWEET_ID="$TWEET_ID_ARG"
  echo "  ツイートID: $TWEET_ID (引数指定)"
else
  # 1) ローカルDBから取得（最優先）
  TWEET_ID=""
  if [ -f "$TWEET_DB" ]; then
    TWEET_ID=$(grep -P "^${POST_ID}\t" "$TWEET_DB" | tail -1 | cut -f2 || true)
  fi
  if [ -n "$TWEET_ID" ]; then
    echo "  ツイートID: $TWEET_ID (ローカルDB)"
  else
    # 2) WordPressメタから取得（フォールバック）
    META_RESPONSE=$(curl -s "${WP_BASE}/posts/${POST_ID}?context=edit" \
      -K "$HOME/.wp_auth" 2>/dev/null)
    TWEET_ID=$(echo "$META_RESPONSE" | python3 -c "
import json, sys
d = json.load(sys.stdin)
meta = d.get('meta', {})
tid = meta.get('_x_tweet_id', '') or meta.get('x_tweet_id', '')
print(tid)
" 2>/dev/null || true)
    echo "  ツイートID: ${TWEET_ID:-（未登録）}"
  fi
fi

# ── 2. X投稿削除 ──
if [ -n "$TWEET_ID" ]; then
  DELETE_RESULT=$(python3 - "$TWEET_ID" << 'PYEOF'
import json, sys, os, hmac, hashlib, base64, time, uuid
import urllib.request, urllib.error, urllib.parse

tweet_id = sys.argv[1]
CREDS_FILE = os.path.expanduser("~/.x_credentials")

if not os.path.exists(CREDS_FILE):
    print("❌ ~/.x_credentials が見つかりません")
    sys.exit(1)

with open(CREDS_FILE) as f:
    creds = json.load(f)

api_key             = creds["api_key"]
api_secret          = creds["api_secret"]
access_token        = creds["access_token"]
access_token_secret = creds["access_token_secret"]


def make_oauth_header(method: str, endpoint: str) -> str:
    params = {
        "oauth_consumer_key":     api_key,
        "oauth_nonce":            uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp":        str(int(time.time())),
        "oauth_token":            access_token,
        "oauth_version":          "1.0",
    }
    params_string = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(params.items())
    )
    base_string = f"{method}&{urllib.parse.quote(endpoint, safe='')}&{urllib.parse.quote(params_string, safe='')}"
    signing_key = f"{urllib.parse.quote(api_secret, safe='')}&{urllib.parse.quote(access_token_secret, safe='')}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()
    params["oauth_signature"] = signature
    return "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(params.items())
    )

endpoint = f"https://api.twitter.com/2/tweets/{tweet_id}"
auth_header = make_oauth_header("DELETE", endpoint)
req = urllib.request.Request(
    endpoint,
    method="DELETE",
    headers={
        "Authorization": auth_header,
        "User-Agent":    "KPOPJournalBot/1.0",
    },
)
try:
    with urllib.request.urlopen(req, timeout=30) as res:
        result = json.loads(res.read())
    deleted = result.get("data", {}).get("deleted", False)
    if deleted:
        print(f"✅ X投稿削除成功: tweet_id={tweet_id}")
    else:
        print(f"⚠️ X API応答: {result}")
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", errors="replace")
    print(f"❌ X投稿削除失敗 (HTTP {e.code}): {body}")
    sys.exit(1)
PYEOF
  ) || true
  echo "  $DELETE_RESULT"
else
  echo "  ⚠️ ツイートIDが取得できないためX削除をスキップ"
fi

# ── 3. WordPress記事を削除/ゴミ箱 ──
if [ "$FORCE_DELETE_WP" = "1" ]; then
  echo "=== WordPress記事を完全削除 (ID: $POST_ID) ==="
  WP_DEL=$(curl -s -X DELETE "${WP_BASE}/posts/${POST_ID}?force=true" \
    -K "$HOME/.wp_auth" 2>/dev/null)
  DELETED_ID=$(echo "$WP_DEL" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || true)
  [ -n "$DELETED_ID" ] && echo "  ✅ WordPress記事削除完了 (ID=$DELETED_ID)" || echo "  ⚠️ WordPress削除失敗: $WP_DEL"
else
  echo "=== WordPress記事をゴミ箱へ移動 (ID: $POST_ID) ==="
  WP_TRASH=$(curl -s -X DELETE "${WP_BASE}/posts/${POST_ID}" \
    -K "$HOME/.wp_auth" 2>/dev/null)
  TRASH_STATUS=$(echo "$WP_TRASH" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status',''))" 2>/dev/null || true)
  [ "$TRASH_STATUS" = "trash" ] && echo "  ✅ WordPress記事ゴミ箱移動完了" || echo "  ⚠️ ステータス: $TRASH_STATUS"
fi

echo "=== 完了 ==="
