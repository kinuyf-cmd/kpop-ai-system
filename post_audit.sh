#!/bin/bash
# ============================================================
# post_audit.sh - 投稿後自動監査・自動修正スクリプト
#
# 投稿直後に呼び出し、以下を自動チェック＆修正する:
#   1. 本文: 文字数・h2数・情報元・NGワード
#   2. タイトル: 文字数・速報ルール
#   3. SEO: メタ説明の有無
#   4. カテゴリ: 記事内容との整合性（Stray Kids等の誤設定）
#   5. タグ: 空かどうか → アーティスト名からタグを自動生成
#   6. アイキャッチ: altテキストの有無
#   7. X投稿: 成功/スキップの確認 → スキップなら再試行
#   8. Google Search Console: Indexing APIへの登録確認
#   9. ファクトチェック: アーカイブのアルセウス判定を再確認
#
# Usage:
#   bash post_audit.sh <POST_ID> <POST_URL> <TITLE> <RUN_ID>
#   bash post_audit.sh 2133 https://... "タイトル" 20260409_135304
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/env_loader.sh" 2>/dev/null || true
source "$SCRIPT_DIR/lib/discord_channels.sh" 2>/dev/null || true

POST_ID="${1:-}"
POST_URL="${2:-}"
TITLE="${3:-}"
RUN_ID="${4:-}"
ARCHIVE_DIR="${HOME}/kpop_archives/${RUN_ID}"
LOG_FILE="$SCRIPT_DIR/logs/post_audit.log"
# TEST MODE のログは本番監査ログに混ぜない(QAダミー記事 ID=99999 の
# CRITICAL 行が日次エラー集計で実記事の問題と誤認されるため)
if [[ "${KPOP_AUDIT_TEST_MODE:-0}" == "1" ]]; then
  LOG_FILE="${KPOP_AUDIT_TEST_LOG_FILE:-$SCRIPT_DIR/logs/post_audit_test.log}"
fi

mkdir -p "$(dirname "$LOG_FILE")"

alog() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [AUDIT] $*" | tee -a "$LOG_FILE"; }
ISSUES=()
FIXES=()

if [[ -z "$POST_ID" ]]; then
  alog "❌ POST_IDが指定されていません"
  exit 1
fi

alog "===== 投稿後監査開始: ID=$POST_ID URL=$POST_URL ====="

# ─── WordPress から記事情報を取得 ──────────────────────────────────────────
# TEST MODE: 本番 WP API を叩かず、ファイルからモック投稿JSONを読む（ユニットテスト用）
if [[ "${KPOP_AUDIT_TEST_MODE:-0}" == "1" ]]; then
  alog "🧪 TEST MODE: モック投稿JSONを使用（WP API はスキップ）"
  if [[ "${KPOP_AUDIT_TEST_HTTP_STATUS:-200}" != "200" ]]; then
    alog "❌ TEST MODE: HTTP_STATUS=${KPOP_AUDIT_TEST_HTTP_STATUS} のため取得失敗を模擬"
    exit 1
  fi
  if [[ -n "${KPOP_AUDIT_TEST_POST_JSON_FILE:-}" && -f "${KPOP_AUDIT_TEST_POST_JSON_FILE}" ]]; then
    POST_JSON=$(cat "${KPOP_AUDIT_TEST_POST_JSON_FILE}")
  else
    alog "❌ TEST MODE: KPOP_AUDIT_TEST_POST_JSON_FILE が未指定または不在"
    exit 1
  fi
else
  POST_JSON=$(curl -s "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}?context=edit" \
    -u "${WP_USER:-}:${WP_PASS:-}" 2>/dev/null)
fi

if [[ -z "$POST_JSON" ]] || echo "$POST_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('id') else 1)" 2>/dev/null; then
  : # OK
else
  alog "❌ WordPress API から記事取得失敗"
  exit 1
fi

