#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 比較・まとめ記事パイプライン
# 「○○ vs ○○」「TOP10」記事を毎日自動生成
# 毎日 16:00 自動実行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/env_loader.sh"
export PYTHONIOENCODING=utf-8
export LANG=${LANG:-en_US.UTF-8}
export LC_ALL=${LC_ALL:-en_US.UTF-8}
source "$SCRIPT_DIR/lib/sanitize_output.sh"

# パイプライン排他実行ロック
_GLOBAL_PIPELINE_LOCK="/tmp/kpop_pipeline_global.flock"
exec 9>"$_GLOBAL_PIPELINE_LOCK"
if ! flock -w 300 9; then
  echo "⏭️  他のパイプラインが実行中のため、この起動はスキップします（comparison）"
  exit 0
fi

if [ "${ENABLE_TOKEN_TRACKING:-0}" = "1" ]; then
  source "$SCRIPT_DIR/lib/claude_wrapper.sh"
fi

PIPELINE_JSONL="$SCRIPT_DIR/logs/pipeline.jsonl"
mkdir -p "$SCRIPT_DIR/logs"

TODAY=$(date '+%Y年%m月%d日')
TODAY_ISO=$(date '+%Y-%m-%d')
RUN_ID=$(date '+%Y%m%d_%H%M%S')
PIPELINE_START=$(date +%s)
ARCHIVE_DIR=~/kpop_archives/$RUN_ID

log_step() {
  local step="$1" status="$2" file="${3:-}" msg="${4:-}"
  local ts; ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  local sz=0; [[ -n "$file" && -f "$file" ]] && sz=$(wc -c < "$file")
  msg="${msg//\\/\\\\}"; msg="${msg//\"/\\\"}"
  printf '{"timestamp":"%s","run_id":"%s","pipeline":"comparison","step":"%s","status":"%s","file":"%s","size_bytes":%d,"message":"%s"}\n' \
    "$ts" "$RUN_ID" "$step" "$status" "$file" "$sz" "$msg" >> "$PIPELINE_JSONL"
}

REPORTS_DIR="$SCRIPT_DIR/reports_${RUN_ID}"
mkdir -p "$REPORTS_DIR"
if [[ -L "$SCRIPT_DIR/reports" ]]; then rm -f "$SCRIPT_DIR/reports"
elif [[ -d "$SCRIPT_DIR/reports" ]]; then rm -rf "$SCRIPT_DIR/reports"; fi
ln -sfn "$REPORTS_DIR" "$SCRIPT_DIR/reports"
ln -sf "$SCRIPT_DIR/static/news-sitemap.xml" "$REPORTS_DIR/news-sitemap.xml" 2>/dev/null || true
export TOKEN_LOG="$ARCHIVE_DIR/token_usage.jsonl"

check_output() {
  local file="$1" step="$2"
  if [[ ! -s "$file" ]]; then
    echo "❌ [$step] 出力が空"; log_step "$step" "error" "$file" "空"; archive_and_exit 1
  fi
  local _sz; _sz=$(wc -c < "$file" 2>/dev/null || echo 0)
  if [[ "$_sz" -lt 500 ]]; then
    echo "❌ [$step] 出力極小 (${_sz}bytes)"; log_step "$step" "error" "$file" "極小"; archive_and_exit 1
  fi
  if grep -qE '申し訳ありません[がで。、 ]|お手伝いできますか|許可してください|入力記事が見当たりません|記事を提供してください' "$file"; then
    echo "❌ [$step] エラー応答"; log_step "$step" "error" "$file" "エラー応答"; archive_and_exit 1
  fi
  echo "  ✓ [$step] OK ($(wc -c < "$file" | tr -d ' ') bytes)"; log_step "$step" "ok" "$file"
}

