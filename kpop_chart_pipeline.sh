#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── UTF-8 エンコーディング強制（U+FFFD文字化け根本防止） ──
export PYTHONIOENCODING=utf-8
export LANG=${LANG:-en_US.UTF-8}
export LC_ALL=${LC_ALL:-en_US.UTF-8}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# パイプライン排他実行ロック（breaking/strategy/chart 共通）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_GLOBAL_PIPELINE_LOCK="/tmp/kpop_pipeline_global.flock"
exec 9>"$_GLOBAL_PIPELINE_LOCK"
if ! flock -w 300 9; then
  echo "⏭️  他のパイプラインが実行中のため、この起動はスキップします（chart）"
  exit 0
fi

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

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# K-POPチャートランキング記事パイプライン
# 毎週月曜 8:00 自動実行
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

wp_health_check() {
  echo "=== WordPress 接続確認 ==="
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1" \
    -K "$HOME/.wp_auth" \
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

  SIMILARITY=$(claude --no-session-persistence -p "
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

TODAY=$(date '+%Y年%m月%d日')
WEEK=$(date '+%Y年%m月第%V週')
RUN_ID=$(date '+%Y%m%d_%H%M%S')
ARCHIVE_DIR=~/kpop_archives/chart_$RUN_ID

# run_idごとに reports を分離（並列実行時のファイル競合を防止）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
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

claude --no-session-persistence --allowedTools WebSearch --agent zapdos -p "
今日は${TODAY}（${WEEK}）です。
以下の手順でK-POP総合チャートランキング記事を生成せよ。

【検索手順 — 6チャート横断】
1.「Billboard K-POP Hot 100 ${TODAY}」で最新ランキング取得
2.「Melon TOP100 今週 ${TODAY}」で韓国国内チャート取得
3.「Oricon K-POP 週間ランキング ${TODAY}」で日本チャート取得
4.「Spotify K-POP top songs this week ${TODAY}」でSpotifyグローバルK-POPランキング取得
5.「Apple Music K-POP charts ${TODAY}」でApple Musicランキング取得
6.「YouTube Music K-POP trending ${TODAY}」でYouTube Music/MV再生数ランキング取得
7. 今週の記録更新・初登場・急上昇・MV再生回数マイルストーンを確認

【記事構成（必須H2セクション）】
1. 今週のK-POPチャート総まとめ — リード文で最大ハイライト
2. Billboard K-POP Hot 100 — TOP10を表形式（順位・先週比・アーティスト・曲名・注目ポイント）
3. Melon TOP100 韓国国内チャート — TOP10表形式
4. Oricon K-POP 週間ランキング — TOP10表形式
5. Spotify グローバルK-POPランキング — TOP10（ストリーミング数も可能な範囲で）
6. Apple Music / YouTube Music 注目曲 — 各チャートのトピック
7. 今週の注目ポイント5選 — 記録・初登場・急上昇・MV再生数・カムバック
8. 来週の注目カムバック情報 — 予定されているカムバック・リリース
9. まとめ — 今週のK-POPシーン総括

【品質要件】
- タイトルに「${WEEK}」と「Billboard・Melon・Spotify」を含める
- 5000文字以上の充実した内容
- チャートデータは必ず表（<table>）形式で記載
- 各チャートの特徴の違い（国内vs海外、ストリーミングvsダウンロード）を解説
- 末尾に「※本記事は${TODAY}時点の情報です」
- FAQ「よくある質問」（K-POPチャートの見方等）を3問以上含める

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（例：${WEEK} K-POP総合チャートTOP10｜Billboard・Melon・Spotify最新ランキング）
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ
" > reports/chart_0_article.md

if [[ ! -s reports/chart_0_article.md ]]; then
  echo "❌ ザップドス: 出力が空 → 停止"
  log_step "zapdos" "error" "reports/chart_0_article.md" "出力が空"
  exit 1
fi
echo "  ✓ reports/chart_0_article.md ($(wc -c < reports/chart_0_article.md | tr -d ' ') bytes)"
log_step "zapdos" "ok" "reports/chart_0_article.md"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [2] アラカザム: ファクトチェック
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "[2/4] アラカザム: 順位・日付ファクトチェック..."

claude --no-session-persistence --agent alakazam_kpop -p "
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
  log_step "alakazam" "skipped" "reports/chart_1_checked.md" "出力空→フォールバック"
else
  # [ガード] アラカザムがAI内部分析文・定型文を出力した場合はフォールバック
  _ALAKAZAM_CRASH=$(python3 -c "
import sys, re
text = open('reports/chart_1_checked.md', encoding='utf-8', errors='ignore').read()[:300]
CRASH_PATTERNS = [
    r'重大な問題があります',
    r'ファクトチェックを実施します',
    r'内部矛盾.*分析',
    r'ウェブフェッチはできません',
    r'提供してください',
    r'確認させてください',
    r'申し訳ありません',
    r'権限が付与されていません',
    r'記事の元情報.*貼り付け',
    r'ファクトチェック結果をまとめます',
    r'ファクトチェック結果',
    r'以下の問題を発見',
]
for pat in CRASH_PATTERNS:
    if re.search(pat, text):
        print('CRASH')
        sys.exit(1)
sys.exit(0)
" 2>/dev/null; echo $?)
  if [[ "$_ALAKAZAM_CRASH" != "0" ]]; then
    echo "❌ [アラカザム後ガード] AI内部文・定型文を検出 → ザップドス出力にフォールバック"
    echo "  内容冒頭: $(head -c 150 reports/chart_1_checked.md)"
    cp reports/chart_0_article.md reports/chart_1_checked.md
    log_step "alakazam" "skipped" "reports/chart_1_checked.md" "崩壊文検出→フォールバック"
  else
    log_step "alakazam" "ok" "reports/chart_1_checked.md"
  fi
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
# [2026-04-16] ライコウで2行コピー生成（旧来は cut -c1-30 だけでタイトル冒頭が切れて表示されていた）
_CHART_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/generate_thumb_copy.sh
source "$_CHART_DIR/lib/generate_thumb_copy.sh"
_CHART_BODY_FILE="$_CHART_DIR/reports/final_post.md"
[[ ! -s "$_CHART_BODY_FILE" ]] && _CHART_BODY_FILE=""
THUMB_TITLE=$(generate_thumb_copy "$TITLE" "ranking" "$_CHART_BODY_FILE")
echo "  THUMB_TITLE=$THUMB_TITLE"
THUMB_META_FILE=$(mktemp)
python3 "$_CHART_DIR/make_thumbnail.py" "$THUMB_TITLE" --genre ranking --title "$TITLE" 2>"$THUMB_META_FILE"
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
title = '''$TITLE'''
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

DESC=$(echo "$CONTENT" | sed -e 's/<[^>]*>//g' | head -c 120)
echo "$TITLE"   > /tmp/chart_title.txt
echo "$CONTENT" > /tmp/chart_content.txt
echo "$DESC"    > /tmp/chart_desc.txt

# [再発防止] WP投稿直前のサニタイズ（リテラル\n・JSONメタデータ除去）
source "$SCRIPT_DIR/lib/sanitize_output.sh"
sanitize_wp_content /tmp/chart_content.txt
sanitize_wp_content /tmp/chart_title.txt

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

# トークン合計をエクスポート
if [ "${ENABLE_TOKEN_TRACKING:-0}" = "1" ] && [ -f "$TOKEN_LOG" ]; then
  export PIPELINE_TOKEN_COUNT=$(token_total "$TOKEN_LOG")
  echo "  トークン合計: $PIPELINE_TOKEN_COUNT"
fi

RESPONSE=$(curl -s -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/posts \
  -K "$HOME/.wp_auth" \
  -H "Content-Type: application/json" \
  -d "$JSON")

POST_URL=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('link','（URL取得失敗）'))" 2>/dev/null)
POST_ID=$(echo "$RESPONSE"  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null)

if [[ "$POST_ID" =~ ^[0-9]+$ ]]; then
  log_step "wordpress_post" "ok" "reports/chart_1_checked.md" "post_id=$POST_ID"
else
  log_step "wordpress_post" "error" "reports/chart_1_checked.md" "POST_ID不正"
fi

# === AIOSEO description 自動設定（再発防止） ===
if [[ -n "$POST_ID" && "$POST_ID" =~ ^[0-9]+$ ]]; then
  echo "=== AIOSEO description 自動設定 ==="
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
    -K "$HOME/.wp_auth" \
    -H "Content-Type: application/json" \
    -d "{\"meta\":{\"_aioseo_description\": \"$(echo "$AIOSEO_DESC" | sed 's/"/\\"/g')\"}}" > /dev/null 2>&1 \
    && echo "  ✅ AIOSEO description設定完了" || echo "  ⚠️ AIOSEO設定スキップ"
fi

echo "=== 記事構造補完（3行まとめ + プロフィール） ==="
python3 "$SCRIPT_DIR/pipeline/post_publish_enricher.py" --post-id "$POST_ID" 2>&1 || echo "⚠️ 構造補完スキップ"

# [追加 2026-04-11] kpop_pipeline.shとの統一: 内部リンク・GSC・Bing登録が欠落していたため追加
echo "=== 内部リンク自動挿入 ==="
if [ -n "${POST_URL:-}" ]; then
  _SLUG_PATH=$(echo "$POST_URL" | sed 's|https://www.kpopjournal.tokyo||' | sed 's|/$||')
  bash "$SCRIPT_DIR/google_metrics/add_internal_links.sh" "$_SLUG_PATH" 2>&1 || echo "⚠️ 内部リンクスキップ"
fi

echo "=== Google Indexing API ==="
bash "$SCRIPT_DIR/google_metrics/request_index.sh" "$POST_URL" 2>&1 || echo "⚠️ Google インデックススキップ"

echo "=== Bing URL Submission ==="
bash "$SCRIPT_DIR/google_metrics/request_bing_index.sh" "$POST_URL" 2>&1 || echo "⚠️ Bing インデックススキップ"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [4] ペルシアン: SNS拡散戦略
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "[4/4] ペルシアン: SNS拡散戦略..."

claude --no-session-persistence --agent persian -p "
今日は${TODAY}です。
以下のK-POPチャートランキング記事が投稿されました。SNS拡散戦略を設計せよ。

【記事タイトル】$TITLE
【記事URL】$POST_URL
【概要】${WEEK}の最新K-POPチャートランキング記事

X投稿文3パターン・推奨ハッシュタグセット・最適投稿タイミング・採用推奨パターンを出力せよ。
" > reports/chart_2_sns.md
log_step "persian" "ok" "reports/chart_2_sns.md"

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
X投稿       : (監査後に実行)
SUMMARY

bash ~/kpop_notify.sh success "チャート" "記事投稿完了: $TITLE" "$POST_URL" 2>/dev/null

# クリーンアップ: run専用reportsディレクトリを削除
if [[ -n "${REPORTS_DIR:-}" ]] && [[ -d "$REPORTS_DIR" ]]; then
  rm -rf "$REPORTS_DIR"
fi
if [[ -L "$SCRIPT_DIR/reports" ]]; then
  rm -f "$SCRIPT_DIR/reports"
elif [[ -d "$SCRIPT_DIR/reports" ]]; then
  rm -rf "$SCRIPT_DIR/reports"
fi
# news-sitemap.xml 復元
mkdir -p "$SCRIPT_DIR/reports" 2>/dev/null || true
ln -sf "$SCRIPT_DIR/static/news-sitemap.xml" "$SCRIPT_DIR/reports/news-sitemap.xml" 2>/dev/null || true

echo ""
echo "========================================"
echo " ✅ チャートランキング記事投稿完了"
echo " 記事ID  : $POST_ID"
echo " URL     : $POST_URL"
echo " アーカイブ: $ARCHIVE_DIR"
echo "========================================"

# ─── 投稿後自動監査 ────────────────────────────────────────────────────────
echo "=== 投稿後自動監査 ==="
if [[ -n "${POST_ID:-}" ]] && [[ -n "${POST_URL:-}" ]]; then
  env -u AUDIT_LOOP_COUNT bash "$SCRIPT_DIR/post_audit.sh" "$POST_ID" "$POST_URL" "${TITLE:-}" "${RUN_ID:-}" 2>&1 || true
fi

# X/Twitter 自動投稿（監査通過後のみ）
echo "=== X/Twitter 自動投稿 ==="
X_POST_LOG="/home/aiuser/kpop-ai-system/logs/x_post.log"
_WP_STATUS_NOW=$(curl -s "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
  -K ~/.wp_auth 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")
if [[ "$_WP_STATUS_NOW" == "publish" ]]; then
  X_POST_RESULT=$(bash "$SCRIPT_DIR/google_metrics/post_to_x.sh" "$TITLE" "$POST_URL" "reports/chart_2_sns.md" 2>&1) || {
    echo "X投稿スキップ (エラーはログ参照: $X_POST_LOG)"
    X_POST_RESULT="X投稿失敗"
  }
  X_TWEET_URL=$(echo "$X_POST_RESULT" | grep -oP 'https://x\.com/\S+' | head -1 || true)
  if [ -n "$X_TWEET_URL" ]; then
    echo "X投稿成功: $X_TWEET_URL"
  elif echo "$X_POST_RESULT" | grep -q "DRY-RUN"; then
    echo "X投稿: DRY-RUN（テストモード）"
  fi
else
  echo "X投稿スキップ: 記事ステータスが publish ではありません ($_WP_STATUS_NOW)"
fi
