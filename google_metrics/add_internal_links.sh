#!/bin/bash
set -e

# .envから環境変数を読み込み
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a; source "$SCRIPT_DIR/.env"; set +a
fi

WP_API="https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
WP_USER="${WP_USER:-kpop-bot}"
WP_PASS="${WP_PASS}"
DISCORD_WEBHOOK="$DISCORD_WEBHOOK"

TARGET_PAGE="$1"

if [ -z "$TARGET_PAGE" ]; then
  echo "使い方: bash ~/google_metrics/add_internal_links.sh /slug/"
  exit 1
fi

SLUG=$(python3 - << 'PY' "$TARGET_PAGE"
import sys
page = sys.argv[1].strip().rstrip("/")
print(page.split("/")[-1])
PY
)

POST_JSON=$(curl -s -u "$WP_USER:$WP_PASS" "$WP_API?slug=$SLUG")
POST_ID=$(echo "$POST_JSON" | python3 - << 'PY'
import sys, json
data = json.load(sys.stdin)
if isinstance(data, list) and len(data) > 0:
    print(data[0].get("id",""))
else:
    print("")
PY
)

TITLE=$(echo "$POST_JSON" | python3 - << 'PY'
import sys, json
data = json.load(sys.stdin)
if isinstance(data, list) and len(data) > 0:
    print(data[0].get("title",{}).get("rendered",""))
else:
    print("")
PY
)

CONTENT=$(echo "$POST_JSON" | python3 - << 'PY'
import sys, json
data = json.load(sys.stdin)
if isinstance(data, list) and len(data) > 0:
    print(data[0].get("content",{}).get("rendered",""))
else:
    print("")
PY
)

if [ -z "$POST_ID" ] || [ -z "$TITLE" ] || [ -z "$CONTENT" ]; then
  echo "投稿取得失敗"
  exit 1
fi

# 関連候補抽出用クエリ（日本語タイトルから抽出）
SEARCH_WORD=$(python3 - << 'PY' "$TITLE"
import sys, re
title = sys.argv[1]
title = re.sub(r'【.*?】', '', title)
title = re.sub(r'[0-9０-９]+', '', title)
title = re.sub(r'[｜|【】\[\]「」『』\-\─━]', ' ', title)
title = title.strip()
# 最初の10文字（絞りすぎを防ぐ）
print(title[:10].strip())
PY
)

curl -s -u "$WP_USER:$WP_PASS" "$WP_API?search=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))' "$SEARCH_WORD")&per_page=6" > /tmp/related_posts.json

RELATED_HTML=$(python3 - << 'PY' "$POST_ID"
import sys, json
with open("/tmp/related_posts.json") as f:
    data = json.load(f)
current_id = str(sys.argv[1])

items = []
for post in data:
    if str(post.get("id")) == current_id:
        continue
    title = post.get("title", {}).get("rendered", "").strip()
    link = post.get("link", "").strip()
    if title and link:
        items.append(f'<li><a href="{link}">{title}</a></li>')

items = items[:3]

if items:
    html = '<h2>関連記事</h2><ul>' + ''.join(items) + '</ul>'
else:
    html = ''

print(html)
PY
)

if [ -z "$RELATED_HTML" ]; then
  echo "関連記事候補なし"
  exit 0
fi

# 既に関連記事ブロックがある場合はスキップ
HAS_RELATED=$(CONTENT_IN="$CONTENT" python3 - << 'PY'
import os
content = os.environ["CONTENT_IN"]
print("YES" if "関連記事" in content else "NO")
PY
)

if [ "$HAS_RELATED" = "YES" ]; then
  echo "既に関連記事あり。スキップ"
  exit 0
fi

NEW_CONTENT=$(CONTENT_IN="$CONTENT" RELATED_IN="$RELATED_HTML" python3 - << 'PY'
import os
content = os.environ["CONTENT_IN"]
related = os.environ["RELATED_IN"]
print(content + "\n\n" + related)
PY
)

UPDATE_JSON=$(TITLE_IN="$TITLE" CONTENT_IN="$NEW_CONTENT" python3 - << 'PY'
import os, json
print(json.dumps({
    "title": os.environ["TITLE_IN"],
    "content": os.environ["CONTENT_IN"]
}, ensure_ascii=False))
PY
)

RESP=$(echo "$UPDATE_JSON" | curl -s -X POST "$WP_API/$POST_ID" \
  -u "$WP_USER:$WP_PASS" \
  -H "Content-Type: application/json" \
  -d @-)

UPDATED=$(echo "$RESP" | python3 - << 'PY'
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get("link",""))
except:
    print("")
PY
)

if [ -n "$UPDATED" ]; then
  echo "内部リンク追加成功: $UPDATED"

  python3 - << PY
import requests
webhook = """$DISCORD_WEBHOOK"""
msg = """🔗 内部リンク自動追加\n対象: $TITLE\nURL: $UPDATED"""
requests.post(webhook, json={"content": msg[:1900]}, timeout=20)
PY
else
  echo "内部リンク追加失敗"
fi
