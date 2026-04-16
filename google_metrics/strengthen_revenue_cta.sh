#!/bin/bash
set -e

# .envから環境変数を読み込み
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a; source "$SCRIPT_DIR/.env"; set +a
fi

BASE="$HOME/google_metrics"
WP_API="https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
WP_USER="${WP_USER:-kpop-bot}"
SITE="https://www.kpopjournal.tokyo"
LOCK_FILE="$BASE/revenue_cta_lock.json"
LOG="$BASE/revenue_cta.log"
MAX_PER_DAY=3

echo "" >> "$LOG"
echo "=== $(date '+%Y-%m-%d %H:%M') ===" >> "$LOG"

TODAY=$(date '+%Y-%m-%d')

# 本日上限チェック
DONE_TODAY=$(python3 - << 'PY' "$LOCK_FILE" "$TODAY"
import json, sys, os
f, today = sys.argv[1], sys.argv[2]
data = json.load(open(f)) if os.path.exists(f) else {}
print(data.get(today, {}).get("count", 0))
PY
)

if [ "$DONE_TODAY" -ge "$MAX_PER_DAY" ]; then
  echo "本日上限($MAX_PER_DAY件)に達しました" | tee -a "$LOG"
  exit 0
fi

# 収益カテゴリの記事を取得（スキンケア・コスメ・旅行・ドラマ）
REVENUE_POSTS=$(curl -s -K "$HOME/.wp_auth" \
  "$WP_API?per_page=30&categories=51,54,52,11,70,8&orderby=modified&order=asc" | \
  python3 -c "
import json, sys
posts = json.load(sys.stdin)
for p in posts:
    print(p['id'])
")

PROCESSED=0

for POST_ID in $REVENUE_POSTS; do
  [ "$PROCESSED" -ge "$MAX_PER_DAY" ] && break

  # 24時間以内更新チェック
  RECENTLY=$(python3 - << 'PY' "$LOCK_FILE" "$POST_ID"
import json, sys, os
from datetime import datetime, timedelta
f, pid = sys.argv[1], sys.argv[2]
if not os.path.exists(f): print("NO"); sys.exit()
data = json.load(open(f))
t = data.get("posts", {}).get(pid)
if t and datetime.now() - datetime.fromisoformat(t) < timedelta(hours=24):
    print("YES")
else:
    print("NO")
PY
)
  [ "$RECENTLY" = "YES" ] && continue

  POST=$(curl -s -K "$HOME/.wp_auth" "$WP_API/$POST_ID"?context=edit)
  TITLE=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('title',{}).get('raw','') or d.get('title',{}).get('rendered',''))")
  CONTENT=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('content',{}).get('raw','') or d.get('content',{}).get('rendered',''))")
  CATS=$(echo "$POST" | python3 -c "import json,sys; d=json.load(sys.stdin); print(','.join(map(str,d.get('categories',[]))))")

  # 既にCTAが3つ以上あればスキップ
  CTA_COUNT=$(echo "$CONTENT" | grep -c "revenue-cta\|cta-block\|冒頭CTA\|今すぐチェック" || true)
  if [ "$CTA_COUNT" -ge 3 ]; then
    echo "CTA十分 → スキップ: $TITLE" | tee -a "$LOG"
    continue
  fi

  echo "CTA強化中: $TITLE" | tee -a "$LOG"

  # カテゴリ判定
  ARTICLE_TYPE=$(python3 - << 'PY' "$CATS"
cats = [int(x) for x in sys.argv[1].split(',') if x]
import sys
if any(c in cats for c in [51,54,52,56,12]): print("beauty")
elif any(c in cats for c in [11,70,62,63]): print("travel")
elif any(c in cats for c in [8,27]): print("drama")
elif any(c in cats for c in [5,3]): print("event")
else: print("general")
PY
)

  # Claudeで記事タイプ別CTA生成
  CTA_TOP=$(claude -p "
あなたはK-POPメディアのCVR改善担当です。

以下の記事の冒頭に入れる「冒頭CTA」をHTMLで1つ作成してください。

【記事タイプ】$ARTICLE_TYPE
【タイトル】$TITLE

【ルール】
- 読者がすぐ行動したくなる一言
- ボタン風のHTMLデザイン（枠・色付き）
- class=\"cta-block top-cta\" を付ける
- 1ブロックのみ出力
- 説明・前置き禁止

【タイプ別指針】
beauty: 「今すぐ試せる」「公式で確認する」系
travel: 「ホテルを比較する」「最安値を見る」系
drama: 「今すぐ無料で見る」「配信を確認する」系
event: 「チケットを確認する」「日程をチェック」系
" | grep -v "^$" | head -20)

  CTA_MID=$(claude -p "
以下の記事の中盤に入れる「中盤CTA」をHTMLで1つ作成してください。

【記事タイプ】$ARTICLE_TYPE
【タイトル】$TITLE

【ルール】
- 記事を読み進めた読者への追加提案
- class=\"cta-block mid-cta\" を付ける
- 関連する別記事や行動喚起を含める
- 1ブロックのみ出力
- 説明禁止
" | grep -v "^$" | head -20)

  FAQ=$(claude -p "
以下の記事に入れるFAQセクションをHTMLで作成してください。

【タイトル】$TITLE
【記事タイプ】$ARTICLE_TYPE

【ルール】
- Q&A形式、3〜5問
- 読者が本当に知りたいことを想定
- <h2>よくある質問</h2>から始める
- <details><summary>Q: ...</summary>A: ...</details> 形式
- 説明禁止・本文のみ出力
" | grep -v "^$" | head -40)

  CTA_BOTTOM=$(claude -p "
以下の記事の末尾に入れる「末尾CTA」をHTMLで1つ作成してください。

【記事タイプ】$ARTICLE_TYPE
【タイトル】$TITLE

【ルール】
- 最後の決め手となる強いCTA
- class=\"cta-block bottom-cta\" を付ける
- 緊急性・限定感を演出
- 1ブロックのみ出力
- 説明禁止
" | grep -v "^$" | head -20)

  # コンテンツに挿入
  NEW_CONTENT=$(python3 - << 'PY' "$CONTENT" "$CTA_TOP" "$CTA_MID" "$FAQ" "$CTA_BOTTOM"
import sys, re

content = sys.argv[1]
cta_top = sys.argv[2]
cta_mid = sys.argv[3]
faq = sys.argv[4]
cta_bottom = sys.argv[5]

# 冒頭CTA: 最初のh2の直前
content = re.sub(r'(<h2)', cta_top + r'\n\1', content, count=1)

# 中盤CTA: 3番目のh2の直前
h2_positions = [m.start() for m in re.finditer(r'<h2', content)]
if len(h2_positions) >= 3:
    pos = h2_positions[2]
    content = content[:pos] + cta_mid + "\n" + content[pos:]

# FAQ + 末尾CTA: 情報元の直前 or 末尾（ブロック要素を壊さない）
if "情報元" in content:
    idx = content.rfind("情報元")
    # 情報元を含む最も近い開始タグ(<p>, <div>等)の先頭を探す
    best = -1
    for tag in ["<p", "<div"]:
        t = content.rfind(tag, 0, idx)
        if t >= 0 and (idx - t) < 300 and t > best:
            best = t
    insert_pos = best if best >= 0 else idx
    content = content[:insert_pos] + faq + "\n\n" + cta_bottom + "\n\n" + content[insert_pos:]
else:
    content = content + "\n\n" + faq + "\n\n" + cta_bottom

print(content)
PY
)

  # WordPress更新
  UPDATE=$(python3 -c "import json,sys; print(json.dumps({'content': sys.argv[1]}, ensure_ascii=False))" "$NEW_CONTENT")
  RESP=$(curl -s -X POST "$WP_API/$POST_ID" \
    -K "$HOME/.wp_auth" \
    -H "Content-Type: application/json" \
    -d "$UPDATE")

  LINK=$(echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('link',''))" 2>/dev/null)

  if [ -n "$LINK" ]; then
    echo "✅ CTA強化完了: $TITLE" | tee -a "$LOG"
    curl -s -X POST "$$DISCORD_WEBHOOK" \
      -H "Content-Type: application/json" \
      -d "{\"content\":\"🎯 収益記事CTA強化\n$TITLE\n冒頭/中盤/FAQ/末尾CTA追加済み\"}" > /dev/null
  else
    echo "❌ 更新失敗: $TITLE" | tee -a "$LOG"
  fi

  # ロック更新
  python3 - << 'PY' "$LOCK_FILE" "$TODAY" "$POST_ID"
import json, sys, os
from datetime import datetime
f, today, pid = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.load(open(f)) if os.path.exists(f) else {}
data.setdefault(today, {})["count"] = data.get(today, {}).get("count", 0) + 1
data.setdefault("posts", {})[pid] = datetime.now().isoformat()
json.dump(data, open(f, "w"), ensure_ascii=False)
PY

  PROCESSED=$((PROCESSED + 1))

done

echo "CTA強化完了: ${PROCESSED}件" | tee -a "$LOG"
