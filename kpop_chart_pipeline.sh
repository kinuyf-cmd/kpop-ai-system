#!/bin/bash

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# K-POPチャートランキング記事パイプライン
# 毎週月曜 8:00 自動実行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

wp_health_check() {
  echo "=== WordPress 接続確認 ==="
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1" \
    -u "$WP_USER:$WP_PASS" \
    --connect-timeout 10 --max-time 15)
  if [[ "$HTTP_CODE" != "200" ]]; then
    echo "❌ WordPress API 接続失敗 (HTTP ${HTTP_CODE}) → パイプライン停止"
    bash ~/kpop_notify.sh error "チャート" "WordPress API 接続失敗 (HTTP ${HTTP_CODE})" 2>/dev/null
    exit 1
  fi
  echo "  ✓ WordPress API 正常 (HTTP ${HTTP_CODE})"
}

check_duplicate() {
  local title="$1"
  local days="${2:-7}"
  echo "=== 重複投稿チェック（過去${days}日）==="

  RECENT_TITLES=$(python3 - "$days" <<'PYEOF'
import sys, json, urllib.request, base64, urllib.parse
from datetime import datetime, timedelta, timezone
days = int(sys.argv[1])
cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=30&after=" + urllib.parse.quote(cutoff)
auth = base64.b64encode(os.environ.get("WP_USER","kpop-bot").encode() + b":" + os.environ.get("WP_PASS","").encode()).decode()
req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
try:
    with urllib.request.urlopen(req, timeout=10) as res:
        posts = json.loads(res.read())
    print("\n".join(p.get("title", {}).get("rendered", "") for p in posts))
except Exception:
    print("")
PYEOF
  )

  if [[ -z "$RECENT_TITLES" ]]; then
    echo "  ⚠️  投稿履歴取得失敗 → チェックスキップ"
    return 0
  fi

  echo "  直近${days}日の投稿: $(echo "$RECENT_TITLES" | grep -c .)件"

  SIMILARITY=$(claude -p "
【タスク】類似記事重複チェック
新しく投稿しようとしている記事タイトルが、過去${days}日間の投稿済みタイトルと内容が重複しているか判定せよ。
【新タイトル】${title}
【過去${days}日間の投稿済みタイトル】
${RECENT_TITLES}
【判定基準】
- 同じウィーク・同じランキング記事 → 重複（YES）
- 別の週・別テーマ → 重複なし（NO）
【出力ルール】YESまたはNOの1単語のみ。他は出力禁止。
")

  if [[ "$SIMILARITY" == "YES" ]]; then
    echo "  ⚠️  重複あり: 類似記事が過去${days}日以内に投稿済み → スキップ"
    echo "    新タイトル: $title"
    exit 0
  fi

  echo "  ✓ 重複なし"
}

mkdir -p reports

TODAY=$(date '+%Y年%m月%d日')
WEEK=$(date '+%Y年%m月第%V週')
RUN_ID=$(date '+%Y%m%d_%H%M%S')
ARCHIVE_DIR=~/kpop_archives/chart_$RUN_ID

echo "========================================"
echo " K-POPチャートランキングパイプライン"
echo " 実行日: $TODAY"
echo "========================================"

wp_health_check

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [1] ザップドス: チャートランキング記事生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "[1/4] ザップドス: 最新チャートランキング記事生成..."

claude --allowedTools WebSearch --agent zapdos -p "
今日は${TODAY}（${WEEK}）です。
以下の手順でK-POPチャートランキング記事を生成せよ。

【検索手順】
1.「Billboard K-POP Hot 100 ${TODAY}」で最新ランキング取得
2.「Melon TOP100 今週 ${TODAY}」で韓国チャート取得
3.「Oricon K-POP 週間ランキング ${TODAY}」で日本チャート取得
4. 今週の記録更新・初登場・急上昇を確認

【記事要件】
- タイトルに「${WEEK}」と「Billboard・Melon」を含める
- リード文で今週の最大ハイライトを伝える
- チャートTOP10以上を表形式で記載（順位・先週比・アーティスト・曲名・注目ポイント）
- 今週の注目ポイント3選（記録・初登場・急上昇）
- 来週の注目カムバック情報
- 末尾に「※本記事は${TODAY}時点の情報です」

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（例：${WEEK} K-POPチャートTOP50｜Billboard・Melon最新ランキング）
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ
" > reports/chart_0_article.md

if [[ ! -s reports/chart_0_article.md ]]; then
  echo "❌ ザップドス: 出力が空 → 停止"
  exit 1
fi
echo "  ✓ reports/chart_0_article.md ($(wc -c < reports/chart_0_article.md | tr -d ' ') bytes)"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [2] アラカザム: ファクトチェック
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "[2/4] アラカザム: 順位・日付ファクトチェック..."

claude --agent alakazam_kpop -p "
今日は${TODAY}です。
以下のK-POPチャートランキング記事をファクトチェックせよ。

【記事】
$(cat reports/chart_0_article.md)

【チェック重点項目】
1. 順位・数字が時制と矛盾していないか
2. 「先週比」の矢印（↑↓→）が正しいか
3. 未来のランキングを断定していないか
4. 情報元の明記があるか

修正が必要な箇所のみ修正して完成記事を出力せよ。

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（##禁止）
2行目：空行
3行目以降：HTML本文のみ
" > reports/chart_1_checked.md

if [[ ! -s reports/chart_1_checked.md ]]; then
  echo "❌ アラカザム: 出力が空 → ザップドス出力をそのまま使用"
  cp reports/chart_0_article.md reports/chart_1_checked.md
fi
echo "  ✓ reports/chart_1_checked.md"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [3] 品質チェック・投稿
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "[3/4] 品質チェック・投稿..."

TITLE=$(head -n 1 reports/chart_1_checked.md)
check_duplicate "$TITLE" 7
CONTENT=$(tail -n +2 reports/chart_1_checked.md)

if [[ -z "$TITLE" ]] || [[ "$TITLE" == "#"* ]]; then
  echo "❌ 品質NG: タイトル異常（$TITLE）→ 停止"
  exit 1
fi

if [[ -z "$CONTENT" ]]; then
  echo "❌ 品質NG: 本文が空 → 停止"
  exit 1
fi

CONTENT_LENGTH=$(python3 -c "import sys; print(len(sys.argv[1]))" "$CONTENT")

if [ "$CONTENT_LENGTH" -lt 800 ]; then
  echo "❌ 品質NG: 本文${CONTENT_LENGTH}文字 → 停止"
  exit 1
fi

echo "✅ 品質OK（${CONTENT_LENGTH}文字）"

# アイキャッチ生成
THUMB_TITLE=$(echo "$TITLE" | cut -c1-30)
python3 ~/make_thumbnail.py "$THUMB_TITLE" 2>/dev/null

MEDIA_ID=0
if [[ -f thumbnail.jpg ]]; then
  MEDIA_RESPONSE=$(curl -s -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/media \
    -u "$WP_USER:$WP_PASS" \
    -H "Content-Disposition: attachment; filename=thumbnail.jpg" \
    -H "Content-Type: image/jpeg" \
    --data-binary @thumbnail.jpg)
  MEDIA_ID=$(echo "$MEDIA_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',0))" 2>/dev/null || echo 0)
  echo "  メディアID: $MEDIA_ID"
fi

DESC=$(echo "$CONTENT" | sed -e 's/<[^>]*>//g' | head -c 120)
echo "$TITLE"   > /tmp/chart_title.txt
echo "$CONTENT" > /tmp/chart_content.txt
echo "$DESC"    > /tmp/chart_desc.txt

JSON=$(python3 - << 'PY' "$MEDIA_ID"
import json, sys
media_id = int(sys.argv[1])
with open("/tmp/chart_title.txt")   as f: title   = f.read().strip()
with open("/tmp/chart_content.txt") as f: content = f.read().strip()
with open("/tmp/chart_desc.txt")    as f: desc    = f.read().strip()

data = {
    'title': title,
    'content': content,
    'status': 'publish',
    'categories': [71],  # チャート・ランキングカテゴリ
    'excerpt': desc
}
if media_id > 0:
    data['featured_media'] = media_id

print(json.dumps(data, ensure_ascii=False))
PY
)

RESPONSE=$(curl -s -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/posts \
  -u "$WP_USER:$WP_PASS" \
  -H "Content-Type: application/json" \
  -d "$JSON")

POST_URL=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('link','（URL取得失敗）'))" 2>/dev/null)
POST_ID=$(echo "$RESPONSE"  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [4] ペルシアン: SNS拡散戦略
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "[4/4] ペルシアン: SNS拡散戦略..."

claude --agent persian -p "
今日は${TODAY}です。
以下のK-POPチャートランキング記事が投稿されました。SNS拡散戦略を設計せよ。

【記事タイトル】$TITLE
【記事URL】$POST_URL
【概要】${WEEK}の最新K-POPチャートランキング記事

X投稿文3パターン・推奨ハッシュタグセット・最適投稿タイミング・採用推奨パターンを出力せよ。
" > reports/chart_2_sns.md

echo "=== X/Twitter 自動投稿 ==="
bash ~/google_metrics/post_to_x.sh "$TITLE" "$POST_URL" "reports/chart_2_sns.md" 2>/dev/null || echo "X投稿スキップ"

# アーカイブ
mkdir -p "$ARCHIVE_DIR"
cp reports/chart_* "$ARCHIVE_DIR/" 2>/dev/null
cat > "$ARCHIVE_DIR/summary.txt" << SUMMARY
実行ID      : chart_$RUN_ID
パイプライン: chart
日時        : $TODAY
記事ID      : $POST_ID
URL         : $POST_URL
タイトル    : $TITLE
文字数      : $CONTENT_LENGTH
判定        : 投稿OK
SUMMARY

bash ~/kpop_notify.sh success "チャート" "記事投稿完了: $TITLE" "$POST_URL" 2>/dev/null

echo ""
echo "========================================"
echo " ✅ チャートランキング記事投稿完了"
echo " 記事ID  : $POST_ID"
echo " URL     : $POST_URL"
echo " SNS戦略 : reports/chart_2_sns.md"
echo "========================================"