cleanup_reports_dir() {
  [[ -n "${REPORTS_DIR:-}" ]] && [[ -d "$REPORTS_DIR" ]] && rm -rf "$REPORTS_DIR"
  if [[ -L "$SCRIPT_DIR/reports" ]]; then
    local _lt; _lt=$(readlink "$SCRIPT_DIR/reports" 2>/dev/null || echo "")
    [[ -z "${REPORTS_DIR:-}" || "$_lt" == "$REPORTS_DIR" || ! -e "$_lt" ]] && rm -f "$SCRIPT_DIR/reports"
  elif [[ -d "$SCRIPT_DIR/reports" ]]; then rm -rf "$SCRIPT_DIR/reports"; fi
  # news-sitemap.xml 復元
  mkdir -p "$SCRIPT_DIR/reports" 2>/dev/null || true
  ln -sf "$SCRIPT_DIR/static/news-sitemap.xml" "$SCRIPT_DIR/reports/news-sitemap.xml" 2>/dev/null || true
}

archive_and_exit() {
  local code="${1:-1}"
  [[ -n "$ARCHIVE_DIR" ]] && { mkdir -p "$ARCHIVE_DIR"; cp reports/* "$ARCHIVE_DIR/" 2>/dev/null; }
  cleanup_reports_dir
  bash "$SCRIPT_DIR/kpop_notify.sh" error "比較記事" "パイプライン停止 (RUN: $RUN_ID)" 2>/dev/null
  exit "$code"
}

wp_health_check() {
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1" \
    -K "$HOME/.wp_auth" --connect-timeout 10 --max-time 15)
  [[ "$HTTP_CODE" != "200" ]] && { echo "❌ WordPress API失敗 (HTTP ${HTTP_CODE})"; exit 1; }
  echo "  ✓ WordPress API 正常"
}

check_duplicate() {
  local title="$1" days="${2:-5}"
  echo "=== 重複チェック（過去${days}日）==="
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
except: print("")
PYEOF
  )
  [[ -z "$RECENT_TITLES" ]] && { echo "  ⚠️ 取得失敗→スキップ"; return 0; }
  SIMILARITY=$(claude --no-session-persistence -p "
【タスク】類似記事重複チェック
【新タイトル】${title}
【投稿済み】
${RECENT_TITLES}
【判定基準】
- 同じ「vs」比較対象の組み合わせ → YES
- 同じTOP10テーマ（同じカテゴリ+同じ切り口） → YES
- 別の比較対象・別の切り口 → NO
【出力】YESまたはNOのみ。
")
  [[ "$SIMILARITY" == "YES" ]] && { echo "  ⚠️ 重複あり→スキップ"; archive_and_exit 0; }
  echo "  ✓ 重複なし"
}

echo "========================================"
echo " 比較・まとめ記事パイプライン: $TODAY"
echo " 実行ID: $RUN_ID"
echo "========================================"

wp_health_check
log_step "start" "ok" "" "comparison pipeline start"

# ━━━ テーマ選定（日替わりローテーション） ━━━
# 偶数日=「vs比較」記事、奇数日=「TOP10/おすすめ」記事
ARTICLE_FORMAT=$(python3 -c "
from datetime import date
d = date.today().day
print('vs' if d % 2 == 0 else 'top10')
")

echo "  記事フォーマット: $ARTICLE_FORMAT"

# ━━━ PHASE 1: テーマ選定 + 記事生成 ━━━
echo ""
echo "━━━ PHASE 1: バタフリー — トレンド調査 + テーマ選定 ━━━"

if [[ "$ARTICLE_FORMAT" == "vs" ]]; then
  THEME_INSTRUCTION="
【記事フォーマット: VS比較記事】
K-POPの「○○ vs ○○」比較記事を書け。

テーマ候補（WebSearchで今話題のものを選べ）：
- グループ比較: 「NewJeans vs LE SSERAFIM」「IVE vs aespa」等
- アルバム比較: 「○○ vs ○○ どちらが上？」
- サービス比較: 「Weverse vs Bubble どっちがいい？」
- 会場比較: 「東京ドーム vs 味の素スタジアム K-POPライブならどっち？」
- 商品比較: 「韓国コスメ○○ vs ○○」

【構成ルール】
- タイトル形式: 「○○ vs ○○ 徹底比較！〇〇の違いは？」（40文字以内）
- H2-1: ○○と○○の基本情報
- H2-2: 比較ポイント①（数字・データで客観比較）
- H2-3: 比較ポイント②
- H2-4: 比較ポイント③
- H2-5: 結論：どちらを選ぶべき？
- 比較表（<table>タグ）を必ず含める
"
else
  THEME_INSTRUCTION="
【記事フォーマット: TOP10/おすすめ記事】
K-POPの「TOP10」「おすすめ○選」記事を書け。

テーマ候補（WebSearchで今話題のものを選べ）：
- 「2026年注目のK-POPグループTOP10」
- 「K-POPファンおすすめ韓国旅行スポットTOP10」
- 「K-POPアイドル愛用コスメTOP10」
- 「K-POP楽曲再生回数ランキングTOP10（今月）」
- 「K-POPファン必見の韓国ドラマTOP10」
- 「K-POPグループデビュー曲おすすめTOP10」

【構成ルール】
- タイトル形式: 「○○おすすめTOP10！〇〇が1位の理由は？」（40文字以内）
- H2-1: このランキングの選定基準
- H2-2〜H2-6: TOP10を2〜3個ずつ紹介
- H2-7: まとめ
- ランキング表（<table>または<ol>タグ）を必ず含める
"
fi

echo "[1/5] バタフリー + deoxys_kpop: トレンド調査 + 記事生成..."
claude --no-session-persistence --allowedTools WebSearch --agent deoxys_kpop -p "
今日は${TODAY}です。
まずWebSearchで最新のK-POPトレンドを調査し、以下の指示に従って比較・まとめ記事を生成せよ。

${THEME_INSTRUCTION}

【生成ルール】
- 必ずWebSearchで最新情報を調査してから書く
- 架空の情報・データは絶対に禁止
- 2500〜3500文字（HTMLタグ除く）
- 各比較項目に数字・データ・根拠を必ず含める
- 末尾に「※本記事は${TODAY}時点の情報です」を明記

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（マークダウン禁止）
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ（2500文字以上）
" > reports/1_comparison_article.md
sanitize_output reports/1_comparison_article.md

if [[ ! -s reports/1_comparison_article.md ]]; then
  echo "  ⚠️ 空出力→リトライ..."
  sleep 30
  claude --no-session-persistence --allowedTools WebSearch --agent deoxys_kpop -p "
今日は${TODAY}です。K-POPの${ARTICLE_FORMAT}記事をWebSearch調査して書け。2500文字以上HTML。
1行目:タイトルのみ 2行目:空行 3行目以降:<h2>からHTML本文。比較表を必ず含める。
" > reports/1_comparison_article.md
  sanitize_output reports/1_comparison_article.md
fi
check_output reports/1_comparison_article.md "deoxys_kpop"

# ━━━ PHASE 2: 品質チェック ━━━
echo ""
echo "━━━ PHASE 2: 品質チェック ━━━"

echo "[2/5] アラカザム: ファクトチェック..."
claude --no-session-persistence --agent alakazam_kpop -p "
今日は${TODAY}です。
以下の比較・まとめ記事のファクトチェックを行え。
数字・データ・ランキング・メンバー名・デビュー日等の正確性を重点チェック。

【記事】
$(cat reports/1_comparison_article.md)

【出力形式】1行目:タイトルのみ 2行目:空行 3行目以降:修正済みHTML本文
" > reports/2_comparison_checked.md
sanitize_output reports/2_comparison_checked.md
check_output reports/2_comparison_checked.md "アラカザム"

echo "[3/5] ゲンガー: SEO品質監査..."
claude --no-session-persistence --agent gengar -p "
今日は${TODAY}です。以下の比較記事のSEO・品質を最終監査せよ。
【記事】
$(cat reports/2_comparison_checked.md)
1行目:タイトルのみ 2行目:空行 3行目以降:HTML本文のみ
" > reports/3_comparison_audited.md
sanitize_output reports/3_comparison_audited.md
check_output reports/3_comparison_audited.md "ゲンガー"

grep -q '❌ 投稿停止' reports/3_comparison_audited.md && { echo "❌ 投稿停止判定"; archive_and_exit 1; }

# ━━━ PHASE 3: CVR最適化 ━━━
echo ""
echo "━━━ PHASE 3: CVR最適化 ━━━"

echo "[4/5] カイリュー: CVR最適化..."
ARTICLE_LINE=$(grep -n '^<h2>' reports/3_comparison_audited.md | head -1 | cut -d: -f1)
if [[ -n "$ARTICLE_LINE" ]]; then
  TITLE_LINE=$((ARTICLE_LINE - 2)); [[ $TITLE_LINE -lt 1 ]] && TITLE_LINE=1
  sed -n "${TITLE_LINE}p" reports/3_comparison_audited.md > /tmp/comparison_article.md
  echo "" >> /tmp/comparison_article.md
  tail -n "+${ARTICLE_LINE}" reports/3_comparison_audited.md >> /tmp/comparison_article.md
else
  cp reports/3_comparison_audited.md /tmp/comparison_article.md
fi

_KAIRYU_INPUT_SZ=$(wc -c < /tmp/comparison_article.md 2>/dev/null || echo 0)
claude --no-session-persistence --agent kairyu_kpop -p "
今日は${TODAY}です。以下の比較・まとめ記事にCVR導線を追加せよ。
【記事】
$(cat /tmp/comparison_article.md)
【改善指示】
1. 記事タイプ: <p class=\"article-type explanation\">【徹底比較】</p> or <p class=\"article-type explanation\">【ランキング】</p>
2. CTAボックス2箇所（中盤・末尾）
3. 関連記事リンク（同カテゴリの他比較記事への導線）
4. SNSシェア促進
【出力形式】1行目:タイトルのみ 2行目:空行 3行目以降:HTML本文のみ
【絶対禁止】改善内容の説明・まとめ・コメントを出力しないこと。記事HTML全文をそのまま出力すること。
" > reports/4_comparison_final.md
sanitize_output reports/4_comparison_final.md

# [カイリュー出力ガード] HTML記事ではなくメタ解説を出力した場合は入力記事にフォールバック
_KAIRYU_SZ=$(wc -c < reports/4_comparison_final.md 2>/dev/null || echo 0)
_KAIRYU_HTML_TAGS=$(grep -c '<h[2-6]\|<p[ >]\|<div\|<table\|<ul' reports/4_comparison_final.md 2>/dev/null || echo 0)
if [[ "$_KAIRYU_SZ" -lt $((_KAIRYU_INPUT_SZ / 2)) ]] || [[ "$_KAIRYU_HTML_TAGS" -lt 3 ]]; then
  echo "  ⚠️ [カイリュー出力ガード] 記事HTML不足(${_KAIRYU_SZ}bytes, HTMLタグ${_KAIRYU_HTML_TAGS}個) → 入力記事(${_KAIRYU_INPUT_SZ}bytes)にフォールバック"
  cp /tmp/comparison_article.md reports/4_comparison_final.md
  log_step "kairyu" "warn" "reports/4_comparison_final.md" "メタ解説出力→フォールバック"
fi
check_output reports/4_comparison_final.md "カイリュー"

# ━━━ PHASE 4: 投稿 ━━━
echo ""
echo "━━━ PHASE 4: 投稿 ━━━"

python3 - <<'PY'
from pathlib import Path
import re, sys
src = Path("reports/4_comparison_final.md")
dst = Path("reports/final_post.md")
text = src.read_text(encoding="utf-8", errors="replace")

# AIメタ応答パターン検出（記事HTMLではなく説明文を出力してしまった場合）
META_PATTERNS = [
    r'^以下が改善内容', r'^適用内容のサマリ', r'^以下に完成記事',
    r'^改善内容の(まとめ|サマリ)', r'^修正内容の(まとめ|サマリ)',
    r'^以下が(修正|改善|完成)', r'^記事を生成します',
]
first_line = text.strip().split('\n')[0] if text.strip() else ''
is_meta = any(re.search(p, first_line) for p in META_PATTERNS)
if is_meta:
    print(f"  ⚠️ AIメタ応答検出: {first_line[:60]}", file=sys.stderr)

lines = text.splitlines()
html_idx = None
for i, line in enumerate(lines):
    if re.match(r'\s*<(h[1-6]|p[ >]|ul|ol|div|table|hr)', line, re.IGNORECASE):
        html_idx = i; break
if html_idx is not None:
    title_idx = None
    for j in range(html_idx - 1, -1, -1):
        s = lines[j].strip()
        if not s: continue
        if not s.startswith("<"): title_idx = j; break
    start = title_idx if title_idx is not None else html_idx
    cleaned = "\n".join(lines[start:]).strip() + "\n"
elif is_meta:
    # メタ応答でHTMLなし → 空にして本文不足ガードで停止させる
    cleaned = "\n"
else:
    cleaned = text.strip() + "\n"
# U+FFFD（replacement character）を除去
cleaned = cleaned.replace('\ufffd', '')
dst.write_text(cleaned, encoding="utf-8")
PY

TITLE=$(head -n 1 reports/final_post.md)
CONTENT=$(tail -n +2 reports/final_post.md)

check_duplicate "$TITLE" 5

[[ -z "$TITLE" || "${#TITLE}" -lt 10 ]] && { echo "❌ タイトル異常: '$(echo "$TITLE" | head -c 60)'"; log_step "publish" "error" "reports/final_post.md" "タイトル異常"; archive_and_exit 1; }
CONTENT_SIZE=$(echo "$CONTENT" | wc -c)
if [[ "$CONTENT_SIZE" -lt 3000 ]]; then
  echo "❌ 本文不足 (${CONTENT_SIZE}bytes < 3000) — AI記事生成がメタ応答を返した可能性"
  echo "  タイトル冒頭: $(echo "$TITLE" | head -c 60)"
  log_step "publish" "error" "reports/final_post.md" "本文不足: ${CONTENT_SIZE}bytes（AIメタ応答の疑い）"
  archive_and_exit 1
fi

# カテゴリ: 4（考察・比較・解説）
CATEGORY_ID=4

# アーティスト別カテゴリも自動判定
ARTIST_CATEGORY_IDS=$(python3 - << 'PY' "$TITLE"
import sys
title = sys.argv[1].lower()
artist_rules = [
    (19, ['bigbang','g-dragon']), (23, ['blackpink','jennie','jisoo','rose','lisa']),
    (18, ['bts']), (25, ['aespa','karina','winter']),
    (38, ['babymonster']), (44, ['illit']), (68, ['ive','wonyoung']),
    (41, ['le sserafim','lesserafim']), (32, ['newjeans','minji','hani']),
    (39, ['riize']), (24, ['seventeen','svt']),
    (43, ['stray kids','skz']), (22, ['twice']),
]
matched = []
for cid, keywords in artist_rules:
    if any(word in title for word in keywords):
        matched.append(str(cid))
print(",".join(matched))
PY
)

SLUG=$(python3 "$SCRIPT_DIR/lib/slug_generator.py" "$TITLE" 2>/dev/null || python3 "$SCRIPT_DIR/lib/slug.py" "$TITLE" 2>/dev/null || echo "kpop-comparison-$(date +%Y%m%d)")
[[ "$SLUG" =~ ^[0-9] ]] && SLUG="kpop-${SLUG}"

TAG_NAMES=$(python3 - << 'PY' "$TITLE"
import sys
title = sys.argv[1].lower()
rules = [
    ('徹底比較', ['vs', '比較', '違い']),
    ('おすすめ', ['top10', 'top 10', 'おすすめ', 'ランキング']),
    ('K-POP', []),  # always add
]
matched = [tag for tag, kws in rules if kws and any(w in title for w in kws)]
matched.append('K-POP')
print('|'.join(list(dict.fromkeys(matched))))
PY
)

TAG_IDS=$(python3 - << 'PY' "$TAG_NAMES"
import sys, json, urllib.request, urllib.parse, base64, os
raw = sys.argv[1].strip()
if not raw: print(""); sys.exit()
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
        if match: tag_ids.append(str(match["id"])); continue
    except: pass
    req = urllib.request.Request(base_url, data=json.dumps({"name": name}).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req) as res: tag_ids.append(str(json.loads(res.read())["id"]))
    except: pass
print(",".join(tag_ids))
PY
)

DESC=$(echo "$CONTENT" | sed -e 's/<[^>]*>//g' | python3 -c "import sys; print(sys.stdin.read().strip()[:120])")
echo "$TITLE"   > /tmp/kpop_title.txt
echo "$CONTENT" > /tmp/kpop_content.txt
echo "$DESC"    > /tmp/kpop_desc.txt

# WP投稿直前の最終サニタイズ（\n・JSONメタデータ除去）
sanitize_wp_content /tmp/kpop_content.txt
sanitize_wp_content /tmp/kpop_title.txt

MEDIA_ID=0
echo "[5/5] サムネイル生成..."
THUMB_RESULT=$(python3 "$SCRIPT_DIR/make_thumbnail.py" --title "$TITLE" --genre comparison 2>&1) || true
MEDIA_ID=$(echo "$THUMB_RESULT" | grep -oP 'media_id=\K[0-9]+' | head -1 || echo "0")

JSON=$(python3 - << 'PY' "$SLUG" "$CATEGORY_ID" "${MEDIA_ID:-0}" "$ARTIST_CATEGORY_IDS" "$TAG_IDS"
import json, sys
slug, main_cat = sys.argv[1], int(sys.argv[2])
media_id = int(sys.argv[3]) if sys.argv[3] else 0
artist_ids_raw, tag_ids_raw = sys.argv[4].strip(), sys.argv[5].strip()
with open("/tmp/kpop_title.txt", encoding='utf-8') as f: title = f.read().strip()
with open("/tmp/kpop_content.txt", encoding='utf-8') as f: content = f.read().strip()
with open("/tmp/kpop_desc.txt", encoding='utf-8') as f: desc = f.read().strip()
categories = [main_cat]
for x in (artist_ids_raw.split(",") if artist_ids_raw else []):
    x = x.strip()
    if x: categories.append(int(x))
categories = list(dict.fromkeys(categories))
tags = [int(x.strip()) for x in tag_ids_raw.split(",") if x.strip()] if tag_ids_raw else []
data = {'title': title, 'content': content, 'status': 'publish', 'slug': slug,
        'categories': categories, 'tags': tags, 'excerpt': desc}
if media_id > 0: data['featured_media'] = media_id
print(json.dumps(data, ensure_ascii=False))
PY
)

if ! echo "$JSON" | python3 "$SCRIPT_DIR/lib/validate_post.py"; then echo "❌ バリデーション失敗"; archive_and_exit 1; fi
if ! echo "$JSON" | python3 "$SCRIPT_DIR/lib/darkrai_audit.py"; then echo "❌ 権利監査失敗"; archive_and_exit 1; fi

RESPONSE=$(curl -s -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/posts -K ~/.wp_auth -H "Content-Type: application/json" -d "$JSON")
POST_URL=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('link',''))" 2>/dev/null)
POST_ID=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)

if [[ -n "$POST_ID" && "$POST_ID" =~ ^[0-9]+$ ]]; then
  log_step "wordpress_post" "ok" "" "post_id=$POST_ID"
  echo "  ✅ 投稿成功: POST_ID=$POST_ID"
else
  log_step "wordpress_post" "error" "" "失敗"; archive_and_exit 1
fi

# AIOSEO
[[ -n "$POST_ID" && "$POST_ID" =~ ^[0-9]+$ ]] && {
  AIOSEO_DESC=$(echo "$CONTENT" | sed 's/<[^>]*>//g' | python3 -c "
import sys, re
text = re.sub(r'\s+', ' ', sys.stdin.read().strip())
for s in re.split(r'[。！？]', text):
    if len(s.strip()) >= 30: print((s.strip()+'。')[:120]); break
else: print(text[:120])
" 2>/dev/null)
  curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
    -K ~/.wp_auth -H "Content-Type: application/json" \
    -d "{\"meta\":{\"_aioseo_description\": \"$(echo "$AIOSEO_DESC" | sed 's/"/\\"/g')\"}}" > /dev/null 2>&1
}

bash "$SCRIPT_DIR/google_metrics/inject_revenue_links.sh" "$POST_ID" 2>&1 || true
bash "$SCRIPT_DIR/google_metrics/request_index.sh" "$POST_URL" 2>&1 || true
bash "$SCRIPT_DIR/google_metrics/request_bing_index.sh" "$POST_URL" 2>&1 || true

mkdir -p "$ARCHIVE_DIR"; cp reports/* "$ARCHIVE_DIR/" 2>/dev/null
CONTENT_LENGTH=$(echo "$CONTENT" | sed 's/<[^>]*>//g' | wc -m | tr -d ' ')
cat > "$ARCHIVE_DIR/summary.txt" << SUMMARY
実行ID: $RUN_ID | パイプライン: comparison | 日時: $TODAY
記事ID: $POST_ID | URL: $POST_URL | タイトル: $TITLE | 文字数: $CONTENT_LENGTH
SUMMARY
bash "$SCRIPT_DIR/kpop_notify.sh" success "比較記事" "記事投稿完了: $TITLE" "$POST_URL" 2>/dev/null

python3 - << 'KPI_PY' "$SCRIPT_DIR/lib/kpi_logger.py" "$POST_ID" "$TITLE" "$POST_URL" "$SLUG" "$CATEGORY_ID" "$CONTENT_LENGTH"
import sys, importlib.util
try:
    spec = importlib.util.spec_from_file_location("kpi_logger", sys.argv[1])
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    mod.log_post({"post_id": sys.argv[2], "title": sys.argv[3], "url": sys.argv[4],
        "slug": sys.argv[5], "article_type": "comparison", "categories": [int(sys.argv[6])],
        "char_count": int(sys.argv[7] or 0), "pipeline": "comparison", "has_cta": True})
except: pass
KPI_PY

cleanup_reports_dir

[[ -n "${POST_ID:-}" && -n "${POST_URL:-}" ]] && \
  env -u AUDIT_LOOP_COUNT bash "$SCRIPT_DIR/post_audit.sh" "$POST_ID" "$POST_URL" "${TITLE:-}" "$RUN_ID" 2>&1 || true

# X投稿（監査通過後のみ）
_WP_STATUS=$(curl -s "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
  -K ~/.wp_auth 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
if [[ "$_WP_STATUS" == "publish" ]]; then
  bash "$SCRIPT_DIR/google_metrics/post_to_x.sh" "$TITLE" "$POST_URL" "" 2>&1 || true
fi

echo ""
echo "========================================"
echo " ✅ 比較・まとめ記事パイプライン完了"
echo " 記事ID: $POST_ID | URL: $POST_URL"
echo "========================================"
