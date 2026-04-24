#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# K-POPチャート速報（ミッドウィーク更新）パイプライン
# 毎週木曜 8:00 自動実行 — 週中のチャート変動速報記事を生成
#
# 月曜の週次総合記事（kpop_chart_pipeline.sh）を補完する速報版
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/env_loader.sh"

# パイプライン排他ロック
_GLOBAL_PIPELINE_LOCK="/tmp/kpop_pipeline_global.flock"
exec 9>"$_GLOBAL_PIPELINE_LOCK"
if ! flock -n 9; then
  echo "⏭️  他のパイプラインが実行中のため、この起動はスキップします（chart_midweek）"
  exit 0
fi

# 1日最大投稿数チェック
_DAILY_MAX="${DAILY_POST_LIMIT:-15}"
_TODAY=$(date +%Y-%m-%d)
_KPI_LOG="$SCRIPT_DIR/logs/kpi_posts.jsonl"
_TODAY_COUNT=0
if [[ -f "$_KPI_LOG" ]]; then
  _TODAY_COUNT=$(grep -c "\"date\": \"${_TODAY}\"" "$_KPI_LOG" 2>/dev/null) || _TODAY_COUNT=0
fi
if [[ "$_TODAY_COUNT" -ge "$_DAILY_MAX" ]]; then
  echo "⛔ 本日の投稿上限（${_DAILY_MAX}本）に達しています" >&2
  exit 0
fi

# パイプラインログ
PIPELINE_JSONL="$SCRIPT_DIR/logs/pipeline.jsonl"
mkdir -p "$SCRIPT_DIR/logs"

log_step() {
  local step="$1" status="$2" file="${3:-}" msg="${4:-}"
  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  msg="${msg//\\/\\\\}"
  msg="${msg//\"/\\\"}"
  printf '{"timestamp":"%s","run_id":"%s","pipeline":"chart_midweek","step":"%s","status":"%s","file":"%s","message":"%s"}\n' \
    "$ts" "${RUN_ID:-unknown}" "$step" "$status" "$file" "$msg" >> "$PIPELINE_JSONL"
}

TODAY=$(date '+%Y年%m月%d日')
WEEK=$(date '+%Y年%m月第%V週')
RUN_ID=$(date '+%Y%m%d_%H%M%S')
ARCHIVE_DIR=~/kpop_archives/chart_mid_$RUN_ID

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

echo "========================================"
echo " K-POPチャート速報（ミッドウィーク）"
echo " 実行日: $TODAY"
echo "========================================"

# WordPress接続確認
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1" \
  -K "$HOME/.wp_auth" \
  --connect-timeout 10 --max-time 15)
if [[ "$HTTP_CODE" != "200" ]]; then
  echo "❌ WordPress API 接続失敗 (HTTP ${HTTP_CODE}) → 停止"
  exit 1
fi
echo "  ✓ WordPress API 正常"

log_step "start" "ok" "" "midweek chart pipeline"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [1] チャート速報記事生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "[1/3] チャート速報記事生成..."

claude --no-session-persistence --allowedTools WebSearch --agent zapdos -p "
今日は${TODAY}（${WEEK}・ミッドウィーク）です。
K-POPチャート速報記事を生成せよ。週中の注目変動にフォーカスする。

【検索手順】
1.「K-POP chart update midweek ${TODAY}」で週中チャート変動を検索
2.「Spotify K-POP daily chart ${TODAY}」でリアルタイムストリーミング動向を検索
3.「K-POP comeback new release this week ${TODAY}」で今週のカムバック・新曲情報を検索
4.「K-POP MV views milestone ${TODAY}」でMV再生数の注目マイルストーンを検索

【記事構成（必須H2セクション）】
1. 今週のK-POPチャート速報 — ミッドウィーク注目変動まとめ
2. 急上昇・初登場曲 — 今週注目の新曲・急上昇曲（3〜5曲）
3. ストリーミング動向 — Spotify/Apple Musicのリアルタイム注目曲
4. MV再生数マイルストーン — 億回再生達成などの記録
5. 今週のカムバック・新曲 — リリース済み＆予定の新曲情報
6. 週末に向けた注目ポイント — 週末のランキング予想
7. まとめ

【品質要件】
- 2500文字以上
- 速報感のあるテンポの良い文体
- 末尾に「※本記事は${TODAY}時点の速報です。週間確定ランキングは月曜更新予定」
- FAQ2問以上

【出力形式・絶対厳守】
1行目：タイトル文字列のみ（例：${WEEK} K-POPチャート速報｜急上昇・新曲・注目の動きをチェック）
2行目：空行
3行目以降：<h2>から始まるHTML本文のみ
" > reports/chart_mid_0_article.md

if [[ ! -s reports/chart_mid_0_article.md ]]; then
  echo "❌ 出力が空 → 停止"
  log_step "zapdos_mid" "error" "reports/chart_mid_0_article.md" "出力が空"
  exit 1
fi
echo "  ✓ reports/chart_mid_0_article.md ($(wc -c < reports/chart_mid_0_article.md | tr -d ' ') bytes)"
log_step "zapdos_mid" "ok" "reports/chart_mid_0_article.md"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [2] 品質チェック・投稿
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "[2/3] 品質チェック・投稿..."

TITLE=$(head -n 1 reports/chart_mid_0_article.md)
CONTENT=$(tail -n +2 reports/chart_mid_0_article.md)

if [[ -z "$TITLE" ]] || [[ "$TITLE" == "#"* ]]; then
  echo "❌ 品質NG: タイトル異常 → 停止"
  exit 1
