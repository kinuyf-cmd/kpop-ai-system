#!/bin/bash
set -e

WP_API="https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
WP_USER="${WP_USER:-kpop-bot}"
WP_PASS="${WP_PASS}"
DISCORD_WEBHOOK="${DISCORD_WEBHOOK}"

POST_ID="$1"
[ -z "$POST_ID" ] && echo "使い方: inject_abema_cta.sh POST_ID" && exit 0

POST=$(curl -s -u "$WP_USER:$WP_PASS" "$WP_API/$POST_ID")
TITLE=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('title',{}).get('rendered',''))" 2>/dev/null)
CONTENT=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('content',{}).get('rendered',''))" 2>/dev/null)

[ -z "$TITLE" ] && echo "タイトル取得失敗 → スキップ" && exit 0
[ -z "$CONTENT" ] && echo "本文取得失敗 → スキップ" && exit 0

PLAIN=$(python3 -c "
import re, sys
text = sys.argv[1] + ' ' + sys.argv[2]
print(re.sub(r'<[^>]+>', '', text))
" "$TITLE" "$CONTENT" 2>/dev/null)

MATCH=$(python3 - << 'PY' "$PLAIN"
import sys
text = sys.argv[1]
keywords = [
    "スウパ",
    "STREET WOMAN FIGHTER",
    "SWF",
    "見逃し配信",
    "無料視聴",
    "無料で見る",
    "ABEMA",
    "アベマ",
    "配信で見る",
    "視聴方法",
]
print("YES" if any(kw in text for kw in keywords) else "NO")
PY
)

if [ "$MATCH" != "YES" ]; then
  echo "キーワード不一致 → スキップ: $TITLE"
  exit 0
fi

HAS_CTA=$(echo "$CONTENT" | grep -c "cta-box" || true)
if [ "$HAS_CTA" -gt 0 ]; then
  echo "CTA既存 → スキップ: $TITLE"
  exit 0
fi

CHAR_COUNT=$(echo "$PLAIN" | wc -m | tr -d ' ')
if [ "$CHAR_COUNT" -lt 500 ]; then
  echo "本文短すぎ(${CHAR_COUNT}字) → スキップ: $TITLE"
  exit 0
fi

CTA_HTML='<div class="cta-box" style="border:1px solid #ddd;padding:16px;margin:20px 0;text-align:center;">
<p style="font-size:16px;font-weight:bold;">
📺 スウパ3を無料で見るならABEMA
</p>
<p style="margin:10px 0;">
<a href="https://px.a8.net/svt/ejp?a8mat=457NRV+ASS3KQ+4EKC+5YJRM" rel="nofollow" style="display:inline-block;padding:12px 20px;background:#ff2d55;color:#fff;text-decoration:none;font-weight:bold;border-radius:6px;">
ABEMAで無料視聴する
</a>
</p>
<img border="0" width="1" height="1" src="https://www13.a8.net/0.gif?a8mat=457NRV+ASS3KQ+4EKC+5YJRM" alt="">
<p style="font-size:12px;color:#777;margin-top:8px;">
※無料トライアル期間中の解約も可能です
</p>
</div>'

NEW_CONTENT=$(python3 - << 'PY' "$CONTENT" "$CTA_HTML"
import sys, re
content = sys.argv[1]
cta = sys.argv[2]

if "情報元" in content:
    idx = content.rfind("情報元")
    content = content[:idx] + cta + "\n\n" + content[idx:]
else:
    content = content + "\n\n" + cta

h2_first = re.search(r'<h2', content)
if h2_first:
    pos = h2_first.start()
    content = content[:pos] + cta + "\n\n" + content[pos:]

print(content)
PY
)

UPDATE=$(python3 -c "import json,sys; print(json.dumps({'content': sys.argv[1]}, ensure_ascii=False))" "$NEW_CONTENT")
RESP=$(curl -s -X POST "$WP_API/$POST_ID" \
  -u "$WP_USER:$WP_PASS" \
  -H "Content-Type: application/json" \
  -d "$UPDATE")

LINK=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('link',''))" 2>/dev/null)

if [ -n "$LINK" ]; then
  echo "✅ ABEMA CTA挿入完了: $TITLE"
else
  echo "❌ ABEMA CTA更新失敗: POST_ID=$POST_ID"
fi
