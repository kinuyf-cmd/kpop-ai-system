#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ライフスタイル記事パイプライン
# snorlax（レビュー・比較記事担当）を接続
# K-POPグッズ・コスメレビュー・ソウル旅行スポット記事を自動生成
# 毎日 14:00 自動実行
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
  echo "⏭️  他のパイプラインが実行中のため、この起動はスキップします（lifestyle）"
  exit 0
fi

if [ "${ENABLE_TOKEN_TRACKING:-0}" = "1" ]; then
  source "$SCRIPT_DIR/lib/claude_wrapper.sh"
fi

PIPELINE_JSONL="$SCRIPT_DIR/logs/pipeline.jsonl"
mkdir -p "$SCRIPT_DIR/logs"

TODAY=$(date '+%Y年%m月%d日')
RUN_ID=$(date '+%Y%m%d_%H%M%S')
PIPELINE_START=$(date +%s)
ARCHIVE_DIR=~/kpop_archives/$RUN_ID

log_step() {
  local step="$1" status="$2" file="${3:-}" msg="${4:-}"
  local ts sz
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  if [[ -n "$file" && -f "$file" ]]; then sz=$(wc -c < "$file"); else sz=0; fi
  msg="${msg//\\/\\\\}"; msg="${msg//\"/\\\"}"
  printf '{"timestamp":"%s","run_id":"%s","pipeline":"lifestyle","step":"%s","status":"%s","file":"%s","size_bytes":%d,"message":"%s"}\n' \
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
    echo "❌ [$step] 出力が空 → パイプライン停止"; log_step "$step" "error" "$file" "出力が空"; archive_and_exit 1
  fi
  local _sz; _sz=$(wc -c < "$file" 2>/dev/null || echo 0)
  if [[ "$_sz" -lt 500 ]]; then
    echo "❌ [$step] 出力が極小 (${_sz}bytes) → パイプライン停止"; log_step "$step" "error" "$file" "出力極小"; archive_and_exit 1
  fi
  if grep -qE '申し訳ありません[がで。、 ]|申し訳ありません$|お手伝いできますか|許可してください|入力記事が見当たりません|記事を提供してください|元の記事が提供されていません' "$file"; then
    echo "❌ [$step] エラー応答検出 → パイプライン停止"; log_step "$step" "error" "$file" "エラー応答"; archive_and_exit 1
  fi
  echo "  ✓ [$step] OK ($(wc -c < "$file" | tr -d ' ') bytes)"; log_step "$step" "ok" "$file"
}

cleanup_reports_dir() {
  [[ -n "${REPORTS_DIR:-}" ]] && [[ -d "$REPORTS_DIR" ]] && rm -rf "$REPORTS_DIR"
  if [[ -L "$SCRIPT_DIR/reports" ]]; then
    local _lt; _lt=$(readlink "$SCRIPT_DIR/reports" 2>/dev/null || echo "")
    if [[ -z "${REPORTS_DIR:-}" ]] || [[ "$_lt" == "$REPORTS_DIR" ]] || [[ ! -e "$_lt" ]]; then rm -f "$SCRIPT_DIR/reports"; fi
  elif [[ -d "$SCRIPT_DIR/reports" ]]; then rm -rf "$SCRIPT_DIR/reports"; fi
  # news-sitemap.xml 復元
  mkdir -p "$SCRIPT_DIR/reports" 2>/dev/null || true
  ln -sf "$SCRIPT_DIR/static/news-sitemap.xml" "$SCRIPT_DIR/reports/news-sitemap.xml" 2>/dev/null || true
}

