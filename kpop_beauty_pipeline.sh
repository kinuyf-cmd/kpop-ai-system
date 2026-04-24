#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 美容・コスメ記事パイプライン
# beautywriter（記事生成）+ mewtwo_cosme（戦略統括）を接続
# 毎日 11:00 自動実行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/env_loader.sh"
export PYTHONIOENCODING=utf-8
export LANG=${LANG:-en_US.UTF-8}
export LC_ALL=${LC_ALL:-en_US.UTF-8}
source "$SCRIPT_DIR/lib/sanitize_output.sh"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# パイプライン排他実行ロック（共通）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_GLOBAL_PIPELINE_LOCK="/tmp/kpop_pipeline_global.flock"
exec 9>"$_GLOBAL_PIPELINE_LOCK"
if ! flock -w 300 9; then
  echo "⏭️  他のパイプラインが実行中のため、この起動はスキップします（beauty）"
  exit 0
fi

# トークントラッキング
if [ "${ENABLE_TOKEN_TRACKING:-0}" = "1" ]; then
  source "$SCRIPT_DIR/lib/claude_wrapper.sh"
fi

# パイプラインログ
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
  if [[ -n "$file" && -f "$file" ]]; then
    sz=$(wc -c < "$file")
  else
    sz=0
  fi
  msg="${msg//\\/\\\\}"
  msg="${msg//\"/\\\"}"
  printf '{"timestamp":"%s","run_id":"%s","pipeline":"beauty","step":"%s","status":"%s","file":"%s","size_bytes":%d,"message":"%s"}\n' \
    "$ts" "$RUN_ID" "$step" "$status" "$file" "$sz" "$msg" >> "$PIPELINE_JSONL"
}

# run_idごとに reports を分離
REPORTS_DIR="$SCRIPT_DIR/reports_${RUN_ID}"
mkdir -p "$REPORTS_DIR"
if [[ -L "$SCRIPT_DIR/reports" ]]; then
  rm -f "$SCRIPT_DIR/reports"
elif [[ -d "$SCRIPT_DIR/reports" ]]; then
  rm -rf "$SCRIPT_DIR/reports"
fi
ln -sfn "$REPORTS_DIR" "$SCRIPT_DIR/reports"
ln -sf "$SCRIPT_DIR/static/news-sitemap.xml" "$REPORTS_DIR/news-sitemap.xml" 2>/dev/null || true
export TOKEN_LOG="$ARCHIVE_DIR/token_usage.jsonl"

check_output() {
  local file="$1"
  local step="$2"
  if [[ ! -s "$file" ]]; then
    echo "❌ [$step] 出力が空 → パイプライン停止"
    log_step "$step" "error" "$file" "出力が空"
    archive_and_exit 1
  fi
  local _sz
  _sz=$(wc -c < "$file" 2>/dev/null || echo 0)
  if [[ "$_sz" -lt 500 ]]; then
    echo "❌ [$step] 出力が極小 (${_sz}bytes < 500) → パイプライン停止"
    log_step "$step" "error" "$file" "出力極小: ${_sz}bytes"
    archive_and_exit 1
  fi
  if grep -qE '申し訳ありません[がで。、 ]|申し訳ありません$|お手伝いできますか|許可してください|許可が必要です|入力記事が見当たりません|記事を提供してください|ウェブフェッチはできません|元の記事が提供されていません' "$file"; then
    echo "❌ [$step] エラー応答を検出 → パイプライン停止"
    log_step "$step" "error" "$file" "エラー応答検出"
    archive_and_exit 1
  fi
  echo "  ✓ [$step] OK ($(wc -c < "$file" | tr -d ' ') bytes)"
  log_step "$step" "ok" "$file"
}

