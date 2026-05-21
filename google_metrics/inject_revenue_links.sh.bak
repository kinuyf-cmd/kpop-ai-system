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
DISCORD_WEBHOOK="${DISCORD_WEBHOOK:-}"
BASE="$HOME/google_metrics"
SITE="https://www.kpopjournal.tokyo"

POST_ID="$1"
[ -z "$POST_ID" ] && echo "使い方: inject_revenue_links.sh POST_ID" && exit 1

POST=$(curl -s -u "$WP_USER:$WP_PASS" "$WP_API/$POST_ID")
CATS=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(','.join(map(str,d.get('categories',[]))))")
CONTENT=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('content',{}).get('rendered',''))")
TITLE=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('title',{}).get('rendered',''))")

# 既存CTAチェック
HAS_CTA=$(echo "$CONTENT" | grep -c "revenue-cta" || true)
[ "$HAS_CTA" -gt 0 ] && echo "CTA既存 → スキップ: $POST_ID" && exit 0

# カテゴリ→収益記事マッピング
REVENUE_BLOCK=$(python3 - << 'PY' "$CATS" "$SITE"
import sys
cats = [int(x) for x in sys.argv[1].split(',') if x]
site = sys.argv[2]

mapping = {
    # ライブ・イベント・チケット
    (3, 5): [
        ("/kpop-events-japan-april-2026-complete/", "2026年4月 K-POPライブ・来日イベント完全ガイド"),
        ("/kpop-events-japan-2025-list/", "日本のK-POPイベント総まとめ"),
    ],
    # 美容・スキンケア・コスメ
    (51, 12, 54, 52, 56): [
        ("/medicube-age-r-boosterpro-review/", "メディキューブAGE-R ブースタープロ徹底レビュー"),
        ("/korean-eyeshadow-palette-itzy-2025/", "韓国最新トレンドアイパレット特集"),
        ("/kpop-idol-hairset-morning5min/", "朝5分でできる韓国アイドル式ヘアセット術"),
    ],
    # ドラマ・映画
    (8, 27): [
        ("/confidenceman-kr-guide/", "コンフィデンスマンKR 完全配信ガイド"),
    ],
    # 旅行・ソウル
    (11, 70, 62, 63): [
        ("/hongdae-hotel-arex-stay-2025/", "弘大ホテル｜空港鉄道直結で移動ラク"),
        ("/bts-pilgrimage-hongdae-hybe-seongsu/", "BTS聖地巡礼ガイド｜弘大・HYBE"),
        ("/incheon-to-seoul-arex-vs-allstop/", "仁川空港↔ソウル 移動ガイド"),
    ],
}

selected = []
for cat_group, articles in mapping.items():
    if any(c in cats for c in cat_group):
        selected = articles[:2]
        break

if not selected:
    # デフォルト: 複数の導線を提供
    selected = [
        ("/kpop-events-japan-april-2026-complete/", "2026年4月 K-POPライブ・来日イベント完全ガイド"),
        ("/glass-skin-routine-kpop-2026/", "BTS・IVEも実践するガラス肌ルーティン5選"),
    ]

links = "".join(
    f'<li><a href="{site}{slug}?utm_source=internal&utm_medium=cta&utm_campaign=revenue_link" style="color:#ff4d6d;font-weight:bold;">{title}</a></li>'
    for slug, title in selected
)

html = f'''<div class="revenue-cta" style="border:2px solid #ff4d6d;padding:20px;margin:32px 0;border-radius:12px;background:#fff5f7;">
<p style="font-size:1.1em;font-weight:bold;margin:0 0 12px;">📌 あわせて読みたい</p>
<ul style="margin:0;padding-left:20px;line-height:2;">{links}</ul>
</div>'''
print(html)
PY
)

NEW_CONTENT=$(CONTENT_IN="$CONTENT" BLOCK_IN="$REVENUE_BLOCK" python3 - << 'PY'
import os
content = os.environ["CONTENT_IN"]
block = os.environ["BLOCK_IN"]
# 末尾の情報元の前に挿入（囲むブロック要素ごと分割して壊さない）
if "情報元" in content:
    idx = content.rfind("情報元")
    # 情報元を含む最も近い開始タグ(<p>, <div>等)の先頭を探す
    best = -1
    for tag in ["<p", "<div"]:
        t = content.rfind(tag, 0, idx)
        if t >= 0 and (idx - t) < 300 and t > best:
            best = t
    insert_pos = best if best >= 0 else idx
    print(content[:insert_pos] + block + "\n\n" + content[insert_pos:])
else:
    print(content + "\n\n" + block)
PY
)

UPDATE=$(CONTENT_IN="$NEW_CONTENT" python3 -c "import json,os; print(json.dumps({'content': os.environ['CONTENT_IN']}, ensure_ascii=False))")

RESP=$(echo "$UPDATE" | curl -s -X POST "$WP_API/$POST_ID"   -u "$WP_USER:$WP_PASS"   -H "Content-Type: application/json"   -d @-)

LINK=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('link',''))")

if [ -n "$LINK" ]; then
  echo "✅ 収益導線追加: $TITLE"
  source "$SCRIPT_DIR/lib/discord_channels.sh" 2>/dev/null || true
  SALES_WEBHOOK=$(get_discord_webhook "sales_monetization" 2>/dev/null || echo "$DISCORD_WEBHOOK")
  curl -s -X POST "$SALES_WEBHOOK" -H "Content-Type: application/json"     -d "{\"content\":\"💰 収益導線追加\n$TITLE\n$LINK\"}" > /dev/null
else
  echo "❌ 失敗: POST_ID=$POST_ID"
fi