# ─── 基本情報を取得（ファイル経由でJSON配列のeval問題を回避）─────────────
_TMP_INFO=$(mktemp /tmp/audit_info.XXXXXX)
echo "$POST_JSON" | python3 -c "
import sys, json, re
d = json.load(sys.stdin)
content = d['content']['raw']
text = re.sub(r'<[^>]+>', '', content)
print(len(text))                          # 1: CONTENT_LEN
print(content.count('<h2'))               # 2: H2_COUNT
print(1 if 'href=' in content else 0)    # 3: HAS_HREF
print(d['featured_media'])               # 4: FEAT_MEDIA
print(json.dumps(d['categories']))       # 5: CAT_IDS_JSON
print(json.dumps(d['tags']))             # 6: TAG_IDS_JSON
meta = d.get('meta', {})
desc = meta.get('_aioseo_description', '')
print(len(desc))                         # 7: META_DESC_LEN
print(d['status'])                       # 8: STATUS
# 9: CITE_LAYER 判定（categories_slug から記事レイヤを決定）
#   Layer1=主要メディア引用 / Layer2=リリース引用 / Layer3=独自記事
#   news,media,citation 系 → L1 / release,prtimes → L2 / それ以外(travel等) → L3
slugs = [s.lower() for s in d.get('categories_slug', [])]
L1 = {'news', 'media', 'citation', 'kpop-news'}
L2 = {'release', 'prtimes', 'comeback'}
if any(s in L1 for s in slugs):
    print(1)
elif any(s in L2 for s in slugs):
    print(2)
else:
    print(3)
" 2>/dev/null > "$_TMP_INFO"

CONTENT_LEN=$(sed -n '1p' "$_TMP_INFO")
H2_COUNT=$(sed -n '2p' "$_TMP_INFO")
HAS_HREF=$(sed -n '3p' "$_TMP_INFO")
FEAT_MEDIA=$(sed -n '4p' "$_TMP_INFO")
CAT_IDS=$(sed -n '5p' "$_TMP_INFO")
TAG_IDS=$(sed -n '6p' "$_TMP_INFO")
META_DESC_LEN=$(sed -n '7p' "$_TMP_INFO")
STATUS=$(sed -n '8p' "$_TMP_INFO")
CITE_LAYER=$(sed -n '9p' "$_TMP_INFO")
rm -f "$_TMP_INFO"

alog "本文文字数=$CONTENT_LEN / h2=$H2_COUNT / カテゴリ=$CAT_IDS / タグ=$TAG_IDS / メタ説明=${META_DESC_LEN}文字"

# ─── 重大度の凡例 ───────────────────────────────────────────────────────────
#   CRITICAL = 公開不可（HARD_FAIL / draft化）
#   HIGH     = 要修正（自動修正 or 手動）
#   MEDIUM   = 改善推奨
#   LOW      = 参考情報
# ISSUES へは "[CRITICAL] ..." の形で重大度を前置する。

# ─── [1] 本文チェック ──────────────────────────────────────────────────────
alog "--- [1] 本文チェック ---"
if [[ "${CONTENT_LEN:-0}" -lt 3000 ]]; then
  # CONTENT_LEN が必須下限 3000 字未満 → CRITICAL
  ISSUES+=("[CRITICAL] 本文テキスト文字数不足: ${CONTENT_LEN}文字（3000字必須）")
  alog "🚨 [CRITICAL] 本文文字数不足: ${CONTENT_LEN}文字（3000字必須）"
elif [[ "${CONTENT_LEN:-0}" -lt 800 ]]; then
  ISSUES+=("[HIGH] 本文が800文字未満: ${CONTENT_LEN}文字")
  alog "⚠️ [HIGH] 本文が短すぎます: ${CONTENT_LEN}文字"
else
  alog "✅ 本文文字数OK: ${CONTENT_LEN}文字"
fi

if [[ "${H2_COUNT:-0}" -lt 3 ]]; then
  ISSUES+=("h2見出しが3本未満: ${H2_COUNT}本")
  alog "⚠️ h2見出しが少ない: ${H2_COUNT}本"
else
  alog "✅ h2見出しOK: ${H2_COUNT}本"
fi