fi
# zapdos の前置き文混入チェック（「必要な情報」「記事を生成」等はタイトルとして無効）
if echo "$TITLE" | grep -qE "^(必要な情報|記事を生成|情報が揃|チャートデータ|ランキングを生成|生成します|了解|わかりました|承知)"; then
  echo "❌ 品質NG: zapdos前置き文がタイトルに混入 → 停止 (TITLE=$TITLE)"
  exit 1
fi

CONTENT_LENGTH=$(python3 -c "import sys; print(len(sys.argv[1]))" "$CONTENT")
if [ "$CONTENT_LENGTH" -lt 500 ]; then
  echo "❌ 品質NG: 本文${CONTENT_LENGTH}文字 → 停止"
  exit 1
fi
echo "✅ 品質OK（${CONTENT_LENGTH}文字）"

# サムネイル生成
source "$SCRIPT_DIR/lib/generate_thumb_copy.sh"
THUMB_TITLE=$(generate_thumb_copy "$TITLE" "ranking" "")
python3 "$SCRIPT_DIR/make_thumbnail.py" "$THUMB_TITLE" --genre ranking --title "$TITLE" 2>/dev/null

MEDIA_ID=0
if [[ -f thumbnail.jpg ]]; then
  MEDIA_RESPONSE=$(curl -s -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/media \
    -K "$HOME/.wp_auth" \
    -H "Content-Disposition: attachment; filename=thumbnail.jpg" \
    -H "Content-Type: image/jpeg" \
    --data-binary @thumbnail.jpg)
  MEDIA_ID=$(echo "$MEDIA_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',0))" 2>/dev/null || echo 0)
  echo "  メディアID: $MEDIA_ID"
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
  fi
fi

DESC=$(echo "$CONTENT" | sed -e 's/<[^>]*>//g' | head -c 120)
echo "$TITLE"   > /tmp/chart_mid_title.txt
echo "$CONTENT" > /tmp/chart_mid_content.txt
echo "$DESC"    > /tmp/chart_mid_desc.txt

JSON=$(python3 - << 'PY' "$MEDIA_ID"
import json, sys
media_id = int(sys.argv[1])
with open("/tmp/chart_mid_title.txt")   as f: title   = f.read().strip()
with open("/tmp/chart_mid_content.txt") as f: content = f.read().strip()
with open("/tmp/chart_mid_desc.txt")    as f: desc    = f.read().strip()

data = {
    'title': title,
    'content': content,
    'status': 'publish',
    'categories': [71],
    'excerpt': desc
}
if media_id > 0:
    data['featured_media'] = media_id

print(json.dumps(data, ensure_ascii=False))
PY
)

RESPONSE=$(curl -s -X POST https://www.kpopjournal.tokyo/wp-json/wp/v2/posts \
  -K "$HOME/.wp_auth" \
  -H "Content-Type: application/json" \
  -d "$JSON")

POST_URL=$(echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('link',''))" 2>/dev/null)
POST_ID=$(echo "$RESPONSE"  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null)

if [[ "$POST_ID" =~ ^[0-9]+$ ]]; then
  log_step "wordpress_post" "ok" "" "post_id=$POST_ID"
  echo "  ✅ 投稿完了: ID=$POST_ID URL=$POST_URL"
else
  log_step "wordpress_post" "error" "" "投稿失敗"
  echo "  ❌ 投稿失敗"
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
    -K "$HOME/.wp_auth" \
    -H "Content-Type: application/json" \
    -d "{\"meta\":{\"_aioseo_description\": \"$(echo "$AIOSEO_DESC" | sed 's/"/\\"/g')\"}}" > /dev/null 2>&1
fi

# インデックス登録
echo "=== Google/Bing インデックス登録 ==="
bash "$SCRIPT_DIR/google_metrics/request_index.sh" "$POST_URL" 2>&1 || echo "⚠️ Google インデックススキップ"
bash "$SCRIPT_DIR/google_metrics/request_bing_index.sh" "$POST_URL" 2>&1 || echo "⚠️ Bing インデックススキップ"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [3] SNS拡散
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo ""
echo "[3/3] SNS拡散..."

claude --no-session-persistence --agent persian -p "
今日は${TODAY}です。
以下のK-POPチャート速報記事が投稿されました。SNS拡散戦略を設計せよ。
【記事タイトル】$TITLE
【記事URL】$POST_URL
X投稿文2パターン・推奨ハッシュタグ・最適投稿タイミングを出力せよ。
" > reports/chart_mid_1_sns.md

log_step "sns" "ok" "reports/chart_mid_1_sns.md"

# アーカイブ
mkdir -p "$ARCHIVE_DIR"
cp reports/chart_mid_* "$ARCHIVE_DIR/" 2>/dev/null

# クリーンアップ
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
echo " ✅ チャート速報（ミッドウィーク）完了"
echo " 記事ID: $POST_ID"
echo " URL: $POST_URL"
echo "========================================"
log_step "complete" "ok"

# 投稿後自動監査
if [[ -n "${POST_ID:-}" ]] && [[ -n "${POST_URL:-}" ]]; then
  env -u AUDIT_LOOP_COUNT bash "$SCRIPT_DIR/post_audit.sh" "$POST_ID" "$POST_URL" "${TITLE:-}" "${RUN_ID:-}" 2>&1 || true
fi

# X投稿（監査通過後のみ）
_WP_STATUS_NOW=$(curl -s "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
  -K ~/.wp_auth 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")
if [[ "$_WP_STATUS_NOW" == "publish" ]]; then
  bash "$SCRIPT_DIR/google_metrics/post_to_x.sh" "$TITLE" "$POST_URL" "reports/chart_mid_1_sns.md" 2>&1 || echo "⚠️ X投稿スキップ"
fi