archive_and_exit() {
  local code="${1:-1}"
  if [[ -n "$ARCHIVE_DIR" ]]; then
    mkdir -p "$ARCHIVE_DIR"; cp reports/* "$ARCHIVE_DIR/" 2>/dev/null
    cat > "$ARCHIVE_DIR/summary.txt" << SUMMARY
実行ID: $RUN_ID | パイプライン: lifestyle | 日時: $TODAY | 判定: 停止
SUMMARY
  fi
  cleanup_reports_dir
  bash "$SCRIPT_DIR/kpop_notify.sh" error "ライフスタイル" "パイプライン停止 (RUN: $RUN_ID)" 2>/dev/null
  exit "$code"
}

wp_health_check() {
  echo "=== WordPress 接続確認 ==="
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1" \
    -K "$HOME/.wp_auth" --connect-timeout 10 --max-time 15)
  if [[ "$HTTP_CODE" != "200" ]]; then
    echo "❌ WordPress API 接続失敗 (HTTP ${HTTP_CODE})"; exit 1
  fi
  echo "  ✓ WordPress API 正常"
}

check_duplicate() {
  local title="$1" days="${2:-5}"
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
except Exception: print("")
PYEOF
  )
  if [[ -z "$RECENT_TITLES" ]]; then echo "  ⚠️  取得失敗 → スキップ"; return 0; fi
  SIMILARITY=$(claude --no-session-persistence -p "
【タスク】類似記事重複チェック
【新タイトル】${title}
【投稿済みタイトル】
${RECENT_TITLES}
【判定基準】同じ商品/スポットのレビュー記事あり→YES、別テーマ→NO
【出力】YESまたはNOのみ。
")
  if [[ "$SIMILARITY" == "YES" ]]; then
    echo "  ⚠️  重複あり → スキップ"; archive_and_exit 0
  fi
  echo "  ✓ 重複なし"
}

echo "========================================"
echo " ライフスタイルパイプライン 開始: $TODAY"
echo " 実行ID: $RUN_ID"
echo "========================================"

wp_health_check
log_step "start" "ok" "" "lifestyle pipeline start"

# ━━━ PHASE 1: snorlax — レビュー・比較記事テーマ選定＋生成 ━━━
echo ""
echo "━━━ PHASE 1: snorlax — レビュー・比較記事生成 ━━━"

# 記事タイプをローテーション（日ごと: 月=コスメ 火=グッズ 水=旅行 木=コスメ 金=グッズ 土=旅行 日=コスメ）
ARTICLE_TYPE=$(python3 -c "
from datetime import date
types = ['cosme_review', 'goods_compare', 'travel_review', 'cosme_review', 'goods_compare', 'travel_review', 'cosme_review']
print(types[date.today().weekday()])
")
echo "  記事タイプ: $ARTICLE_TYPE"

case "$ARTICLE_TYPE" in
  cosme_review)
    THEME_PROMPT="韓国コスメの商品レビュー記事を生成せよ。タイプA（コスメレビュー記事）のテンプレに従い、K-POPアイドル愛用コスメや話題の韓国コスメ商品をWebSearchで調査し、実際の成分・口コミ・効果を含む信頼性の高いレビュー記事を書け。"
    CATEGORY_ID=12
    ;;
  goods_compare)
    THEME_PROMPT="K-POP公式グッズのおすすめ比較記事を生成せよ。タイプB（グッズ比較記事）のテンプレに従い、人気アーティストの公式グッズをWebSearchで調査し、3商品以上を比較するランキング記事を書け。"
    CATEGORY_ID=13
    ;;
  travel_review)
    THEME_PROMPT="ソウルのK-POPファン向けスポットレビュー記事を生成せよ。タイプC（旅行スポットレビュー）のテンプレに従い、聖地巡礼スポット・カフェ・ポップアップストア等をWebSearchで調査し、実用的なガイド記事を書け。"
    CATEGORY_ID=11
    ;;
esac

echo "[1/5] snorlax: レビュー・比較記事生成..."
claude --no-session-persistence --allowedTools WebSearch --agent snorlax -p "
今日は${TODAY}です。
${THEME_PROMPT}

【生成ルール】
- 必ずWebSearchで最新情報を調査してから書く
- 架空の商品名・店舗名・価格は絶対に書かない
- 実在する商品・スポットのみ掲載
- 2000〜3500文字（HTMLタグ除く）
- 比較記事は必ず3商品/スポット以上を比較する
- アフィリエイトリンク候補を明記
- 末尾に「※本記事は${TODAY}時点の情報です」を明記

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（マークダウン・説明文禁止）
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ（2000文字以上）
" > reports/1_lifestyle_article.md
sanitize_output reports/1_lifestyle_article.md

if [[ ! -s reports/1_lifestyle_article.md ]]; then
  echo "  ⚠️ snorlax空出力 → 30秒待機後リトライ..."
  sleep 30
  claude --no-session-persistence --allowedTools WebSearch --agent snorlax -p "
今日は${TODAY}です。${THEME_PROMPT}
WebSearchで最新情報を調査し、2000文字以上のHTML記事を書け。架空情報禁止。
1行目:タイトルのみ 2行目:空行 3行目以降:<h2>からHTML本文
" > reports/1_lifestyle_article.md
  sanitize_output reports/1_lifestyle_article.md
fi
check_output reports/1_lifestyle_article.md "snorlax"

# ━━━ PHASE 2: 品質チェック ━━━
echo ""
echo "━━━ PHASE 2: 品質チェック ━━━"

echo "[2/5] アラカザム: ファクトチェック..."
claude --no-session-persistence --agent alakazam_kpop -p "
今日は${TODAY}です。
以下のレビュー・比較記事の事実確認を行い、必要箇所のみ修正せよ。
商品名・価格・店舗名・住所・営業時間の正確性を重点チェック。

【記事】
$(cat reports/1_lifestyle_article.md)

【出力形式】1行目:タイトルのみ 2行目:空行 3行目以降:修正済みHTML本文
" > reports/2_lifestyle_checked.md
sanitize_output reports/2_lifestyle_checked.md
check_output reports/2_lifestyle_checked.md "アラカザム"

echo "[3/5] ゲンガー: SEO品質監査..."
claude --no-session-persistence --agent gengar -p "
今日は${TODAY}です。
以下のレビュー記事のSEO・品質を最終監査し、修正できる問題は修正せよ。

【記事】
$(cat reports/2_lifestyle_checked.md)

1行目:タイトルのみ 2行目:空行 3行目以降:HTML本文のみ
" > reports/3_lifestyle_audited.md
sanitize_output reports/3_lifestyle_audited.md
check_output reports/3_lifestyle_audited.md "ゲンガー"

# サイズガード: gengar が diff のみ出力した場合、checked をフォールバック使用
_AUDITED_SIZE=$(wc -c < reports/3_lifestyle_audited.md 2>/dev/null || echo 0)
_CHECKED_SIZE=$(wc -c < reports/2_lifestyle_checked.md 2>/dev/null || echo 0)
if [[ "$_AUDITED_SIZE" -lt 3000 && "$_CHECKED_SIZE" -gt 3000 ]]; then
  echo "  ⚠️ [gengar_size_guard] 出力 ${_AUDITED_SIZE}bytes < 3000 → 2_lifestyle_checked.md をフォールバック使用"
  cp reports/2_lifestyle_checked.md reports/3_lifestyle_audited.md
fi

if grep -q '❌ 投稿停止' reports/3_lifestyle_audited.md; then
  echo "❌ ゲンガーが投稿停止を判定"; archive_and_exit 1
fi

# ━━━ PHASE 3: CVR最適化 ━━━
echo ""
echo "━━━ PHASE 3: CVR最適化 ━━━"

echo "[4/5] カイリュー: CVR・回遊最適化..."
ARTICLE_LINE=$(grep -n '^<h2>' reports/3_lifestyle_audited.md | head -1 | cut -d: -f1)
if [[ -n "$ARTICLE_LINE" ]]; then
  TITLE_LINE=$((ARTICLE_LINE - 2)); [[ $TITLE_LINE -lt 1 ]] && TITLE_LINE=1
  sed -n "${TITLE_LINE}p" reports/3_lifestyle_audited.md > /tmp/lifestyle_article.md
  echo "" >> /tmp/lifestyle_article.md
  tail -n "+${ARTICLE_LINE}" reports/3_lifestyle_audited.md >> /tmp/lifestyle_article.md
else
  cp reports/3_lifestyle_audited.md /tmp/lifestyle_article.md
fi

_KAIRYU_INPUT_SZ=$(wc -c < /tmp/lifestyle_article.md 2>/dev/null || echo 0)
claude --no-session-persistence --agent kairyu_kpop -p "
今日は${TODAY}です。以下のレビュー記事にCVR導線を追加せよ。
【記事】
$(cat /tmp/lifestyle_article.md)
【改善指示】
1. 記事タイプ付与: <p class=\"article-type guide\">【レビュー】</p>
2. CTAボックスを2箇所に配置（中盤=購入リンク、末尾=まとめ購入導線）
3. 関連記事リンクを中盤と末尾に配置
4. 末尾にSNSシェア促進を追加
【出力形式】1行目:タイトルのみ 2行目:空行 3行目以降:HTML本文のみ
【絶対禁止】改善内容の説明・まとめ・コメントを出力しないこと。記事HTML全文をそのまま出力すること。
" > reports/4_lifestyle_final.md
sanitize_output reports/4_lifestyle_final.md
# [カイリュー出力ガード] HTML記事ではなくメタ解説を出力した場合は入力記事にフォールバック
_KAIRYU_SZ=$(wc -c < reports/4_lifestyle_final.md 2>/dev/null || echo 0)
_KAIRYU_HTML_TAGS=$(grep -c '<h[2-6]\|<p[ >]\|<div\|<table\|<ul' reports/4_lifestyle_final.md 2>/dev/null || echo 0)
if [[ "$_KAIRYU_SZ" -lt $((_KAIRYU_INPUT_SZ / 2)) ]] || [[ "$_KAIRYU_HTML_TAGS" -lt 3 ]]; then
  echo "  ⚠️ [カイリュー出力ガード] 記事HTML不足(${_KAIRYU_SZ}bytes, HTMLタグ${_KAIRYU_HTML_TAGS}個) → 入力記事(${_KAIRYU_INPUT_SZ}bytes)にフォールバック"
  cp /tmp/lifestyle_article.md reports/4_lifestyle_final.md
  log_step "kairyu" "warn" "reports/4_lifestyle_final.md" "メタ解説出力→フォールバック"
fi
check_output reports/4_lifestyle_final.md "カイリュー"

# ━━━ PHASE 4: 投稿 ━━━
echo ""
echo "━━━ PHASE 4: 投稿 ━━━"

python3 - <<'PY'
from pathlib import Path
import re
src = Path("reports/4_lifestyle_final.md")
dst = Path("reports/final_post.md")
text = src.read_text(encoding="utf-8", errors="ignore")
lines = text.splitlines()
html_idx = None
for i, line in enumerate(lines):
    if re.match(r'\s*<(h[1-6]|p[ >]|ul|ol|div|hr|blockquote)', line, re.IGNORECASE):
        html_idx = i; break
if html_idx is not None:
    title_idx = None
    for j in range(html_idx - 1, -1, -1):
        s = lines[j].strip()
        if not s: continue
        if not s.startswith("<"): title_idx = j; break
    start = title_idx if title_idx is not None else html_idx
    cleaned = "\n".join(lines[start:]).strip() + "\n"
else:
    cleaned = text.strip() + "\n"
dst.write_text(cleaned, encoding="utf-8")
PY

TITLE=$(head -n 1 reports/final_post.md | python3 -c "import sys,re; t=sys.stdin.read().strip(); print(re.sub(r'<[^>]+>','',t).strip())")
CONTENT=$(tail -n +2 reports/final_post.md)

check_duplicate "$TITLE" 5

if [[ -z "$TITLE" ]] || [[ "${#TITLE}" -lt 10 ]]; then echo "❌ タイトル異常"; archive_and_exit 1; fi
CONTENT_SIZE=$(echo "$CONTENT" | wc -c)
if [[ "$CONTENT_SIZE" -lt 3000 ]]; then echo "❌ 本文サイズ不足 (${CONTENT_SIZE}bytes)"; archive_and_exit 1; fi

SLUG=$(python3 "$SCRIPT_DIR/lib/slug_generator.py" "$TITLE" 2>/dev/null || python3 "$SCRIPT_DIR/lib/slug.py" "$TITLE" 2>/dev/null || echo "kpop-lifestyle-$(date +%Y%m%d)")
[[ "$SLUG" =~ ^[0-9] ]] && SLUG="kpop-${SLUG}"

TAG_NAMES=$(python3 - << 'PY' "$TITLE"
import sys
title = sys.argv[1].lower()
rules = [
    ('韓国コスメ', ['コスメ','化粧品','メイク']),
    ('K-POPグッズ', ['グッズ','公式グッズ','ペンライト','フォトカード']),
    ('ソウル旅行', ['ソウル','韓国旅行','聖地巡礼','カフェ','ポップアップ']),
    ('おすすめ', ['おすすめ','ランキング','比較','レビュー']),
]
matched = [tag for tag, kws in rules if any(w in title for w in kws)]
if not matched: matched = ['K-POPライフスタイル']
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

DESC=$(echo "$CONTENT" | sed -e 's/<[^>]*>//g' | python3 -c "import sys; t=sys.stdin.read().strip(); print(t[:120])")
echo "$TITLE"   > /tmp/kpop_title.txt
echo "$CONTENT" > /tmp/kpop_content.txt
echo "$DESC"    > /tmp/kpop_desc.txt

# WP投稿直前の最終サニタイズ（\n・JSONメタデータ除去）
sanitize_wp_content /tmp/kpop_content.txt
sanitize_wp_content /tmp/kpop_title.txt

MEDIA_ID=0
echo "[5/5] サムネイル生成..."
THUMB_RESULT=$(python3 "$SCRIPT_DIR/make_thumbnail.py" --title "$TITLE" --genre lifestyle 2>&1) || true
MEDIA_ID=$(echo "$THUMB_RESULT" | grep -oP 'media_id=\K[0-9]+' | head -1 || echo "0")

JSON=$(python3 - << 'PY' "$SLUG" "$CATEGORY_ID" "${MEDIA_ID:-0}" "" "$TAG_IDS"
import json, sys
slug, main_cat, media_id_raw = sys.argv[1], int(sys.argv[2]), sys.argv[3]
media_id = int(media_id_raw) if media_id_raw else 0
tag_ids_raw = sys.argv[5].strip()
with open("/tmp/kpop_title.txt", encoding='utf-8') as f: title = f.read().strip()
with open("/tmp/kpop_content.txt", encoding='utf-8') as f: content = f.read().strip()
with open("/tmp/kpop_desc.txt", encoding='utf-8') as f: desc = f.read().strip()
tags = [int(x.strip()) for x in tag_ids_raw.split(",") if x.strip()] if tag_ids_raw else []
data = {'title': title, 'content': content, 'status': 'publish', 'slug': slug,
        'categories': [main_cat], 'tags': tags, 'excerpt': desc}
if media_id > 0: data['featured_media'] = media_id
print(json.dumps(data, ensure_ascii=False))
PY
)

echo "=== 投稿前バリデーション ==="
if ! echo "$JSON" | python3 "$SCRIPT_DIR/lib/validate_post.py"; then echo "❌ バリデーション失敗"; archive_and_exit 1; fi
echo "=== ダークライ権利監査 ==="
if ! echo "$JSON" | python3 "$SCRIPT_DIR/lib/darkrai_audit.py"; then echo "❌ 権利監査失敗"; archive_and_exit 1; fi

RESPONSE=$(curl -s -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/posts -K ~/.wp_auth -H "Content-Type: application/json" -d "$JSON")
POST_URL=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('link',''))" 2>/dev/null)
POST_ID=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null)

if [[ -n "$POST_ID" && "$POST_ID" =~ ^[0-9]+$ ]]; then
  log_step "wordpress_post" "ok" "" "post_id=$POST_ID"
  echo "  ✅ 投稿成功: POST_ID=$POST_ID"
else
  log_step "wordpress_post" "error" "" "POST_ID取得失敗"; archive_and_exit 1
fi

# AIOSEO
if [[ -n "$POST_ID" && "$POST_ID" =~ ^[0-9]+$ ]]; then
  AIOSEO_DESC=$(echo "$CONTENT" | sed -e 's/<[^>]*>//g' | python3 -c "
import sys, re
text = re.sub(r'\s+', ' ', sys.stdin.read().strip())
for s in re.split(r'[。！？]', text):
    if len(s.strip()) >= 30: print((s.strip() + '。')[:120]); break
else: print(text[:120])
" 2>/dev/null)
  curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
    -K ~/.wp_auth -H "Content-Type: application/json" \
    -d "{\"meta\":{\"_aioseo_description\": \"$(echo "$AIOSEO_DESC" | sed 's/"/\\"/g')\"}}" > /dev/null 2>&1
fi

echo "=== 記事構造補完（3行まとめ + プロフィール） ==="
python3 "$SCRIPT_DIR/pipeline/post_publish_enricher.py" --post-id "$POST_ID" 2>&1 || echo "⚠️ 構造補完スキップ"

bash "$SCRIPT_DIR/google_metrics/inject_revenue_links.sh" "$POST_ID" 2>&1 || true
bash "$SCRIPT_DIR/google_metrics/request_index.sh" "$POST_URL" 2>&1 || true
bash "$SCRIPT_DIR/google_metrics/request_bing_index.sh" "$POST_URL" 2>&1 || true

# アーカイブ
mkdir -p "$ARCHIVE_DIR"; cp reports/* "$ARCHIVE_DIR/" 2>/dev/null
CONTENT_LENGTH=$(echo "$CONTENT" | sed 's/<[^>]*>//g' | wc -m | tr -d ' ')
cat > "$ARCHIVE_DIR/summary.txt" << SUMMARY
実行ID: $RUN_ID | パイプライン: lifestyle | 日時: $TODAY
記事ID: $POST_ID | URL: $POST_URL | タイトル: $TITLE | 文字数: $CONTENT_LENGTH
SUMMARY
bash "$SCRIPT_DIR/kpop_notify.sh" success "ライフスタイル" "記事投稿完了: $TITLE" "$POST_URL" 2>/dev/null

python3 - << 'KPI_PY' "$SCRIPT_DIR/lib/kpi_logger.py" "$POST_ID" "$TITLE" "$POST_URL" "$SLUG" "$CATEGORY_ID" "$CONTENT_LENGTH"
import sys, importlib.util
try:
    spec = importlib.util.spec_from_file_location("kpi_logger", sys.argv[1])
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    mod.log_post({"post_id": sys.argv[2], "title": sys.argv[3], "url": sys.argv[4],
        "slug": sys.argv[5], "article_type": "lifestyle", "categories": [int(sys.argv[6])],
        "char_count": int(sys.argv[7] or 0), "pipeline": "lifestyle", "has_cta": True})
except: pass
KPI_PY

cleanup_reports_dir

if [[ -n "${POST_ID:-}" ]] && [[ -n "${POST_URL:-}" ]]; then
  env -u AUDIT_LOOP_COUNT bash "$SCRIPT_DIR/post_audit.sh" "$POST_ID" "$POST_URL" "${TITLE:-}" "$RUN_ID" 2>&1 || true
fi

# X投稿（監査通過後のみ）
_WP_STATUS=$(curl -s "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
  -K ~/.wp_auth 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
if [[ "$_WP_STATUS" == "publish" ]]; then
  bash "$SCRIPT_DIR/google_metrics/post_to_x.sh" "$TITLE" "$POST_URL" "" 2>&1 || true
fi

echo ""
echo "========================================"
echo " ✅ ライフスタイルパイプライン完了"
echo " 記事ID: $POST_ID | URL: $POST_URL"
echo " アーカイブ: $ARCHIVE_DIR"
echo "========================================"
