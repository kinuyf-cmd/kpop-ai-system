#!/bin/bash
set -e

# .envから環境変数を読み込み
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a; source "$SCRIPT_DIR/.env"; set +a
fi

WP_API="https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
WP_USER="${WP_USER:-kpop-bot}"
DISCORD_WEBHOOK="${DISCORD_WEBHOOK}"

POST_ID="$1"
[ -z "$POST_ID" ] && echo "使い方: inject_abema_cta.sh POST_ID" && exit 0

# 重要: ?context=edit で content.raw を取得する
# content.rendered を使うと WordPressプラグインが挿入した広告がベイクインされ、
# 書き戻し時に script タグの中身が wpautop で <br /> 化されてAdSense破壊する
POST=$(curl -s -K "$HOME/.wp_auth" "$WP_API/$POST_ID?context=edit")
TITLE=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('title',{}).get('raw','') or d.get('title',{}).get('rendered',''))" 2>/dev/null)
CONTENT=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('content',{}).get('raw','') or d.get('content',{}).get('rendered',''))" 2>/dev/null)

[ -z "$TITLE" ] && echo "タイトル取得失敗 → スキップ" && exit 0
[ -z "$CONTENT" ] && echo "本文取得失敗 → スキップ" && exit 0

PLAIN=$(TITLE_IN="$TITLE" CONTENT_IN="$CONTENT" python3 -c "
import re, os
text = os.environ['TITLE_IN'] + ' ' + os.environ['CONTENT_IN']
print(re.sub(r'<[^>]+>', '', text))
" 2>/dev/null)

MATCH=$(PLAIN_IN="$PLAIN" python3 - << 'PY'
import os
text = os.environ["PLAIN_IN"]
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

NEW_CONTENT=$(CONTENT_IN="$CONTENT" CTA_IN="$CTA_HTML" python3 - << 'PY'
import os, re
content = os.environ["CONTENT_IN"]
cta = os.environ["CTA_IN"]

# 挿入位置: 情報元の前 > 末尾（ブロック要素を壊さない）
if "情報元" in content:
    idx = content.rfind("情報元")
    # 情報元を含む最も近い開始タグ(<p>, <div>等)の先頭を探す
    best = -1
    for tag in ["<p", "<div"]:
        t = content.rfind(tag, 0, idx)
        if t >= 0 and (idx - t) < 300 and t > best:
            best = t
    insert_pos = best if best >= 0 else idx
    content = content[:insert_pos] + cta + "\n\n" + content[insert_pos:]
else:
    content = content + "\n\n" + cta

print(content)
PY
)

UPDATE=$(CONTENT_IN="$NEW_CONTENT" python3 -c "import json,os; print(json.dumps({'content': os.environ['CONTENT_IN']}, ensure_ascii=False))")
RESP=$(echo "$UPDATE" | curl -s -X POST "$WP_API/$POST_ID" \
  -K "$HOME/.wp_auth" \
  -H "Content-Type: application/json" \
  -d @-)

LINK=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('link',''))" 2>/dev/null)

if [ -n "$LINK" ]; then
  echo "✅ ABEMA CTA挿入完了: $TITLE"
else
  echo "❌ ABEMA CTA更新失敗: POST_ID=$POST_ID"
fi
