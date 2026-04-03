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
  echo "  ✓ [$step] OK ($(wc -c < "$file" | tr -d ' ') bytes)"
}

archive_and_exit() {
  local code="${1:-1}"
  if [[ -n "$ARCHIVE_DIR" ]]; then
    mkdir -p "$ARCHIVE_DIR"
    cp reports/* "$ARCHIVE_DIR/" 2>/dev/null
    cat > "$ARCHIVE_DIR/summary.txt" << SUMMARY
実行ID      : $RUN_ID
パイプライン: strategy
日時        : $TODAY
判定        : 停止
SUMMARY
    echo "  アーカイブ保存: $ARCHIVE_DIR"
  fi
  bash ~/kpop_notify.sh error "戦略" "パイプライン停止 (RUN: $RUN_ID)" 2>/dev/null
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
    bash ~/kpop_notify.sh error "戦略" "WordPress API 接続失敗 (HTTP ${HTTP_CODE})" 2>/dev/null
    exit 1
  fi
  echo "  ✓ WordPress API 正常 (HTTP ${HTTP_CODE})"
}

check_duplicate() {
  local title="$1"
  local days="${2:-5}"
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
echo " K-POP戦略パイプライン 開始: $TODAY"
echo " 実行ID: $RUN_ID | 全15エージェント"
echo "========================================"

wp_health_check

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 1: インテリジェンス収集
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ PHASE 1: インテリジェンス収集 ━━━"

echo "[1/15] バタフリー: 最新トレンド収集..."
claude --allowedTools WebSearch --agent butterfree -p "
今日は${TODAY}です。
K-POPの最新トレンドをWebSearchで収集し、記事化優先度スコア付きのインテリジェンスレポートを出力せよ。

検索手順：
1.「K-POP 最新ニュース ${TODAY}」
2.「BTS BLACKPINK NewJeans aespa TWICE 新曲 コンサート 受賞 ${TODAY}」
3.「K-POP Billboard Melon Oricon チャート 今週」
4.「K-POP Twitter トレンド 話題 炎上」
5. 急上昇が見られたアーティストを追加検索

速報TOP5・チャート動向・SNS反応・イベントカレンダー・記事化推奨テーマ（優先度スコア付き）を必ず出力せよ。
" > reports/1_trend.md
check_output reports/1_trend.md "バタフリー"

echo "[2/15] ラプラス: SEOキーワード戦略..."
claude --agent lapras -p "
今日は${TODAY}です。
以下のK-POPトレンドレポートを分析し、記事が検索上位を狙えるキーワード戦略を立案せよ。

【トレンドレポート】
$(cat reports/1_trend.md)

優先度Aの案件を中心に：
- メインキーワード（1つ）：意図分類・難易度・採用理由付き
- サブキーワード（10個）：KW/意図/推奨配置場所
- ロングテール候補（5個）
- ブルーオーシャン発見（2〜3個）
- タイトル構造テンプレート（3パターン）
- 避けるべきキーワード
を必ず出力せよ。
" > reports/2_seo.md
check_output reports/2_seo.md "ラプラス"

echo "[3/15] ミミッキュ: 競合分析・差別化設計..."
claude --allowedTools WebSearch --agent mimikyu -p "
今日は${TODAY}です。
以下のSEOキーワード戦略のメインキーワードでWebSearchし、競合記事を実際に調査・分析して差別化戦略を設計せよ。

【SEOキーワード戦略】
$(cat reports/2_seo.md)

WebSearchで上位3〜5記事を確認した上で：
- 競合調査サマリー（使ったKW・上位記事の概要）
- 競合の強み（必ず書くべき内容）
- 競合の弱点・穴
- 差別化ポイント（3つ、期待効果付き）
- 推奨記事構成案（H2 4〜6個）
- 勝算評価
を出力せよ。
" > reports/3_competitor.md
check_output reports/3_competitor.md "ミミッキュ"

# ▶ ソーナンス（4）とジラーチ（5）を並列実行
echo "[4+5/15] ソーナンス・ジラーチ: 並列実行..."

claude --agent wobbuffet -p "
今日は${TODAY}です。
以下のトレンド・競合分析を元に、K-POPファンの読者ニーズと記事の最適な切り口を分析せよ。

【トレンドレポート】
$(cat reports/1_trend.md)

【競合分析レポート】
$(cat reports/3_competitor.md)

- 最も強いニーズ層（速報/深掘り/感情共有/実用）と理由
- 読者が最も知りたいこと TOP3
- 記事切り口の比較表（3案、推奨度付き）
- デオキシスへの推奨メモ（冒頭の書き方・感情ワード・避けるべき表現・シェアされやすい要素）
を出力せよ。
" > reports/4_reader.md &
PID_SONANSU=$!

claude --agent jirachi_kpop -p "
今日は${TODAY}です。
以下のレポートを元に、今後72時間でバズる可能性が高いテーマを予測し、リスク評価を行え。

【トレンドレポート】
$(cat reports/1_trend.md)

【競合分析レポート】
$(cat reports/3_competitor.md)

以下を出力せよ：
1. 今後72時間でバズる可能性TOP3（根拠付き）
2. 時事的リスク（炎上・不確定情報・時制ミスが起きやすい要素）
3. 確認が必要な不確定情報のリスト
" > reports/5_future.md &
PID_JIRACHI=$!

wait $PID_SONANSU $PID_JIRACHI
check_output reports/4_reader.md "ソーナンス"
check_output reports/5_future.md "ジラーチ"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 2: 戦略設計
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ PHASE 2: 戦略設計 ━━━"

echo "[6/15] フシギバナ: SEO記事構成設計..."
claude --agent venusaur -p "
今日は${TODAY}です。
以下のSEOキーワード戦略・競合分析・読者ニーズ分析を統合し、記事の設計図を作成せよ。

【SEOキーワード戦略】
$(cat reports/2_seo.md)

【競合分析・差別化設計】
$(cat reports/3_competitor.md)

【読者ニーズ分析】
$(cat reports/4_reader.md)

- 記事タイプの決定
- メインキーワード配置（タイトル案・冒頭1文・末尾KW）
- H2見出し構成表（4〜6個、各H2に含めるKW・書く内容）
- 差別化ポイントの組み込み位置
- 推奨文字数配分
- デオキシスへの引き継ぎメモ
を必ず出力せよ。
" > reports/6_structure.md
check_output reports/6_structure.md "フシギバナ"

echo "[7/15] ミュウツー: 戦略統合・編集長判断..."
claude --agent mewtwo -p "
今日は${TODAY}です。
以下の全レポートを統合し、今日書くべきK-POP記事TOP3を意思決定せよ。

【バタフリー：トレンド】
$(cat reports/1_trend.md)

【ラプラス：SEOキーワード】
$(cat reports/2_seo.md)

【ミミッキュ：競合分析】
$(cat reports/3_competitor.md)

【ソーナンス：読者ニーズ】
$(cat reports/4_reader.md)

【ジラーチ：リスク予測】
$(cat reports/5_future.md)

【フシギバナ：記事構成設計】
$(cat reports/6_structure.md)

矛盾・重複を整理し、時事性・検索ポテンシャル・差別化可能性・ファン感情・継続価値の5軸で評価して
TOP3を優先度・タイトル3案・推奨構成付きで出力せよ。
異常検知・注意事項と、デオキシスへの具体的な実行指示も出力せよ。
" > reports/7_strategy.md
check_output reports/7_strategy.md "ミュウツー"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 3: 記事生成・品質改善
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ PHASE 3: 記事生成・品質改善 ━━━"

echo "[8/15] デオキシス: 高品質記事生成..."
claude --allowedTools WebSearch --agent deoxys_kpop -p "
今日は${TODAY}です。
以下の戦略レポートの第1位テーマで高品質K-POP記事を生成せよ。

【戦略レポート（ミュウツー）】
$(cat reports/7_strategy.md)

【記事構成設計（フシギバナ）】
$(cat reports/6_structure.md)

【読者ニーズ（ソーナンス）】
$(cat reports/4_reader.md)

【生成指示】
- 必ずWebSearchで事実・数字・日付を確認してから書く
- フシギバナの設計図（H2構成・KW配置）に従う
- ソーナンスの推奨メモ（冒頭の書き方・感情ワード）を反映する
- 2000〜3000文字（HTMLタグ除く）
- 各H2に数字・固有名詞・日付を最低1つ含める
- 末尾に情報元と「※本記事は${TODAY}時点の情報です」を明記

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（##・マークダウン・説明文禁止）
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ
" > reports/8_article.md
check_output reports/8_article.md "デオキシス"

echo "[9/15] メタモン: CTRリライト..."
claude --agent metamon_kpop -p "
今日は${TODAY}です。
以下の記事をCTRとSEOの両方を最大化する形にリライトせよ。

【元記事】
$(cat reports/8_article.md)

【SEOキーワード（活用せよ）】
$(cat reports/2_seo.md | head -40)

【リライト指示】
- タイトルは内部で3案考え、最もCTRが高い1案を採用して1行目に出力
- タイトルに：数字or記録 + アーティスト名 + 具体イベント名 を含める
- 冒頭3行を最大限のフックに強化
- H2見出しをより感情・数字訴求に改善（内容・構造は変えない）
- 事実・HTMLタグは変えない

【出力形式・絶対厳守】
1行目：採用タイトルのみ（マークダウン禁止）
2行目：空行
3行目以降：HTML本文のみ
" > reports/9_rewrite.md
check_output reports/9_rewrite.md "メタモン"

echo "[10/15] イーブイ: タイトルA/B最終選定..."
claude --agent eevee -p "
今日は${TODAY}です。
以下の記事のタイトルをA/B評価し、最も効果的な1案を選定して最終タイトルを確定せよ。

【記事（メタモン出力）】
$(cat reports/9_rewrite.md)

【SEOメインキーワード】
$(cat reports/2_seo.md | grep -A3 'メインキーワード' | head -5)

5案（速報型/感情型/SEO型/数字型/疑問型）を生成し、CTR/SEO/感情の3軸で評価表を作成。
採用タイトルを決定したら、1行目にタイトルのみ・2行目以降に記事本文をそのまま出力せよ。
" > reports/10_title.md
check_output reports/10_title.md "イーブイ"

echo "[11/15] アラカザム: ファクトチェック..."
claude --agent alakazam_kpop -p "
今日は${TODAY}です。
以下の記事の日付・時制・事実・誇張表現を確認し、必要箇所のみ修正せよ。

【記事】
$(cat reports/10_title.md)

【チェック優先順位】
1. 未来の出来事が過去形になっていないか（${TODAY}基準で判断）
2. 根拠のない「世界初・史上初・歴代最高」がないか
3. 実在しないアルバム名・受賞歴がないか
4. 情報元の明記があるか

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（##・「ファクトチェック結果」等の説明文禁止）
2行目：空行
3行目以降：修正済みHTML本文のみ（<h2>から始める）
" > reports/11_checked.md
check_output reports/11_checked.md "アラカザム"

echo "[12/15] ゲンガー: SEO・品質最終監査..."
claude --agent gengar -p "
今日は${TODAY}です。
以下の記事に対してSEO・コンテンツ品質・リスクの3観点で最終監査を行え。

【記事】
$(cat reports/11_checked.md)

【SEOキーワード（基準として使用）】
$(cat reports/2_seo.md | head -30)

全チェックリスト項目を確認し、修正できる問題は自分で修正せよ。
監査サマリー・修正箇所・最終判定（✅投稿OK/⚠️要確認/❌投稿停止）を出力した後、
OKまたは要確認の場合のみ以下の形式で最終記事を出力：
1行目：タイトルのみ
2行目：空行
3行目以降：HTML本文のみ（<h2>から始める）
" > reports/12_audited.md
check_output reports/12_audited.md "ゲンガー"

if grep -q '❌ 投稿停止' reports/12_audited.md; then
  echo "❌ ゲンガーが投稿停止を判定 → パイプライン停止"
  grep '投稿停止' reports/12_audited.md
  archive_and_exit 1
fi

echo "[13/15] カイリュー: CVR・回遊最適化..."
# ゲンガー出力から記事部分を抽出
ARTICLE_LINE=$(grep -n '^<h2>' reports/12_audited.md | head -1 | cut -d: -f1)
if [[ -n "$ARTICLE_LINE" ]]; then
  TITLE_LINE=$((ARTICLE_LINE - 2))
  [[ $TITLE_LINE -lt 1 ]] && TITLE_LINE=1
  sed -n "${TITLE_LINE}p" reports/12_audited.md > /tmp/gengar_article.md
  echo "" >> /tmp/gengar_article.md
  tail -n "+${ARTICLE_LINE}" reports/12_audited.md >> /tmp/gengar_article.md
else
  cp reports/12_audited.md /tmp/gengar_article.md
fi

claude --agent kairyu_kpop -p "
今日は${TODAY}です。
以下の記事にCVR・回遊導線を追加せよ。

【記事】
$(cat /tmp/gengar_article.md)

【改善指示】
- 記事の1/3付近と末尾近くにCTAボックスを追加
- 末尾に関連記事誘導セクションを追加（URLは#でOK）
- 末尾にSNSシェア促進を追加（アーティスト名のタグ含む）
- 事務的なH2見出しをファン感情に響く言葉に調整（内容は変えない）

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（##・説明文禁止）
2行目：空行
3行目以降：改善済みHTML本文のみ（<h2>から始める）
" > reports/13_final.md
check_output reports/13_final.md "カイリュー"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 4: 総監督・最終承認
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ PHASE 4: 総監督・最終承認 ━━━"

echo "[14/15] アルセウス: 総監督・最終承認..."
claude --agent arceus -p "
今日は${TODAY}です。
以下の全エージェントのレポートと最終記事を確認し、総監督レポートを出力せよ。

【バタフリー: トレンド】
$(head -50 reports/1_trend.md)

【ラプラス: SEO】
$(head -40 reports/2_seo.md)

【ミミッキュ: 競合分析】
$(head -40 reports/3_competitor.md)

【ソーナンス: 読者ニーズ】
$(head -30 reports/4_reader.md)

【ジラーチ: リスク予測】
$(head -30 reports/5_future.md)

【フシギバナ: 記事構成】
$(head -40 reports/6_structure.md)

【ミュウツー: 戦略判断】
$(head -50 reports/7_strategy.md)

【最終記事（カイリュー出力）】
$(cat reports/13_final.md)

全エージェントを採点表で評価し、最終記事品質を評価して投稿承認/却下を判定せよ。
" > reports/14_arceus.md
check_output reports/14_arceus.md "アルセウス"

if grep -q '❌ 投稿却下' reports/14_arceus.md; then
  echo ""
  echo "❌ アルセウスが投稿を却下しました"
  grep '投稿却下' reports/14_arceus.md
  archive_and_exit 1
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 5: 品質チェック・投稿・拡散
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ PHASE 5: 品質チェック・投稿・拡散 ━━━"

TITLE=$(head -n 1 reports/13_final.md)
check_duplicate "$TITLE" 5
CONTENT=$(tail -n +2 reports/13_final.md)

if [[ -z "$TITLE" ]] || [[ "$TITLE" == "#"* ]] || \
   [[ "$TITLE" == *"ファクトチェック"* ]] || [[ "$TITLE" == *"申し訳ありません"* ]]; then
  echo "❌ 品質NG: タイトル異常（$TITLE）→ 投稿停止"
  archive_and_exit 1
fi

if [[ -z "$CONTENT" ]] || [[ "$CONTENT" == *"できません"* ]] || \
   [[ "$CONTENT" == *"申し訳ありません"* ]]; then
  echo "❌ 品質NG: 本文異常 → 投稿停止"
  archive_and_exit 1
fi

CONTENT_LENGTH=$(python3 -c "import sys; print(len(sys.argv[1]))" "$CONTENT")

if [ "$CONTENT_LENGTH" -lt 1500 ]; then
  echo "❌ 品質NG: 本文${CONTENT_LENGTH}文字（最低1500文字必要）→ 投稿停止"
  archive_and_exit 1
fi

echo "✅ 品質チェック通過（${CONTENT_LENGTH}文字）"

PUBLISH_TITLE=$(echo "$TITLE" | sed 's/^/【戦略】/')

# === アイキャッチ生成 ===
echo "--- アイキャッチ生成..."
THUMB_TITLE=$(echo "$PUBLISH_TITLE" | cut -c1-30)
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

# === カテゴリ自動判定 ===
CATEGORY_ID=$(python3 - << 'PY' "$PUBLISH_TITLE"
import sys
title = sys.argv[1].lower()
rules = [
    (71, ['チャート','ランキング','1位','billboard','gaon','spotify']),
    (3,  ['カムバック','カムバ','復帰','新アルバム','ミニアルバム']),
    (6,  ['新曲','mv公開','ミュージックビデオ','配信開始','音源公開']),
    (5,  ['ライブ','コンサート','ツアー','来日','ファンミ','チケット']),
    (7,  ['出演','テレビ','番組','放送','ラジオ']),
    (28, ['音楽番組','人気歌謡','music bank','m countdown']),
    (8,  ['ドラマ','主演','俳優','女優']),
    (10, ['コラボ','feat','ユニット']),
    (15, ['広告','アンバサダー','cm']),
    (13, ['新商品','グッズ','限定']),
    (14, ['熱愛','炎上','騒動','脱退','訴訟']),
    (9,  ['話題','注目','バズ','海外の反応']),
    (4,  ['考察','分析','なぜ','解説','深掘り','特集','まとめ']),
]
for cid, keywords in rules:
    if any(word in title for word in keywords):
        print(cid)
        sys.exit()
print(2)
PY
)
echo "  CATEGORY_ID=$CATEGORY_ID"

# === アーティスト別カテゴリ ===
ARTIST_CATEGORY_IDS=$(python3 - << 'PY' "$PUBLISH_TITLE"
import sys
title = sys.argv[1].lower()
artist_rules = [
    (19, ['bigbang','g-dragon','gd','taeyang']),
    (23, ['blackpink','jennie','jisoo','rose','lisa']),
    (18, ['bts','방탄','rm','jin','suga','j-hope','jimin',' v ','jungkook']),
    (25, ['aespa','karina','winter','ningning','giselle']),
    (38, ['babymonster','baby monster']),
    (44, ['illit']),
    (68, ['ive','wonyoung','yujin']),
    (41, ['le sserafim','lesserafim','sakura','chaewon']),
    (32, ['newjeans','new jeans','minji','hani','danielle']),
    (39, ['riize']),
    (24, ['seventeen','svt']),
    (43, ['stray kids','skz']),
    (22, ['twice','nayeon','momo','sana','jihyo']),
    (42, ['zerobaseone','zb1']),
    (60, ['exo','baekhyun','kai','suho']),
    (37, ['itzy']),
    (33, ['xg']),
    (40, ['nct']),
]
matched = []
for cid, keywords in artist_rules:
    if any(word in title for word in keywords):
        matched.append(str(cid))
print(",".join(matched))
PY
)

# === タグ自動生成・取得 ===
TAG_NAMES=$(python3 - << 'PY' "$PUBLISH_TITLE"
import sys
title = sys.argv[1]
rules = [
    ('BTS', ['bts','rm','jin','suga','j-hope','jimin','jungkook']),
    ('BIGBANG', ['bigbang','g-dragon','gd']),
    ('BLACKPINK', ['blackpink','jennie','jisoo','rose','lisa']),
    ('aespa', ['aespa','karina','winter','ningning']),
    ('BABYMONSTER', ['babymonster','baby monster']),
    ('ILLIT', ['illit']),
    ('IVE', ['ive','wonyoung']),
    ('LE SSERAFIM', ['le sserafim','lesserafim']),
    ('SEVENTEEN', ['seventeen','svt']),
    ('TWICE', ['twice']),
    ('Stray Kids', ['stray kids','skz']),
    ('NewJeans', ['newjeans','new jeans']),
    ('XG', ['xg']),
    ('カムバック', ['カムバック','カムバ','復帰']),
    ('ワールドツアー', ['ワールドツアー','ツアー','コンサート']),
    ('K-POP速報', ['速報','最新情報']),
]
title_l = title.lower()
matched = [tag for tag, kws in rules if any(w in title_l for w in kws)]
print('|'.join(list(dict.fromkeys(matched))))
PY
)

TAG_IDS=$(python3 - << 'PY' "$TAG_NAMES"
import sys, json, urllib.request, urllib.parse, base64
raw = sys.argv[1].strip()
if not raw:
    print(""); sys.exit()
tag_names = [t for t in raw.split("|") if t.strip()]
auth = base64.b64encode(os.environ.get("WP_USER","kpop-bot").encode() + b":" + os.environ.get("WP_PASS","").encode()).decode()
headers = {"Authorization": "Basic " + auth, "Content-Type": "application/json"}
base_url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/tags"
tag_ids = []
for name in tag_names:
    req = urllib.request.Request(base_url + "?search=" + urllib.parse.quote(name) + "&per_page=5", headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read())
        match = next((t for t in data if t["name"] == name), None)
        if match:
            tag_ids.append(str(match["id"])); continue
    except: pass
    req = urllib.request.Request(base_url, data=json.dumps({"name": name}).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req) as res:
            tag_ids.append(str(json.loads(res.read())["id"]))
    except: pass
print(",".join(tag_ids))
PY
)

DESC=$(echo "$CONTENT" | sed -e 's/<[^>]*>//g' | python3 -c "import sys; t=sys.stdin.read().strip(); print(t[:120])")
echo "$PUBLISH_TITLE" > /tmp/kpop_title.txt
echo "$CONTENT"       > /tmp/kpop_content.txt
echo "$DESC"          > /tmp/kpop_desc.txt

JSON=$(python3 - << 'PY' "$CATEGORY_ID" "$MEDIA_ID" "$ARTIST_CATEGORY_IDS" "$TAG_IDS"
import json, sys
main_cat       = int(sys.argv[1])
media_id       = int(sys.argv[2])
artist_ids_raw = sys.argv[3].strip()
tag_ids_raw    = sys.argv[4].strip()
with open("/tmp/kpop_title.txt")   as f: title   = f.read().strip()
with open("/tmp/kpop_content.txt") as f: content = f.read().strip()
with open("/tmp/kpop_desc.txt")    as f: desc    = f.read().strip()
categories = [main_cat]
for x in (artist_ids_raw.split(",") if artist_ids_raw else []):
    x = x.strip()
    if x: categories.append(int(x))
categories = list(dict.fromkeys(categories))
tags = [int(x.strip()) for x in tag_ids_raw.split(",") if x.strip()] if tag_ids_raw else []
data = {'title': title, 'content': content, 'status': 'publish',
        'categories': categories, 'tags': tags, 'excerpt': desc}
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

echo "[15/15] ペルシアン: SNS拡散戦略..."
claude --agent persian -p "
今日は${TODAY}です。
以下のK-POP記事が投稿されました。SNS拡散戦略を設計せよ。

【記事タイトル】$TITLE
【記事URL】$POST_URL
【記事冒頭】
$(echo "$CONTENT" | sed 's/<[^>]*>//g' | head -c 300)

X投稿文3パターン・推奨ハッシュタグセット・最適投稿タイミング・採用推奨パターンを出力せよ。
" > reports/15_sns.md
check_output reports/15_sns.md "ペルシアン"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# レジギガス: 実行履歴アーカイブ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ レジギガス: 実行履歴アーカイブ ━━━"
mkdir -p "$ARCHIVE_DIR"
cp reports/* "$ARCHIVE_DIR/" 2>/dev/null
cat > "$ARCHIVE_DIR/summary.txt" << SUMMARY
実行ID      : $RUN_ID
パイプライン: strategy
日時        : $TODAY
記事ID      : $POST_ID
URL         : $POST_URL
タイトル    : $TITLE
文字数      : $CONTENT_LENGTH
判定        : 投稿OK
SUMMARY
echo "  保存先: $ARCHIVE_DIR ($(ls "$ARCHIVE_DIR" | wc -l | tr -d ' ')ファイル)"

bash ~/kpop_notify.sh success "戦略" "記事投稿完了: $TITLE" "$POST_URL" 2>/dev/null

echo ""
echo "========================================"
echo " ✅ パイプライン完了"
echo " 記事ID  : $POST_ID"
echo " URL     : $POST_URL"
echo " SNS戦略 : reports/15_sns.md"
echo " アーカイブ: $ARCHIVE_DIR"
echo "========================================"