if [[ "${HAS_HREF:-0}" -eq 0 ]]; then
  ISSUES+=("情報元リンクが見当たらない（hrefなし）")
  alog "⚠️ 情報元リンクなし"
else
  alog "✅ 情報元リンクあり"
fi

# ─── [2] タイトルチェック ──────────────────────────────────────────────────
alog "--- [2] タイトルチェック ---"
TITLE_LEN=${#TITLE}
if [[ $TITLE_LEN -lt 10 ]]; then
  ISSUES+=("タイトルが短すぎる: ${TITLE_LEN}文字")
  alog "⚠️ タイトル短すぎ: $TITLE_LEN文字"
elif [[ $TITLE_LEN -gt 80 ]]; then
  ISSUES+=("タイトルが80文字超: ${TITLE_LEN}文字")
  alog "⚠️ タイトル長すぎ: $TITLE_LEN文字"
else
  alog "✅ タイトル文字数OK: ${TITLE_LEN}文字"
fi

# ─── [3] メタ説明チェック＆自動修正 ────────────────────────────────────────
alog "--- [3] SEOメタ説明チェック ---"
if [[ "${META_DESC_LEN:-0}" -lt 50 ]]; then
  alog "⚠️ メタ説明が空または短い → 自動生成して設定"
  # 本文冒頭から120文字を抽出してメタ説明を生成
  AUTO_DESC=$(echo "$POST_JSON" | python3 -c "
import sys, json, re
d = json.load(sys.stdin)
content = d['content']['raw']
text = re.sub(r'<[^>]+>', '', content).strip()
# 最初の段落を取得
first = ' '.join(text.split()[:60])
print(first[:120])
" 2>/dev/null || echo "$TITLE")

  curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
    -u "$WP_USER:$WP_PASS" \
    -H "Content-Type: application/json" \
    -d "{\"meta\":{\"_aioseo_description\":\"${AUTO_DESC}\"}}" > /dev/null 2>&1 && \
    alog "✅ メタ説明を自動設定: ${AUTO_DESC:0:50}..." && \
    FIXES+=("メタ説明を自動生成して設定")
else
  # [3b] 本文冒頭の流用チェック（120字以上でも非独立型は警告）
  IS_COPIED=$(echo "$POST_JSON" | python3 -c "
import sys, json, re
d = json.load(sys.stdin)
meta = d.get('meta',{}).get('_aioseo_description','')
content = d.get('content',{}).get('raw','')
text = re.sub(r'<[^>]+>','',content).strip()
# メタ説明が本文冒頭30字と一致する場合は「流用」と判定
print('YES' if text[:30] and meta.startswith(text[:30]) else 'NO')
" 2>/dev/null || echo "NO")
  if [[ "$IS_COPIED" == "YES" ]]; then
    alog "⚠️ メタ説明が本文冒頭の流用（SEO効果が低い）: ${META_DESC_LEN}文字"
    ISSUES+=("メタ説明が本文冒頭の流用（独立したメタ説明を設定推奨）")
  else
    alog "✅ メタ説明OK: ${META_DESC_LEN}文字"
  fi
fi

# ─── [4] カテゴリチェック＆修正 ────────────────────────────────────────────
alog "--- [4] カテゴリチェック ---"
# アーティスト固有カテゴリIDとアーティスト名のマッピング
BAD_ARTIST_CATS=$(echo "$CAT_IDS" | python3 -c "
import sys, json

# アーティスト専用カテゴリ（コンテンツと一致しない場合は除外対象）
ARTIST_CATS = {
    43: 'Stray Kids',
    44: 'BTS',
    45: 'BLACKPINK',
    46: 'aespa',
    47: 'TWICE',
    48: 'SEVENTEEN',
    49: 'NewJeans',
    50: 'IVE',
    51: 'LE SSERAFIM',
}
cats = json.loads(sys.argv[1])
bad = [str(c) for c in cats if c in ARTIST_CATS]
print(','.join(bad))
" "$CAT_IDS" 2>/dev/null || echo "")

if [[ -n "$BAD_ARTIST_CATS" ]]; then
  # タイトルにそのアーティスト名が含まれているか確認
  ARTIST_IN_TITLE=$(echo "$POST_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
title = d['title']['raw'].lower()
cats = json.loads(d.get('class_list',{}).get('9','[]') if False else '[]')

artist_map = {
    43: 'stray kids',
    44: 'bts',
    45: 'blackpink',
    46: 'aespa',
    47: 'twice',
    48: 'seventeen',
    49: 'newjeans',
    50: 'ive',
    51: 'le sserafim',
}
cat_ids = json.loads(sys.argv[1])
for cid in cat_ids:
    if cid in artist_map:
        if artist_map[cid] in title:
            print('MATCH')
            sys.exit()
print('MISMATCH')
" "$CAT_IDS" 2>/dev/null || echo "MISMATCH")

  if [[ "$ARTIST_IN_TITLE" == "MISMATCH" ]]; then
    alog "⚠️ カテゴリにアーティスト固有カテゴリが含まれるがタイトルと不一致 → 修正"
    # アーティスト固有カテゴリを除いたカテゴリリストで更新
    NEW_CATS=$(echo "$CAT_IDS" | python3 -c "
import sys, json
ARTIST_CATS = {43,44,45,46,47,48,49,50,51}
cats = json.loads(sys.argv[1])
filtered = [c for c in cats if c not in ARTIST_CATS]
if not filtered:
    filtered = [71]  # K-POPチャートをデフォルト
print(json.dumps(filtered))
" "$CAT_IDS" 2>/dev/null)

    curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
      -u "$WP_USER:$WP_PASS" \
      -H "Content-Type: application/json" \
      -d "{\"categories\":${NEW_CATS}}" > /dev/null 2>&1 && \
      alog "✅ カテゴリを修正: $CAT_IDS → $NEW_CATS" && \
      FIXES+=("誤アーティストカテゴリを除去: $CAT_IDS → $NEW_CATS")
  else
    alog "✅ カテゴリとタイトルが一致"
  fi
else
  alog "✅ カテゴリOK"
fi

# ─── [5] タグチェック＆自動生成 ────────────────────────────────────────────
alog "--- [5] タグチェック ---"
TAG_COUNT=$(echo "$TAG_IDS" | python3 -c "import sys,json; print(len(json.loads(sys.argv[1])))" "$TAG_IDS" 2>/dev/null || echo "0")

if [[ "$TAG_COUNT" -lt 2 ]]; then
  alog "⚠️ タグが少ない($TAG_COUNT件) → タイトルからタグを自動生成"
  # タイトルからK-POPアーティスト名・キーワードを抽出してタグ作成
  NEW_TAG_IDS=$(python3 - "$TITLE" "$WP_USER" "$WP_PASS" << 'TAGPY'
import sys, json, re, urllib.request, urllib.parse, base64

title = sys.argv[1]
user = sys.argv[2]
passwd = sys.argv[3]
auth = base64.b64encode(f"{user}:{passwd}".encode()).decode()

# 既知アーティスト名パターン
ARTISTS = [
    "BTS","BLACKPINK","aespa","TWICE","SEVENTEEN","Stray Kids","NewJeans",
    "IVE","LE SSERAFIM","ENHYPEN","TXT","ATEEZ","NCT","EXO","BIGBANG",
    "AKMU","악동뮤지션","MAMAMOO","Red Velvet","SHINee","Super Junior",
    "KISS OF LIFE","RIIZE","ILLIT","BABYMONSTER","ZeroBaseOne","GOT7",
]
# チャート・プラットフォーム名
PLATFORMS = ["Melon","Billboard","Genie","Bugs","FLO","Oricon","Spotify"]
# 一般キーワード
GENERAL = ["K-POPニュース","カムバック","チャート","速報","フルアルバム"]

tags_to_create = []
for a in ARTISTS:
    if a.lower() in title.lower():
        tags_to_create.append(a)
for p in PLATFORMS:
    if p.lower() in title.lower():
        tags_to_create.append(p)
if not tags_to_create:
    tags_to_create = ["K-POPニュース"]
tags_to_create.append("K-POPニュース")

tag_ids = []
for tag_name in tags_to_create[:6]:
    try:
        data = json.dumps({"name": tag_name}).encode()
        req = urllib.request.Request(
            "https://www.kpopjournal.tokyo/wp-json/wp/v2/tags",
            data=data,
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            tag_ids.append(result["id"])
    except Exception as e:
        # 409 = already exists → GET existing
        try:
            url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/tags?search={urllib.parse.quote(tag_name)}"
            req2 = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
            with urllib.request.urlopen(req2, timeout=10) as resp2:
                results = json.loads(resp2.read())
                if results:
                    tag_ids.append(results[0]["id"])
        except:
            pass

print(json.dumps(list(set(tag_ids))))
TAGPY
)

  if [[ -n "$NEW_TAG_IDS" ]] && [[ "$NEW_TAG_IDS" != "[]" ]]; then
    curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
      -u "$WP_USER:$WP_PASS" \
      -H "Content-Type: application/json" \
      -d "{\"tags\":${NEW_TAG_IDS}}" > /dev/null 2>&1 && \
      alog "✅ タグを自動生成・設定: $NEW_TAG_IDS" && \
      FIXES+=("タグを自動生成して設定: $NEW_TAG_IDS")
  fi
else
  alog "✅ タグOK: $TAG_COUNT件"
fi

# ─── [6] アイキャッチ altテキスト＆サムネイル整合性チェック ─────────────────
alog "--- [6] アイキャッチ altテキスト・サムネイル整合性チェック ---"
if [[ "${FEAT_MEDIA:-0}" -gt 0 ]]; then
  MEDIA_JSON=$(curl -s "https://www.kpopjournal.tokyo/wp-json/wp/v2/media/${FEAT_MEDIA}" \
    -u "$WP_USER:$WP_PASS" 2>/dev/null)
  ALT_TEXT=$(echo "$MEDIA_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('alt_text',''))" 2>/dev/null || echo "")
  MEDIA_TITLE=$(echo "$MEDIA_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('title',{}).get('rendered',''))" 2>/dev/null || echo "")

  # [6a] ALTテキストチェック
  if [[ -z "$ALT_TEXT" ]]; then
    alog "⚠️ アイキャッチのaltテキストが空 → 自動設定"
    AUTO_ALT=$(echo "$TITLE" | cut -c1-60)
    curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/media/${FEAT_MEDIA}" \
      -u "$WP_USER:$WP_PASS" \
      -H "Content-Type: application/json" \
      -d "{\"alt_text\":\"${AUTO_ALT}\"}" > /dev/null 2>&1 && \
      alog "✅ altテキスト自動設定: $AUTO_ALT" && \
      FIXES+=("アイキャッチaltテキストを自動設定")
  else
    alog "✅ altテキストOK: $ALT_TEXT"
  fi

  # [6b] サムネイルタイトルと記事タイトルの整合性チェック
  # サムネのthumb_textをログから確認（thumbnail_performance.jsonlに記録されている）
  THUMB_TEXT=$(python3 -c "
import json, sys
from pathlib import Path
perf_file = Path('$SCRIPT_DIR/logs/thumbnail_performance.jsonl')
if not perf_file.exists():
    sys.exit(0)
lines = perf_file.read_text().strip().split('\n')
for line in reversed(lines):
    try:
        d = json.loads(line)
        if str(d.get('post_id','')) == '$POST_ID':
            print(d.get('thumb_text',''))
            sys.exit(0)
    except:
        pass
" 2>/dev/null || echo "")

  if [[ -n "$THUMB_TEXT" ]]; then
    # サムネテキストが記事タイトルの主要キーワードと全く一致しないかチェック
    MATCH=$(python3 -c "
import re, sys
thumb = '$THUMB_TEXT'.lower()
title = '$TITLE'.lower()
# タイトルからアーティスト名候補を抽出（5文字以内の英数字ブロック、または日本語2文字以上）
artists = re.findall(r'[A-Za-z]{2,}|[\u30A0-\u30FF\u4E00-\u9FFF]{2,}', title)
matches = sum(1 for a in artists if a.lower() in thumb or thumb in a.lower())
print('YES' if matches >= 1 else 'NO')
" 2>/dev/null || echo "YES")

    if [[ "$MATCH" == "NO" ]]; then
      alog "⚠️ サムネイルテキスト「$THUMB_TEXT」が記事タイトルと不一致 → 要確認"
      ISSUES+=("サムネイルテキストと記事タイトルが不一致: thumb='$THUMB_TEXT' title='$TITLE'")
    else
      alog "✅ サムネイル整合性OK: $THUMB_TEXT"
    fi
  fi
else
  ISSUES+=("アイキャッチ画像が設定されていない")
  alog "⚠️ アイキャッチ未設定"
fi

# ─── [7] X投稿チェック＆再試行 ─────────────────────────────────────────────
alog "--- [7] X投稿チェック ---"
# X自動投稿の長期停止中(x_scheduled_poster cronがコメントアウト)は再試行しない
# (シャドウバン対応の全停止をpost_audit経由の直接投稿がすり抜ける事故の防止)
if ! crontab -l 2>/dev/null | grep -E '^[^#]' | grep -q 'x_scheduled_poster'; then
  alog "ℹ️ X自動投稿は停止中(cron無効) → X投稿チェックをスキップ"
  X_SUCCESS="__X_PAUSED__"
else
# x_post.logはTITLEとURLで記録されているので両方で確認
X_SUCCESS=$(grep -A5 "TITLE: ${TITLE}" "$SCRIPT_DIR/logs/x_post.log" 2>/dev/null | grep "フック投稿成功" | tail -1 || \
            grep "フック投稿成功" "$SCRIPT_DIR/logs/x_post.log" 2>/dev/null | tail -1 || echo "")
fi

if [[ -z "$X_SUCCESS" ]]; then
  alog "⚠️ X投稿が未成功 → 自動再試行"
  # アーカイブから4_sns.mdを確認
  SNS_FILE="${ARCHIVE_DIR}/4_sns.md"
  if [[ -f "$SNS_FILE" ]]; then
    # 正しいフォーマットで4_sns.mdを再作成してpost_to_x.shを実行
    HOOK_TEXT=$(python3 -c "
import re
from pathlib import Path
text = Path('$SNS_FILE').read_text()
# パターンマッチで抽出
m = re.search(r'パターンA[^\n]*\n\x60{3}\n(.*?)\n\x60{3}', text, re.DOTALL)
if m:
    print(m.group(1).strip())
    exit()
# 全テキストをそのまま使う
lines = [l for l in text.strip().split('\n') if l.strip()]
print('\n'.join(lines[:8]))
" 2>/dev/null || echo "")

    if [[ -n "$HOOK_TEXT" ]]; then
      RETRY_SNS_FILE=$(mktemp /tmp/audit_sns.XXXXXX.md)
      printf 'パターンA（採用推奨）\n```\n%s\n```\n' "$HOOK_TEXT" > "$RETRY_SNS_FILE"
      X_RESULT=$(bash "$SCRIPT_DIR/google_metrics/post_to_x.sh" "$TITLE" "$POST_URL" "$RETRY_SNS_FILE" 2>&1 || echo "失敗")
      rm -f "$RETRY_SNS_FILE"
      if echo "$X_RESULT" | grep -q "フック投稿成功"; then
        TWEET_URL=$(echo "$X_RESULT" | grep -oP 'https://x\.com/\S+' | head -1 || echo "")
        alog "✅ X投稿再試行成功: $TWEET_URL"
        FIXES+=("X投稿を再試行して成功: $TWEET_URL")
      else
        ISSUES+=("X投稿が失敗: スコア不足またはAPIエラー")
        alog "❌ X投稿再試行も失敗"
      fi
    fi
  fi
elif [[ "$X_SUCCESS" != "__X_PAUSED__" ]]; then
  alog "✅ X投稿OK: $(echo "$X_SUCCESS" | grep -oP 'https://x\.com/\S+' | head -1)"
fi

# ─── [8] Google Search Console チェック ────────────────────────────────────
alog "--- [8] Google Search Console チェック ---"
GSC_SENT=$(grep -F "インデックス登録リクエスト成功: ${POST_URL}" ~/ai_kpop.log 2>/dev/null | tail -1 || echo "")

if [[ -z "$GSC_SENT" ]]; then
  alog "⚠️ GSCインデックス登録確認できず → 再送信"
  GSC_RESULT=$(bash "$SCRIPT_DIR/google_metrics/request_index.sh" "$POST_URL" 2>&1 || echo "スキップ")
  alog "GSC再送信: $GSC_RESULT"
  FIXES+=("GSCインデックス登録を再送信")
else
  alog "✅ GSCインデックス登録済み"
fi

# ─── [9] アーカイブのファクトチェック判定を再確認 ──────────────────────────
alog "--- [9] ファクトチェック再確認 ---"
if [[ -n "$RUN_ID" ]] && [[ -f "$ARCHIVE_DIR/3_arceus.md" ]]; then
  ARCEUS_RESULT=$(grep -E "(✅ 投稿承認|✅ 承認|APPROVED|CONDITIONAL APPROVE|CONDITIONAL PASS|条件付き承認|投稿判定.*承認|即時投稿可)" "$ARCHIVE_DIR/3_arceus.md" | head -1 || echo "")
  ARCEUS_REJECT=$(grep -E "(❌ 投稿却下|投稿不可|REJECT)" "$ARCHIVE_DIR/3_arceus.md" | head -1 || echo "")

  if [[ -n "$ARCEUS_REJECT" ]]; then
    ISSUES+=("⚠️ アルセウスが却下判定を出しているのに投稿されています: $ARCEUS_REJECT")
    alog "🚨 アルセウス却下判定で投稿された可能性: $ARCEUS_REJECT"
  elif [[ -n "$ARCEUS_RESULT" ]]; then
    alog "✅ ファクトチェック承認確認: $ARCEUS_RESULT"
  else
    ISSUES+=("アルセウスの承認判定が確認できない")
    alog "⚠️ アルセウス判定が不明"
  fi
else
  alog "ℹ️ アーカイブなし or RUN_ID未指定 → スキップ"
fi

# ─── [14b] 3ペルソナ・ゲート（C-4 必須化 / kpop-original-article §4・§9-1）──────
#   Layer3 独自記事のみ対象。①初心者/ライト ②コアファン ③検索流入一般読者 の
#   3視点すべてに価値があるかを検査。欠落があれば CRITICAL(HARD_FAIL) で exit 2。
#   引用記事（Layer1/Layer2）はゲート対象外。
alog "--- [14b] 3ペルソナ・ゲート（C-4）---"
if [[ "${CITE_LAYER:-1}" == "3" ]]; then
  PERSONA_RESULT=$(echo "$POST_JSON" | python3 -c "
import sys, json, re
d = json.load(sys.stdin)
content = d.get('content', {}).get('raw', '')
text = re.sub(r'<[^>]+>', '', content)

# ① 初心者/ライト層: 入門・基礎・初心者・とは 等
beginner_kw = ['初心者', '入門', '基礎', 'とは', '初めて', 'はじめて', 'わかりやすく']
# ② コアファン/オタク: 固有グループ名 + ファン文脈語
group_names = ['BTS', 'NewJeans', 'BLACKPINK', 'aespa', 'SEVENTEEN', 'TWICE',
               'IVE', 'LE SSERAFIM', 'Stray Kids', 'ENHYPEN', 'TXT', 'ITZY',
               'NCT', 'ATEEZ', 'RIIZE', 'ILLIT', '推し', 'メンバー', 'ファンダム']
fan_context = ['ファン目線', 'ファン', '推し', '聖地', 'グッズ', '深掘り', 'オタク']
# ③ 検索流入一般読者: 比較・ランキング・行き方・料金・おすすめ 等の結論
search_kw = ['比較', 'ランキング', '行き方', 'アクセス', '料金', 'おすすめ', 'まとめ', '徹底']

has_beginner = any(k in text for k in beginner_kw)
has_group = any(g in text for g in group_names)
has_fancontext = any(c in text for c in fan_context)
has_fan = has_group and has_fancontext
has_search = any(k in text for k in search_kw)

missing = []
if not has_beginner: missing.append('①初心者/ライト層')
if not has_fan:      missing.append('②ファン向け深掘り')
if not has_search:   missing.append('③検索意図への結論')

print('|'.join(missing))
" 2>/dev/null || echo "PARSE_ERROR")

  if [[ "$PERSONA_RESULT" == "PARSE_ERROR" ]]; then
    alog "⚠️ 3ペルソナ・ゲート: 本文解析に失敗（判定スキップ）"
  elif [[ -z "$PERSONA_RESULT" ]]; then
    alog "✅ 3ペルソナ・ゲート PASS（①②③すべて充足）"
  else
    MISSING_PERSONA=$(echo "$PERSONA_RESULT" | tr '|' '、')
    ISSUES+=("[CRITICAL] 3ペルソナ・ゲート不成立: 欠落ペルソナ=${MISSING_PERSONA}（HARD_FAIL: kpop-original-article §4/§9-1、C-4 必須化）")
    alog "🚨 [CRITICAL] 3ペルソナ・ゲート不成立: 欠落ペルソナ=${MISSING_PERSONA}"
    alog "🚫 HARD_FAIL → exit 2（公開不可）"
    echo ""
    echo "**🚨 3ペルソナ・ゲート不成立: 欠落=${MISSING_PERSONA}**"
    exit 2
  fi
else
  alog "ℹ️ 3ペルソナ・ゲートは対象外（Layer${CITE_LAYER:-1} 引用記事）"
fi

# ─── 監査結果サマリー ─────────────────────────────────────────────────────
alog "===== 監査完了 ====="
alog "問題数: ${#ISSUES[@]} / 修正数: ${#FIXES[@]}"

SUMMARY="**📋 投稿後監査レポート: ID=$POST_ID**\n"
SUMMARY+="URL: $POST_URL\n\n"

if [[ ${#FIXES[@]} -gt 0 ]]; then
  SUMMARY+="**✅ 自動修正済み (${#FIXES[@]}件):**\n"
  for fix in "${FIXES[@]}"; do
    SUMMARY+="- $fix\n"
  done
  SUMMARY+="\n"
fi

if [[ ${#ISSUES[@]} -gt 0 ]]; then
  SUMMARY+="**⚠️ 要確認 (${#ISSUES[@]}件):**\n"
  for issue in "${ISSUES[@]}"; do
    SUMMARY+="- $issue\n"
  done
  CHANNEL="urgent_errors"
else
  SUMMARY+="**問題なし ✅**"
  CHANNEL="publishing_log"
fi

# Discord通知
WEBHOOK=$(cat ~/.kpop_discord_webhook 2>/dev/null | tr -d '[:space:]' || echo "")
if [[ -n "$WEBHOOK" ]]; then
  python3 -c "
import urllib.request, json, sys
msg = sys.argv[1]
webhook = sys.argv[2]
payload = json.dumps({'content': msg[:1900]}).encode()
req = urllib.request.Request(webhook, data=payload, headers={'Content-Type': 'application/json'})
try:
    urllib.request.urlopen(req, timeout=10)
    print('Discord通知送信完了')
except Exception as e:
    print(f'Discord通知失敗: {e}')
" "$SUMMARY" "$WEBHOOK" 2>/dev/null || true
fi

echo ""
echo "$SUMMARY"

# 終了コード: 問題あり=1, 問題なし=0
if [[ ${#ISSUES[@]} -gt 0 ]]; then
  exit 1
fi
exit 0