cleanup_reports_dir() {
  if [[ -n "${REPORTS_DIR:-}" ]] && [[ -d "$REPORTS_DIR" ]]; then
    rm -rf "$REPORTS_DIR"
  fi
  if [[ -L "$SCRIPT_DIR/reports" ]]; then
    local _link_target
    _link_target=$(readlink "$SCRIPT_DIR/reports" 2>/dev/null || echo "")
    if [[ -z "${REPORTS_DIR:-}" ]] || [[ "$_link_target" == "$REPORTS_DIR" ]] || [[ ! -e "$_link_target" ]]; then
      rm -f "$SCRIPT_DIR/reports"
    fi
  elif [[ -d "$SCRIPT_DIR/reports" ]]; then
    rm -rf "$SCRIPT_DIR/reports"
  fi
  # news-sitemap.xml 復元
  mkdir -p "$SCRIPT_DIR/reports" 2>/dev/null || true
  ln -sf "$SCRIPT_DIR/static/news-sitemap.xml" "$SCRIPT_DIR/reports/news-sitemap.xml" 2>/dev/null || true
}

archive_and_exit() {
  local code="${1:-1}"
  if [[ -n "$ARCHIVE_DIR" ]]; then
    mkdir -p "$ARCHIVE_DIR"
    cp reports/* "$ARCHIVE_DIR/" 2>/dev/null
    cat > "$ARCHIVE_DIR/summary.txt" << SUMMARY
実行ID      : $RUN_ID
パイプライン: beauty
日時        : $TODAY
判定        : 停止
SUMMARY
    echo "  アーカイブ保存: $ARCHIVE_DIR"
  fi
  cleanup_reports_dir
  bash "$SCRIPT_DIR/kpop_notify.sh" error "美容" "パイプライン停止 (RUN: $RUN_ID)" 2>/dev/null
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
  SIMILARITY=$(claude --no-session-persistence -p "
【タスク】類似記事重複チェック
新タイトルが過去${days}日間の投稿済みタイトルと重複しているか判定せよ。
【新タイトル】${title}
【過去${days}日間の投稿済みタイトル】
${RECENT_TITLES}
【判定基準】
- 美容・スキンケア・ガラス肌・韓国コスメ・Kビューティ系記事が過去${days}日に既に1本以上ある → 重複（YES）
- 同じ商品・同じテーマ → 重複（YES）
- 別テーマ → 重複なし（NO）
【出力ルール】YESまたはNOの1単語のみ。
")
  if [[ "$SIMILARITY" == "YES" ]]; then
    echo "  ⚠️  重複あり → スキップ"
    archive_and_exit 0
  fi
  echo "  ✓ 重複なし"
}

echo "========================================"
echo " 美容・コスメパイプライン 開始: $TODAY"
echo " 実行ID: $RUN_ID"
echo "========================================"

wp_health_check
log_step "start" "ok" "" "beauty pipeline start"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 1: mewtwo_cosme — 美容テーマ戦略立案
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ PHASE 1: mewtwo_cosme — 美容テーマ戦略 ━━━"

echo "[1/7] mewtwo_cosme: 美容コンテンツ戦略..."
claude --no-session-persistence --allowedTools WebSearch --agent mewtwo_cosme -p "
今日は${TODAY}です。
あなたは美容メディア戦略責任者です。WebSearchで最新の韓国美容・コスメトレンドを調査し、
今日書くべき美容記事のテーマを1つ決定してbeautywriterへの制作指示を作成せよ。

検索手順：
1.「韓国コスメ 2026 トレンド 人気」
2.「K-POP アイドル スキンケア 愛用 ${TODAY}」
3.「韓国 美容 新商品 話題」

【出力内容】
- 記事テーマ（1つに絞る）
- ターゲットキーワード（メイン1個 + サブ3個）
- 記事構成案（H2 4〜6個）
- beautywriterへの制作指示（具体的に）
- 差別化ポイント
- 推奨文字数: 2000〜3000文字
" > reports/1_beauty_strategy.md
sanitize_output reports/1_beauty_strategy.md

# 空出力リトライ
if [[ ! -s reports/1_beauty_strategy.md ]]; then
  echo "  ⚠️ mewtwo_cosme空出力 → 30秒待機後リトライ..."
  sleep 30
  claude --no-session-persistence --allowedTools WebSearch --agent mewtwo_cosme -p "
今日は${TODAY}です。WebSearchで韓国コスメの最新トレンドを調査し、記事テーマを1つ決定してbeautywriterへの制作指示を出力せよ。
検索語: 「韓国コスメ トレンド 2026」「アイドル スキンケア 人気」
出力: テーマ・キーワード・H2構成・制作指示・差別化ポイント
" > reports/1_beauty_strategy.md
  sanitize_output reports/1_beauty_strategy.md
fi
check_output reports/1_beauty_strategy.md "mewtwo_cosme"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 2: beautywriter — 記事生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ PHASE 2: beautywriter — 記事生成 ━━━"

echo "[2/7] beautywriter: 美容記事生成..."
claude --no-session-persistence --allowedTools WebSearch --agent beautywriter -p "
今日は${TODAY}です。
以下のmewtwo_cosme（美容戦略責任者）の制作指示に従い、韓国美容・コスメ記事を生成せよ。

【制作指示（mewtwo_cosme）】
$(cat reports/1_beauty_strategy.md)

【生成ルール】
- 必ずWebSearchで最新の商品情報・成分・口コミを調査してから書く
- 架空の商品名・成分・価格は絶対に書かない
- 2000〜3000文字（HTMLタグ除く）
- 各H2に具体的な商品名・成分名・数字を最低1つ含める
- 末尾に「※本記事は${TODAY}時点の情報です」を明記

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（マークダウン・説明文禁止）
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ（2000文字以上）
" > reports/2_beauty_article.md
sanitize_output reports/2_beauty_article.md
check_output reports/2_beauty_article.md "beautywriter"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 3: 品質チェック（アラカザム + ゲンガー）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ PHASE 3: 品質チェック ━━━"

echo "[3/7] アラカザム: ファクトチェック..."
claude --no-session-persistence --agent alakazam_kpop -p "
今日は${TODAY}です。
以下の美容記事の事実・成分名・価格・効果の正確性を確認し、必要箇所のみ修正せよ。

【記事】
$(cat reports/2_beauty_article.md)

【チェック優先順位】
1. 商品名・ブランド名が実在するか
2. 成分名・効果の記述が正確か
3. 価格情報が最新か（古い場合は「公式サイトで確認」に変更）
4. アイドルの愛用情報が確認可能か

【出力形式・絶対厳守】
1行目：タイトル文字列のみ
2行目：空行
3行目以降：修正済みHTML本文のみ
" > reports/3_beauty_checked.md
sanitize_output reports/3_beauty_checked.md
check_output reports/3_beauty_checked.md "アラカザム"

echo "[4/7] ゲンガー: SEO品質監査..."
claude --no-session-persistence --agent gengar -p "
今日は${TODAY}です。
以下の美容記事のSEO・コンテンツ品質を最終監査し、修正できる問題は自分で修正せよ。

【記事】
$(cat reports/3_beauty_checked.md)

監査サマリー・修正箇所・最終判定を出力し、
OKまたは要確認の場合のみ以下の形式で最終記事を出力：
1行目：タイトルのみ
2行目：空行
3行目以降：HTML本文のみ
" > reports/4_beauty_audited.md
sanitize_output reports/4_beauty_audited.md
check_output reports/4_beauty_audited.md "ゲンガー"

if grep -q '❌ 投稿停止' reports/4_beauty_audited.md; then
  echo "❌ ゲンガーが投稿停止を判定 → パイプライン停止"
  archive_and_exit 1
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 4: CVR最適化 + 記事タイプ付与
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ PHASE 4: CVR最適化 ━━━"

echo "[5/7] カイリュー: CVR・回遊最適化..."
# ゲンガー出力から記事部分を抽出
ARTICLE_LINE=$(grep -n '^<h2>' reports/4_beauty_audited.md | head -1 | cut -d: -f1)
if [[ -n "$ARTICLE_LINE" ]]; then
  TITLE_LINE=$((ARTICLE_LINE - 2))
  [[ $TITLE_LINE -lt 1 ]] && TITLE_LINE=1
  sed -n "${TITLE_LINE}p" reports/4_beauty_audited.md > /tmp/beauty_article.md
  echo "" >> /tmp/beauty_article.md
  tail -n "+${ARTICLE_LINE}" reports/4_beauty_audited.md >> /tmp/beauty_article.md
else
  cp reports/4_beauty_audited.md /tmp/beauty_article.md
fi

_KAIRYU_INPUT_SZ=$(wc -c < /tmp/beauty_article.md 2>/dev/null || echo 0)
claude --no-session-persistence --agent kairyu_kpop -p "
今日は${TODAY}です。
以下の美容記事にCVR・回遊導線を追加せよ。

【記事】
$(cat /tmp/beauty_article.md)

【改善指示】
1. 記事タイプ付与: <p class=\"article-type guide\">【ビューティ】</p>
2. CTAボックスを2箇所に配置（中盤・末尾）
3. 関連記事リンクを中盤と末尾に配置
4. 末尾にSNSシェア促進を追加

【出力形式・絶対厳守】
1行目：タイトル文字列のみ
2行目：空行
3行目以降：改善済みHTML本文のみ
【絶対禁止】改善内容の説明・まとめ・コメントを出力しないこと。記事HTML全文をそのまま出力すること。
" > reports/5_beauty_final.md
sanitize_output reports/5_beauty_final.md
# [カイリュー出力ガード] HTML記事ではなくメタ解説を出力した場合は入力記事にフォールバック
_KAIRYU_SZ=$(wc -c < reports/5_beauty_final.md 2>/dev/null || echo 0)
_KAIRYU_HTML_TAGS=$(grep -c '<h[2-6]\|<p[ >]\|<div\|<table\|<ul' reports/5_beauty_final.md 2>/dev/null || echo 0)
if [[ "$_KAIRYU_SZ" -lt $((_KAIRYU_INPUT_SZ / 2)) ]] || [[ "$_KAIRYU_HTML_TAGS" -lt 3 ]]; then
  echo "  ⚠️ [カイリュー出力ガード] 記事HTML不足(${_KAIRYU_SZ}bytes, HTMLタグ${_KAIRYU_HTML_TAGS}個) → 入力記事(${_KAIRYU_INPUT_SZ}bytes)にフォールバック"
  cp /tmp/beauty_article.md reports/5_beauty_final.md
  log_step "kairyu" "warn" "reports/5_beauty_final.md" "メタ解説出力→フォールバック"
fi
check_output reports/5_beauty_final.md "カイリュー"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PHASE 5: final_post.md 生成・投稿
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "━━━ PHASE 5: 投稿 ━━━"

# final_post.md 生成
python3 - <<'PY'
from pathlib import Path
import re
src = Path("reports/5_beauty_final.md")
dst = Path("reports/final_post.md")
text = src.read_text(encoding="utf-8", errors="ignore")
lines = text.splitlines()
html_idx = None
for i, line in enumerate(lines):
    if re.match(r'\s*<(h[1-6]|p[ >]|ul|ol|div|hr|blockquote)', line, re.IGNORECASE):
        html_idx = i
        break
if html_idx is not None:
    title_idx = None
    for j in range(html_idx - 1, -1, -1):
        s = lines[j].strip()
        if not s: continue
        if not s.startswith("<"):
            title_idx = j
            break
    start = title_idx if title_idx is not None else html_idx
    cleaned = "\n".join(lines[start:]).strip() + "\n"
else:
    cleaned = text.strip() + "\n"
dst.write_text(cleaned, encoding="utf-8")
PY

echo "  ✓ reports/final_post.md 生成完了"

TITLE=$(head -n 1 reports/final_post.md)
CONTENT=$(tail -n +2 reports/final_post.md)

check_duplicate "$TITLE" 5

# タイトル品質チェック
if [[ -z "$TITLE" ]] || [[ "${#TITLE}" -lt 10 ]]; then
  echo "❌ タイトル異常 → 投稿停止"
  archive_and_exit 1
fi

# 本文品質チェック
CONTENT_SIZE=$(echo "$CONTENT" | wc -c)
if [[ "$CONTENT_SIZE" -lt 3000 ]]; then
  echo "❌ 本文サイズ不足 (${CONTENT_SIZE}bytes) → 投稿停止"
  archive_and_exit 1
fi

# カテゴリ: 美容=12
CATEGORY_ID=12

# スラッグ生成
SLUG=$(python3 "$SCRIPT_DIR/lib/slug_generator.py" "$TITLE" 2>/dev/null || python3 "$SCRIPT_DIR/lib/slug.py" "$TITLE" 2>/dev/null || echo "kpop-beauty-$(date +%Y%m%d)")
if [[ "$SLUG" =~ ^[0-9] ]]; then
  SLUG="kpop-${SLUG}"
fi
echo "  slug: $SLUG"

# タグ自動判定
TAG_NAMES=$(python3 - << 'PY' "$TITLE"
import sys
title = sys.argv[1].lower()
rules = [
    ('韓国コスメ', ['コスメ','化粧品','メイク','ファンデ','リップ','クッション']),
    ('スキンケア', ['スキンケア','美容液','保湿','クレンジング','洗顔','化粧水','ガラス肌']),
    ('Kビューティ', ['韓国美容','kビューティ','k-beauty']),
]
matched = [tag for tag, kws in rules if any(w in title for w in kws)]
if not matched:
    matched = ['韓国コスメ']
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
        with urllib.request.urlopen(req) as res:
            tag_ids.append(str(json.loads(res.read())["id"]))
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
# サムネイル生成
echo "[6/7] サムネイル生成..."
THUMB_RESULT=$(python3 "$SCRIPT_DIR/make_thumbnail.py" --title "$TITLE" --genre beauty 2>&1) || true
MEDIA_ID=$(echo "$THUMB_RESULT" | grep -oP 'media_id=\K[0-9]+' | head -1 || echo "0")
echo "  MEDIA_ID=${MEDIA_ID:-0}"

JSON=$(python3 - << 'PY' "$SLUG" "$CATEGORY_ID" "${MEDIA_ID:-0}" "" "$TAG_IDS"
import json, sys
slug = sys.argv[1]
main_category = int(sys.argv[2])
media_id = int(sys.argv[3]) if sys.argv[3] else 0
artist_ids_raw = sys.argv[4].strip()
tag_ids_raw = sys.argv[5].strip()
with open("/tmp/kpop_title.txt", encoding='utf-8', errors='ignore') as f: title = f.read().strip()
with open("/tmp/kpop_content.txt", encoding='utf-8', errors='ignore') as f: content = f.read().strip()
with open("/tmp/kpop_desc.txt", encoding='utf-8', errors='ignore') as f: desc = f.read().strip()
categories = [main_category]
tags = [int(x.strip()) for x in tag_ids_raw.split(",") if x.strip()] if tag_ids_raw else []
data = {'title': title, 'content': content, 'status': 'publish',
        'slug': slug, 'categories': categories, 'tags': tags, 'excerpt': desc}
if media_id > 0:
    data['featured_media'] = media_id
print(json.dumps(data, ensure_ascii=False))
PY
)

# 投稿前バリデーション
echo "=== 投稿前バリデーション ==="
if ! echo "$JSON" | python3 "$SCRIPT_DIR/lib/validate_post.py"; then
  echo "❌ バリデーション失敗 → 投稿中止"
  archive_and_exit 1
fi

echo "=== ダークライ権利監査 ==="
if ! echo "$JSON" | python3 "$SCRIPT_DIR/lib/darkrai_audit.py"; then
  echo "❌ 権利監査失敗 → 投稿中止"
  archive_and_exit 1
fi

RESPONSE=$(curl -s -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/posts \
  -K ~/.wp_auth \
  -H "Content-Type: application/json" \
  -d "$JSON")

POST_URL=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('link',''))" 2>/dev/null)
POST_ID=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null)

if [[ -n "$POST_ID" && "$POST_ID" =~ ^[0-9]+$ ]]; then
  log_step "wordpress_post" "ok" "reports/final_post.md" "post_id=$POST_ID"
  echo "  ✅ 投稿成功: POST_ID=$POST_ID"
else
  log_step "wordpress_post" "error" "reports/final_post.md" "POST_ID取得失敗"
  echo "  ❌ 投稿失敗"
  archive_and_exit 1
fi

# AIOSEO description
if [[ -n "$POST_ID" && "$POST_ID" =~ ^[0-9]+$ ]]; then
  AIOSEO_DESC=$(echo "$CONTENT" | sed -e 's/<[^>]*>//g' | python3 -c "
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
    -K ~/.wp_auth \
    -H "Content-Type: application/json" \
    -d "{\"meta\":{\"_aioseo_description\": \"$(echo "$AIOSEO_DESC" | sed 's/"/\\"/g')\"}}" > /dev/null 2>&1 \
    && echo "  ✅ AIOSEO description設定完了" || echo "  ⚠️ AIOSEO設定スキップ"

echo "=== 記事構造補完（3行まとめ + プロフィール） ==="
python3 "$SCRIPT_DIR/pipeline/post_publish_enricher.py" --post-id "$POST_ID" 2>&1 || echo "⚠️ 構造補完スキップ"
fi

# ABEMA CTA・収益導線
echo "=== 収益導線自動挿入 ==="
bash "$SCRIPT_DIR/google_metrics/inject_revenue_links.sh" "$POST_ID" 2>&1 || echo "⚠️ 収益導線スキップ"

# インデックス登録
echo "=== Google Indexing API ==="
bash "$SCRIPT_DIR/google_metrics/request_index.sh" "$POST_URL" 2>&1 || echo "⚠️ Google インデックススキップ"
echo "=== Bing URL Submission ==="
bash "$SCRIPT_DIR/google_metrics/request_bing_index.sh" "$POST_URL" 2>&1 || echo "⚠️ Bing インデックススキップ"

# SNS
echo "[7/7] ペルシアン: SNS拡散..."
claude --no-session-persistence --agent persian -p "
今日は${TODAY}です。
以下の美容記事が投稿されました。SNS拡散戦略を設計せよ。
【記事タイトル】$TITLE
【記事URL】$POST_URL
X投稿文3パターン・推奨ハッシュタグ・最適投稿タイミングを出力せよ。
" > reports/6_sns.md 2>/dev/null
sanitize_output reports/6_sns.md

# アーカイブ
mkdir -p "$ARCHIVE_DIR"
cp reports/* "$ARCHIVE_DIR/" 2>/dev/null
CONTENT_LENGTH=$(echo "$CONTENT" | sed 's/<[^>]*>//g' | wc -m | tr -d ' ')
cat > "$ARCHIVE_DIR/summary.txt" << SUMMARY
実行ID      : $RUN_ID
パイプライン: beauty
日時        : $TODAY
記事ID      : $POST_ID
URL         : $POST_URL
タイトル    : $TITLE
文字数      : $CONTENT_LENGTH
判定        : 投稿OK
SUMMARY

bash "$SCRIPT_DIR/kpop_notify.sh" success "美容" "記事投稿完了: $TITLE" "$POST_URL" 2>/dev/null

# KPIログ
python3 - << 'KPI_PY' "$SCRIPT_DIR/lib/kpi_logger.py" "$POST_ID" "$TITLE" "$POST_URL" "$SLUG" "$CATEGORY_ID" "$CONTENT_LENGTH"
import json, sys, importlib.util
logger_path = sys.argv[1]
data = {
    "post_id": sys.argv[2], "title": sys.argv[3], "url": sys.argv[4],
    "slug": sys.argv[5], "article_type": "beauty",
    "categories": [int(sys.argv[6])], "char_count": int(sys.argv[7] or 0),
    "pipeline": "beauty", "has_cta": True, "has_thumbnail": True,
}
try:
    spec = importlib.util.spec_from_file_location("kpi_logger", logger_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.log_post(data)
except Exception:
    pass
KPI_PY

cleanup_reports_dir

# 投稿後自動監査
if [[ -n "${POST_ID:-}" ]] && [[ -n "${POST_URL:-}" ]]; then
  env -u AUDIT_LOOP_COUNT bash "$SCRIPT_DIR/post_audit.sh" "$POST_ID" "$POST_URL" "${TITLE:-}" "$RUN_ID" 2>&1 || true
fi

# X投稿（監査通過後のみ）
_WP_STATUS_NOW=$(curl -s "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
  -K ~/.wp_auth 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")
if [[ "$_WP_STATUS_NOW" == "publish" ]]; then
  bash "$SCRIPT_DIR/google_metrics/post_to_x.sh" "$TITLE" "$POST_URL" "reports/6_sns.md" 2>&1 || echo "⚠️ X投稿スキップ"
fi

echo ""
echo "========================================"
echo " ✅ 美容パイプライン完了"
echo " 記事ID  : $POST_ID"
echo " URL     : $POST_URL"
echo " アーカイブ: $ARCHIVE_DIR"
echo "========================================"
