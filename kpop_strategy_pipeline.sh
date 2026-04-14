#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/env_loader.sh"
source "$SCRIPT_DIR/lib/sanitize_output.sh"

# トークントラッキング（ENABLE_TOKEN_TRACKING=1 で有効化）
if [ "${ENABLE_TOKEN_TRACKING:-0}" = "1" ]; then
  source "$SCRIPT_DIR/lib/claude_wrapper.sh"
fi

# パイプラインログ
PIPELINE_JSONL="$SCRIPT_DIR/logs/pipeline.jsonl"
mkdir -p "$SCRIPT_DIR/logs"

log_step() {
  local step="$1" status="$2" file="${3:-}" msg="${4:-}"
  local ts sz
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  if [[ -n "$file" && -f "$file" ]]; then
    sz=$(wc -c < "$file")
  else
    sz=0
  fi
  msg="${msg//\\/\\\\}"
  msg="${msg//\"/\\\"}"
  printf '{"timestamp":"%s","run_id":"%s","step":"%s","status":"%s","file":"%s","size_bytes":%d,"message":"%s"}\n' \
    "$ts" "${RUN_ID:-unknown}" "$step" "$status" "$file" "$sz" "$msg" >> "$PIPELINE_JSONL"
}

# 日本語名→英語ステップ名マッピング
declare -A AGENT_KEY=(
  ["バタフリー"]="butterfree" ["ラプラス"]="lapras" ["ミミッキュ"]="mimikyu"
  ["ソーナンス"]="wobbuffet" ["ジラーチ"]="jirachi" ["フシギバナ"]="venusaur"
  ["ミュウツー"]="mewtwo" ["デオキシス"]="deoxys" ["メタモン"]="metamon"
  ["イーブイ"]="eevee" ["アラカザム"]="alakazam" ["ゲンガー"]="gengar"
  ["アルセウス"]="arceus" ["ペルシアン"]="persian"
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ユーティリティ: 出力検証関数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
check_output() {
  local file="$1"
  local step="$2"
  local key="${AGENT_KEY[$step]:-$step}"
  if [[ ! -s "$file" ]]; then
    echo "❌ [$step] 出力が空 → パイプライン停止"
    log_step "$key" "error" "$file" "出力が空"
    archive_and_exit 1
  fi
  # 先頭行がHTMLコメントのみ → 本文なし扱い
  local _first_line
  _first_line=$(head -1 "$file")
  if [[ "$_first_line" =~ ^\s*\<!--.*--\>\s*$ ]] && \
     ! [[ "$_first_line" =~ article-type|TITLE_LOG|pipeline-meta ]]; then
    echo "❌ [$step] 先頭行がHTMLコメントのみ → 本文なし扱い → パイプライン停止"
    echo "  先頭行: $_first_line"
    log_step "$key" "error" "$file" "先頭行HTMLコメントのみ"
    archive_and_exit 1
  fi
  # 【SRE調査】プレフィックス行はシステムコメントのためNGワードチェック対象外
  if grep -vE '^\s*【SRE調査】' "$file" | grep -qE '申し訳ありません[がで。、 ]|申し訳ありません$|お手伝いできますか|許可してください|許可が必要です|確認させてください|WebSearchを使用|ウェブ検索の許可|許可を?いただ|入力記事が見当たりません|記事の入力が見当たりません|チェック対象の記事本文を貼り付けてください|記事を提供してください|記事の元となるコンテンツ|リライトしたい記事の本文|元となる記事の原文|ウェブフェッチはできません|ウェブフェッチ(は|が|でき)|ユーザーから記事のソース|元の記事が提供されていません|記事本文・題材・元記事URL|対象アーティスト・トピック・元記事内容を貼り付け' ; then
    echo "❌ [$step] エラー応答を検出 → パイプライン停止"
    echo "  先頭行: $(head -1 "$file")"
    log_step "$key" "error" "$file" "エラー応答検出"
    archive_and_exit 1
  fi
  echo "  ✓ [$step] OK ($(wc -c < "$file" | tr -d ' ') bytes)"
  log_step "$key" "ok" "$file"
}

cleanup_reports_dir() {
  if [[ -n "${REPORTS_DIR:-}" ]] && [[ -d "$REPORTS_DIR" ]]; then
    rm -rf "$REPORTS_DIR"
  fi
  if [[ -L "$SCRIPT_DIR/reports" ]]; then
    rm -f "$SCRIPT_DIR/reports"
  elif [[ -d "$SCRIPT_DIR/reports" ]]; then
    rm -rf "$SCRIPT_DIR/reports"
  fi
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
  cleanup_reports_dir
  bash ~/kpop_notify.sh error "戦略" "パイプライン停止 (RUN: $RUN_ID)" 2>/dev/null
  exit "$code"
}

wp_health_check() {
  echo "=== WordPress 接続確認 ==="
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1" \
    -K "$HOME/.wp_auth" \
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
import sys, json, os, urllib.request, base64, urllib.parse
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

  SIMILARITY=$(claude --no-session-persistence -p "
【タスク】類似記事重複チェック
新しく投稿しようとしている記事タイトルが、過去${days}日間の投稿済みタイトルと内容が重複しているか判定せよ。
【新タイトル】${title}
【過去${days}日間の投稿済みタイトル】
${RECENT_TITLES}
【判定基準】
- 同じアーティスト＋同じイベント＋同じ時期 → 重複（YES）
- 同じアーティストでも別イベント・別テーマ → 重複なし（NO）
- チャートランキングは毎週異なるため常に重複なし（NO）
- 美容・スキンケア・ガラス肌・韓国コスメ・Kビューティ系記事が過去${days}日に既に1本以上ある → 重複（YES）
【出力ルール】YESまたはNOの1単語のみ。他は出力禁止。
")

  if [[ "$SIMILARITY" == "YES" ]]; then
    echo "  ⚠️  重複あり: 類似記事が過去${days}日以内に投稿済み → スキップ"
    echo "    新タイトル: $title"
    archive_and_exit 0
  fi

  echo "  ✓ 重複なし"
}

TODAY=$(date '+%Y年%m月%d日')
RUN_ID=$(date '+%Y%m%d_%H%M%S')
ARCHIVE_DIR=~/kpop_archives/$RUN_ID

# run_idごとに reports を分離（並列実行時のファイル競合を防止）
REPORTS_DIR="$SCRIPT_DIR/reports_${RUN_ID}"
mkdir -p "$REPORTS_DIR"
if [[ -L "$SCRIPT_DIR/reports" ]]; then
  rm -f "$SCRIPT_DIR/reports"
elif [[ -d "$SCRIPT_DIR/reports" ]]; then
  rm -rf "$SCRIPT_DIR/reports"
fi
ln -sfn "$REPORTS_DIR" "$SCRIPT_DIR/reports"
export TOKEN_LOG="$ARCHIVE_DIR/token_usage.jsonl"

echo "========================================"
echo " K-POP戦略パイプライン 開始: $TODAY"
echo " 実行ID: $RUN_ID | 全15エージェント"
echo "========================================"

wp_health_check

# 直近3日間の投稿タイトルを取得（ネタ被り防止）
echo "=== 直近投稿タイトル取得（ネタ被り防止）==="
RECENT_POSTED=$(python3 - <<'PYEOF'
import json, urllib.request, urllib.parse, base64, os
from datetime import datetime, timedelta, timezone
cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")
url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=30&after=" + urllib.parse.quote(cutoff) + "&status=publish"
auth = base64.b64encode((os.environ.get("WP_USER","kpop-bot") + ":" + os.environ.get("WP_PASS","")).encode()).decode()
try:
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
    with urllib.request.urlopen(req, timeout=10) as resp:
        posts = json.loads(resp.read())
    if not posts:
        print("（直近3日間の投稿なし）")
    else:
        for p in posts:
            print("- " + p["title"]["rendered"])
except Exception as e:
    print("（取得失敗: " + str(e)[:80] + "）")
PYEOF
)
echo "  直近3日間の投稿: $(echo "$RECENT_POSTED" | grep -c '^\-' || echo 0)件"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 1: インテリジェンス収集
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ PHASE 1: インテリジェンス収集 ━━━"

echo "[1/15] バタフリー: 最新トレンド収集..."
_BUTTERFREE_PROMPT="今日は${TODAY}です。
K-POPの最新トレンドをWebSearchで収集し、記事化優先度スコア付きのインテリジェンスレポートを出力せよ。

検索手順：
1.「K-POP 最新ニュース ${TODAY}」
2.「BTS BLACKPINK NewJeans aespa TWICE 新曲 コンサート 受賞 ${TODAY}」
3.「K-POP Billboard Melon Oricon チャート 今週」
4.「K-POP Twitter トレンド 話題 炎上」
5. 急上昇が見られたアーティストを追加検索

速報TOP5・チャート動向・SNS反応・イベントカレンダー・記事化推奨テーマ（優先度スコア付き）を必ず出力せよ。"

claude --no-session-persistence --allowedTools WebSearch --agent butterfree -p "$_BUTTERFREE_PROMPT" > reports/1_trend.md
sanitize_output reports/1_trend.md

# 空出力なら1回リトライ
if [[ ! -s reports/1_trend.md ]]; then
  echo "  ⚠️ バタフリー空出力 → 30秒待機後リトライ..."
  sleep 30
  claude --no-session-persistence --allowedTools WebSearch --agent butterfree -p "$_BUTTERFREE_PROMPT" > reports/1_trend.md
  sanitize_output reports/1_trend.md
fi

# リトライ後も空なら直近成功アーカイブからフォールバック
if [[ ! -s reports/1_trend.md ]]; then
  _FALLBACK=$(ls -t /home/aiuser/kpop_archives/*/1_trend.md 2>/dev/null | head -1)
  if [[ -n "$_FALLBACK" && -s "$_FALLBACK" ]]; then
    echo "  ⚠️ バタフリーリトライ失敗 → 直近アーカイブからフォールバック: $_FALLBACK"
    cp "$_FALLBACK" reports/1_trend.md
    echo "" >> reports/1_trend.md
    echo "※ このレポートは ${TODAY} のバタフリー空出力フォールバックです。" >> reports/1_trend.md
    log_step "butterfree" "fallback" "reports/1_trend.md" "空出力→アーカイブフォールバック"
  else
    echo "❌ バタフリー: リトライ・フォールバックともに失敗 → パイプライン停止"
    log_step "butterfree" "error" "reports/1_trend.md" "空出力（フォールバックなし）"
    archive_and_exit 1
  fi
fi
check_output reports/1_trend.md "バタフリー"

echo "[2/15] ラプラス: SEOキーワード戦略..."
claude --no-session-persistence --agent lapras -p "
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
sanitize_output reports/2_seo.md
check_output reports/2_seo.md "ラプラス"

echo "[3/15] ミミッキュ: 競合分析・差別化設計..."
claude --no-session-persistence --allowedTools WebSearch --agent mimikyu -p "
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
sanitize_output reports/3_competitor.md
check_output reports/3_competitor.md "ミミッキュ"

# ▶ ソーナンス（4）とジラーチ（5）を並列実行
echo "[4+5/15] ソーナンス・ジラーチ: 並列実行..."

claude --no-session-persistence --agent wobbuffet -p "
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

claude --no-session-persistence --agent jirachi_kpop -p "
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
sanitize_output reports/4_reader.md
check_output reports/4_reader.md "ソーナンス"
sanitize_output reports/5_future.md
check_output reports/5_future.md "ジラーチ"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 2: 戦略設計
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ PHASE 2: 戦略設計 ━━━"

echo "[6/15] フシギバナ: SEO記事構成設計..."
claude --no-session-persistence --agent venusaur -p "
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
sanitize_output reports/6_structure.md
check_output reports/6_structure.md "フシギバナ"

echo "[7/15] ミュウツー: 戦略統合・編集長判断..."
claude --no-session-persistence --agent mewtwo -p "
今日は${TODAY}です。
以下の全レポートを統合し、今日書くべきK-POP記事TOP3を意思決定せよ。

【★最重要★ ネタ被り絶対禁止】
同じネタを繰り返すな。直近3日間の投稿と被らないテーマを選べ。
以下は直近3日間に既に投稿済みの記事タイトル一覧である。
これらと同じテーマ・同じ切り口・同じまとめ形式の記事を選ぶことは絶対に禁止。
TOP3の全てが投稿済み記事と異なるテーマであることを確認せよ。

【直近3日間の投稿済み記事（これらと被るテーマは禁止）】
${RECENT_POSTED}

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
【重要】TOP3の各テーマが直近3日間の投稿済み記事と被っていないことを明記せよ。
異常検知・注意事項と、デオキシスへの具体的な実行指示も出力せよ。
" > reports/7_strategy.md
sanitize_output reports/7_strategy.md
check_output reports/7_strategy.md "ミュウツー"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 3: 記事生成・品質改善
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ PHASE 3: 記事生成・品質改善 ━━━"

echo "[8/15] デオキシス: 高品質記事生成..."
claude --no-session-persistence --allowedTools WebSearch --agent deoxys_kpop -p "
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

【UI/UX品質指示（必須）】
- 冒頭100文字以内に必ず数字または結論を1つ入れる（例：「初週641,000枚」「3週連続1位」）
- article-typeラベルの直後、最初の<h2>の前に結論1行を<p>タグで追加する
  形式：<p class="conclusion-lead"><strong>結論：〇〇。</strong></p>
- 1段落（<p>タグ）は最大3行（スマホ表示で約60文字×3行）に収める。長い段落は分割する
- 数字・重要ワード（アーティスト名・記録・順位）は<strong>タグで囲む
- 画像（<img>タグや[caption]）は必ず関連する説明テキストより前に配置する

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（##・マークダウン・説明文禁止）
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ
" > reports/8_article.md
sanitize_output reports/8_article.md
check_output reports/8_article.md "デオキシス"

echo "[9/15] メタモン: CTRリライト（3案→自己選定）..."
claude --no-session-persistence --agent metamon_kpop -p "
今日は${TODAY}です。
以下の記事をCTRとSEOの両方を最大化する形にリライトせよ。

【元記事】
$(cat reports/8_article.md)

【SEOキーワード（活用せよ）】
$(cat reports/2_seo.md | head -40)

━━━━━━━━━━━━━━━━━━━
【タイトル生成ルール（最重要）】
━━━━━━━━━━━━━━━━━━━

必ず以下3パターンのタイトルを内部で生成し、最もクリックされる1案を採用せよ：

A【SEO型】：検索キーワードを自然に含む。「誰が・何を・いつ」が一目で分かる
B【感情フック型】：驚き・違和感・疑問・危機感のいずれかを含む。「なぜ」「まさか」「強すぎる」「ついに」等
C【異常性・ギャップ型】：「異常」「強すぎる」「止まらない」「なぜだけ残った」等の違和感ワードを使う

選定基準（この順で判断）：
1. 一瞬で「気になる」か
2. 読者の感情（驚き・疑問・共感）を動かすか
3. SEOキーワードが自然に入っているか

【絶対禁止】
- 「〜について解説」「まとめ」「とは？」「分析」「〜を徹底解説」等の弱い表現
- 【戦略】【速報】等の内部ラベル
- 40文字超のタイトル

━━━━━━━━━━━━━━━━━━━

【リライト指示】
- 冒頭は「違和感・疑問の代弁」から入れ（分析から始めるな）
  例：「IVE、なんでこんなに強いの？」「正直「強すぎない？」って思いましたよね」
- H2見出しをより感情・疑問訴求に改善（事実・構造は変えない）
- 本文は「です・ます調」で統一（感情パートは会話風に崩してOK）
- 専門用語は中学生でも分かる言葉に言い換える
- 1文を短く。改行を多く。スマホで読みやすく。
- 各<h2>の直前に感情フック1行を<p class="section-hook">タグで追加する
  形式：<p class="section-hook">〇〇、実はここが一番ヤバい。</p>
- 1<p>タグは最大3行。それ以上になる段落は分割する
- 記事の中盤（全体の約1/2の位置）に再フック文を1つ追加する
  形式：<p class="rehook"><strong>ここまで読んでくれたあなたへ——本当に大事な話はここから。</strong></p>

【出力形式・絶対厳守】
1行目：採用タイトルのみ（マークダウン・説明文禁止）
2行目：空行
3行目以降：HTML本文のみ

【内部ログ（本文出力前に1行だけ記録）】
TITLE_LOG: A=「Aタイトル」 B=「Bタイトル」 C=「Cタイトル」 → 採用=X（採用理由を1行）
この1行の後に空行を入れ、採用タイトルと本文を出力せよ。
" > reports/9_rewrite.md
sanitize_output reports/9_rewrite.md
# TITLE_LOG行をログに記録してから本文から除去（final_post.mdに漏れ込み防止）
_TITLE_LOG=$(grep '^TITLE_LOG:' reports/9_rewrite.md | head -1)
if [[ -n "$_TITLE_LOG" ]]; then
  echo "  [metamon] $_TITLE_LOG"
  grep -v '^TITLE_LOG:' reports/9_rewrite.md > /tmp/9_rewrite_clean.md && mv /tmp/9_rewrite_clean.md reports/9_rewrite.md
fi
check_output reports/9_rewrite.md "メタモン"

echo "[10/15] イーブイ: タイトルA/B最終選定..."
claude --no-session-persistence --agent eevee -p "
今日は${TODAY}です。
以下の記事を受け取り、タイトルを「最もクリックされる1案」に確定して出力せよ。

【記事（メタモン出力）】
$(cat reports/9_rewrite.md)

【SEOメインキーワード】
$(cat reports/2_seo.md | grep -A3 'メインキーワード' | head -5)

━━━━━━━━━━━━━━━━━━━
【タイトル評価・確定ルール】
━━━━━━━━━━━━━━━━━━━

メタモンが出したタイトルを以下の基準で評価し、必要なら改善して確定せよ：

確定基準（全て満たすこと）：
1. 一瞬で「なんで？」「気になる」と思えるか
2. アーティスト名が入っているか
3. 数字・具体的事実・感情ワードのいずれかが入っているか
4. 40文字以内か
5. 「解説」「まとめ」「とは？」「〜について」「分析」等の弱い表現がないか

もし弱ければ改善案を出して差し替える。強ければそのまま採用。

【出力形式・絶対厳守】
1行目：確定タイトルのみ（マークダウン・説明禁止）
2行目：空行
3行目以降：記事HTML本文をそのまま出力（変更禁止）
" > reports/10_title.md
sanitize_output reports/10_title.md
check_output reports/10_title.md "イーブイ"

echo "[11/15] アラカザム: ファクトチェック..."

# カテゴリ111（視聴方法・配信ガイド）判定
_ARTICLE_TITLE=$(head -1 reports/10_title.md | sed 's/^[#[:space:]]*//')
_IS_STREAMING_GUIDE=$(python3 -c "
import sys
title = sys.argv[1].lower()
keywords = ['視聴方法','どこで見れる','無料視聴','配信サービス','配信比較','サブスク','abema','netflix','hulu','prime video','ライブ配信','見る方法','見る全方法','視聴ガイド']
print('yes' if any(k in title for k in keywords) else 'no')
" "$_ARTICLE_TITLE" 2>/dev/null)

if [[ "$_IS_STREAMING_GUIDE" == "yes" ]]; then
  echo "  ⚠️  視聴導線記事（カテゴリ111相当）検出 → 強化ファクトチェックモード"
  _STREAMING_EXTRA_RULES="

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【視聴導線記事 専用ファクトチェックルール（最優先・必須）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

この記事は「視聴方法・配信ガイド」カテゴリに属するため、以下を全項目チェックし必ず修正せよ。

■ 料金チェック（price）
- ABEMAプレミアム: 正しい金額は月1,180円（2026年4月改定済み）。960円が残っていたら即修正
- Leminoプレミアム: 正しい金額はWeb登録月1,540円（2026年2月改定済み）。990円が残っていたら即修正
- 料金を記載している箇所には必ず「最新料金は公式サイトをご確認ください」を同段落内に追加
- 他サービス（Netflix/KNTV/スカパー等）の料金も断定しない。「詳細は公式サイトで確認」を必ず追記

■ 配信可否チェック（stream）
- 配信状況は必ず「確認済み」「未確認」「過去実績あり」の3分類で表現せよ
- 「過去実績あり」を「2026年も配信決定」と混同している箇所を全て修正
- 「配信予定です」「配信されます」「見られます」「視聴できます」が未確認情報に付いていたら削除または「過去実績あり（2026年は要確認）」に変更
- 公式発表がない配信には「現時点で公式発表なし」を明記

■ スケジュール・日付チェック（schedule）
- 日付・開催地・タイムテーブルは公式情報のみ記載
- 「予定」は確定情報との混同を防ぐため「〇〇予定（公式発表待ち）」と明記
- 確定済みの情報は「確定」と明記

■ 活動状況チェック（status）
- メンバーの活動状況・休止・訴訟・脱退等は最新公式情報または一次報道のみ記載
- 現在の活動状況を断定しない。「〇〇時点の情報」と明記
- Weverse導線: IVEはKakao系（Weverse非対応）。IVEの記事にWeverseへの導線があれば削除し、公式SNSに置き換えよ
- HYBE系（BTS・SEVENTEEN・NewJeans・aespa等）のWeverse言及は適切

■ プラットフォーム正確性（platform）
- 各アーティストの所属系列を確認：
  - HYBE系（Weverse対応）: BTS/SEVENTEEN/NewJeans/TOMORROW X TOGETHER/ENHYPEN/aespa等
  - Kakao系（Weverse非対応）: IVE/Kep1er等
  - SM系: aespaはSM所属だがWeverse対応（HYBE提携のため）
- YouTubeは「無料公開動画あり」と表現し「全て無料視聴可能」は使わない

■ 出力末尾への監査ログ追加（必須）
本文出力の最後の行の後に、必ず以下形式の監査ログを1行追加せよ：
FACTCHECK_LOG: price=OK/NG stream=OK/NG schedule=OK/NG status=OK/NG source_count=N
（各項目: OK=問題なし/修正済み, NG=問題あり要人手確認, N=参照した情報元の数）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
  _STREAMING_EXTRA_RULES=""
fi

claude --no-session-persistence --agent alakazam_kpop -p "
今日は${TODAY}です。
以下の記事の日付・時制・事実・誇張表現を確認し、必要箇所のみ修正せよ。

【記事】
$(cat reports/10_title.md)

【チェック優先順位】
1. 未来の出来事が過去形になっていないか（${TODAY}基準で判断）
2. 根拠のない「世界初・史上初・歴代最高」がないか
3. 実在しないアルバム名・受賞歴がないか
4. 情報元の明記があるか
${_STREAMING_EXTRA_RULES}
【出力形式・絶対厳守】
1行目：タイトル文字列のみ（##・「ファクトチェック結果」等の説明文禁止）
2行目：空行
3行目以降：修正済みHTML本文のみ（<h2>から始める）
視聴導線記事の場合のみ、本文の最後の行の後にFACTCHECK_LOGを追加せよ（本文内には含めない）
" > reports/11_checked.md
sanitize_output reports/11_checked.md
# FACTCHECK_LOG行をログに保存して本文から除去
_FACTCHECK_LOG=$(grep '^FACTCHECK_LOG:' reports/11_checked.md | head -1)
if [[ -n "$_FACTCHECK_LOG" ]]; then
  echo "  [alakazam] $_FACTCHECK_LOG"
  echo "$_FACTCHECK_LOG" >> "$SCRIPT_DIR/logs/factcheck.log"
  grep -v '^FACTCHECK_LOG:' reports/11_checked.md > /tmp/11_checked_clean.md && mv /tmp/11_checked_clean.md reports/11_checked.md
fi
check_output reports/11_checked.md "アラカザム"

echo "[12/15] ゲンガー: SEO・品質最終監査..."
claude --no-session-persistence --agent gengar -p "
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
sanitize_output reports/12_audited.md
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

claude --no-session-persistence --agent kairyu_kpop -p "
今日は${TODAY}です。
以下の記事にCVR・回遊導線を追加せよ。

【記事】
$(cat /tmp/gengar_article.md)

【改善指示（優先順）】
1. 【記事タイプ付与】HTML本文の先頭（最初の<p>か<h2>の直前）に記事タイプを判定して挿入する
   - 「速報」「決定」「判明」「解禁」等 → <p class=\"article-type speed\">【速報】</p>
   - 「視聴方法」「チケット」「アクセス」「持ち物」等 → <p class=\"article-type guide\">【ガイド】</p>
   - それ以外 → <p class=\"article-type explanation\">【解説】</p>
   - タイトルに既に【速報】等が含まれる場合は重複付与しない
2. CTAボックスを2箇所に配置する
   - 1箇所目：記事の中盤（全体の約1/2の位置、H2の直後）に配置
   - 2箇所目：末尾近く（最後のH2の後）に配置
3. 関連記事リンクを本文中（中盤）と末尾の2箇所に配置する
   - 中盤：<div class=\"related-mid\"><p>📌 あわせて読みたい</p><ul>（関連3件）</ul></div>
   - 末尾：BTS/BLACKPINK/IVE等の主要10グループはハブページへのリンクを必ず含める
4. 末尾にSNSシェア促進を追加（アーティスト名のタグ含む）
5. 事務的なH2見出しをファン感情に響く言葉に調整（内容は変えない）

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（##・説明文禁止）
2行目：空行
3行目以降：改善済みHTML本文のみ（<h2>から始める）
" > reports/13_final.md
sanitize_output reports/13_final.md
check_output reports/13_final.md "カイリュー"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 4: 総監督・最終承認
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ PHASE 4: 総監督・最終承認 ━━━"

# === [13.5] ガルデvoir: 刺さり品質ゲート ===
echo "[13.5/15] ガルデvoir: 刺さり品質判定..."
# ガルデvoir ログファイルを事前に確保（存在しない場合は作成）
touch "$SCRIPT_DIR/logs/gardevoir_hook.jsonl"
GARDEVOIR_DIRECTIVE=$(python3 "$SCRIPT_DIR/lib/auto_improve.py" directive --agent gardevoir_hook_critic 2>/dev/null || echo "")

# タイトル取得（strategy: reports/13_final.mdの1行目）
_GDV_TITLE=$(head -1 reports/13_final.md | sed 's/^[#[:space:]]*//')

# [前段ガード] タイトル崩壊パターン検出 → サーナイト呼び出し前に即停止
# 根拠: gardevoir HARD_FAIL率68%の主因がタイトル崩壊であることをagent_monitorが検出
_TITLE_COLLAPSE=0
if echo "$_GDV_TITLE" | grep -qE '(以下に|分析します|ウェブフェッチ|以下の記事|提供してください|見当たりません|コンテンツが提供されていません|^以下)'; then
  _TITLE_COLLAPSE=1
fi
_TITLE_LEN=${#_GDV_TITLE}
if [[ $_TITLE_LEN -lt 10 ]]; then
  _TITLE_COLLAPSE=1
fi
if [[ "$_TITLE_COLLAPSE" == "1" ]]; then
  echo "❌ [前段ガード] タイトル崩壊を検出しました → パイプライン停止"
  echo "  検出タイトル: ${_GDV_TITLE}"
  echo "  原因: 上流エージェントがメタコメントをタイトルとして出力した可能性"
  log_step "gardevoir_hook_critic" "ERROR" "reports/13_final.md" "前段ガード: タイトル崩壊検出 title=${_GDV_TITLE}"
  python3 "$SCRIPT_DIR/lib/kpi_logger.py" log_error "{\"error_type\":\"title_collapse\",\"step\":\"pre_gardevoir_guard\",\"pipeline\":\"strategy\",\"title\":\"${_GDV_TITLE}\",\"message\":\"タイトル崩壊パターン検出: 上流エージェントのメタコメント混入疑い\",\"recoverable\":false}" 2>/dev/null || true
  bash "$SCRIPT_DIR/kpop_notify.sh" error "strategy" "タイトル崩壊検出で停止 (RUN: $RUN_ID) title=${_GDV_TITLE}" 2>/dev/null || true
  archive_and_exit 1
fi

# 冒頭500文字・H2一覧抽出
_GDV_HOOK=$(python3 -c "
import re
text=open('reports/13_final.md').read()
body=re.sub(r'^.*\n','',text,count=1)
body=re.sub(r'<[^>]+>','',body)
print(body[:500])
" 2>/dev/null || sed -n '3,25p' reports/13_final.md)

_GDV_H2=$(grep -oP '(?<=<h2>)[^<]+' reports/13_final.md 2>/dev/null | head -10 | sed 's/^/- /' || grep -E '^## ' reports/13_final.md | head -10)
[ -z "$_GDV_H2" ] && _GDV_H2="（H2なし）"

# カテゴリ（strategyはCATEGORY_IDが設定済みの場合もある）
_GDV_CATEGORY="${CATEGORY_ID:-${CATEGORY_HINT:-不明}}"

_GDV_RETRY=0
_GDV_VERDICT=""

while true; do
  echo "  ガルデvoir採点中... (試行$((${_GDV_RETRY}+1)))"
  claude --no-session-persistence --agent gardevoir_hook_critic -p "
以下の記事を採点せよ。出力は SCORE: から始まる固定フォーマットのみとする。会話・説明・質問を出力してはならない。

${GARDEVOIR_DIRECTIVE}

記事カテゴリ: ${_GDV_CATEGORY}
想定ターゲット: KPOPファン・韓国カルチャー好き・旅行/美容/ファッション興味層
タイトル: ${_GDV_TITLE}
メタディスクリプション: （なし）

【冒頭300〜500文字】
${_GDV_HOOK}

【H2一覧】
${_GDV_H2}

【CTA】
（記事末尾のCTAを参照してください）

【記事全文】
$(cat reports/13_final.md)
" > reports/13_5_gardevoir.md 2>/dev/null
  sanitize_output reports/13_5_gardevoir.md

  _GDV_VERDICT=$(grep -oP '^VERDICT:\s*\K(PASS|SOFT_RETRY|HARD_FAIL)' reports/13_5_gardevoir.md | head -1)
  # SCORE パース: 複数フォーマットに対応
  #   パターン1: "SCORE: 81"           (同一行にスコアあり)
  #   パターン2: "SCORE: 81/100"       (同一行に /100 付き)
  #   パターン3: "TOTAL: 81/100"       (TOTAL行)
  #   パターン4: "SCORE:\n総合: 81/100"  (直後行)
  #   パターン5: "SCORE:\n- 総合: 81/100" (直後行・箇条書き)
  #   パターン6: "- 総合スコア: 87/100"  (任意行・総合スコア)
  #   パターン7: "総合: 87/100"         (任意行・総合のみ)
  _GDV_SCORE=$(python3 -c "
import re, sys
text = open('reports/13_5_gardevoir.md', errors='replace').read()
# パターン1/2: SCORE: 81 または SCORE: 81/100 (同一行)
m = re.search(r'^SCORE:\s*(\d+)', text, re.MULTILINE)
if m:
    print(m.group(1)); sys.exit(0)
# パターン3: TOTAL: 81/100 (同一行)
m = re.search(r'^TOTAL[：:]\s*(\d+)', text, re.MULTILINE)
if m:
    print(m.group(1)); sys.exit(0)
# パターン4/5: SCORE:行の後（距離制限なし）に 総合: or - 総合: or 合計: が来るケース
m = re.search(r'^SCORE:\s*\n(?:.*\n)*?[-\s]*(?:総合|合計)[：:]\s*(\d+)', text, re.MULTILINE)
if m:
    print(m.group(1)); sys.exit(0)
# パターン6: 任意行の「総合スコア: 87/100」
m = re.search(r'総合スコア[：:]\s*(\d+)', text)
if m:
    print(m.group(1)); sys.exit(0)
# パターン7: 任意行の「総合: 87/100」(総合スコアとは別語)
m = re.search(r'総合[：:]\s*(\d+)', text)
if m:
    print(m.group(1)); sys.exit(0)
# パターン8: 任意行の「合計: 87/100」(合計キーワード)
m = re.search(r'合計[：:]\s*(\d+)', text)
if m:
    print(m.group(1)); sys.exit(0)
# パターン9: 任意行の「総合点: 81/100」(総合点キーワード)
m = re.search(r'総合点[：:]\s*(\d+)', text)
if m:
    print(m.group(1)); sys.exit(0)
# パターン10a: テーブルセル形式 | 合計 | 81 | or | 合計 | 81/100 |
m = re.search(r'\|\s*(?:合計|総合|SCORE|スコア)\s*\|\s*(\d+)', text)
if m:
    print(m.group(1)); sys.exit(0)
# パターン10b: フォールバック — テキスト中の NN/100 形式を拾う（最後の手段）
m = re.search(r'(?<!\d)([6-9]\d|100)/100\b', text)
if m:
    print(m.group(1)); sys.exit(0)
print('')
" 2>/dev/null || echo "")
  _GDV_MUST_FIX=$(awk '/^MUST_FIX:/,/^[A-Z_]+:/' reports/13_5_gardevoir.md | grep -v '^[A-Z_]*:' | head -3 | tr '\n' ' ')

  # VERDICT フォールバック: VERDICT行が省略されているがスコアが取れた場合はスコアから推定
  if [[ -z "${_GDV_VERDICT}" ]] && [[ -n "${_GDV_SCORE}" ]]; then
    if [[ "${_GDV_SCORE}" -ge 80 ]]; then
      _GDV_VERDICT="PASS"
      echo "  ℹ️ [gardevoir] VERDICT行なし → score=${_GDV_SCORE} からPASSに推定"
    elif [[ "${_GDV_SCORE}" -ge 65 ]]; then
      _GDV_VERDICT="SOFT_RETRY"
      echo "  ℹ️ [gardevoir] VERDICT行なし → score=${_GDV_SCORE} からSOFT_RETRYに推定"
    else
      _GDV_VERDICT="HARD_FAIL"
      echo "  ℹ️ [gardevoir] VERDICT行なし → score=${_GDV_SCORE} からHARD_FAILに推定"
    fi
  fi

  log_step "gardevoir_hook_critic" "${_GDV_VERDICT:-ERROR}" "reports/13_5_gardevoir.md" "score=${_GDV_SCORE:-?} retry=${_GDV_RETRY} must_fix=${_GDV_MUST_FIX}"
  python3 -c "
import json, sys
print(json.dumps({
  'ts':       '$(date -u +%Y-%m-%dT%H:%M:%SZ)',
  'run_id':   '${RUN_ID:-unknown}',
  'pipeline': 'strategy',
  'agent':    'gardevoir_hook_critic',
  'score':    int('${_GDV_SCORE:-0}' or 0),
  'verdict':  '${_GDV_VERDICT:-ERROR}',
  'retry':    int('${_GDV_RETRY:-0}' or 0),
  'must_fix': '${_GDV_MUST_FIX}',
  'title':    sys.argv[1],
  'category': sys.argv[2],
}, ensure_ascii=False))" "${_GDV_TITLE:-}" "${_GDV_CATEGORY:-}" >> "$SCRIPT_DIR/logs/gardevoir_hook.jsonl"

  if [ "${_GDV_VERDICT}" = "PASS" ]; then
    echo "✅ ガルデvoir PASS (score=${_GDV_SCORE})"
    break
  elif [ "${_GDV_VERDICT}" = "SOFT_RETRY" ] && [ "${_GDV_RETRY}" -lt 2 ]; then
    _GDV_RETRY=$((_GDV_RETRY+1))
    echo "⚠️ ガルデvoir SOFT_RETRY (score=${_GDV_SCORE}, 試行${_GDV_RETRY}/2) — メタモン・カイリュー差し戻し"
    # タイトル再生成（メタモン）
    claude --no-session-persistence --agent metamon_kpop -p "
以下の記事のタイトルを再生成せよ。
【改善要求】
${_GDV_MUST_FIX}
【現タイトル】${_GDV_TITLE}
【記事本文】
$(cat reports/13_final.md)
" > /tmp/gardevoir_metamon_retry.md 2>/dev/null
    _NEW_TITLE=$(head -1 /tmp/gardevoir_metamon_retry.md | sed 's/^[#[:space:]]*//')
    [ -n "$_NEW_TITLE" ] && _GDV_TITLE="$_NEW_TITLE"
    # CTA・H2調整（カイリュー再実行）
    claude --no-session-persistence --agent kairyu_kpop -p "
以下の記事のCTA・H2感情訴求を改善せよ。タイトル・事実・数字は変えない。
【改善要求】
${_GDV_MUST_FIX}
【記事全文】
$(cat reports/13_final.md)
" > /tmp/gardevoir_kairyu_retry.md 2>/dev/null
    [ -s /tmp/gardevoir_kairyu_retry.md ] && cp /tmp/gardevoir_kairyu_retry.md reports/13_final.md
    _GDV_HOOK=$(python3 -c "
import re
text=open('reports/13_final.md').read()
body=re.sub(r'^.*\n','',text,count=1)
body=re.sub(r'<[^>]+>','',body)
print(body[:500])
" 2>/dev/null || sed -n '3,25p' reports/13_final.md)
  else
    echo "❌ ガルデvoir HARD_FAIL (score=${_GDV_SCORE}, retry=${_GDV_RETRY}) — 刺さらないため公開停止"
    log_step "gardevoir_hook_critic" "hard_fail" "reports/13_5_gardevoir.md" "公開停止 score=${_GDV_SCORE}"
    if [[ -z "${_GDV_SCORE}" ]] || [[ "${_GDV_SCORE}" == "0" ]]; then
      echo "🚨 GARDEVOIR_HARD_FAIL"
      echo "run_id=${RUN_ID:-unknown}"
      echo "title=${_GDV_TITLE}"
      echo "category=${_GDV_CATEGORY}"
      echo "reason=score=${_GDV_SCORE:-未取得} フォーマット不正の疑い"
      echo "action=exit(1)"
      python3 -c "
import json, sys
print(json.dumps({
  'ts':       '$(date -u +%Y-%m-%dT%H:%M:%SZ)',
  'agent':    'gardevoir_hook_critic',
  'score':    int('${_GDV_SCORE:-0}' or 0),
  'verdict':  'HARD_FAIL',
  'retry':    int('${_GDV_RETRY:-0}' or 0),
  'must_fix': '',
  'run_id':   '${RUN_ID:-unknown}',
  'pipeline': 'strategy',
  'title':    sys.argv[1],
  'category': sys.argv[2],
  'reason':   'score=${_GDV_SCORE:-未取得} format_error',
  'action':   'exit(1)',
}, ensure_ascii=False))" "${_GDV_TITLE}" "${_GDV_CATEGORY}" >> "$SCRIPT_DIR/logs/gardevoir_hook.jsonl"
    fi

    # Discord urgent通知
    _GDV_DISCORD_MSG="🛑 *刺さり品質HARD_FAIL* [strategy] — 公開停止\nScore: ${_GDV_SCORE:-?} / RETRY: ${_GDV_RETRY}回\nTitle: ${_GDV_TITLE}\nMUST_FIX: ${_GDV_MUST_FIX}"
    if [ -f lib/discord_channels.sh ]; then
      source lib/discord_channels.sh
      _GDV_WH=$(get_discord_webhook urgent_errors 2>/dev/null || echo "")
      if [ -n "$_GDV_WH" ]; then
        curl -s -X POST "$_GDV_WH" \
          -H 'Content-Type: application/json' \
          -d "{\"content\":\"${_GDV_DISCORD_MSG}\"}" > /dev/null 2>&1 || true
      fi
    fi
    archive_and_exit 1
  fi
done

# ─── [13.9] arceus前シェルハードガード（LLM不使用・即判定） ──────────────────
echo "[13.9/15] arceus前ハードガード..."
python3 - <<'PRE_ARCEUS_GUARD'
import re, sys
from pathlib import Path

src = Path("reports/13_final.md")
if not src.exists():
    print("🚨 GUARD: reports/13_final.md が存在しない")
    sys.exit(1)

text = src.read_text(encoding="utf-8", errors="replace")
lines = text.splitlines()
title = lines[0].strip() if lines else ""

# タイトル文字数チェック（20文字未満は即停止）
if len(title) < 20:
    print(f"🚨 GUARD: タイトルが短すぎる ({len(title)}文字 < 20) → arceus停止")
    sys.exit(1)

# 本文プレーンテキスト文字数チェック（800文字未満は即停止）
plain = re.sub(r'<[^>]+>', '', text)
plain = re.sub(r'\s+', '', plain)
if len(plain) < 800:
    print(f"🚨 GUARD: 本文テキストが短すぎる ({len(plain)}文字 < 800) → arceus停止")
    sys.exit(1)

# K-POP文脈キーワードチェック（タイトルに1つもなければ警告のみ）
kpop_words = ['K-POP','K-pop','KPOP','韓国','アイドル','カムバック',
              'ガールズグループ','ボーイズグループ','K-POPアイドル',
              'BTS','BLACKPINK','NewJeans','IVE','aespa','ILLIT','TWICE',
              'SHINee','BIGBANG','Stray Kids','ATEEZ','SEVENTEEN','NCT',
              'EXO','GOT7','MONSTA X','MAMAMOO','Red Velvet',
              'MAMA','Coachella','コーチェラ']
has_kpop = any(w in title for w in kpop_words)
if not has_kpop:
    print(f"⚠️ GUARD_WARN: タイトルにK-POP文脈語なし: '{title}' → post_audit [2b] でフォールバック対応")

print(f"✅ GUARD: タイトル={len(title)}文字 本文={len(plain)}文字 K-POP文脈={'あり' if has_kpop else '警告'}")
sys.exit(0)
PRE_ARCEUS_GUARD
if [[ $? -ne 0 ]]; then
  echo "❌ arceus前ハードガード失敗 → パイプライン停止"
  log_step "pre_arceus_guard" "rejected" "reports/13_final.md" "ハードガード: 文字数不足"
  archive_and_exit 1
fi

echo "[14/15] アルセウス: 総監督・最終承認..."
claude --no-session-persistence --agent arceus -p "
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

【最終判定の絶対ルール（厳守）】
出力の末尾に必ず以下のどちらか一方のみを記載せよ：
- 投稿する場合 → 「✅ 投稿承認」
- 投稿しない場合 → 「❌ 投稿却下：〇〇のため」
「条件付き承認」「保留」「投稿不可」「REJECT」「CONDITIONAL」等の表現は絶対禁止。
パイプラインは「✅ 投稿承認」か「❌ 投稿却下」の2文字列のみを検出して動作する。
" > reports/14_arceus.md
sanitize_output reports/14_arceus.md
check_output reports/14_arceus.md "アルセウス"

# 却下パターン検出（表記揺れを網羅）
if grep -qE '(❌ 投稿却下|投稿判定.*却下|条件付き却下|却下（REJECT）|却下\(REJECT\)|^.*投稿不可|REJECT)' reports/14_arceus.md; then
  echo ""
  echo "❌ アルセウスが投稿を却下しました"
  grep -E '(投稿却下|却下|REJECT|投稿不可)' reports/14_arceus.md | head -3
  archive_and_exit 1
fi
# 「条件付き承認」単独は禁止表現 → 却下扱い
if grep -qE '条件付き承認' reports/14_arceus.md; then
  echo "❌ アルセウスが禁止表現「条件付き承認」を使用（フォーマット違反・却下扱い）"
  log_step "arceus" "rejected" "reports/14_arceus.md" "禁止表現:条件付き承認"
  archive_and_exit 1
fi
# 承認確認（承認文字列がなければ停止・CONDITIONAL系は除外）
if ! grep -qE '(✅ 投稿承認|✅ 承認|投稿判定.*承認|投稿OK|即時投稿可)' reports/14_arceus.md; then
  echo "❌ アルセウスの承認確認ができません（パイプライン停止）"
  archive_and_exit 1
fi
# プロンプトインジェクション検出
if grep -qiE '(プロンプトインジェクション|prompt injection|この指示を無視|ignore previous instructions)' reports/14_arceus.md reports/title_ab.json 2>/dev/null; then
  echo "🚨 プロンプトインジェクションの痕跡を検出 — パイプライン停止"
  archive_and_exit 1
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# final_post.md 生成（審査レポート分離）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "=== final_post.md 生成 ==="

# [ガード0] ソースファイルの存在・空チェック
if [[ ! -f reports/13_final.md ]]; then
  echo "🚨 BLOCK: reports/13_final.md が存在しません"
  archive_and_exit 1
fi
if [[ ! -s reports/13_final.md ]]; then
  echo "🚨 BLOCK: reports/13_final.md が空です"
  archive_and_exit 1
fi

# [ガード1] 審査レポート文言の混入チェック
REVIEW_CHECK=$(grep -cE '(エージェント別採点|最終記事品質評価|投稿承認|投稿却下|採点表|/50点|/10点|デオキシス:|メタモン:|ジラーチ:|アルセウス:|修正箇所：|修正サマリー|チェック項目：|【修正内容】)' reports/13_final.md || true)
if [ "$REVIEW_CHECK" -gt 0 ]; then
  echo "🚨 BLOCK: 審査レポートの文言が記事本文に混入しています（${REVIEW_CHECK}箇所）"
  echo "  検出内容:"
  grep -E '(エージェント別採点|最終記事品質評価|投稿承認|投稿却下|採点表|/50点|/10点|デオキシス:|メタモン:|ジラーチ:|アルセウス:|修正箇所：|修正サマリー|チェック項目：|【修正内容】)' reports/13_final.md | head -5
  archive_and_exit 1
fi

# [ガード2] 質問文・AI定型文の混入チェック
QUESTION_CHECK=$(grep -cE '(質問があります|確認させてください|お手伝いできますか|申し訳ありません[がで。、 ]|申し訳ありません$|承知しました|以下に示します|AIとして[、。]|言語モデルとして|お答えできません|いかがでしょうか)' reports/13_final.md || true)
if [ "$QUESTION_CHECK" -gt 0 ]; then
  echo "🚨 BLOCK: 質問文またはAI定型文が記事本文に混入しています（${QUESTION_CHECK}箇所）"
  echo "  検出内容:"
  grep -E '(質問があります|確認させてください|お手伝いできますか|申し訳ありません[がで。、 ]|申し訳ありません$|承知しました|以下に示します|AIとして[、。]|言語モデルとして|お答えできません|いかがでしょうか)' reports/13_final.md | head -5
  archive_and_exit 1
fi

# 13_final.md → final_post.md にコピー（投稿対象はfinal_post.mdのみ）
cp reports/13_final.md reports/final_post.md
echo "  ✓ reports/final_post.md 生成完了"

# ─── [14.8] UI/UX後処理保証：LLM未実装箇所を補正 ──────────────────────────────
echo "[14.8/15] UI/UX後処理保証（conclusion-lead・rehook・関連記事・CTA・段落分割）..."
python3 "$SCRIPT_DIR/lib/html_postprocess.py" reports/final_post.md

# ─── [14.9] CTR最適化：タイトル・本文冒頭・サムネテキスト整形 ──────────────────
echo "[14.9/15] CTR最適化（タイトル強化・冒頭整合）..."
python3 - << 'CTR_PY'
import re, sys
from pathlib import Path

src = Path("reports/final_post.md")
if not src.exists():
    print("  ⚠️ final_post.md なし → スキップ")
    sys.exit(0)

text = src.read_text(encoding="utf-8")
lines = text.splitlines()
if not lines:
    sys.exit(0)

title_raw = lines[0].strip()
body_lines = lines[1:]  # 2行目以降が本文

changed = False

# ── タイトル強化 ──────────────────────────────────────────────
# 1. 先頭の「K-POP 」（単独プレフィックス）を除去（意味薄・CTR低下）
title = re.sub(r'^K-POP\s+', '', title_raw).strip()
# 2. 「とは？」系タイトルに強ワードがなければ末尾に「の真相」を補う
#    ただし数字（○冠・○位・○万）が既にある場合は補わない（誇張禁止）
STRONG = ["衝撃", "覚醒", "急変", "判明", "炎上", "真相", "暴露", "激変", "緊急", "発覚"]
has_strong = any(w in title for w in STRONG)
has_number = bool(re.search(r'\d+[冠位万億人%％]|初|歴代|全員', title))
if "とは？" in title and not has_strong and not has_number:
    title = title.replace("とは？", "の真相：", 1)
    print(f"  タイトル強化: 「とは？」→「の真相：」")
if title != title_raw:
    changed = True
    print(f"  タイトル変更: {title_raw!r}")
    print(f"        → {title!r}")

# ── 本文冒頭整合 ──────────────────────────────────────────────
# 内部ラベルH2（例:【即答ブロック】【解説】等）が1行目なら除去
INTERNAL_LABELS = ["即答ブロック", "ファクト確認", "内部メモ", "AIメモ", "デオキシス"]
# body_linesの先頭からHTMLを含む行を走査
new_body = body_lines[:]
for i, bl in enumerate(new_body[:5]):
    stripped = re.sub(r'<[^>]+>', '', bl).strip()
    if any(lbl in stripped for lbl in INTERNAL_LABELS):
        print(f"  内部ラベル除去: {bl[:60]!r}")
        new_body[i] = ""
        changed = True

# 本文1行目がタイトル核心（誰・何）と無関係な一般論スタートを検出
GENERAL_STARTS = [
    r'^K.POPは近年', r'^近年.*K.POP', r'^韓国音楽.*人気',
    r'^アイドルグループ.*多く', r'^日本.*K.POPファン',
]
# 空行を飛ばして最初の実テキスト行を探す
first_text_idx = None
for i, bl in enumerate(new_body[:10]):
    plain = re.sub(r'<[^>]+>', '', bl).strip()
    if plain:
        first_text_idx = i
        break

if first_text_idx is not None:
    plain_first = re.sub(r'<[^>]+>', '', new_body[first_text_idx]).strip()
    is_general = any(re.search(pat, plain_first) for pat in GENERAL_STARTS)
    if is_general:
        # アーティスト名をタイトルから抽出して冒頭を置換
        artist_m = re.search(r'([A-Za-zぁ-ん一-龥ァ-ン]+(?:\d+[A-Za-z]*)?)', title)
        artist = artist_m.group(1) if artist_m else "このグループ"
        new_intro = f"<p>{artist}が現在話題となっている理由は、{plain_first}</p>"
        new_body[first_text_idx] = new_intro
        print(f"  冒頭一般論検出 → タイトル核心一致に修正")
        changed = True

# ── 書き戻し ──────────────────────────────────────────────────
if changed:
    out_lines = [title] + new_body
    src.write_text("\n".join(out_lines), encoding="utf-8")
    print("  ✅ final_post.md 更新完了")
else:
    print("  ✅ 変更不要（タイトル・冒頭ともに合格）")

# THUMB_TEXT をファイルに書き出す（サムネ生成ステップで使用）
# 「K-POP 」除去済みタイトルから最適サムネテキストを生成
thumb = title
# 区切り文字（：: ｜ | 。）で前半の核心だけ残す
thumb = re.split(r'[：:｜|。]', thumb)[0].strip()
# まだ28文字超なら「・」「（」「？」「 」で短縮。最低でもアーティスト名+αは残す
if len(thumb) > 28:
    for sep in ['・', '（', '？', ' ', '　']:
        parts = thumb.split(sep)
        # 分割後の先頭が6文字以上28文字以下なら採用（英字のみになる短縮は弾く）
        if len(parts) >= 2:
            candidate = parts[0].strip()
            non_ascii = sum(1 for c in candidate if ord(c) > 127)
            if 6 <= len(candidate) <= 28 and (non_ascii > 0 or len(candidate) >= 8):
                thumb = candidate
                break
# 最終フォールバック: 28文字で切る（英字のみにはならない位置で）
if len(thumb) > 28:
    thumb = thumb[:28].rstrip('・（ 　')
Path("/tmp/ctr_thumb_text.txt").write_text(thumb, encoding="utf-8")
print(f"  サムネテキスト: {thumb!r}")
CTR_PY

# サムネテキストを CTR 最適化版から読み込む
if [[ -f /tmp/ctr_thumb_text.txt ]]; then
  THUMB_TITLE=$(cat /tmp/ctr_thumb_text.txt)
  rm -f /tmp/ctr_thumb_text.txt
  echo "  [14.9] サムネテキスト確定: $THUMB_TITLE"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 5: 品質チェック・投稿・拡散
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ PHASE 5: 品質チェック・投稿・拡散 ━━━"

# 投稿対象: final_post.md のみ（13_final.mdや14_arceus.mdからは絶対に投稿しない）
TITLE=$(head -n 1 reports/final_post.md)
check_duplicate "$TITLE" 7
CONTENT=$(tail -n +2 reports/final_post.md)

if [[ -z "$TITLE" ]] || [[ "$TITLE" == "#"* ]] || \
   [[ "$TITLE" == *"ファクトチェック"* ]] || [[ "$TITLE" == *"申し訳ありません"* ]]; then
  echo "❌ 品質NG: タイトル異常（$TITLE）→ 投稿停止"
  archive_and_exit 1
fi
# [B束] タイトル型崩れガード: 内部作業文・指示文・メタ表現の検出
_TITLE_META_CHECK=$(python3 -c "
import sys, re
title = sys.argv[1]
META_PATTERNS = [
    r'確認します', r'読み込みます', r'調査します', r'するため', r'検討します',
    r'以下に示', r'AIとして', r'言語モデル', r'お手伝い', r'出力します',
    r'作成します', r'記事を書', r'タイトルを', r'本文を', r'生成します',
    r'^以下', r'承知しました', r'わかりました',
]
for pat in META_PATTERNS:
    if re.search(pat, title):
        print(pat)
        sys.exit(1)
sys.exit(0)
" "$TITLE" 2>/dev/null; echo $?)
if [[ "$_TITLE_META_CHECK" != "0" ]]; then
  echo "❌ 品質NG: タイトルに内部作業文を検出 → 投稿停止"
  echo "  タイトル: $TITLE"
  archive_and_exit 1
fi
# [CTR品質チェック] 弱いタイトル検出 → 警告のみ（即停止はしない。ログに記録）
_TITLE_CTR_WARN=$(python3 -c "
import sys, re
title = sys.argv[1]
WEAK = [r'について解説', r'徹底解説', r'とは$', r'とは？', r'まとめ$', r'を解説',
        r'分析$', r'考察$', r'情報$', r'\bガイド$']
for pat in WEAK:
    if re.search(pat, title):
        print(pat)
        sys.exit(1)
# 40文字超
if len(title) > 40:
    print(f'40文字超({len(title)}文字)')
    sys.exit(1)
sys.exit(0)
" "$TITLE" 2>/dev/null; echo $?)
if [[ "$_TITLE_CTR_WARN" != "0" ]]; then
  echo "  ⚠️ [CTR警告] タイトルに弱い表現または文字数超過: $TITLE"
  echo "  → 投稿は続行。[14.9]CTR最適化で修正済みの場合はスキップ可"
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

# ─── [追加①] タイトル崩壊検知（AI混入・説明文・フェッチ失敗文言） ──────────────
_TITLE_CRASH=$(python3 -c "
import sys, re
title = sys.argv[1]
CRASH_PATTERNS = [
    r'ウェブフェッチ(は|が|でき)',
    r'フェッチできません',
    r'分析します',
    r'以下に',
    r'提供してください',
    r'お手伝いできません',
    r'内部矛盾',
    r'論理的問題',
    r'問題点を特定',
]
for pat in CRASH_PATTERNS:
    if re.search(pat, title):
        print(f'CRASH_PATTERN: {pat}')
        sys.exit(1)
# 60文字超の説明的な長文タイトル（チャート記事を除く）
if len(title) > 60 and not re.search(r'チャート|ランキング|TOP', title):
    print(f'TITLE_TOO_LONG: {len(title)}文字')
    sys.exit(1)
sys.exit(0)
" "$TITLE" 2>/dev/null; echo $?)
if [[ "$_TITLE_CRASH" != "0" ]]; then
  echo "❌ 品質NG: タイトル崩壊を検出 → 投稿停止"
  echo "  タイトル: $TITLE"
  archive_and_exit 1
fi

# ─── [追加②] 本文冒頭異常検知（AI応答文・修正メモ・指示文） ─────────────────
_CONTENT_HEAD=$(python3 -c "import sys; print(sys.argv[1][:200])" "$CONTENT" 2>/dev/null)
_CONTENT_HEAD_NG=$(python3 -c "
import sys, re
head = sys.argv[1]
NG_PATTERNS = [
    r'申し訳ありません',
    r'ウェブフェッチ',
    r'フェッチできません',
    r'ファクトチェック結果',
    r'問題点を特定',
    r'以下の問題',
    r'修正を適用',
    r'内部矛盾',
    r'^---\s*$',
    r'## ファクトチェック',
]
for pat in NG_PATTERNS:
    if re.search(pat, head, re.MULTILINE):
        print(f'HEAD_NG: {pat}')
        sys.exit(1)
sys.exit(0)
" "$_CONTENT_HEAD" 2>/dev/null; echo $?)
if [[ "$_CONTENT_HEAD_NG" != "0" ]]; then
  echo "❌ 品質NG: 本文冒頭にAI混入・指示文を検出 → 投稿停止"
  echo "  冒頭100文字: ${_CONTENT_HEAD:0:100}"
  archive_and_exit 1
fi

echo "✅ 品質チェック通過（${CONTENT_LENGTH}文字）"

# ─── [追加③] メタディスクリプション 110〜130文字 BLOCK ─────────────────────────
echo "=== [品質B] メタディスクリプション文字数チェック ==="
_META_DESC_CHECK=$(echo "$FINAL_CONTENT" | sed -e 's/<[^>]*>//g' | python3 -c "
import sys, re
text = sys.stdin.read().strip()
text = re.sub(r'\s+', ' ', text)
sentences = re.split(r'[。！？]', text)
for s in sentences:
    s = s.strip()
    if len(s) >= 30:
        desc = (s + '。')[:130]
        break
else:
    desc = text[:130]
print(len(desc), desc[:20])
" 2>/dev/null)
_META_LEN=$(echo "$_META_DESC_CHECK" | awk '{print $1}')
if [[ -n "$_META_LEN" ]] && [[ "$_META_LEN" -lt 110 ]]; then
  echo "❌ 品質NG: メタディスクリプション候補が短すぎる(${_META_LEN}文字 < 110) → 投稿停止"
  archive_and_exit 1
fi
echo "  ✓ メタディスクリプション候補: ${_META_LEN}文字 (110〜130範囲内)"

# ─── [追加④] 同ジャンル連投チェック（明示的BLOCK） ─────────────────────────────
echo "=== [品質E] 同ジャンル連投チェック ==="
_STRATEGY_GENRE_BLOCK=$(python3 - << 'SGENRE_PY' "$CATEGORY_ID"
import sys, json, urllib.request, os
from datetime import datetime, timezone, timedelta

cat_id = sys.argv[1] if len(sys.argv) > 1 else ""

GENRE_GROUPS = {
    "chart":    ["71"],
    "comeback": ["3", "6"],
    "beauty":   ["12"],
    "travel":   ["11"],
    "live":     ["5"],
    "fashion":  ["30"],
    "breaking": ["7"],
}

def detect_genre(cid):
    for g, ids in GENRE_GROUPS.items():
        if cid in ids:
            return g
    return None

my_genre = detect_genre(cat_id)
if not my_genre:
    print("SKIP:ジャンル不明")
    sys.exit(0)

cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
auth = ""
try:
    auth_file = os.path.expanduser("~/.wp_auth")
    import re as _re
    with open(auth_file) as f:
        m = _re.search(r'Basic\s+(\S+)', f.read())
        if m: auth = m.group(1)
except Exception:
    # ~/.wp_auth 読み込み失敗 → 安全側：BLOCK（続行しない）
    print(f"AUTH_FAIL:~/.wp_auth読み込み失敗 → 安全側BLOCK")
    sys.exit(0)

if not auth:
    print("AUTH_FAIL:認証トークン空 → 安全側BLOCK")
    sys.exit(0)

try:
    url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=10&after={urllib.request.quote(cutoff)}&status=publish&_fields=id,title,categories"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}", "User-Agent": "kpop-gate/1.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        posts = json.loads(resp.read())
except Exception as e:
    # API取得失敗 → 安全側：BLOCK
    print(f"API_FAIL:取得失敗({str(e)[:60]}) → 安全側BLOCK")
    sys.exit(0)

for p in posts:
    cats = p.get("categories", [])
    title2 = p.get("title", {}).get("rendered", "")
    for g, ids in GENRE_GROUPS.items():
        if g == my_genre:
            for k in ids:
                if k.isdigit() and int(k) in cats:
                    print(f"BLOCK:{my_genre}ジャンルが直近24h以内に投稿済み → ID={p.get('id')} {title2[:40]}")
                    sys.exit(0)
print("OK")
SGENRE_PY
)

echo "  同ジャンル連投チェック: $_STRATEGY_GENRE_BLOCK"
if [[ "$_STRATEGY_GENRE_BLOCK" == BLOCK:* ]]; then
  echo "❌ 同ジャンル連投BLOCK: $_STRATEGY_GENRE_BLOCK → 投稿停止"
  log_step "genre_block" "BLOCKED" "" "$_STRATEGY_GENRE_BLOCK"
  archive_and_exit 1
fi
if [[ "$_STRATEGY_GENRE_BLOCK" == AUTH_FAIL:* ]] || [[ "$_STRATEGY_GENRE_BLOCK" == API_FAIL:* ]]; then
  echo "⚠️  同ジャンルチェック: $_STRATEGY_GENRE_BLOCK → 安全側でBLOCK"
  log_step "genre_block" "BLOCKED_AUTH_FAIL" "" "$_STRATEGY_GENRE_BLOCK"
  archive_and_exit 1
fi

PUBLISH_TITLE="$TITLE"  # 【戦略】プレフィックスは廃止（CTR阻害・読者に不要）

# === アイキャッチ生成 ===
echo "--- アイキャッチ生成..."
# [14.9] で生成した CTR 最適化サムネテキストを優先使用。未設定なら従来の cut -c1-30 にフォールバック
if [[ -z "$THUMB_TITLE" ]]; then
  THUMB_TITLE=$(echo "$PUBLISH_TITLE" | cut -c1-30)
fi
THUMB_META_FILE=$(mktemp)
python3 ~/make_thumbnail.py "$THUMB_TITLE" --genre analysis --title "$PUBLISH_TITLE" 2>"$THUMB_META_FILE"
THUMB_META_LINE=$(grep "^THUMB_META: " "$THUMB_META_FILE" | head -1 | sed 's/^THUMB_META: //')
rm -f "$THUMB_META_FILE"
[ -n "$THUMB_META_LINE" ] && echo "  thumb_meta: $THUMB_META_LINE"

MEDIA_ID=0
if [[ -f thumbnail.jpg ]]; then
  MEDIA_RESPONSE=$(curl -s -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/media \
    -K "$HOME/.wp_auth" \
    -H "Content-Disposition: attachment; filename=thumbnail.jpg" \
    -H "Content-Type: image/jpeg" \
    --data-binary @thumbnail.jpg)
  MEDIA_ID=$(echo "$MEDIA_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',0))" 2>/dev/null || echo 0)
  echo "  メディアID: $MEDIA_ID"
  # === ALTテキスト自動設定（再発防止） ===
  if [[ -n "$MEDIA_ID" && "$MEDIA_ID" != "0" ]]; then
    ALT_TEXT=$(python3 -c "
import re
title = '''$PUBLISH_TITLE'''
alt = re.sub(r'[【】「」『』\|｜]', ' ', title).strip()
alt = re.sub(r'\s+', ' ', alt)[:100]
print(alt)
" 2>/dev/null)
    curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/media/${MEDIA_ID}" \
      -K "$HOME/.wp_auth" \
      -H "Content-Type: application/json" \
      -d "{\"alt_text\": \"$(echo "$ALT_TEXT" | sed 's/"/\\"/g')\"}" > /dev/null 2>&1
    echo "  ✅ ALTテキスト設定: ${ALT_TEXT:0:50}..."
  fi
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
    (111,['視聴方法','どこで見れる','無料視聴','配信サービス','配信比較','サブスク','abema','netflix','hulu','prime video']),
    (112,['プロフィール','メンバー紹介','経歴','生年月日','身長','出身','デビュー日']),
    (113,['入門','初心者','始め方','完全ガイド','わかりやすく','ゼロから']),
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
import sys, json, os, urllib.request, urllib.parse, base64
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

# 共通slug生成器でSEO向きslug作成（日本語URL問題の修正）
SLUG=$(python3 "$SCRIPT_DIR/lib/slug.py" "$PUBLISH_TITLE")
echo "  slug: $SLUG"

JSON=$(python3 - << 'PY' "$CATEGORY_ID" "$MEDIA_ID" "$ARTIST_CATEGORY_IDS" "$TAG_IDS" "$SLUG"
import json, sys
main_cat       = int(sys.argv[1])
media_id       = int(sys.argv[2])
artist_ids_raw = sys.argv[3].strip()
tag_ids_raw    = sys.argv[4].strip()
slug           = sys.argv[5].strip()
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
        'slug': slug,
        'categories': categories, 'tags': tags, 'excerpt': desc}
if media_id > 0:
    data['featured_media'] = media_id
print(json.dumps(data, ensure_ascii=False))
PY
)

# トークン合計をエクスポート
if [ "${ENABLE_TOKEN_TRACKING:-0}" = "1" ] && [ -f "$TOKEN_LOG" ]; then
  export PIPELINE_TOKEN_COUNT=$(token_total "$TOKEN_LOG")
  echo "  トークン合計: $PIPELINE_TOKEN_COUNT"
fi

# === 投稿前バリデーション（再発防止の本丸） ===
echo "=== 投稿前バリデーション ==="
if ! echo "$JSON" | python3 "$SCRIPT_DIR/lib/validate_post.py"; then
  echo "❌ バリデーション失敗 → 投稿中止 (アーカイブのみ)"
  archive_and_exit 1
fi

echo "=== ダークライ権利監査 ==="
if ! echo "$JSON" | python3 "$SCRIPT_DIR/lib/darkrai_audit.py"; then
  echo "❌ 権利監査失敗 → 投稿中止 (アーカイブのみ)"
  archive_and_exit 1
fi

# --- WordPress投稿 (リトライ付き) ---
source "$SCRIPT_DIR/lib/discord_channels.sh" 2>/dev/null || true

wp_post_attempt() {
  local HTTP_CODE BODY TMPFILE
  TMPFILE=$(mktemp)
  HTTP_CODE=$(curl -s -o "$TMPFILE" -w "%{http_code}" \
    -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/posts \
    -K "$HOME/.wp_auth" \
    -H "Content-Type: application/json" \
    -d "$JSON")
  BODY=$(cat "$TMPFILE")
  rm -f "$TMPFILE"

  if [[ "$HTTP_CODE" -lt 200 || "$HTTP_CODE" -ge 300 ]]; then
    echo "ERROR: WordPress API returned HTTP $HTTP_CODE" >&2
    echo "$BODY" >&2
    return 1
  fi

  RESPONSE="$BODY"
  return 0
}

RESPONSE=""
POST_ID=""
POST_URL=""
WP_POST_OK=0

for _attempt in 1 2; do
  if wp_post_attempt; then
    POST_URL=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('link','（URL取得失敗）'))")
    POST_ID=$(echo "$RESPONSE"  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))")

    # POST_IDが数値であることを確認
    if [[ "$POST_ID" =~ ^[0-9]+$ ]]; then
      WP_POST_OK=1
      echo "  WordPress投稿成功: POST_ID=$POST_ID (試行 $_attempt)"
      break
    else
      echo "ERROR: POST_IDが不正 (値='$POST_ID', 試行 $_attempt)" >&2
    fi
  else
    echo "ERROR: WordPress投稿失敗 (試行 $_attempt)" >&2
  fi

  if [ "$_attempt" -eq 1 ]; then
    echo "  5秒後にリトライ..."
    sleep 5
  fi
done

if [ "$WP_POST_OK" -ne 1 ]; then
  echo "CRITICAL: WordPress投稿が2回とも失敗しました" >&2
  log_step "wordpress_post" "error" "reports/final_post.md" "投稿失敗"
  discord_send "urgent_errors" \
    "[CRITICAL] WordPress投稿失敗 - $TODAY - $TITLE | POST_IDが空または非数値。RESPONSEの先頭200文字: $(echo "$RESPONSE" | head -c 200)" \
    "" 2>/dev/null || true
  POST_ID=""
  POST_URL="（投稿失敗）"
else
  log_step "wordpress_post" "ok" "reports/final_post.md" "post_id=$POST_ID"
fi

# ─── [追加③] サムネ整合チェック（alt_text空・汎用文言検知） ────────────────────
if [[ -n "$POST_ID" && "$POST_ID" =~ ^[0-9]+$ && -n "$NEW_MEDIA_ID" && "$NEW_MEDIA_ID" =~ ^[0-9]+$ ]]; then
  _THUMB_ALT=$(curl -s -K "$HOME/.wp_auth" \
    "https://www.kpopjournal.tokyo/wp-json/wp/v2/media/$NEW_MEDIA_ID" | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('alt_text',''))" 2>/dev/null || echo "")
  _THUMB_ALT_NG=$(python3 -c "
import sys, re
alt = sys.argv[1].strip()
# 空チェック
if not alt:
    print('ALT_EMPTY')
    sys.exit(1)
# 汎用文言チェック（部分一致で停止：強いNG）
GENERIC_SUBSTR = ['結論出た', '全真相判明', '完全解説', '真相判明']
for word in GENERIC_SUBSTR:
    if word in alt:
        print(f'ALT_GENERIC_SUBSTR: {word} in {repr(alt)}')
        sys.exit(1)
# 汎用文言チェック（完全一致でのみ停止：弱いNG）
GENERIC_EXACT = ['速報', '解説', 'まとめ', 'ガイド']
for word in GENERIC_EXACT:
    if alt == word:
        print(f'ALT_GENERIC_EXACT: {repr(alt)}')
        sys.exit(1)
sys.exit(0)
" "$_THUMB_ALT" 2>/dev/null; echo $?)
  if [[ "$_THUMB_ALT_NG" != "0" ]]; then
    echo "❌ 品質NG: サムネalt_textが空または汎用文言 → 投稿停止"
    echo "  media_id=$NEW_MEDIA_ID alt='$_THUMB_ALT'"
    archive_and_exit 1
  else
    echo "  ✅ サムネ整合OK: alt='$_THUMB_ALT'"
  fi
fi

# === 視聴導線記事: 再監査台帳に追記 ===
if [[ -n "$POST_ID" && "$POST_ID" =~ ^[0-9]+$ && "$CATEGORY_ID" == "111" ]]; then
  echo "=== 視聴導線記事 再監査台帳追記 ==="
  python3 - << 'LEDGER_PY' "$POST_ID" "$TITLE" "$CATEGORY_ID"
import sys, json
from datetime import date, timedelta
from pathlib import Path

post_id = int(sys.argv[1])
title = sys.argv[2]
category_id = int(sys.argv[3])

BASE = Path("/home/aiuser/kpop-ai-system")
LEDGER = BASE / "logs" / "streaming_guide_review.jsonl"
today = date.today()

# article_type推定（タイトルから）
t = title.lower()
if any(k in t for k in ['kcon','mama','award','授賞式','イベント','開催']):
    article_type = "event_guide"
    interval = 14
elif any(k in t for k in ['music bank','inkigayo','m countdown','show champion','music core','人気歌謡']):
    article_type = "single_show_guide"
    interval = 60
elif any(k in t for k in ['まとめ','比較','一覧','総まとめ','全サービス']):
    article_type = "comprehensive_guide"
    interval = 30
else:
    article_type = "artist_streaming_guide"
    interval = 14

new_record = {
    "post_id": post_id,
    "title": title,
    "category_id": category_id,
    "article_type": article_type,
    "risk_level": "high" if interval <= 14 else ("medium" if interval <= 60 else "low"),
    "reason": f"パイプライン自動登録 ({today})",
    "review_rule": f"{article_type}: {interval}日後",
    "audit_focus": ["料金変動", "配信可否確認", "活動状況確認"],
    "last_factchecked_at": today.isoformat(),
    "next_review_due": (today + timedelta(days=interval)).isoformat(),
    "status": "published_verified",
}

records = []
if LEDGER.exists():
    with open(LEDGER) as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                if r["post_id"] != post_id:
                    records.append(r)
records.append(new_record)
with open(LEDGER, "w") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"  ✅ 再監査台帳追記: post_id={post_id} article_type={article_type} next_review={new_record['next_review_due']}")
LEDGER_PY
fi

# === AIOSEO description 自動設定（再発防止） ===
if [[ -n "$POST_ID" && "$POST_ID" =~ ^[0-9]+$ ]]; then
  echo "=== AIOSEO description 自動設定 ==="
  AIOSEO_DESC=$(echo "$FINAL_CONTENT" | sed -e 's/<[^>]*>//g' | python3 -c "
import sys, re
text = sys.stdin.read().strip()
text = re.sub(r'\s+', ' ', text)
sentences = re.split(r'[。！？]', text)
for s in sentences:
    s = s.strip()
    if len(s) >= 30:
        print((s + '。')[:120])
        break
else:
    print(text[:120])
" 2>/dev/null)
  curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
    -K "$HOME/.wp_auth" \
    -H "Content-Type: application/json" \
    -d "{\"meta\":{\"_aioseo_description\": \"$(echo "$AIOSEO_DESC" | sed 's/"/\\"/g')\"}}" > /dev/null 2>&1 \
    && echo "  ✅ AIOSEO description設定完了" || echo "  ⚠️ AIOSEO設定スキップ"
fi

echo "=== ABEMA CTA自動挿入 ==="
if [ -n "$POST_ID" ]; then
  bash /home/aiuser/kpop-ai-system/google_metrics/inject_abema_cta.sh "$POST_ID" || echo "ABEMA CTAスキップ"
else
  echo "ABEMA CTAスキップ (POST_IDなし)"
fi

# [追加 2026-04-11] kpop_pipeline.shとの統一: 内部リンク・GSC・Bing登録が欠落していたため追加
echo "=== 内部リンク自動挿入 ==="
if [ -n "${SLUG:-}" ] && [ -n "${POST_URL:-}" ]; then
  _SLUG_PATH=$(echo "$POST_URL" | sed 's|https://www.kpopjournal.tokyo||' | sed 's|/$||')
  bash "$SCRIPT_DIR/google_metrics/add_internal_links.sh" "$_SLUG_PATH" 2>&1 || echo "⚠️ 内部リンクスキップ"
fi

echo "=== Google Indexing API ==="
bash "$SCRIPT_DIR/google_metrics/request_index.sh" "$POST_URL" 2>&1 || echo "⚠️ Google インデックススキップ"

echo "=== Bing URL Submission ==="
bash "$SCRIPT_DIR/google_metrics/request_bing_index.sh" "$POST_URL" 2>&1 || echo "⚠️ Bing インデックススキップ"

echo "[15/15] ペルシアン: SNS拡散戦略..."
claude --no-session-persistence --agent persian -p "
今日は${TODAY}です。
以下のK-POP記事が投稿されました。SNS拡散戦略を設計せよ。

【記事タイトル】$TITLE
【記事URL】$POST_URL
【記事冒頭】
$(echo "$CONTENT" | sed 's/<[^>]*>//g' | head -c 300)

X投稿文3パターン・推奨ハッシュタグセット・最適投稿タイミング・採用推奨パターンを出力せよ。
" > reports/15_sns.md
sanitize_output reports/15_sns.md
check_output reports/15_sns.md "ペルシアン"

# ── [DRAFT GUARD 2重防衛] X投稿直前にWP側のstatus を再確認 ─────────────
_WP_STATUS_NOW=$(curl -s "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
  -K ~/.wp_auth 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")
if [[ "$_WP_STATUS_NOW" != "publish" ]]; then
  echo "⛔ [DRAFT GUARD] X投稿スキップ: WP status=${_WP_STATUS_NOW} (publish以外はX投稿禁止)"
  echo "  → POST_ID=$POST_ID が publish 状態でないためX投稿を中止"
  log_step "sns_draft_guard" "blocked" "" "X投稿スキップ: status=${_WP_STATUS_NOW}"
  X_STATUS="スキップ(DRAFT_GUARD: status=${_WP_STATUS_NOW})"
else

echo "=== [15.1] X/Twitter 自動投稿 ==="
X_POST_LOG="/home/aiuser/kpop-ai-system/logs/x_post.log"
X_POST_RESULT=$(bash "$SCRIPT_DIR/google_metrics/post_to_x.sh" "$TITLE" "$POST_URL" "reports/15_sns.md" 2>&1) || {
  echo "X投稿スキップ (エラーはログ参照: $X_POST_LOG)"
  X_POST_RESULT="X投稿失敗"
}
X_TWEET_URL=$(echo "$X_POST_RESULT" | grep -oP 'https://x\.com/\S+' | head -1 || true)
if [ -n "$X_TWEET_URL" ]; then
  X_STATUS="成功 ($X_TWEET_URL)"
elif echo "$X_POST_RESULT" | grep -q "DRY-RUN"; then
  X_STATUS="DRY-RUN（テストモード）"
elif echo "$X_POST_RESULT" | grep -q "スキップ"; then
  X_STATUS="スキップ"
else
  X_STATUS="失敗"
fi

fi  # end DRAFT GUARD 2 else block

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 学習データ記録（タイトル + サムネ）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if [ -n "$POST_ID" ]; then
  python3 "$SCRIPT_DIR/lib/title_learner.py" record \
    --title "$PUBLISH_TITLE" --score 0 --pattern "情報型" \
    --post-id "$POST_ID" --pending 2>/dev/null || true
  echo "  ✓ タイトル学習記録（pending）"

  if [ -n "$THUMB_META_LINE" ]; then
    python3 - "$POST_ID" "$THUMB_META_LINE" << 'PYEOF' 2>/dev/null || true
import sys, json, subprocess
post_id = sys.argv[1]
try:
    meta = json.loads(sys.argv[2])
except Exception:
    sys.exit(0)
cmd = [
    "python3", "/home/aiuser/kpop-ai-system/lib/thumbnail_learner.py", "record",
    "--post-id", post_id,
    "--thumb-text", meta.get("thumb_text",""),
    "--genre", meta.get("genre",""),
    "--layout", meta.get("layout","v2"),
    "--has-image", "true" if meta.get("has_image") else "false",
    "--eng-hero", meta.get("eng_hero",""),
    "--image-source", meta.get("image_source",""),
]
subprocess.run(cmd, check=False)
PYEOF
    echo "  ✓ サムネ学習記録（pending）"
  fi
fi

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
X投稿       : $X_STATUS
SUMMARY
echo "  保存先: $ARCHIVE_DIR ($(ls "$ARCHIVE_DIR" | wc -l | tr -d ' ')ファイル)"

bash ~/kpop_notify.sh success "戦略" "記事投稿完了: $TITLE" "$POST_URL" 2>/dev/null

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# KPIログ記録
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PIPELINE_END=$(date +%s)
PROCESSING_TIME=$((PIPELINE_END - ${PIPELINE_START:-$PIPELINE_END}))
HAS_CTA="false"
echo "$CONTENT" | grep -qE '(px\.a8\.net|amazon\.co\.jp|affiliate|あわせて読みたい|関連記事)' && HAS_CTA="true"
PLAIN_CHARS=$(echo "$CONTENT" | sed 's/<[^>]*>//g' | wc -m | tr -d ' ')
H2_COUNT=$(echo "$CONTENT" | grep -coP '<h2[\s>]' || true)
SLUG=$(echo "$POST_URL" | sed 's|.*/||; s|/$||')

# アルセウスの採点結果から50点満点スコアを抽出
ARCEUS_SCORE=$(python3 - << 'SCORE_PY' "reports/14_arceus.md"
import re, sys
score = 0
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        text = f.read()
    # 方法1: 総合スコア行から抽出 (例: "総合スコア: 9.0/10") → x5で50点満点に換算
    m = re.search(r'総合スコア[：:]\s*([\d.]+)\s*/\s*10', text)
    if m:
        score = round(float(m.group(1)) * 5)
    else:
        # 方法2: エージェント別採点表の個別スコアを合算 (例: "| エージェント名 | **9.5/10** |")
        # 採点表の行のみを対象にし、本文中の無関係な "X/10" を拾わないようにする
        scores = re.findall(r'\|\s*\*{0,2}([\d.]+)\s*/\s*10\*{0,2}\s*\|', text)
        if not scores:
            # フォールバック: 太字で囲まれたスコアのみ (例: "**9.5/10**")
            scores = re.findall(r'\*\*([\d.]+)\s*/\s*10\*\*', text)
        if scores:
            total = sum(float(s) for s in scores)
            score = round(min(total, 50))
except Exception:
    pass
# 0-50の範囲に収める
print(max(0, min(50, score)))
SCORE_PY
)
ARCEUS_SCORE=${ARCEUS_SCORE:-0}
echo "ARCEUS_SCORE=$ARCEUS_SCORE"

# KPIログ: JSONをPythonで安全に構築（タイトル等の特殊文字でJSON破損を防止）
python3 - << 'KPI_PY' "$SCRIPT_DIR/lib/kpi_logger.py" "$POST_ID" "$TITLE" "$POST_URL" "$SLUG" "$CATEGORY_ID" "$PLAIN_CHARS" "$H2_COUNT" "$ARCEUS_SCORE" "$HAS_CTA" "${PIPELINE_TOKEN_COUNT:-0}" "$PROCESSING_TIME"
import json, sys, importlib.util

logger_path, post_id, title, url, slug = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
category_id, plain_chars, h2_count = sys.argv[6], sys.argv[7], sys.argv[8]
arceus_score, has_cta, token_count, proc_time = sys.argv[9], sys.argv[10], sys.argv[11], sys.argv[12]

def safe_int(v, default=0):
    try: return int(v)
    except: return default

def safe_bool(v):
    return v.lower() == "true"

data = {
    "post_id": post_id,
    "title": title,
    "url": url,
    "slug": slug,
    "article_type": "stock",
    "categories": [safe_int(category_id)],
    "char_count": safe_int(plain_chars),
    "h2_count": safe_int(h2_count),
    "score": safe_int(arceus_score),
    "pipeline": "strategy",
    "has_cta": safe_bool(has_cta),
    "has_thumbnail": True,
    "token_count": safe_int(token_count),
    "processing_time_sec": safe_int(proc_time),
}

spec = importlib.util.spec_from_file_location("kpi_logger", logger_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
result = mod.log_post(data)
print(json.dumps(result, ensure_ascii=False))
KPI_PY
if [ $? -ne 0 ]; then
  echo "KPIログ記録スキップ"
fi

cleanup_reports_dir

echo ""
echo "========================================"
echo " ✅ パイプライン完了"
echo " 記事ID  : $POST_ID"
echo " URL     : $POST_URL"
echo " SNS戦略 : (archived) $ARCHIVE_DIR/15_sns.md"
echo " アーカイブ: $ARCHIVE_DIR"
echo "========================================"

# ─── 投稿後自動監査 ────────────────────────────────────────────────────────
echo "=== 投稿後自動監査 ==="
if [[ -n "${POST_ID:-}" ]] && [[ -n "${POST_URL:-}" ]]; then
  env -u AUDIT_LOOP_COUNT bash "$SCRIPT_DIR/post_audit.sh" "$POST_ID" "$POST_URL" "${TITLE:-}" "$RUN_ID" 2>&1 || true
fi
