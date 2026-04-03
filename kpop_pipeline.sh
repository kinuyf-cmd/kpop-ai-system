#!/bin/bash

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ユーティリティ: 出力検証関数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
check_output() {
  local file="$1"
  local step="$2"
  if [[ ! -s "$file" ]]; then
    echo "❌ [$step] 出力が空 → パイプライン停止"
    archive_and_exit 1
  fi
  if grep -qE '申し訳ありません|お手伝いできますか' "$file"; then
    echo "❌ [$step] エラー応答を検出 → パイプライン停止"
    echo "  先頭行: $(head -1 "$file")"
    archive_and_exit 1
  fi
  echo "  ✓ [$step] OK"
}

archive_and_exit() {
  local code="${1:-1}"
  if [[ -n "$ARCHIVE_DIR" ]]; then
    mkdir -p "$ARCHIVE_DIR"
    cp reports/* "$ARCHIVE_DIR/" 2>/dev/null
    cat > "$ARCHIVE_DIR/summary.txt" << SUMMARY
実行ID      : $RUN_ID
パイプライン: speed
日時        : $TODAY
判定        : 停止
SUMMARY
    echo "  アーカイブ保存: $ARCHIVE_DIR"
  fi
  bash ~/kpop_notify.sh error "速報" "パイプライン停止 (RUN: $RUN_ID)" 2>/dev/null
  exit "$code"
}

wp_health_check() {
  echo "=== WordPress 接続確認 ==="
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1" \
    -u "$WP_USER:$WP_PASS" \
    --connect-timeout 10 --max-time 15)
  if [[ "$HTTP_CODE" != "200" ]]; then
    echo "❌ WordPress API 接続失敗 (HTTP ${HTTP_CODE}) → パイプライン停止"
    bash ~/kpop_notify.sh error "速報" "WordPress API 接続失敗 (HTTP ${HTTP_CODE})" 2>/dev/null
    exit 1
  fi
  echo "  ✓ WordPress API 正常 (HTTP ${HTTP_CODE})"
}

check_duplicate() {
  local title="$1"
  local days="${2:-2}"
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
- 同じアーティスト＋同じイベント＋同じ時期 → 重複（YES）
- 同じアーティストでも別イベント・別テーマ → 重複なし（NO）
- チャートランキングは毎週異なるため常に重複なし（NO）
【出力ルール】YESまたはNOの1単語のみ。他は出力禁止。
")

  if [[ "$SIMILARITY" == "YES" ]]; then
    echo "  ⚠️  重複あり: 類似記事が過去${days}日以内に投稿済み → スキップ"
    echo "    新タイトル: $title"
    archive_and_exit 0
  fi

  echo "  ✓ 重複なし"
}

mkdir -p reports

TODAY=$(date '+%Y年%m月%d日')
RUN_ID=$(date '+%Y%m%d_%H%M%S')
ARCHIVE_DIR=~/kpop_archives/$RUN_ID

echo "========================================"
echo " K-POP速報パイプライン 開始: $TODAY"
echo " 実行ID: $RUN_ID"
echo "========================================"

wp_health_check

echo "=== [1] デオキシス: 速報取得・記事化 ==="
claude --allowedTools WebSearch --agent deoxys_kpop -p "
今日は${TODAY}です。今すぐK-POP速報を取得して記事化せよ。

【最重要ルール：日付と時制】
- 今日は${TODAY}。これを基準に判断する
- 未来の日付 → 未来形（予定・見込み・開催予定）
- 過去・当日 → 過去形（開催された・発表された）
- 絶対に未来の出来事を過去形で書くな
- 日付は必ず本文に明記する

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（##・説明文禁止）
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ
末尾に情報元と「※本記事は${TODAY}時点の情報です」を明記
" > reports/0_breaking.md
check_output reports/0_breaking.md "デオキシス"

echo "=== [2] メタモン: CTRリライト ==="
claude --agent metamon_kpop -p "
あなたはK-POPニュース専門ライター兼CTR改善担当です。

以下の記事を、SEOとCTRの両方が強い完成記事にしてください。

【絶対ルール】
・修正内容や理由は一切書かない
・『修正箇所』『修正サマリー』『理由』『チェック項目』などの文言を一切出力しない
・説明文・前置き・後書き・表・箇条書き禁止
・質問禁止
・完成記事本文だけを書くこと

【最重要ルール：日付と時制】
- 今日は${TODAY}。未来は未来形・過去は過去形
- 日付は必ず本文に明記すること

【CTR強化ルール】
・タイトルは内部で3案作り、最もクリックされやすい1案だけ出力する
・タイトルには必ず「アーティスト名」「数字 or 日付」「具体イベント名」のうち2つ以上を含める
・タイトルは24〜38文字を目安にする
・弱い一般表現は禁止
・冒頭3行は必ず「結論 → 注目理由 → 読む価値」で構成する

【精度ルール】
- 実在しない情報を増やさない
- 不確実な内容は断定しない
- 記事末尾に情報元を明記する
- 記事末尾に「※本記事は${TODAY}時点の情報です」を入れる

【出力形式】
1行目：タイトルのみ
2行目以降：HTML本文のみ

【重要】
最終完成記事だけを出力せよ

---
$(cat reports/0_breaking.md)
" > reports/1_rewrite.md
check_output reports/1_rewrite.md "メタモン"

echo "=== [2.5] イーブイ: タイトルA/B選定 ==="
claude --agent eevee -p "
以下の記事のタイトルを複数パターンで比較・評価し、最もCTRが高いタイトルを選定せよ。

【絶対ルール】
- 📄最終出力セクションのみ出力（比較表は内部で検討するだけ）
- 1行目：採用タイトルのみ
- 2行目：空行
- 3行目以降：記事本文そのまま（変更なし）

---
$(cat reports/1_rewrite.md)
" > reports/1_eevee.md
check_output reports/1_eevee.md "イーブイ"
cp reports/1_eevee.md reports/1_rewrite.md

echo "=== [3] ジラーチ: ファクトチェック ==="
claude --agent jirachi_kpop -p "
今日は${TODAY}です。
以下の記事をファクトチェックして修正せよ。

【絶対ルール：出力制限】
- 修正箇所・修正理由・修正内容を一切書かない
- 表・箇条書き・サマリーで修正内容を説明しない
- 説明文・前置き・後書き禁止
- 最終完成記事のみを出力せよ

【チェック項目】
- 日付と時制の整合性（${TODAY}基準・最重要）
- 実在しない情報がないか
- 未来の出来事が過去形になっていないか
- 不自然な誇張（世界初・史上初など）
- 情報元表記があるか

【ルール】
- 修正が必要な箇所のみ修正
- 構造は変えない
- 必ず完成記事を出力
- 断定しすぎる表現を避ける

【出力形式・絶対厳守】
1行目：修正後タイトルのみ（##・説明文禁止）
2行目：空行
3行目以降：修正済みHTML本文のみ

---
$(cat reports/1_rewrite.md)
" > reports/2_checked.md
check_output reports/2_checked.md "ジラーチ"

echo "=== [4] アルセウス: 品質監督・最終承認 ==="
claude --agent arceus -p "
今日は${TODAY}です。
以下の速報記事を監督・審査し、投稿可否を判定せよ。

【速報記事（ジラーチ出力）】
$(cat reports/2_checked.md)

【速報パイプライン担当エージェント】
- デオキシス（速報取得）: 事実・数字・日付の充実度
- メタモン（CTRリライト）: タイトル強度・フックの質
- ジラーチ（ファクトチェック）: 時制・事実整合・出力形式

【最終記事の合格基準】
- 1行目がタイトル文字列のみ（##なし）
- 本文800文字以上
- 時制が${TODAY}と整合している
- 情報元の記載がある

エージェント別採点表・最終記事品質評価・投稿承認/却下を出力せよ。
" > reports/3_arceus.md
check_output reports/3_arceus.md "アルセウス"

if grep -q '❌ 投稿却下' reports/3_arceus.md; then
  echo "❌ アルセウスが投稿を却下しました"
  grep '投稿却下' reports/3_arceus.md
  archive_and_exit 1
fi

echo "=== 投稿 ==="

TITLE=$(head -n 1 reports/2_checked.md)
check_duplicate "$TITLE" 2
TITLE=$(echo "$TITLE" | sed 's/^/【速報】/')
CONTENT=$(tail -n +2 reports/2_checked.md)

echo "=== 品質チェック ==="

# -----------------------------------------------
# [A] タイトル基本チェック
# -----------------------------------------------
if [[ -z "$TITLE" ]]; then
  echo "❌ 品質NG: タイトルが空 → 投稿停止"
  archive_and_exit 1
fi

# タイトルNGワード（AI定型文・マークダウン記法）
TITLE_NG_RESULT=$(python3 - << 'PY' "$TITLE"
import sys
t = sys.argv[1]
ng_words = [
    "お手伝いできますか", "申し訳ありません", "承知しました", "以下に",
    "まとめました", "解説します", "ご質問", "サポート",
    "AIとして", "言語モデル", "できません", "お答えできません",
    "修正箇所", "修正サマリー", "##",
]
hit = [w for w in ng_words if w in t]
# マークダウンコードブロック検出
if t.startswith("#") or "```" in t:
    hit.append("markdown記法")
print("|".join(hit) if hit else "OK")
PY
)
if [[ "$TITLE_NG_RESULT" != "OK" ]]; then
  echo "❌ 品質NG: タイトルにNGワード（$TITLE_NG_RESULT）→ 投稿停止"
  archive_and_exit 1
fi

# タイトル文字数（24〜45文字）
TITLE_LEN=${#TITLE}
if [ "$TITLE_LEN" -lt 20 ]; then
  echo "❌ 品質NG: タイトルが短すぎる（${TITLE_LEN}文字）→ 投稿停止"
  archive_and_exit 1
fi
if [ "$TITLE_LEN" -gt 60 ]; then
  echo "⚠️  警告: タイトルが長すぎる（${TITLE_LEN}文字）→ 続行"
fi
echo "  ✓ タイトル文字数OK（${TITLE_LEN}文字）"

# -----------------------------------------------
# [B] 本文基本チェック
# -----------------------------------------------
if [[ -z "$CONTENT" ]]; then
  echo "❌ 品質NG: 本文が空 → 投稿停止"
  archive_and_exit 1
fi

# 本文NGワード（AI定型文・エラー応答）
CONTENT_NG_RESULT=$(python3 - << 'PY' "$CONTENT"
import sys
c = sys.argv[1]
ng_words = [
    "申し訳ありません", "お手伝いできますか", "承知しました",
    "以下に示します", "AIとして", "言語モデル", "お答えできません",
    "修正箇所：", "修正サマリー", "チェック項目：", "【修正内容】", "申し訳",
]
hit = [w for w in ng_words if w in c]
# コードブロック混入チェック
if "```" in c:
    hit.append("codeblock混入")
print("|".join(hit) if hit else "OK")
PY
)
if [[ "$CONTENT_NG_RESULT" != "OK" ]]; then
  echo "❌ 品質NG: 本文にNGワード（$CONTENT_NG_RESULT）→ 投稿停止"
  archive_and_exit 1
fi

# -----------------------------------------------
# [C] 実文字数チェック（HTMLタグ除外）
# -----------------------------------------------
CONTENT_STATS=$(python3 - << 'PY' "$CONTENT"
import sys, re
content = sys.argv[1]
plain = re.sub(r'<[^>]+>', '', content).strip()
plain = re.sub(r'\s+', ' ', plain)
char_count = len(plain)
h2_count = len(re.findall(r'<h2', content, re.IGNORECASE))
h3_count = len(re.findall(r'<h3', content, re.IGNORECASE))
p_count  = len(re.findall(r'<p',  content, re.IGNORECASE))
has_source = any(w in content for w in ['情報元', '出典', '参照', '引用', '参考'])
print(f"{char_count}|{h2_count}|{h3_count}|{p_count}|{'YES' if has_source else 'NO'}")
PY
)

PLAIN_CHARS=$(echo "$CONTENT_STATS" | cut -d'|' -f1)
H2_COUNT=$(echo "$CONTENT_STATS"    | cut -d'|' -f2)
H3_COUNT=$(echo "$CONTENT_STATS"    | cut -d'|' -f3)
P_COUNT=$(echo "$CONTENT_STATS"     | cut -d'|' -f4)
HAS_SOURCE=$(echo "$CONTENT_STATS"  | cut -d'|' -f5)

echo "  純テキスト: ${PLAIN_CHARS}文字 / h2:${H2_COUNT} / h3:${H3_COUNT} / p:${P_COUNT} / 情報元:${HAS_SOURCE}"

if [ "$PLAIN_CHARS" -lt 800 ]; then
  echo "❌ 品質NG: 純テキストが短すぎる（${PLAIN_CHARS}文字）→ 投稿停止"
  archive_and_exit 1
fi

if [ "$H2_COUNT" -lt 2 ]; then
  echo "❌ 品質NG: h2見出しが少なすぎる（${H2_COUNT}個）→ 投稿停止"
  archive_and_exit 1
fi

if [[ "$HAS_SOURCE" == "NO" ]]; then
  echo "⚠️  警告: 情報元の記載なし → 続行（要改善）"
fi

CONTENT_LENGTH="$PLAIN_CHARS"
echo "✅ 品質OK（純テキスト${PLAIN_CHARS}文字 / h2:${H2_COUNT} / p:${P_COUNT}）"
STATUS="publish"

echo "=== CTRタイトル採点 ==="
TITLE_SCORE_JSON=$(python3 ~/google_metrics/score_title_ctr.py "$TITLE")
echo "$TITLE_SCORE_JSON"

TITLE_PASS=$(python3 - << 'PY2' "$TITLE_SCORE_JSON"
import json, sys
data = json.loads(sys.argv[1])
print("YES" if data.get("pass") else "NO")
PY2
)

TITLE_SCORE=$(python3 - << 'PY3' "$TITLE_SCORE_JSON"
import json, sys
data = json.loads(sys.argv[1])
print(data.get("score", 0))
PY3
)

echo "TITLE_SCORE=$TITLE_SCORE"

if [ "$TITLE_PASS" != "YES" ]; then
  echo "❌ CTR NG: タイトルが弱い → 投稿停止"
  exit 1
fi

echo "=== サムネ文言生成 ==="
THUMB_TITLE=$(claude -p "
あなたはK-POPニュースのサムネイルCTR改善担当です。

以下のタイトルに対して、サムネイル用の短い訴求文言を1つだけ作ってください。

【ルール】
・4〜14文字
・短く強く
・クリックしたくなる言葉にする
・本文タイトルのコピペは禁止
・『修正箇所』『特定』『まとめ』のような弱い語は禁止
・説明禁止
・1行だけ出力

タイトル：
$TITLE
" | tail -n 1)

echo "THUMB_TITLE=$THUMB_TITLE"

echo "=== サムネ文言採点 ==="
THUMB_SCORE_JSON=$(python3 ~/google_metrics/score_thumbnail_text.py "$THUMB_TITLE")
echo "$THUMB_SCORE_JSON"

THUMB_PASS=$(python3 - << 'PY2' "$THUMB_SCORE_JSON"
import json, sys
data = json.loads(sys.argv[1])
print("YES" if data.get("pass") else "NO")
PY2
)

THUMB_SCORE=$(python3 - << 'PY3' "$THUMB_SCORE_JSON"
import json, sys
data = json.loads(sys.argv[1])
print(data.get("score", 0))
PY3
)

echo "THUMB_SCORE=$THUMB_SCORE"

if [ "$THUMB_PASS" != "YES" ]; then
  echo "❌ サムネ文言NG → デフォルト文言に切替"
  THUMB_TITLE="緊急発表"
fi

echo "=== アイキャッチ生成 ==="
python3 ~/make_thumbnail.py "$THUMB_TITLE"

echo "=== アイキャッチアップロード ==="
MEDIA_RESPONSE=$(curl -s -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/media \
-u "$WP_USER:$WP_PASS" \
-H "Content-Disposition: attachment; filename=thumbnail.jpg" \
-H "Content-Type: image/jpeg" \
--data-binary @thumbnail.jpg)

MEDIA_ID=$(echo "$MEDIA_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "メディアID: $MEDIA_ID"

# === カテゴリ自動判定（15分類） ===
CATEGORY_ID=$(python3 - << 'PY' "$TITLE"
import sys
title = sys.argv[1].lower()

rules = [
    (71, ['チャート','ランキング','1位','top10','top 10','top50','top 50','billboard','gaon','circle chart','spotify']),
    (3,  ['カムバック','カムバ','復帰','ソロ復帰','新アルバム','ミニアルバム','ep','カムバック決定']),
    (6,  ['新曲','新曲リリース','mv公開','ミュージックビデオ','先行公開','配信開始','音源公開']),
    (5,  ['ライブ','コンサート','ツアー','来日','ファンミ','ファンミーティング','イベント','ポップアップ','チケット']),
    (7,  ['出演','出演決定','出演情報','テレビ','番組','放送','ラジオ','ゲスト出演']),
    (28, ['音楽番組','人気歌謡','music bank','m countdown','show champion','music core']),
    (8,  ['ドラマ','主演','出演ドラマ','配信ドラマ','俳優','女優']),
    (27, ['映画','映画出演','映画化','スクリーンデビュー']),
    (10, ['コラボ','共同','feat','featuring','ユニット','ブランドコラボ']),
    (15, ['広告','アンバサダー','モデル起用','cm','キャンペーン','ブランドモデル']),
    (13, ['新商品','発売','限定発売','新作','グッズ','公式グッズ']),
    (12, ['美容','コスメ','スキンケア','ヘアケア','ダイエット','インナーケア','サロン','クリニック','ガラス肌','グラスキン','ルーティン','保湿','洗顔','美白','韓国スキンケア','韓国コスメ']),
    (11, ['旅行','ソウル','釜山','ホテル','観光','カフェ','レストラン','渡韓','タクシー']),
    (14, ['熱愛','炎上','騒動','脱退','訴訟','事件','問題','謝罪','ゴシップ']),
    (9,  ['話題','注目','反応','バズ','拡散','snsで話題','海外の反応']),
    (4,  ['考察','分析','なぜ','理由','比較','解説','深掘り','特集','まとめ','徹底解説']),
]

for cid, keywords in rules:
    if any(word in title for word in keywords):
        print(cid)
        sys.exit()

print(2)
PY
)

echo "CATEGORY_ID=$CATEGORY_ID"

# === アーティスト別カテゴリ自動判定 ===
ARTIST_CATEGORY_IDS=$(python3 - << 'PY' "$TITLE"
import sys
title = sys.argv[1].lower()

artist_rules = [
    (19, ['bigbang', 'g-dragon', 'gd', 'taeyang', 'daesung', 'top', 't.o.p']),
    (23, ['blackpink', 'black pink', 'jennie', 'jisoo', 'rose', 'rosé', 'lisa']),
    (18, ['bts', '방탄', 'rm', 'jin', 'suga', 'j-hope', 'jhope', 'jimin', 'v', 'jungkook']),
    (25, ['aespa', 'karina', 'winter', 'ningning', 'giselle']),
    (38, ['babymonster', 'baby monster', 'ahyeon', 'asa', 'ruka', 'pharita', 'rami', 'rora', 'chiquita']),
    (44, ['illit', 'iroha', 'wonhee', 'minju', 'moka', 'yunah']),
    (68, ['ive', 'wonyoung', 'yujin', 'rei', 'gaeul', 'liz', 'leeseo']),
    (41, ['le sserafim', 'lesserafim', 'sakura', 'chaewon', 'yunjin', 'kazuha', 'eunchae']),
    (75, ['monsta x', 'shownu', 'minhyuk', 'kihyun', 'hyungwon', 'jooheon', 'i.m', 'im']),
    (40, ['nct', 'nct wish', 'mark', 'haechan', 'taeyong', 'jaehyun', 'doyoung']),
    (32, ['newjeans', 'new jeans', 'minji', 'hani', 'danielle', 'haerin', 'hyein']),
    (39, ['riize', 'shotaro', 'sungchan', 'wonbin', 'sohee', 'anton', 'eunseok']),
    (24, ['seventeen', 'svt', 'scoups', 's.coups', 'jeonghan', 'joshua', 'jun', 'hoshi', 'wonwoo', 'woozi', 'mingyu', 'dk', 'seungkwan', 'vernon', 'dino']),
    (43, ['stray kids', 'skz', 'bang chan', 'lee know', 'changbin', 'hyunjin', 'han', 'felix', 'seungmin', 'i.n', 'in']),
    (22, ['twice', 'nayeon', 'jeongyeon', 'momo', 'sana', 'jihyo', 'mina', 'dahyun', 'chaeyoung', 'tzuyu']),
    (42, ['zerobaseone', 'zb1', 'sung hanbin', 'han yujin', 'zhang hao', 'ricky']),
    (60, ['exo', 'baekhyun', 'kai', 'suho', 'chanyeol', 'd.o.', 'kyungsoo', 'xiumin', 'chen']),
    (37, ['itzy', 'yeji', 'lia', 'ryujin', 'chaeryeong', 'yuna']),
    (45, ['boa']),
    (33, ['xg', 'jurin', 'chisa', 'hinata', 'harvey', 'juria', 'maya', 'cocona']),
]

matched = []
for cid, keywords in artist_rules:
    if any(word in title for word in keywords):
        matched.append(str(cid))

print(",".join(matched))
PY
)

echo "ARTIST_CATEGORY_IDS=$ARTIST_CATEGORY_IDS"

# === タグ名候補を自動生成 ===
TAG_NAMES=$(python3 - << 'PY' "$TITLE"
import sys

title = sys.argv[1]

rules = [
    ('BTS', ['bts', 'rm', 'jin', 'suga', 'j-hope', 'jhope', 'jimin', 'v', 'jungkook']),
    ('BIGBANG', ['bigbang', 'g-dragon', 'gd', 'taeyang', 'daesung', 'top', 't.o.p']),
    ('BLACKPINK', ['blackpink', 'black pink', 'jennie', 'jisoo', 'rose', 'rosé', 'lisa']),
    ('aespa', ['aespa', 'karina', 'winter', 'ningning', 'giselle']),
    ('BABYMONSTER', ['babymonster', 'baby monster']),
    ('ILLIT', ['illit']),
    ('IVE', ['ive', 'wonyoung', 'yujin']),
    ('LE SSERAFIM', ['le sserafim', 'lesserafim']),
    ('SEVENTEEN', ['seventeen', 'svt']),
    ('TWICE', ['twice']),
    ('Stray Kids', ['stray kids', 'skz']),
    ('NewJeans', ['newjeans', 'new jeans']),
    ('XG', ['xg']),
    ('Coachella', ['coachella']),
    ('カムバック', ['カムバック', 'カムバ', '復帰']),
    ('ワールドツアー', ['ワールドツアー', 'ツアー', 'ライブ', 'コンサート']),
    ('K-POP速報', ['速報', '最新情報', 'breaking']),
]

title_l = title.lower()
matched = []

for tag_name, keywords in rules:
    if any(word in title_l for word in keywords):
        matched.append(tag_name)

matched = list(dict.fromkeys(matched))
print('|'.join(matched))
PY
)

echo "TAG_NAMES=$TAG_NAMES"

# === タグを検索 / なければ作成してIDを取得 ===
TAG_IDS=$(python3 - << 'PY' "$TAG_NAMES"
import sys, json, urllib.request, urllib.parse, base64

raw = sys.argv[1].strip()
if not raw:
    print("")
    sys.exit()

tag_names = [t for t in raw.split("|") if t.strip()]
auth = base64.b64encode(os.environ.get("WP_USER","kpop-bot").encode() + b":" + os.environ.get("WP_PASS","").encode()).decode()
headers = {"Authorization": "Basic " + auth, "Content-Type": "application/json"}
base_url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/tags"
tag_ids = []

for name in tag_names:
    search_url = base_url + "?search=" + urllib.parse.quote(name) + "&per_page=5"
    req = urllib.request.Request(search_url, headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read())
        match = next((t for t in data if t["name"] == name), None)
        if match:
            tag_ids.append(str(match["id"]))
            continue
    except:
        pass
    req = urllib.request.Request(base_url,
        data=json.dumps({"name": name}).encode(),
        headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            tag = json.loads(res.read())
            tag_ids.append(str(tag["id"]))
    except:
        pass

print(",".join(tag_ids))
PY
)

echo "TAG_IDS=$TAG_IDS"

SLUG=$(claude -p "
以下の日本語タイトルをSEOに強い英語スラッグに変換せよ。

ルール：
- 小文字英数字とハイフンのみ
- 30〜50文字
- アーティスト名・イベント種別・年を含める
- 前置き・説明・記号禁止
- 1行のみ出力

タイトル：$TITLE
" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g' | sed 's/-\+/-/g' | sed 's/^-\|-$//' | cut -c1-60)

# フォールバック: 空またはNG文字列の場合は日付ベースのスラッグ
if [[ -z "$SLUG" ]] || [[ ${#SLUG} -lt 5 ]]; then
  SLUG="kpop-news-$(date '+%Y%m%d-%H%M')"
fi

DESC=$(echo "$CONTENT" | sed -e 's/<[^>]*>//g' | python3 -c "import sys; t=sys.stdin.read().strip(); print(t[:120])")

echo "$TITLE"   > /tmp/kpop_title.txt
echo "$CONTENT" > /tmp/kpop_content.txt
echo "$DESC"    > /tmp/kpop_desc.txt

JSON=$(python3 - << 'PY' "$SLUG" "$CATEGORY_ID" "$MEDIA_ID" "$ARTIST_CATEGORY_IDS" "$TAG_IDS" "$STATUS"
import json, sys

slug           = sys.argv[1]
main_category  = int(sys.argv[2])
media_id       = int(sys.argv[3])
artist_ids_raw = sys.argv[4].strip()
tag_ids_raw    = sys.argv[5].strip()
status         = sys.argv[6].strip()

with open("/tmp/kpop_title.txt",   encoding='utf-8', errors='replace') as f: title   = f.read().strip()
with open("/tmp/kpop_content.txt", encoding='utf-8', errors='replace') as f: content = f.read().strip()
with open("/tmp/kpop_desc.txt",    encoding='utf-8', errors='replace') as f: desc    = f.read().strip()

categories = [main_category]
if artist_ids_raw:
    for x in artist_ids_raw.split(","):
        x = x.strip()
        if x:
            categories.append(int(x))
categories = list(dict.fromkeys(categories))

tags = []
if tag_ids_raw:
    for x in tag_ids_raw.split(","):
        x = x.strip()
        if x:
            tags.append(int(x))
tags = list(dict.fromkeys(tags))

print(json.dumps({
    'title': title,
    'content': content,
    'status': status,
    'slug': slug,
    'excerpt': desc,
    'categories': categories,
    'tags': tags,
    'featured_media': media_id
}, ensure_ascii=False))
PY
)

RESPONSE=$(curl -s -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/posts \
-u "$WP_USER:$WP_PASS" \
-H "Content-Type: application/json" \
-d "$JSON")

POST_URL=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('link','（URL取得失敗）'))" 2>/dev/null)
POST_ID=$(echo "$RESPONSE"  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id',''))"  2>/dev/null)

echo "=== [4.5] 収益導線自動挿入 ==="
bash ~/google_metrics/inject_revenue_links.sh "$POST_ID" 2>/dev/null || echo "収益導線スキップ"

echo "=== [4.6] 内部リンク自動挿入 ==="
bash ~/google_metrics/add_internal_links.sh "/$SLUG/" 2>/dev/null || echo "内部リンクスキップ"

echo "=== [4.7] Google Indexing API ==="
bash ~/google_metrics/request_index.sh "$POST_URL" 2>/dev/null || echo "Google インデックススキップ"

echo "=== [4.8] Bing URL Submission ==="
bash ~/google_metrics/request_bing_index.sh "$POST_URL" 2>/dev/null || echo "Bing インデックススキップ"

echo "=== [5] ペルシアン: SNS拡散戦略 ==="
claude --agent persian -p "
今日は${TODAY}です。
以下のK-POP速報記事が投稿されました。SNS拡散戦略を設計せよ。

【記事タイトル】$TITLE
【記事URL】$POST_URL
【記事冒頭】
$(echo "$CONTENT" | sed 's/<[^>]*>//g' | head -c 300)

X投稿文3パターン・推奨ハッシュタグセット・最適投稿タイミング・採用推奨パターンを出力せよ。
" > reports/4_sns.md

echo "=== [5.1] X/Twitter 自動投稿 ==="
bash ~/google_metrics/post_to_x.sh "$TITLE" "$POST_URL" "reports/4_sns.md" 2>/dev/null || echo "X投稿スキップ"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# レジギガス: 実行履歴アーカイブ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
mkdir -p "$ARCHIVE_DIR"
cp reports/* "$ARCHIVE_DIR/" 2>/dev/null
cat > "$ARCHIVE_DIR/summary.txt" << SUMMARY
実行ID      : $RUN_ID
パイプライン: speed
日時        : $TODAY
記事ID      : $POST_ID
URL         : $POST_URL
タイトル    : $TITLE
文字数      : $CONTENT_LENGTH
判定        : 投稿OK
SUMMARY

bash ~/kpop_notify.sh success "速報" "記事投稿完了: $TITLE" "$POST_URL" 2>/dev/null

echo ""
echo "========================================"
echo " ✅ 完了"
echo " 記事ID  : $POST_ID"
echo " URL     : $POST_URL"
echo " SNS戦略 : reports/4_sns.md"
echo " アーカイブ: $ARCHIVE_DIR"
echo "========================================"
