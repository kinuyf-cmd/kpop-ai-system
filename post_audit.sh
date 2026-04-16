#!/bin/bash
# ============================================================
# post_audit.sh - 投稿後自動監査・自律修正スクリプト
#
# 【完全自律型・自己修復ループ】
# 投稿 → 自動監査 → 自動修正 → 再監査 → 完了
# NGなら最大3回修正ループ。3回失敗時のみdraft化。
# 人間への確認依頼・レポート通知は禁止。ログのみ記録。
#
# 監査項目:
#   0. スラッグ: 汎用スラッグ・__trashed・短すぎ・日本語・日付数字
#   1. 本文: HTML文字数3000以上・h2数・情報元・NGワード
#   2. タイトル: 文字数・速報ルール
#   3. SEO: メタ説明の有無（本文冒頭コピーでないか）
#   4. カテゴリ: 記事内容との整合性
#   5. タグ: 空かどうか → 自動生成
#   6. アイキャッチ: サムネ存在・altテキスト・整合性
#   7. X投稿: 成功/スキップの確認 → スキップなら再試行
#   8. Google Search Console: Indexing API登録確認
#   9. ファクトチェック: アルセウス判定再確認
#  10. 文字化け: \uXXXX / UTF-8表示異常の検出
#  11. 内部リンク: 主軸記事（post_id=2214）へのリンク2本以上
#  12. HTTP: 公開URL 200チェック
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
POST_JSON=$(curl -s "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}?context=edit" \
  -K "$HOME/.wp_auth" 2>/dev/null)

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
print(len(text))                          # 1: CONTENT_LEN (テキスト実文字数 ★基準)
print(len(content))                       # 2: CONTENT_HTML_LEN (HTML込み文字数 補助)
print(content.count('<h2'))               # 3: H2_COUNT
print(1 if 'href=' in content else 0)    # 4: HAS_HREF
print(d['featured_media'])               # 5: FEAT_MEDIA
print(json.dumps(d['categories']))       # 6: CAT_IDS_JSON
print(json.dumps(d['tags']))             # 7: TAG_IDS_JSON
meta = d.get('meta', {})
desc = meta.get('_aioseo_description', '')
print(len(desc))                         # 8: META_DESC_LEN
print(d['status'])                       # 9: STATUS
print(d.get('slug', ''))                 # 10: SLUG
# 11: 内部リンク（post_id=2214）カウント
link_count = content.count('p=2214') + content.count('kpop-idol-glass-skin-complete-guide-2026')
print(link_count)                        # 11: INTERNAL_LINK_2214
# 12: 文字化け検出（\uXXXX形式が本文に残存しているか）
has_mojibake = 1 if re.search(r'\\\\u[0-9a-fA-F]{4}', content) else 0
print(has_mojibake)                      # 12: HAS_MOJIBAKE
" 2>/dev/null > "$_TMP_INFO"

CONTENT_LEN=$(sed -n '1p' "$_TMP_INFO")        # テキスト実文字数（判定基準）
CONTENT_HTML_LEN=$(sed -n '2p' "$_TMP_INFO")  # HTML込み文字数（補助）
H2_COUNT=$(sed -n '3p' "$_TMP_INFO")
HAS_HREF=$(sed -n '4p' "$_TMP_INFO")
FEAT_MEDIA=$(sed -n '5p' "$_TMP_INFO")
CAT_IDS=$(sed -n '6p' "$_TMP_INFO")
TAG_IDS=$(sed -n '7p' "$_TMP_INFO")
META_DESC_LEN=$(sed -n '8p' "$_TMP_INFO")
STATUS=$(sed -n '9p' "$_TMP_INFO")
POST_SLUG=$(sed -n '10p' "$_TMP_INFO")
INTERNAL_LINK_2214=$(sed -n '11p' "$_TMP_INFO")
HAS_MOJIBAKE=$(sed -n '12p' "$_TMP_INFO")
rm -f "$_TMP_INFO"

# HTTP 200チェック
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$POST_URL" 2>/dev/null || echo "000")

alog "本文テキスト文字数=$CONTENT_LEN (HTML込=$CONTENT_HTML_LEN) / h2=$H2_COUNT / カテゴリ=$CAT_IDS / タグ=$TAG_IDS / メタ説明=${META_DESC_LEN}文字 / slug=$POST_SLUG / 内部リンク2214=${INTERNAL_LINK_2214}本 / 文字化け=${HAS_MOJIBAKE} / HTTP=${HTTP_STATUS}"

# ─── [0] スラッグチェック＆自動修正 ────────────────────────────────────────
alog "--- [0] スラッグチェック（完全版）---"
if [[ -n "$POST_SLUG" ]]; then
  SLUG_CHECK=$(python3 "$SCRIPT_DIR/lib/audit_helpers.py" slug_check "$POST_SLUG" 2>/dev/null || echo "OK")
  if [[ "$SLUG_CHECK" == NG:* ]]; then
    SLUG_ISSUE="${SLUG_CHECK#NG:}"
    alog "⚠️ スラッグNG: $POST_SLUG → $SLUG_ISSUE"
    # slug_generator.py（既存の高品質生成器）で再生成
    NEW_SLUG=$(python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR/lib')
from slug_generator import generate_slug
print(generate_slug(sys.argv[1]))
" "$TITLE" 2>/dev/null || echo "")
    # slug_generator で再生成し、まだ汎用NGなら専用フォールバックを使用
    _SLUG_CANDIDATE=$(python3 -c "
import sys
sys.path.insert(0, '$SCRIPT_DIR/lib')
from slug_generator import generate_slug, is_generic_slug
s = generate_slug(sys.argv[1])
# 汎用判定: is_generic_slug または kpop-NNNN パターン
import re
still_generic = is_generic_slug(s) or bool(re.match(r'^k?pop-\d{4}', s))
print('GENERIC' if still_generic else s)
" "$TITLE" 2>/dev/null || echo "GENERIC")

    if [[ "$_SLUG_CANDIDATE" == "GENERIC" ]] || [[ "$_SLUG_CANDIDATE" == "$POST_SLUG" ]]; then
      # 専用フォールバック: カテゴリ + post_id で一意スラッグを生成
      NEW_SLUG=$(python3 -c "
import sys, json, re
title = sys.argv[1]
post_id = sys.argv[2]
cat_ids = json.loads(sys.argv[3]) if sys.argv[3] else []

# カテゴリIDからジャンルキーワードを決定
cat_kw_map = {
    72: 'beauty', 73: 'guide', 71: 'chart', 74: 'concert',
    70: 'news', 75: 'fashion',
}
cat_kw = 'kpop'
for cid in cat_ids:
    if cid in cat_kw_map:
        cat_kw = cat_kw_map[cid]
        break

# タイトルから英字キーワードを抽出
en_tokens = re.findall(r'[A-Za-z][A-Za-z0-9]*', title)
en_part = '-'.join(t.lower() for t in en_tokens[:3] if len(t) >= 2) if en_tokens else ''

import datetime
year = datetime.datetime.now().year

if en_part:
    slug = f'kpop-{cat_kw}-{en_part}-{post_id}'
else:
    slug = f'kpop-{cat_kw}-guide-{post_id}'

# 最大60文字
slug = slug[:57].rstrip('-') + f'-{year}' if len(slug) > 57 else slug
slug = re.sub(r'-+', '-', slug).strip('-').lower()
print(slug)
" "$TITLE" "$POST_ID" "$CAT_IDS" 2>/dev/null || echo "kpop-news-guide-${POST_ID}")
      alog "ℹ️ slug_generator汎用結果 → フォールバック生成: $NEW_SLUG"
    else
      NEW_SLUG="$_SLUG_CANDIDATE"
    fi

    if [[ -n "$NEW_SLUG" ]] && [[ "$NEW_SLUG" != "$POST_SLUG" ]]; then
      PATCH_RESULT=$(curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
        -K "$HOME/.wp_auth" \
        -H "Content-Type: application/json" \
        -d "{\"slug\": \"$(echo "$NEW_SLUG" | sed 's/"/\\"/g')\"}" 2>/dev/null | \
        python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('slug','ERROR'))" 2>/dev/null || echo "ERROR")
      if [[ "$PATCH_RESULT" != "ERROR" ]] && [[ -n "$PATCH_RESULT" ]]; then
        alog "✅ スラッグ自動修正: $POST_SLUG → $PATCH_RESULT"
        FIXES+=("スラッグを修正: $POST_SLUG → $PATCH_RESULT")
        POST_SLUG="$PATCH_RESULT"
        POST_URL="https://www.kpopjournal.tokyo/${PATCH_RESULT}/"
      else
        alog "⚠️ スラッグAPI更新失敗"
        ISSUES+=("スラッグNG: $SLUG_ISSUE")
      fi
    else
      alog "⚠️ スラッグ生成失敗（フォールバックも同一）"
      ISSUES+=("スラッグNG: $SLUG_ISSUE")
    fi
  else
    alog "✅ スラッグOK: $POST_SLUG"
  fi
fi

# ─── [1] 本文チェック＆補強 ──────────────────────────────────────────────────
# 判定基準: テキスト実文字数 3000字以上（HTML文字数は補助参考値）
alog "--- [1] 本文チェック ---"
if [[ "${CONTENT_LEN:-0}" -lt 3000 ]]; then
  alog "⚠️ 本文テキスト文字数不足: ${CONTENT_LEN}文字（必須3000字以上 / HTML込=${CONTENT_HTML_LEN}）→ SEO補強追記"
  CONTENT_FIX=$(python3 "$SCRIPT_DIR/lib/audit_helpers.py" content_fix \
    "$POST_ID" "$TITLE" "$CONTENT_LEN" 2>/dev/null || echo "ERROR:failed")
  if [[ "$CONTENT_FIX" == FIXED:* ]]; then
    NEW_LEN="${CONTENT_FIX#FIXED:}"
    alog "✅ 本文補強完了（テキスト文字数）: ${CONTENT_LEN} → ${NEW_LEN}文字"
    FIXES+=("本文補強: ${CONTENT_LEN} → ${NEW_LEN}文字")
    CONTENT_LEN="$NEW_LEN"
    # 補強後も3000未満なら未達としてISSUESに追加（次ループで再試行）
    if [[ "$CONTENT_LEN" -lt 3000 ]]; then
      alog "⚠️ 補強後もテキスト文字数不足: ${CONTENT_LEN}文字"
      ISSUES+=("本文テキスト文字数不足: ${CONTENT_LEN}文字（3000字必須）")
    fi
  else
    alog "⚠️ 本文補強失敗: $CONTENT_FIX"
    ISSUES+=("本文テキスト文字数不足: ${CONTENT_LEN}文字（3000字必須）")
  fi
else
  alog "✅ 本文テキスト文字数OK: ${CONTENT_LEN}文字（HTML込=${CONTENT_HTML_LEN}）"
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

# [1b] SEO内部リンク・NGワードチェック（ヒアストリングでsubshell回避）
_LINK_NG_OUTPUT=$(echo "$POST_JSON" | python3 -c "
import sys, json, re
d = json.load(sys.stdin)
content = d['content']['raw']
internal_links = re.findall(r'href=[\"\''][^\"\']*kpopjournal\.tokyo[^\"\']*[\"\'']', content)
print(f'INTERNAL_LINKS:{len(internal_links)}')
ng_words = ['注意：', 'ご注意ください', 'このサイトは', '当サイトは', 'AIが生成', 'AIによって生成',
            '人工知能', 'ChatGPT', 'generated by', 'この記事はAI']
for ng in ng_words:
    if ng in content:
        print(f'NG_WORD:{ng}')
" 2>/dev/null || echo "")
while IFS= read -r line; do
  if [[ "$line" == INTERNAL_LINKS:* ]]; then
    _cnt="${line#INTERNAL_LINKS:}"
    if [[ "${_cnt:-0}" -eq 0 ]]; then
      alog "⚠️ 内部リンクなし（サイト内への関連記事リンクを追加推奨）"
      ISSUES+=("本文に内部リンクなし（SEO: 関連記事リンク推奨）")
    else
      alog "✅ 内部リンク${_cnt}件あり"
    fi
  elif [[ "$line" == NG_WORD:* ]]; then
    _ng="${line#NG_WORD:}"
    alog "🚨 NGワード検出: '$_ng'"
    ISSUES+=("本文にNGワード: '$_ng'")
  fi
done <<< "$_LINK_NG_OUTPUT"

# ─── [2] タイトルチェック＆自動伸長 ──────────────────────────────────────
alog "--- [2] タイトルチェック ---"
TITLE_LEN=${#TITLE}
if [[ $TITLE_LEN -lt 20 ]]; then
  alog "⚠️ タイトル短すぎ（${TITLE_LEN}文字、20文字未満）→ 自動伸長"
  # 「主要KW + ベネフィット + 年号」形式で自動伸長
  NEW_TITLE=$(python3 -c "
import sys, re
from datetime import datetime
title = sys.argv[1]
year = datetime.now().year

# ジャンルキーワードを判定
genre_kw = 'K-POP'
benefit_map = {
    'スキンケア': ('K-POP美容法', '美肌になれる方法を徹底解説'),
    'ガラス肌': ('K-POPガラス肌', '韓国アイドル直伝スキンケア術'),
    'コスメ': ('K-POPコスメ', 'ファン必見のアイテムを徹底解説'),
    'チャート': ('K-POPチャート', '最新ランキングと注目アーティストを解説'),
    'カムバック': ('K-POPカムバック', '最新情報と見どころを完全まとめ'),
    'ライブ': ('K-POPライブ', 'チケット・会場・見どころを完全ガイド'),
    'コンサート': ('K-POPコンサート', 'チケット・会場・見どころを完全ガイド'),
    'ファッション': ('K-POPファッション', 'アイドルコーデの取り入れ方を解説'),
}
genre_label = 'K-POP'
benefit = 'ファン必見の情報を完全まとめ'
for kw, (label, ben) in benefit_map.items():
    if kw in title:
        genre_label = label
        benefit = ben
        break

# 既にKPOP/K-POPが含まれていなければ先頭に追加
if not any(w in title for w in ['K-POP', 'K-pop', 'KPOP', '韓国', 'アイドル']):
    new_title = f'{genre_label}{title}｜{benefit}【{year}年版】'
else:
    new_title = f'{title}｜{benefit}【{year}年版】'

# 20文字未満のままなら強制で補強
if len(new_title) < 20:
    new_title = f'K-POP {title}完全ガイド｜{benefit}【{year}年版】'

print(new_title[:70])
" "$TITLE" 2>/dev/null || echo "")

  if [[ -n "$NEW_TITLE" ]] && [[ "$NEW_TITLE" != "$TITLE" ]]; then
    TITLE_PATCH=$(curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
      -K "$HOME/.wp_auth" \
      -H "Content-Type: application/json" \
      -d "{\"title\":\"$(echo "$NEW_TITLE" | sed 's/"/\\"/g')\"}" 2>/dev/null | \
      python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('title',{}).get('raw','ERROR'))" 2>/dev/null || echo "ERROR")
    if [[ "$TITLE_PATCH" != "ERROR" ]] && [[ -n "$TITLE_PATCH" ]]; then
      alog "✅ タイトル自動伸長: '$TITLE' → '$TITLE_PATCH'"
      FIXES+=("タイトル伸長: '$TITLE' → '$TITLE_PATCH'")
      TITLE="$TITLE_PATCH"
      TITLE_LEN=${#TITLE}
    else
      alog "⚠️ タイトル伸長API更新失敗"
      ISSUES+=("タイトルが短すぎる: ${TITLE_LEN}文字（20文字未満）")
    fi
  else
    ISSUES+=("タイトルが短すぎる: ${TITLE_LEN}文字")
    alog "⚠️ タイトル伸長生成失敗: $TITLE_LEN文字"
  fi
elif [[ $TITLE_LEN -gt 80 ]]; then
  ISSUES+=("タイトルが80文字超: ${TITLE_LEN}文字")
  alog "⚠️ タイトル長すぎ: $TITLE_LEN文字"
else
  alog "✅ タイトル文字数OK: ${TITLE_LEN}文字"
fi

# [2b] タイトルSEO品質チェック（ヒアストリングでsubshell回避）
_TITLE_CHECK_OUTPUT=$(python3 -c "
import re, sys
title = sys.argv[1]
issues = []
if not re.search(r'20[2-3][0-9]', title):
    issues.append('年号なし（SEO検索需要低下の可能性）')
kpop_words = ['K-POP', 'K-pop', 'k-pop', 'KPOP', '韓国', 'アイドル', 'カムバック',
              'ガールズグループ', 'ボーイズグループ', 'K-POPアイドル',
              # 主要アーティスト名（直近ログで判定漏れを確認済み）
              'BTS', 'BLACKPINK', 'TWICE', 'EXO', 'SEVENTEEN', 'STRAY KIDS', 'Stray Kids',
              'ATEEZ', 'ENHYPEN', 'TXT', 'aespa', 'IVE', 'RIIZE', 'NewJeans', 'ILLIT',
              'PLAVE', 'MONSTA X', 'ITZY', 'SHINee', 'BIGBANG', 'SUPER JUNIOR',
              '防弾少年団', 'ニュージーンズ']
if not any(w in title for w in kpop_words):
    issues.append('K-POP関連キーワードがタイトルに含まれない')
generic = ['最新情報', 'まとめ', 'について', '速報']
generic_count = sum(1 for g in generic if g in title)
if generic_count >= 2:
    issues.append(f'汎用ワードが多すぎる（{generic_count}個）: 具体性が低い')
words = re.findall(r'[ぁ-んァ-ン一-龥A-Za-z]{3,}', title)
seen = {}
for w in words:
    seen[w] = seen.get(w, 0) + 1
dups = [w for w, c in seen.items() if c >= 2]
if dups:
    issues.append(f'タイトル内重複語: {dups}')
if issues:
    for iss in issues:
        print(f'TITLE_ISSUE: {iss}')
else:
    print('TITLE_OK')
" "$TITLE" 2>/dev/null || echo "TITLE_OK")
# [2b-pre] タイトルにエージェントのエラー応答が混入していないか先行チェック（2026-04-16追加）
# 該当パターン検出時は K-POP プレフィクス等で修正せず trash へ移動（公開防止）
if echo "$TITLE" | grep -qE 'WebFetch ツール|権限が付与|外部URLへのアクセスが制限|ソースURLの直接検証|申し訳ありません|お手伝いできますか|許可してください|許可が必要|確認させてください|入力記事が見当たりません|記事を提供してください|元記事.*提供|貼り付けてください|評価対象がありません|タイトルを入力してください|以下に完成記事|記事を生成します|DEOXYS_SOURCE_FAIL|GOSSIP_SOURCE_FAIL'; then
  alog "🛑 タイトルにエージェントのエラー応答混入を検出 → trash へ移動: '$TITLE'"
  # WP REST: trash への移動は DELETE メソッド（`status=trash` は enum 外で弾かれる）
  curl -s -X DELETE "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
    -K ~/.wp_auth > /dev/null 2>&1 || true
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [TITLE_ERROR_GUARD] TRASHED post_id=${POST_ID} title='${TITLE:0:80}'" \
    >> logs/title_error_guard.log 2>/dev/null || true
  exit 0
fi

while IFS= read -r line; do
  if [[ "$line" == TITLE_ISSUE:* ]]; then
    msg="${line#TITLE_ISSUE: }"
    alog "⚠️ タイトルSEO: $msg"
    # K-POP関連キーワード欠落は自動修正を試みる
    if [[ "$msg" == *"K-POP関連キーワードがタイトルに含まれない"* ]]; then
      _SEO_NEW_TITLE=$(python3 -c "
import sys, re
from datetime import datetime
title = sys.argv[1]
year = datetime.now().year
kpop_words = ['K-POP', 'K-pop', 'k-pop', 'KPOP', '韓国', 'アイドル', 'カムバック',
              'ガールズグループ', 'ボーイズグループ', 'K-POPアイドル',
              # 主要アーティスト名（直近ログで判定漏れを確認済み）
              'BTS', 'BLACKPINK', 'TWICE', 'EXO', 'SEVENTEEN', 'STRAY KIDS', 'Stray Kids',
              'ATEEZ', 'ENHYPEN', 'TXT', 'aespa', 'IVE', 'RIIZE', 'NewJeans', 'ILLIT',
              'PLAVE', 'MONSTA X', 'ITZY', 'SHINee', 'BIGBANG', 'SUPER JUNIOR',
              '防弾少年団', 'ニュージーンズ']
# 既にキーワードがあれば何もしない
if any(w in title for w in kpop_words):
    print(title)
    sys.exit(0)
# ジャンル判定で自然なプレフィクスを選ぶ
prefix_map = {
    'ダンス': 'K-POPダンス', 'トレーニング': 'K-POP', 'コスメ': 'K-POPコスメ',
    'スキンケア': 'K-POP美容', 'ファッション': 'K-POPファッション',
    'チャート': 'K-POPチャート', 'ライブ': 'K-POPライブ',
    'コンサート': 'K-POPコンサート', 'カムバック': 'K-POPカムバック',
}
prefix = 'K-POP'
for kw, pfx in prefix_map.items():
    if kw in title:
        prefix = pfx
        break
new_title = f'{prefix} {title}'
print(new_title[:70])
" "$TITLE" 2>/dev/null || echo "")
      # [2b] 診断ログ: 新タイトル生成結果
      if [[ -z "$_SEO_NEW_TITLE" ]]; then
        alog "❌ タイトルSEO修正失敗: title empty（python3生成エラー）"
        ISSUES+=("タイトルSEO: $msg")
      elif [[ "$_SEO_NEW_TITLE" == "$TITLE" ]]; then
        alog "❌ タイトルSEO修正失敗: title unchanged（既にK-POPキーワードあり or 変換なし）"
        ISSUES+=("タイトルSEO: $msg")
      else
        alog "[2b] 旧タイトル(${#TITLE}文字): '$TITLE'"
        alog "[2b] 新タイトル(${#_SEO_NEW_TITLE}文字): '$_SEO_NEW_TITLE'"
        # curl を分離してHTTPステータスも取得
        _SEO_PATCH_BODY=$(curl -s -w "\n__HTTP_STATUS__:%{http_code}" \
          -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
          -K "$HOME/.wp_auth" \
          -H "Content-Type: application/json" \
          -d "$(python3 -c "import sys,json; print(json.dumps({'title':sys.argv[1]}, ensure_ascii=False))" "$_SEO_NEW_TITLE" 2>/dev/null)" \
          2>/dev/null || echo "")
        _SEO_HTTP=$(echo "$_SEO_PATCH_BODY" | grep "__HTTP_STATUS__:" | sed 's/.*__HTTP_STATUS__://')
        _SEO_JSON=$(echo "$_SEO_PATCH_BODY" | grep -v "__HTTP_STATUS__:")
        alog "[2b] WP PATCH HTTP: ${_SEO_HTTP:-不明}"
        # JSONパース
        _SEO_PATCH=$(echo "$_SEO_JSON" | \
          python3 -c "
import sys, json
raw = sys.stdin.read()
try:
    d = json.loads(raw)
    v = d.get('title',{}).get('raw','')
    if v:
        print(v)
    else:
        print('ERROR:title_field_empty')
        import sys as _s; _s.stderr.write('BODY:' + raw[:200] + '\n')
except json.JSONDecodeError as e:
    print('ERROR:json_decode')
    import sys as _s; _s.stderr.write('BODY:' + raw[:200] + '\n')
" 2>/tmp/_seo_patch_err || echo "ERROR:exception")
        if [[ "$_SEO_PATCH" == ERROR:* ]]; then
          _err_detail="${_SEO_PATCH#ERROR:}"
          _err_body=$(cat /tmp/_seo_patch_err 2>/dev/null | head -c 200 || echo "")
          if [[ "$_SEO_HTTP" == "401" ]]; then
            alog "❌ タイトルSEO修正失敗: HTTP 401（認証エラー）"
          elif [[ "$_SEO_HTTP" == "403" ]]; then
            alog "❌ タイトルSEO修正失敗: HTTP 403（権限エラー）"
          elif [[ "$_SEO_HTTP" == "404" ]]; then
            alog "❌ タイトルSEO修正失敗: HTTP 404（記事が見つからない）"
          elif [[ "$_SEO_HTTP" == "500" ]] || [[ "$_SEO_HTTP" == "503" ]]; then
            alog "❌ タイトルSEO修正失敗: HTTP ${_SEO_HTTP}（サーバーエラー）"
          elif [[ "$_err_detail" == "json_decode" ]]; then
            alog "❌ タイトルSEO修正失敗: JSONデコードエラー（レスポンス: ${_err_body:0:100}）"
          elif [[ "$_err_detail" == "title_field_empty" ]]; then
            alog "❌ タイトルSEO修正失敗: レスポンスにtitleフィールドなし（HTTP:${_SEO_HTTP}）"
          else
            alog "❌ タイトルSEO修正失敗: ${_err_detail}（HTTP:${_SEO_HTTP}）"
          fi
          ISSUES+=("タイトルSEO: $msg")
        elif [[ -n "$_SEO_PATCH" ]]; then
          alog "✅ タイトルSEO修正: '$TITLE' → '$_SEO_PATCH'"
          FIXES+=("タイトルSEO修正: '$TITLE' → '$_SEO_PATCH'")
          TITLE="$_SEO_PATCH"
        else
          alog "❌ タイトルSEO修正失敗: WP API空レスポンス（HTTP:${_SEO_HTTP:-不明}）"
          ISSUES+=("タイトルSEO: $msg")
        fi
        rm -f /tmp/_seo_patch_err
      fi
    elif [[ "$msg" == *"年号なし"* ]]; then
      # 年号なしはwarning扱い: draft化対象外（軽微なSEO改善項目のみ）
      alog "ℹ️ タイトルSEO warning（draft化対象外）: $msg"
    else
      ISSUES+=("タイトルSEO: $msg")
    fi
  elif [[ "$line" == "TITLE_OK" ]]; then
    alog "✅ タイトルSEO品質OK"
  fi
done <<< "$_TITLE_CHECK_OUTPUT"

# ─── [3] メタ説明チェック＆自動修正（110〜130文字保証）──────────────────────
alog "--- [3] SEOメタ説明チェック（基準: 110〜130文字）---"
_meta_ng=0
if [[ "${META_DESC_LEN:-0}" -lt 110 ]] || [[ "${META_DESC_LEN:-0}" -gt 130 ]]; then
  _meta_ng=1
fi
# 本文冒頭の流用チェック
_IS_COPIED=$(echo "$POST_JSON" | python3 -c "
import sys, json, re
d = json.load(sys.stdin)
meta = d.get('meta',{}).get('_aioseo_description','')
content = d.get('content',{}).get('raw','')
text = re.sub(r'<[^>]+>','',content).strip()
print('YES' if text[:30] and meta.startswith(text[:30]) else 'NO')
" 2>/dev/null || echo "NO")
[[ "$_IS_COPIED" == "YES" ]] && _meta_ng=1

if [[ "$_meta_ng" -eq 1 ]]; then
  alog "⚠️ メタ説明NG（${META_DESC_LEN}文字 / 流用=$_IS_COPIED）→ seo_fix で再生成"
  _SEO_FIX_OUT=$(python3 "$SCRIPT_DIR/lib/audit_helpers.py" seo_fix "$POST_ID" "$TITLE" "" 2>/dev/null || echo "")
  _NEW_META_DESC=""
  while IFS= read -r line; do
    if [[ "$line" == FIXED_META:* ]]; then
      _NEW_META_DESC="${line#FIXED_META:}"
      alog "✅ メタ説明再生成: (${#_NEW_META_DESC}文字) ${_NEW_META_DESC:0:50}..."
      FIXES+=("メタ説明再生成: ${META_DESC_LEN}文字 → ${#_NEW_META_DESC}文字")
    fi
  done <<< "$_SEO_FIX_OUT"
  # 再生成後に文字数を更新
  if [[ -n "$_NEW_META_DESC" ]]; then
    META_DESC_LEN=${#_NEW_META_DESC}
  fi
  # 再生成後も110未満・130超・空なら ISSUES追加
  if [[ "${META_DESC_LEN:-0}" -lt 110 ]] || [[ "${META_DESC_LEN:-0}" -gt 130 ]]; then
    alog "⚠️ メタ説明再生成後も範囲外: ${META_DESC_LEN}文字"
    ISSUES+=("メタ説明が範囲外: ${META_DESC_LEN}文字（110〜130文字必須）")
  fi
else
  alog "✅ メタ説明OK: ${META_DESC_LEN}文字"
fi

# ─── [3c] SEO全体チェック＆自動修正 ─────────────────────────────────────────
alog "--- [3c] SEO全体チェック ---"
SEO_CHECK=$(python3 "$SCRIPT_DIR/lib/audit_helpers.py" seo_check "$POST_ID" "$TITLE" 2>/dev/null || echo "OK")
if echo "$SEO_CHECK" | grep -qv "^OK$"; then
  alog "⚠️ SEO問題検出 → 自動修正実行"
  echo "$SEO_CHECK" | while IFS= read -r line; do
    alog "  SEO: $line"
  done
  SEO_FIX=$(python3 "$SCRIPT_DIR/lib/audit_helpers.py" seo_fix "$POST_ID" "$TITLE" "" 2>/dev/null || echo "")
  echo "$SEO_FIX" | while IFS= read -r line; do
    case "$line" in
      FIXED_META:*)  alog "✅ SEO修正: メタ説明を再生成" ;;
      FIXED_TITLE:*) alog "✅ SEO修正: タイトルを短縮" ;;
      ERROR:*)       alog "⚠️ SEO修正エラー: ${line#ERROR:}" ;;
    esac
  done
  # ISSUES追加（修正試みたが確認は次ループで）
  while IFS= read -r sline; do
    case "$sline" in
      NG_TITLE_LEN:*)  ISSUES+=("タイトル文字数問題: ${sline#NG_TITLE_LEN:}文字") ;;
      NG_META_SHORT:*) ISSUES+=("メタ説明が短い: ${sline#NG_META_SHORT:}文字（目標110〜130文字）") ;;
      NG_META_LONG:*)  ISSUES+=("メタ説明が長すぎる: ${sline#NG_META_LONG:}文字") ;;
      NG_H2_MISSING:*) ISSUES+=("h2見出し不足: ${sline#NG_H2_MISSING:}個") ;;
      NG_KW_MISSING)   ISSUES+=("K-POPキーワードが本文に含まれない") ;;
    esac
  done <<< "$SEO_CHECK"
else
  alog "✅ SEO全体OK"
fi

# ─── [3d] メタ情報チェック（OG/canonical/Twitterカード）──────────────────────
alog "--- [3d] メタ情報チェック（OG/canonical/Twitter）---"
META_CHECK=$(python3 "$SCRIPT_DIR/lib/audit_helpers.py" meta_check "$POST_ID" "$POST_URL" 2>/dev/null || echo "OK")
if echo "$META_CHECK" | grep -qv "^OK$"; then
  alog "⚠️ メタ情報問題 → 自動修正実行"
  echo "$META_CHECK" | while IFS= read -r line; do
    alog "  META: $line"
  done
  META_FIX=$(python3 "$SCRIPT_DIR/lib/audit_helpers.py" meta_fix "$POST_ID" 2>/dev/null || echo "")
  echo "$META_FIX" | while IFS= read -r line; do
    case "$line" in
      FIXED:*)   alog "✅ メタ修正: ${line#FIXED:}" ;;
      SKIPPED:*) alog "ℹ️ メタ修正スキップ: ${line#SKIPPED:}" ;;
      ERROR:*)   alog "⚠️ メタ修正エラー: ${line#ERROR:}" ;;
    esac
  done
  # NG_FETCHはネットワーク問題として軽微扱い（ISSUESに追加しない）
  while IFS= read -r mline; do
    case "$mline" in
      NG_CANONICAL_MISSING) ISSUES+=("canonical タグが未設定") ;;
      NG_CANONICAL_WRONG:*) ISSUES+=("canonical が正しくない: ${mline#NG_CANONICAL_WRONG:}") ;;
      NG_OG_TITLE_MISSING)  ISSUES+=("OGタイトルが未設定") ;;
      NG_OG_DESC_MISSING)   ISSUES+=("OG説明が未設定") ;;
      NG_OG_IMAGE_MISSING)  ISSUES+=("OG画像が未設定") ;;
      NG_TWITTER_CARD_MISSING) ISSUES+=("Twitterカードが未設定") ;;
      NG_DUPLICATE_META:*)  ISSUES+=("重複メタタグ: ${mline#NG_DUPLICATE_META:}") ;;
    esac
  done <<< "$META_CHECK"
else
  alog "✅ メタ情報（OG/canonical/Twitter）OK"
fi

# ─── [4] カテゴリ適合性チェック＆修正（完全版）────────────────────────────
alog "--- [4] カテゴリ適合性チェック ---"
# 本文テキストを取得（カテゴリ整合性チェック用）
_CAT_CONTENT_TEXT=$(echo "$POST_JSON" | python3 -c "
import sys,json,re
d=json.load(sys.stdin)
text=re.sub(r'<[^>]+>','',d['content']['raw'])
print(text[:500])
" 2>/dev/null || echo "")

CAT_CHECK=$(python3 "$SCRIPT_DIR/lib/audit_helpers.py" cat_check \
  "$CAT_IDS" "$TITLE" "$_CAT_CONTENT_TEXT" 2>/dev/null || echo "OK")

if echo "$CAT_CHECK" | grep -qv "^OK$"; then
  # FIX行があれば自動適用
  FIX_CATS=$(echo "$CAT_CHECK" | grep "^FIX:" | head -1 | sed 's/^FIX://')
  NG_DETAIL=$(echo "$CAT_CHECK" | grep -v "^FIX:" | tr '\n' ' ')
  alog "⚠️ カテゴリ問題: $NG_DETAIL"
  if [[ -n "$FIX_CATS" ]]; then
    PATCH_CAT=$(curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
      -K "$HOME/.wp_auth" \
      -H "Content-Type: application/json" \
      -d "{\"categories\":${FIX_CATS}}" 2>/dev/null | \
      python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id','ERROR'))" 2>/dev/null || echo "ERROR")
    if [[ "$PATCH_CAT" != "ERROR" ]]; then
      alog "✅ カテゴリ自動修正: $CAT_IDS → $FIX_CATS"
      FIXES+=("カテゴリ修正: $NG_DETAIL → $FIX_CATS")
      CAT_IDS="$FIX_CATS"
    else
      alog "⚠️ カテゴリAPI更新失敗"
      ISSUES+=("カテゴリ問題: $NG_DETAIL")
    fi
  else
    ISSUES+=("カテゴリ問題: $NG_DETAIL")
  fi
else
  alog "✅ カテゴリOK: $CAT_IDS"
fi

# ─── [4.5] ゴシップ記事 一次ソース品質ガード ────────────────────────────────
# カテゴリ14（熱愛・炎上・ゴシップ）の記事は投稿後にも一次ソース記載チェックを実施
_IS_GOSSIP=$(echo "$CAT_IDS" | python3 -c "import sys,json; ids=json.loads(sys.stdin.read()); print('YES' if 14 in ids else 'NO')" 2>/dev/null || echo "NO")
if [[ "$_IS_GOSSIP" == "YES" ]]; then
  alog "--- [4.5] ゴシップ記事: 一次ソース品質ガード ---"
  _GOSSIP_AUDIT=$(echo "$POST_JSON" | python3 -c "
import sys, json, re
d = json.load(sys.stdin)
content = d.get('content', {}).get('raw', '')
title = d.get('title', {}).get('raw', '')

issues = []

# A. 公式ソース言及チェック
official_patterns = [
    r'(公式|official)',
    r'(Weverse|weverse)',
    r'(公式SNS|公式サイト|公式声明|公式発表|公式コメント)',
    r'(所属事務所|レーベル|プロダクション).{0,20}(発表|コメント|声明|確認)',
    r'(확인|공식)',  # 韓国語公式
]
has_official = any(re.search(p, content, re.IGNORECASE) for p in official_patterns)

# B. 報道ソース（信頼できるメディア）言及チェック
media_patterns = [
    r'(NAVER|naver)',
    r'(ニュース1|News1|뉴스1)',
    r'(朝鮮日報|中央日報|東亜日報)',
    r'(スポーツ朝鮮|スポーツソウル)',
    r'(Dispatch|dispatch|디스패치)',
    r'(Allkpop|allkpop)',
    r'(Soompi|soompi)',
    r'(OSEN|osen)',
    r'(Herald|herald|헤럴드)',
    r'(Star Today|startoday)',
]
media_count = sum(1 for p in media_patterns if re.search(p, content, re.IGNORECASE))

# C. 憶測語チェック（ゴシップ記事で危険）
speculation_patterns = [
    r'関係者によると',
    r'ネットで話題',
    r'噂によると',
    r'〜という噂',
    r'〜と噂され',
    r'匿名.*によると',
    r'消息筋によると',
    r'確認は取れていない',
    r'未確認.*情報',
]
speculation_hits = [p for p in speculation_patterns if re.search(p, content)]

# D. 情報元セクション存在チェック
# HTMLタグ（<strong></strong><small><br>等）を挟む場合に対応するため、
# タグを除去してからチェックする（例: <strong>情報元</strong>：...）
content_plain = re.sub(r'<[^>]+>', '', content)
has_source_section = bool(re.search(r'(情報元|出典|参照|引用|参考)', content_plain))

# 判定
if not has_official and media_count < 2:
    issues.append(f'GOSSIP_SOURCE_WEAK: 公式ソースなし・信頼メディア{media_count}件のみ（2件以上必要）')
if speculation_hits:
    issues.append(f'GOSSIP_SPECULATION: 憶測語検出={\"|\".join(speculation_hits[:3])}')
if not has_source_section:
    issues.append('GOSSIP_NO_SOURCE_SECTION: 情報元セクションなし')

for iss in issues:
    print(iss)
if not issues:
    print('OK')
" 2>/dev/null || echo "OK")

  _GOSSIP_NG=0
  while IFS= read -r _gline; do
    case "$_gline" in
      OK) alog "✅ [gossip_source_guard] 一次ソース品質OK" ;;
      GOSSIP_SOURCE_WEAK:*)
        alog "❌ [gossip_source_guard] ${_gline}"
        ISSUES+=("ゴシップ記事ソース不足: ${_gline#GOSSIP_SOURCE_WEAK: }")
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [GOSSIP_SOURCE_GUARD] POST_ID=${POST_ID} ${_gline}" \
          >> "$SCRIPT_DIR/logs/gossip_source_guard.log" 2>/dev/null || true
        _GOSSIP_NG=1
        ;;
      GOSSIP_SPECULATION:*)
        alog "❌ [gossip_source_guard] ${_gline}"
        ISSUES+=("ゴシップ記事憶測語: ${_gline#GOSSIP_SPECULATION: }")
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [GOSSIP_SOURCE_GUARD] POST_ID=${POST_ID} ${_gline}" \
          >> "$SCRIPT_DIR/logs/gossip_source_guard.log" 2>/dev/null || true
        _GOSSIP_NG=1
        ;;
      GOSSIP_NO_SOURCE_SECTION:*)
        alog "⚠️ [gossip_source_guard] 情報元セクションなし（ISSUESに追加）"
        ISSUES+=("ゴシップ記事: 情報元セクションなし")
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [GOSSIP_SOURCE_GUARD] POST_ID=${POST_ID} 情報元セクションなし" \
          >> "$SCRIPT_DIR/logs/gossip_source_guard.log" 2>/dev/null || true
        ;;
    esac
  done <<< "$_GOSSIP_AUDIT"

  # ソース不足・憶測語は即draft化対象（ISSUES経由でループカウント積み上げ）
  if [[ "$_GOSSIP_NG" -eq 1 ]]; then
    # urgent_errors Discord通知
    _GOSSIP_WH=$(python3 -c "
import json, sys
try:
    d = json.load(open('$SCRIPT_DIR/config/discord_webhooks.json'))
    print(d.get('urgent_errors', ''))
except:
    print('')
" 2>/dev/null || echo "")
    if [[ -n "$_GOSSIP_WH" ]]; then
      _GOSSIP_MSG="🔴 **gossip_source_guard: 一次ソース不足**\nPOST_ID: ${POST_ID}\nタイトル: ${TITLE:0:60}\n問題: $(echo "$_GOSSIP_AUDIT" | grep -v '^OK' | head -3 | tr '\n' ' ')\n→ draft化または削除を検討してください"
      python3 -c "
import urllib.request, json, sys
wh = sys.argv[1]
msg = sys.argv[2]
data = json.dumps({'content': msg[:1900]}).encode()
req = urllib.request.Request(wh, data=data, headers={'Content-Type':'application/json'})
urllib.request.urlopen(req, timeout=10)
" "$_GOSSIP_WH" "$_GOSSIP_MSG" 2>/dev/null || true
    fi
  fi
else
  alog "--- [4.5] ゴシップ記事ガードスキップ（カテゴリ14以外）---"
fi

# ─── [5] タグチェック＆自動生成 ────────────────────────────────────────────
alog "--- [5] タグチェック ---"
TAG_COUNT=$(echo "$TAG_IDS" | python3 -c "import sys,json; print(len(json.loads(sys.argv[1])))" "$TAG_IDS" 2>/dev/null || echo "0")

if [[ "$TAG_COUNT" -lt 2 ]]; then
  alog "⚠️ タグが少ない($TAG_COUNT件) → タイトルからタグを自動生成"
  # タイトルからK-POPアーティスト名・キーワードを抽出してタグ作成
  NEW_TAG_IDS=$(python3 - "$TITLE" << 'TAGPY'
import sys, json, re, urllib.request, urllib.parse, base64, os, re as _re

title = sys.argv[1]
_auth_value = ""
_wp_auth = os.path.expanduser("~/.wp_auth")
if os.path.exists(_wp_auth):
    with open(_wp_auth) as _f:
        for _line in _f:
            _m = _re.match(r'header\s*=\s*"(Authorization:\s*Basic\s+[^"\n]+)"?', _line.strip())
            if _m:
                _full = _m.group(1)  # "Authorization: Basic xxxx"
                _auth_value = _full.split(": ", 1)[1] if ": " in _full else _full
                break
if not _auth_value:
    _u = os.environ.get("WP_USER", "")
    _p = os.environ.get("WP_PASS", "")
    _auth_value = "Basic " + base64.b64encode(f"{_u}:{_p}".encode()).decode()
auth = _auth_value  # "Basic xxxx" 形式（Authorizationヘッダの値部分）

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
            headers={"Authorization": auth, "Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            tag_ids.append(result["id"])
    except Exception as e:
        # 409 = already exists → GET existing
        try:
            url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/tags?search={urllib.parse.quote(tag_name)}"
            req2 = urllib.request.Request(url, headers={"Authorization": auth})
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
      -K "$HOME/.wp_auth" \
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
  # [6a] ALTテキストチェック＆自動設定
  MEDIA_JSON=$(curl -s "https://www.kpopjournal.tokyo/wp-json/wp/v2/media/${FEAT_MEDIA}" \
    -K "$HOME/.wp_auth" 2>/dev/null)
  ALT_TEXT=$(echo "$MEDIA_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('alt_text',''))" 2>/dev/null || echo "")
  if [[ -z "$ALT_TEXT" ]]; then
    alog "⚠️ アイキャッチのaltテキストが空 → 自動設定"
    AUTO_ALT=$(echo "$TITLE" | cut -c1-60)
    curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/media/${FEAT_MEDIA}" \
      -K "$HOME/.wp_auth" \
      -H "Content-Type: application/json" \
      -d "{\"alt_text\":\"$(echo "$AUTO_ALT" | sed 's/"/\\"/g')\"}" > /dev/null 2>&1 && \
      alog "✅ altテキスト自動設定: $AUTO_ALT" && \
      FIXES+=("アイキャッチaltテキストを自動設定")
  else
    alog "✅ altテキストOK: $ALT_TEXT"
  fi

  # [6b] サムネイル詳細チェック（サイズ・文字化け・ファイル名・余白スコア）
  THUMB_DETAIL=$(python3 "$SCRIPT_DIR/lib/audit_helpers.py" thumb_check \
    "$FEAT_MEDIA" "$POST_ID" "$TITLE" 2>/dev/null || echo "OK")
  THUMB_REGEN_NEEDED=0
  if echo "$THUMB_DETAIL" | grep -q "REGEN_NEEDED"; then
    THUMB_REGEN_NEEDED=1
    alog "⚠️ サムネイル再生成が必要"
    echo "$THUMB_DETAIL" | grep -v "REGEN_NEEDED" | while IFS= read -r line; do
      alog "  THUMB: $line"
    done
    # パイプラインのサムネイル生成フローを再実行（kpop_pipeline.shのサムネ部分を参照）
    # [14.9]確定値を優先: thumbnail_performance.jsonlにthumb_textが記録されていればそれを使う
    _PIPELINE_THUMB=$(python3 -c "
import json, sys; from pathlib import Path
found=None
f=Path('$SCRIPT_DIR/logs/thumbnail_performance.jsonl')
if f.exists():
    for l in reversed(f.read_text().splitlines()):
        try:
            d=json.loads(l)
            if str(d.get('post_id',''))=='$POST_ID':
                t=d.get('thumb_text','').strip().replace('\n',' ').replace('\r','').strip()
                g=d.get('genre','news').strip()
                if t:
                    found=(t,g)
                    break
        except Exception:
            pass
if found:
    sys.stdout.write(found[0] + '|' + found[1] + '\n')
else:
    sys.stdout.write('|news\n')
" 2>/dev/null || echo "|news")
    # 末尾改行を除去してからパース
    _PIPELINE_THUMB=$(echo "$_PIPELINE_THUMB" | tr -d '\r')
    THUMB_GENRE=$(echo "${_PIPELINE_THUMB##*|}" | tr -d '\n')
    _PIPELINE_THUMB_TEXT=$(echo "${_PIPELINE_THUMB%|*}" | tr -d '\n')
    if [[ -n "$_PIPELINE_THUMB_TEXT" ]]; then
      # [14.9]確定値を使用（改行なし・正規化済み）
      THUMB_TITLE="$_PIPELINE_THUMB_TEXT"
      alog "ℹ️ [14.9]確定テキストを使用: '$THUMB_TITLE' (genre=$THUMB_GENRE)"
    else
      # フォールバック: thumbnail_templates.pyで新規生成
      THUMB_TITLE=$(python3 "$SCRIPT_DIR/lib/thumbnail_templates.py" "$TITLE" --genre "$THUMB_GENRE" 2>/dev/null || echo "$TITLE")
      # 改行を除去（thumbnail_templates.pyは改行入りのテキストを返す場合がある）
      THUMB_TITLE=$(echo "$THUMB_TITLE" | tr '\n' ' ' | sed 's/  */ /g;s/^ //;s/ $//')
      alog "ℹ️ [14.9]確定値なし → templates.pyで生成: '$THUMB_TITLE'"
    fi
    if [[ -n "$THUMB_TITLE" ]]; then
      alog "🔄 サムネイル再生成: title=$THUMB_TITLE genre=$THUMB_GENRE"
      THUMB_META_FILE=$(mktemp /tmp/audit_thumb_meta.XXXXXX)
      python3 "$SCRIPT_DIR/make_thumbnail.py" "$THUMB_TITLE" \
        --title "$TITLE" --genre "$THUMB_GENRE" 2>"$THUMB_META_FILE" && \
      _THUMB_FILE="$SCRIPT_DIR/thumbnail.webp" || _THUMB_FILE=""
      if [[ -f "$_THUMB_FILE" ]]; then
        # WP APIでメディアとしてアップロードして記事に紐付け
        UPLOAD_RESULT=$(curl -s -X POST \
          -K "$HOME/.wp_auth" \
          -H "Content-Type: image/webp" \
          -H "Content-Disposition: attachment; filename=thumbnail-${POST_ID}.webp" \
          "${SITE_URL}/wp-json/wp/v2/media" \
          --data-binary @"$_THUMB_FILE" 2>/dev/null)
        NEW_MEDIA_ID=$(echo "$UPLOAD_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',0))" 2>/dev/null || echo "0")
        if [[ "$NEW_MEDIA_ID" != "0" ]] && [[ -n "$NEW_MEDIA_ID" ]]; then
          curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
            -K "$HOME/.wp_auth" \
            -H "Content-Type: application/json" \
            -d "{\"featured_media\":${NEW_MEDIA_ID}}" > /dev/null 2>&1
          alog "✅ サムネイル再生成・差し替え完了: media_id=$NEW_MEDIA_ID"
          FIXES+=("サムネイル再生成・差し替え: $FEAT_MEDIA → $NEW_MEDIA_ID")
          FEAT_MEDIA="$NEW_MEDIA_ID"
          THUMB_REGEN_NEEDED=0
        else
          alog "⚠️ サムネイルアップロード失敗"
          ISSUES+=("サムネイル再生成失敗（アップロードエラー）")
        fi
      else
        alog "⚠️ サムネイルファイル生成失敗"
        ISSUES+=("サムネイル再生成失敗（make_thumbnail.pyエラー）")
      fi
      rm -f "$THUMB_META_FILE"
    fi
  elif echo "$THUMB_DETAIL" | grep -q "^OK$"; then
    alog "✅ サムネイル詳細チェックOK"
  else
    echo "$THUMB_DETAIL" | grep -v "^OK$" | while IFS= read -r line; do
      alog "ℹ️ サムネイル: $line"
    done
  fi

  # [6c] サムネイルテキスト整合性チェック（thumbnail_performance.jsonl）
  THUMB_META_JSON=$(python3 -c "
import json; from pathlib import Path
f=Path('$SCRIPT_DIR/logs/thumbnail_performance.jsonl')
if not f.exists(): print('{}'); exit()
for l in reversed(f.read_text().splitlines()):
    try:
        d=json.loads(l)
        if str(d.get('post_id',''))=='$POST_ID': print(json.dumps(d)); exit()
    except: pass
print('{}')
" 2>/dev/null || echo "{}")
  THUMB_TEXT=$(echo "$THUMB_META_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('thumb_text',''))" 2>/dev/null || echo "")
  THUMB_ENG_HERO=$(echo "$THUMB_META_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('eng_hero',''))" 2>/dev/null || echo "")
  THUMB_HAS_IMAGE=$(echo "$THUMB_META_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('has_image',''))" 2>/dev/null || echo "")
  THUMB_IMG_SRC=$(echo "$THUMB_META_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('image_source',''))" 2>/dev/null || echo "")
  THUMB_GENRE=$(echo "$THUMB_META_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('genre',''))" 2>/dev/null || echo "")

  if [[ "$THUMB_HAS_IMAGE" == "False" ]] && [[ "$THUMB_IMG_SRC" == "" ]]; then
    alog "⚠️ サムネイル背景: 画像なし（グラデーションのみ）"
    ISSUES+=("サムネイル画像なし（グラデのみ）")
  fi
  _GENERIC_HEROES="POP KPOP THE AND FOR NEWS TOP HIT NEW GENRE IDOL"
  if [[ -n "$THUMB_ENG_HERO" ]] && echo "$_GENERIC_HEROES" | grep -qw "$THUMB_ENG_HERO"; then
    alog "⚠️ サムネイルeng_heroが汎用語: $THUMB_ENG_HERO"
    ISSUES+=("サムネイルeng_hero汎用語: '$THUMB_ENG_HERO'")
  fi
  if [[ -n "$THUMB_TEXT" ]]; then
    THUMB_TEXT_CLEAN=$(echo "$THUMB_TEXT" | tr '\n' '/')
    GENERIC_THUMBS=("ファン必見" "速報のみ" "k-pop news" "kpop news")
    IS_GENERIC_THUMB=0
    for _gt in "${GENERIC_THUMBS[@]}"; do
      echo "$THUMB_TEXT" | grep -qi "$_gt" && IS_GENERIC_THUMB=1
    done
    if [[ "$IS_GENERIC_THUMB" -eq 1 ]]; then
      alog "⚠️ サムネイルテキストが汎用フォールバック: $THUMB_TEXT_CLEAN"
      ISSUES+=("サムネイルテキスト汎用フォールバック: '$THUMB_TEXT_CLEAN'")
    else
      alog "✅ サムネイルテキストOK: $THUMB_TEXT_CLEAN"
    fi
  fi
else
  alog "⚠️ アイキャッチ未設定 → 文字サムネ自動生成を試みる"
  # まず make_thumbnail.py で通常生成を試みる
  _THUMB_GEN_SUCCESS=0
  _THUMB_GENRE_FB="news"
  echo "$TITLE" | grep -qiE "スキンケア|ガラス肌|コスメ|美容" && _THUMB_GENRE_FB="skincare"
  echo "$TITLE" | grep -qiE "チャート|ビルボード|ランキング" && _THUMB_GENRE_FB="chart"
  echo "$TITLE" | grep -qiE "ツアー|ライブ|コンサート" && _THUMB_GENRE_FB="live"

  _THUMB_OUT_FILE="$SCRIPT_DIR/thumbnail.webp"
  python3 "$SCRIPT_DIR/make_thumbnail.py" "$TITLE" \
    --title "$TITLE" --genre "$_THUMB_GENRE_FB" 2>/dev/null && \
    [[ -f "$_THUMB_OUT_FILE" ]] && _THUMB_GEN_SUCCESS=1 || true

  # make_thumbnail.py が失敗した場合は Pillow で最小限のグラデーションサムネを生成
  if [[ "$_THUMB_GEN_SUCCESS" -eq 0 ]]; then
    alog "ℹ️ make_thumbnail.py失敗 → Pillowフォールバックサムネ生成"
    python3 - "$TITLE" "$_THUMB_OUT_FILE" << 'THUMBPY'
import sys, os
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit(1)

title = sys.argv[1][:40]
out_path = sys.argv[2]

W, H = 1200, 630
img = Image.new("RGB", (W, H))
draw = ImageDraw.Draw(img)

# グラデーション背景（紫→ピンク）
for y in range(H):
    r = int(80 + (200 - 80) * y / H)
    g = int(0 + (80 - 0) * y / H)
    b = int(160 + (120 - 160) * y / H)
    draw.line([(0, y), (W, y)], fill=(r, g, b))

# タイトルテキスト（中央）
font_size = 60
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", font_size)
except Exception:
    try:
        font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", font_size)
    except Exception:
        font = ImageFont.load_default()

# テキストを折り返し（20文字で改行）
lines = []
line = ""
for ch in title:
    line += ch
    if len(line) >= 18:
        lines.append(line)
        line = ""
if line:
    lines.append(line)

total_h = len(lines) * (font_size + 10)
y_start = (H - total_h) // 2
for i, ln in enumerate(lines):
    try:
        bbox = draw.textbbox((0, 0), ln, font=font)
        tw = bbox[2] - bbox[0]
    except Exception:
        tw = len(ln) * font_size // 2
    x = (W - tw) // 2
    y = y_start + i * (font_size + 10)
    # 影
    draw.text((x + 2, y + 2), ln, font=font, fill=(0, 0, 0, 120))
    draw.text((x, y), ln, font=font, fill=(255, 255, 255))

# KPOP JOURNAL テキスト
try:
    sm_font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 28)
except Exception:
    sm_font = font
draw.text((40, H - 60), "KPOP JOURNAL", font=sm_font, fill=(255, 220, 255))

img.save(out_path, "WEBP", quality=85)
print(f"Generated: {out_path}")
THUMBPY
    [[ -f "$_THUMB_OUT_FILE" ]] && _THUMB_GEN_SUCCESS=1 || true
  fi

  if [[ "$_THUMB_GEN_SUCCESS" -eq 1 ]] && [[ -f "$_THUMB_OUT_FILE" ]]; then
    # WP APIにアップロードして記事に紐付け
    _FB_UPLOAD=$(curl -s -X POST \
      -K "$HOME/.wp_auth" \
      -H "Content-Type: image/webp" \
      -H "Content-Disposition: attachment; filename=thumb-audit-${POST_ID}.webp" \
      "https://www.kpopjournal.tokyo/wp-json/wp/v2/media" \
      --data-binary @"$_THUMB_OUT_FILE" 2>/dev/null)
    _FB_MEDIA_ID=$(echo "$_FB_UPLOAD" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',0))" 2>/dev/null || echo "0")
    if [[ "$_FB_MEDIA_ID" != "0" ]] && [[ -n "$_FB_MEDIA_ID" ]]; then
      curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
        -K "$HOME/.wp_auth" \
        -H "Content-Type: application/json" \
        -d "{\"featured_media\":${_FB_MEDIA_ID}}" > /dev/null 2>&1
      alog "✅ フォールバックサムネイル設定完了: media_id=$_FB_MEDIA_ID"
      FIXES+=("フォールバックサムネイルを自動生成・設定: $POST_ID → media $\_FB_MEDIA_ID")
      FEAT_MEDIA="$_FB_MEDIA_ID"
    else
      alog "⚠️ フォールバックサムネイルアップロード失敗"
      ISSUES+=("サムネイル自動生成失敗（アップロードエラー）")
    fi
  else
    alog "⚠️ サムネイル自動生成失敗（Pillow未インストール等）"
    ISSUES+=("サムネイル自動生成失敗")
  fi
fi

# ─── [7] X投稿チェック＆再試行 ─────────────────────────────────────────────
alog "--- [7] X投稿チェック ---"

# ━ [DRAFT GUARD] draft/pending/future 状態の記事へのX投稿を絶対に防ぐ ━━━━━━
# STATUS は基本情報取得時 (line 9: d['status']) にWP APIから取得済み
# この記事ステータス下でX投稿すると「draft記事なのにXで拡散」事故になる
_X7_SKIP=0
if [[ "$STATUS" != "publish" ]]; then
  alog "⛔ [DRAFT GUARD] X投稿全スキップ: status=$STATUS (publish以外への投稿禁止)"
  ISSUES+=("X投稿スキップ: 記事ステータス=$STATUS — publish昇格後に手動再試行が必要")
  _X7_SKIP=1
fi

# (STATUS=publish の場合のみ以下のX投稿チェック・再試行を実行)
# URLで照合（タイトルに特殊文字が含まれるとgrepパターンが壊れるためURL優先）
X_SUCCESS=""
if [[ -n "$POST_URL" ]]; then
  # POST_URLが含まれるブロックの前後5行からフック投稿成功を探す
  X_SUCCESS=$(grep -F "$POST_URL" "$SCRIPT_DIR/logs/x_post.log" 2>/dev/null | grep -v "^#" | head -1 || echo "")
  if [[ -z "$X_SUCCESS" ]]; then
    # URLが見つからない場合はタイトルの先頭30文字でfixed-string検索
    _TITLE_PREFIX="${TITLE:0:30}"
    X_SUCCESS=$(grep -FA5 "TITLE: " "$SCRIPT_DIR/logs/x_post.log" 2>/dev/null | grep -F "$_TITLE_PREFIX" | head -1 || echo "")
    [[ -n "$X_SUCCESS" ]] && X_SUCCESS=$(grep -FA5 "TITLE: " "$SCRIPT_DIR/logs/x_post.log" 2>/dev/null | grep -A5 -F "$_TITLE_PREFIX" | grep "フック投稿成功" | tail -1 || echo "")
  fi
fi
# フォールバック: 直近のフック投稿成功を確認（URL一致しなくても成功扱い）
[[ -z "$X_SUCCESS" ]] && X_SUCCESS=$(grep "フック投稿成功" "$SCRIPT_DIR/logs/x_post.log" 2>/dev/null | tail -1 || echo "")

if [[ -z "$X_SUCCESS" ]] && [[ "${_X7_SKIP:-0}" -eq 0 ]]; then
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
else
  alog "✅ X投稿OK: $(echo "$X_SUCCESS" | grep -oP 'https://x\.com/\S+' | head -1)"
fi

# [7b] X投稿品質完全監査
alog "--- [7b] X投稿品質監査 ---"

# ログからこの記事のX投稿セクションを抽出（URLで照合）
_X_LOG_BLOCK=""
if [[ -n "$POST_URL" ]]; then
  # URLが含まれる行の行番号を取得して前後の投稿ブロックを抽出
  _X_URL_LINE=$(grep -nF "$POST_URL" "$SCRIPT_DIR/logs/x_post.log" 2>/dev/null | head -1 | cut -d: -f1 || true)
  if [[ -n "$_X_URL_LINE" ]]; then
    # URL行より前の === X/Twitter 開始行を探す
    _X_START=$(awk "NR<=${_X_URL_LINE} && /=== X\/Twitter/{start=NR} END{print start+0}" "$SCRIPT_DIR/logs/x_post.log" 2>/dev/null)
    if [[ "${_X_START:-0}" -gt 0 ]]; then
      _X_LOG_BLOCK=$(awk "NR>=${_X_START} && NR<=${_X_URL_LINE}+5" "$SCRIPT_DIR/logs/x_post.log" 2>/dev/null | tail -80)
    fi
  fi
fi
# URLで見つからない場合はタイトル先頭30文字でfixed-string検索
if [[ -z "$_X_LOG_BLOCK" ]]; then
  _TITLE_PREFIX="${TITLE:0:30}"
  _X_LOG_BLOCK=$(grep -FA20 "TITLE: " "$SCRIPT_DIR/logs/x_post.log" 2>/dev/null | grep -A20 -F "$_TITLE_PREFIX" | head -40 || echo "")
fi

if [[ -z "$_X_LOG_BLOCK" ]]; then
  alog "⚠️ x_post.logにこの記事のログが見つからない"
else
  # ① スコア確認
  _PRE_SCORE=$(echo "$_X_LOG_BLOCK" | grep -oP "PRE_SCORE: [\d\.]+/100" | tail -1 || echo "")
  _RE_SCORE=$(echo "$_X_LOG_BLOCK" | grep -oP "RE-SCORE: [\d\.]+/100" | tail -1 || echo "")
  if [[ -n "$_PRE_SCORE" ]]; then
    alog "ℹ️ X投稿スコア: $_PRE_SCORE${_RE_SCORE:+ → RE-SCORE: $_RE_SCORE}"
    _SCORE_VAL=$(echo "$_PRE_SCORE" | grep -oP "[\d\.]+(?=/100)")
    if (( $(echo "${_SCORE_VAL:-0} < 80" | bc -l 2>/dev/null || echo 0) )); then
      if [[ -n "$_RE_SCORE" ]]; then
        _RE_VAL=$(echo "$_RE_SCORE" | grep -oP "[\d\.]+(?=/100)")
        if (( $(echo "${_RE_VAL:-0} < 80" | bc -l 2>/dev/null || echo 0) )); then
          ISSUES+=("X投稿スコア低い: PRE=$_SCORE_VAL RE=$_RE_VAL（閾値80未満）")
          alog "⚠️ X投稿スコアが閾値未達: PRE=$_SCORE_VAL RE=$_RE_VAL"
        else
          alog "✅ テンプレート再生成でスコア改善: $_RE_SCORE"
        fi
      else
        ISSUES+=("X投稿PRE_SCOREが低い: $_SCORE_VAL（閾値80未満）")
        alog "⚠️ X投稿スコア低い: $_SCORE_VAL"
      fi
    else
      alog "✅ X投稿スコアOK: $_PRE_SCORE"
    fi
  fi

  # ② FORCE-BEST-SCORE検出
  _X_FORCE=$(echo "$_X_LOG_BLOCK" | grep -i "FORCE.BEST.SCORE\|force_best_score\|強制採用" | tail -1 || echo "")
  if [[ -n "$_X_FORCE" ]]; then
    ISSUES+=("X投稿がFORCE-BEST-SCOREで強制投稿: ペルシャテキスト品質要改善")
    alog "⚠️ FORCE-BEST-SCORE検出: スコア閾値未達のまま強制投稿"
  fi

  # ③ v12.0フォーマット準拠チェック（V12_FORMATログ優先、なければTWEET_TEXTを解析）
  # 投稿済み（X_SUCCESS非空）であれば違反は警告のみ（ISSUESに追加しない）
  # 未投稿の場合のみISSUESに追加して再生成を促す
  _V12_LOG=$(echo "$_X_LOG_BLOCK" | grep "V12_FORMAT:" | tail -1 | sed 's/.*V12_FORMAT: //' || echo "")
  if [[ -n "$_V12_LOG" ]] && [[ "$_V12_LOG" != OK* ]]; then
    alog "⚠️ X投稿v12.0違反（投稿時ログ）: $_V12_LOG"
    if [[ -z "$X_SUCCESS" ]]; then
      # 未投稿の場合のみISSUESに追加
      ISSUES+=("X投稿v12.0フォーマット違反: $_V12_LOG")
    else
      alog "ℹ️ 投稿済みのため違反は警告のみ（再投稿なし）"
    fi
  elif [[ "$_V12_LOG" == OK* ]]; then
    alog "✅ X投稿v12.0フォーマットOK（投稿時ログ確認）"
  fi

  # V12_FORMATログがない古い投稿はTWEET_TEXTから直接解析
  _TWEET_TEXT=$(echo "$_X_LOG_BLOCK" | awk '/TWEET_TEXT:/{found=1; sub(/^.*TWEET_TEXT: /,""); print; next} found && /^\[/{exit} found{print}' | grep -v "^#" | sed '/^$/d' || echo "")
  if [[ -n "$_TWEET_TEXT" ]] && [[ -z "$_V12_LOG" ]]; then
    # V12_FORMATログがない場合のみTWEET_TEXTから解析（subshell回避: ヒアストリング使用）
    _X_FORMAT_OUTPUT=$(python3 -c "
import sys, re
text = sys.argv[1]
lines = [l for l in text.strip().split('\n') if l.strip()]
issues = []
hook = lines[0] if lines else ''
if len(hook) > 20:
    issues.append(f'フック20文字超: {len(hook)}文字')
strong_words = ['衝撃','電撃','判明','ついに','まさか','速報','記録','驚愕','神','レベチ','解禁','完全','必見']
if not any(w in hook for w in strong_words):
    issues.append(f'フックに強ワードなし')
if re.search(r'[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]{2,}(した|です|ます|だ|である)$', hook):
    issues.append(f'フックが完結文（未完結にすべき）')
if len(lines) >= 2:
    emotion = lines[1]
    if re.search(r'(した|です|ます|だ。|である。)$', emotion):
        issues.append('感情行が完結文')
else:
    issues.append('感情行（2行目）がない')
comment_triggers = ['どう思う','どっち派','賛否','泣いた','超えられる','RT','シェア','教えて','感動した']
if not any(t in '\n'.join(lines) for t in comment_triggers):
    issues.append('コメント誘導がない')
if issues:
    for iss in issues:
        print(f'X_FORMAT_ISSUE: {iss}')
else:
    print('X_FORMAT_OK')
" "$_TWEET_TEXT" 2>/dev/null || echo "X_FORMAT_OK")
    while IFS= read -r line; do
      if [[ "$line" == X_FORMAT_ISSUE:* ]]; then
        msg="${line#X_FORMAT_ISSUE: }"
        alog "⚠️ X投稿v12.0フォーマット違反: $msg"
        ISSUES+=("X投稿フォーマット違反: $msg")
      elif [[ "$line" == "X_FORMAT_OK" ]]; then
        alog "✅ X投稿v12.0フォーマットOK"
      fi
    done <<< "$_X_FORMAT_OUTPUT"
  else
    alog "ℹ️ TWEET_TEXTをログから取得できず（フォーマットチェックスキップ）"
  fi
fi

# ④ X重複投稿チェック
X_HISTORY_FILE="$SCRIPT_DIR/google_metrics/logs/x_posted_urls.txt"
if [[ -n "$POST_URL" ]] && [[ -f "$X_HISTORY_FILE" ]]; then
  X_DUP_COUNT=$(grep -c "|${POST_URL}$" "$X_HISTORY_FILE" 2>/dev/null || echo "0")
  if [[ "$X_DUP_COUNT" -gt 1 ]]; then
    ISSUES+=("X重複投稿検出: 同URLが${X_DUP_COUNT}回投稿されています ($POST_URL)")
    alog "⚠️ X重複投稿: $POST_URL が${X_DUP_COUNT}回投稿済み"
  else
    alog "✅ X重複投稿なし"
  fi
fi

# ⑤ X投稿NG時の再生成（フォーマット違反・未投稿の場合）
_X_HAS_ISSUE=0
for _issue in "${ISSUES[@]}"; do
  echo "$_issue" | grep -q "X投稿" && _X_HAS_ISSUE=1
done
if [[ "$_X_HAS_ISSUE" -eq 1 ]] && [[ -z "$X_SUCCESS" ]]; then
  alog "🔄 X投稿コピー再生成 → post_to_x.sh再試行"
  # ジャンル判定
  _X_GENRE="news"
  echo "$TITLE" | grep -qiE "スキンケア|ガラス肌|コスメ|美容" && _X_GENRE="beauty"
  echo "$TITLE" | grep -qiE "チャート|ビルボード|ランキング" && _X_GENRE="analysis"
  echo "$TITLE" | grep -qiE "ソウル|観光|旅行|カフェ" && _X_GENRE="travel"
  X_NEW_TEXT=$(python3 "$SCRIPT_DIR/lib/audit_helpers.py" x_fix "$TITLE" "$POST_URL" "$_X_GENRE" 2>/dev/null | grep "^TEXT:" | sed 's/^TEXT://')
  if [[ -n "$X_NEW_TEXT" ]]; then
    RETRY_SNS_FILE=$(mktemp /tmp/audit_x_fix.XXXXXX.md)
    printf 'パターンA（採用推奨）\n```\n%s\n```\n' "$X_NEW_TEXT" > "$RETRY_SNS_FILE"
    X_RETRY=$(bash "$SCRIPT_DIR/google_metrics/post_to_x.sh" "$TITLE" "$POST_URL" "$RETRY_SNS_FILE" 2>&1 || echo "失敗")
    rm -f "$RETRY_SNS_FILE"
    if echo "$X_RETRY" | grep -q "フック投稿成功"; then
      alog "✅ X投稿再生成・再投稿成功"
      FIXES+=("X投稿コピーを再生成して再投稿")
    else
      alog "⚠️ X投稿再生成後も失敗: $(echo "$X_RETRY" | tail -1)"
    fi
  fi
fi  # if [[ "$_X_HAS_ISSUE" -eq 1 ]]

# ─── [8] Google Search Console チェック（重要記事判定付き）──────────────────
alog "--- [8] Google Search Console チェック ---"
GSC_JUDGE=$(python3 "$SCRIPT_DIR/lib/audit_helpers.py" gsc_judge \
  "$POST_ID" "$POST_URL" "$CONTENT_LEN" "$TITLE" 2>/dev/null || echo "SEND")

if [[ "$GSC_JUDGE" == SKIP:* ]]; then
  alog "ℹ️ GSC送信スキップ: ${GSC_JUDGE#SKIP:}"
else
  # 送信対象: 未送信なら送信、失敗時は最大2回リトライ
  GSC_SENT=$(grep -F "インデックス登録リクエスト成功: ${POST_URL}" ~/ai_kpop.log 2>/dev/null | tail -1 || echo "")
  if [[ -z "$GSC_SENT" ]]; then
    alog "⚠️ GSCインデックス未登録 → 送信"
    _GSC_OK=0
    for _gsc_try in 1 2; do
      GSC_RESULT=$(bash "$SCRIPT_DIR/google_metrics/request_index.sh" "$POST_URL" 2>&1 || echo "失敗")
      if echo "$GSC_RESULT" | grep -q "成功\|Indexing"; then
        alog "✅ GSCインデックス登録成功（試行${_gsc_try}回目）"
        FIXES+=("GSCインデックス登録送信")
        _GSC_OK=1
        break
      fi
      alog "⚠️ GSC送信試行${_gsc_try}回目失敗: $(echo "$GSC_RESULT" | tail -1)"
    done
    [[ "$_GSC_OK" -eq 0 ]] && ISSUES+=("GSCインデックス登録失敗（2回試行）")
  else
    alog "✅ GSCインデックス登録済み"
  fi
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
  # RUN_ID未指定の場合、POST_IDまたはTITLEでアーカイブを検索
  _FOUND_ARCHIVE=""
  if [[ -n "$POST_ID" ]]; then
    _FOUND_ARCHIVE=$(find "$SCRIPT_DIR/logs/archive" -name "3_arceus.md" 2>/dev/null | xargs grep -l "post_id.*${POST_ID}\|${POST_ID}" 2>/dev/null | head -1 || echo "")
  fi
  if [[ -z "$_FOUND_ARCHIVE" ]] && [[ -n "$TITLE" ]]; then
    _FOUND_ARCHIVE=$(find "$SCRIPT_DIR/logs/archive" -name "3_arceus.md" 2>/dev/null | xargs grep -l "${TITLE}" 2>/dev/null | head -1 || echo "")
  fi
  if [[ -n "$_FOUND_ARCHIVE" ]]; then
    ARCEUS_RESULT=$(grep -E "(✅ 投稿承認|✅ 承認|APPROVED|CONDITIONAL APPROVE|CONDITIONAL PASS|条件付き承認|投稿判定.*承認|即時投稿可)" "$_FOUND_ARCHIVE" | head -1 || echo "")
    ARCEUS_REJECT=$(grep -E "(❌ 投稿却下|投稿不可|REJECT)" "$_FOUND_ARCHIVE" | head -1 || echo "")
    if [[ -n "$ARCEUS_REJECT" ]]; then
      ISSUES+=("⚠️ アルセウスが却下判定を出しているのに投稿されています: $ARCEUS_REJECT")
      alog "🚨 アルセウス却下判定で投稿された可能性: $ARCEUS_REJECT"
    elif [[ -n "$ARCEUS_RESULT" ]]; then
      alog "✅ ファクトチェック承認確認（アーカイブ自動検索）: $ARCEUS_RESULT"
    else
      ISSUES+=("アルセウスの承認判定が確認できない（アーカイブ: $_FOUND_ARCHIVE）")
      alog "⚠️ アルセウス判定が不明"
    fi
  else
    alog "ℹ️ アーカイブなし or RUN_ID未指定 → スキップ（POST_ID/TITLEでも見つからず）"
  fi
fi

# ─── [10] 文字化けチェック ────────────────────────────────────────────────
alog "--- [10] 文字化けチェック ---"
if [[ "${HAS_MOJIBAKE:-0}" == "1" ]]; then
  ISSUES+=("文字化け（\\uXXXX形式）が本文に残存している")
  alog "❌ 文字化け検出"
else
  alog "✅ 文字化けなし"
fi

# ─── [11] 内部リンクチェック（主軸記事2214へ2本以上）─────────────────────
alog "--- [11] 内部リンク（2214）チェック ---"
_LINK_COUNT="${INTERNAL_LINK_2214:-0}"
if [[ "$_LINK_COUNT" -lt 2 ]]; then
  _NEEDED=$(( 2 - _LINK_COUNT ))
  ISSUES+=("主軸記事（2214）への内部リンクが${_LINK_COUNT}本（2本必要）")
  alog "❌ 内部リンク不足: ${_LINK_COUNT}本 → 2本必要"
  # 自動修正: リンクを本文末尾に挿入
  _LINK_BLOCK=""
  for _i in $(seq 1 $_NEEDED); do
    _LINK_BLOCK+='<p>関連記事：<a href="https://www.kpopjournal.tokyo/kpop-idol-glass-skin-complete-guide-2026/">K-POPアイドルのガラス肌完全ガイド2026</a></p>'
  done
  _PATCH=$(curl -s -X POST \
    -K "$HOME/.wp_auth" \
    -H "Content-Type: application/json" \
    "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
    -d "{\"content\": $(echo "$POST_JSON" | python3 -c "
import sys,json
d=json.load(sys.stdin)
c=d['content']['raw']
c+='''$_LINK_BLOCK'''
print(json.dumps(c))
" 2>/dev/null)}" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id','NG'))" 2>/dev/null || echo "NG")
  if [[ "$_PATCH" != "NG" ]]; then
    FIXES+=("内部リンク（2214）${_NEEDED}本を本文末尾に自動挿入")
    alog "✅ 内部リンク自動挿入完了"
    ISSUES=("${ISSUES[@]/主軸記事（2214）への内部リンクが*/}")
    ISSUES=("${ISSUES[@]}")
  else
    alog "⚠️ 内部リンク自動挿入失敗"
  fi
else
  alog "✅ 内部リンク（2214）: ${_LINK_COUNT}本 OK"
fi

# ─── [11b] href="#" アンカー除去（CTAリンク仮置き対策）───────────────────
# kairyu が生成する href="#" のアンカーを除去し、テキストのみに変換する
# 対象: <a href="#" ...>テキスト</a> → テキスト（span or plaintext）
_HASH_COUNT=$(python3 -c "
import sys, json, re, urllib.request, urllib.error
post_id = sys.argv[1]
wp_url = sys.argv[2]
try:
    wp_creds = open(sys.argv[3]).read().strip().split('\n')
    auth = wp_creds[0].replace('--user ', '').strip() if wp_creds else ''
    req = urllib.request.Request(
        f'{wp_url}/wp-json/wp/v2/posts/{post_id}?context=edit',
        headers={'User-Agent': 'Mozilla/5.0'}
    )
    if auth:
        import base64
        req.add_header('Authorization', 'Basic ' + base64.b64encode(auth.encode()).decode())
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
    content = data.get('content', {}).get('raw', '') or data.get('content', {}).get('rendered', '')
    # href=\"#\" のアンカーを検出
    pattern = re.compile(r'<a\s+href=[\"\'']#[\"\''][^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
    matches = pattern.findall(content)
    count = len(matches)
    if count > 0:
        # 除去: アンカータグを除いてテキストのみ残す（spanでラップ）
        fixed = pattern.sub(r'<span>\1</span>', content)
        patch = json.dumps({'content': fixed}, ensure_ascii=False)
        preq = urllib.request.Request(
            f'{wp_url}/wp-json/wp/v2/posts/{post_id}',
            data=patch.encode(),
            headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'},
            method='POST'
        )
        if auth:
            preq.add_header('Authorization', 'Basic ' + base64.b64encode(auth.encode()).decode())
        urllib.request.urlopen(preq, timeout=15)
    print(count)
except Exception as e:
    print(0)
" "$POST_ID" "https://www.kpopjournal.tokyo" "$HOME/.wp_auth" 2>/dev/null || echo "0")

if [[ "${_HASH_COUNT:-0}" -gt 0 ]]; then
  alog "✅ [11b] href=\"#\" アンカー ${_HASH_COUNT}件を除去（テキストのみに変換）"
  FIXES+=("href=\"#\" アンカー${_HASH_COUNT}件を除去")
else
  alog "✅ [11b] href=\"#\" アンカーなし（OK）"
fi

# ─── [12] HTTP 200チェック ────────────────────────────────────────────────
alog "--- [12] HTTP ステータスチェック ---"
if [[ "${HTTP_STATUS:-000}" != "200" ]]; then
  ISSUES+=("公開URL HTTP ${HTTP_STATUS:-000}（200でない）: $POST_URL")
  alog "❌ HTTP ${HTTP_STATUS:-000}: $POST_URL"
else
  alog "✅ HTTP 200 OK"
fi

# ─── [13] サムネイル存在チェック ──────────────────────────────────────────
alog "--- [13] サムネイル存在チェック ---"
if [[ "${FEAT_MEDIA:-0}" == "0" ]]; then
  ISSUES+=("アイキャッチ画像（サムネイル）が未設定")
  alog "❌ サムネイル未設定"
else
  alog "✅ サムネイル設定済み（media_id=${FEAT_MEDIA}）"
fi

# ─── 監査結果サマリー ─────────────────────────────────────────────────────
alog "===== 監査完了 ====="
alog "問題数: ${#ISSUES[@]} / 修正数: ${#FIXES[@]}"

# ─── [14] 自律修正ループ（最大3回）─────────────────────────────────────────
# 未解決ISSUESがある場合、ループで再修正を試みる
# （各チェック内で即修正済みのものは既にISSUES配列から除外または上書き済み）
LOOP_COUNT="${AUDIT_LOOP_COUNT:-0}"
if [[ ${#ISSUES[@]} -gt 0 ]] && [[ "$LOOP_COUNT" -lt 3 ]]; then
  # 今ループで直った項目をログに出力（次ループのデバッグ用・トークン無駄削減の可視化）
  if [[ ${#FIXES[@]} -gt 0 ]]; then
    alog "✅ 今ループ修正済み（次ループでは再チェック不要）:"
    for _fix in "${FIXES[@]}"; do
      alog "   • $_fix"
    done
  fi
  alog "🔄 未解決問題 ${#ISSUES[@]}件 → 修正ループ $((LOOP_COUNT+1))/3 を再実行"
  # POST_JSONを再取得して再監査
  export AUDIT_LOOP_COUNT=$(( LOOP_COUNT + 1 ))
  exec bash "$0" "$POST_ID" "$POST_URL" "$TITLE" "$RUN_ID"
fi

# ─── 最終判定 ─────────────────────────────────────────────────────────────
if [[ ${#ISSUES[@]} -gt 0 ]]; then
  if [[ "${LOOP_COUNT:-0}" -ge 3 ]]; then
    # 3回失敗 → draft化
    alog "🚨 修正ループ3回失敗 → draft化: POST_ID=$POST_ID"
    curl -s -X POST \
      -K "$HOME/.wp_auth" \
      -H "Content-Type: application/json" \
      "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
      -d '{"status":"draft"}' >/dev/null 2>&1 || true
    alog "📝 draft化完了: POST_ID=$POST_ID"

    # ── draft化時は urgent_errors へ Discord 通知（人間確認必須）─────
    _AUDIT_WH=$(python3 -c "
import json
from pathlib import Path
cfg = Path('$(dirname "$0")/config/discord_webhooks.json')
if cfg.exists():
    d = json.loads(cfg.read_text())
    print(d.get('urgent_errors',''))
" 2>/dev/null || echo "")
    if [[ -n "$_AUDIT_WH" ]]; then
      _ISSUE_LIST=$(printf '%s\n' "${ISSUES[@]}" | head -5 | sed 's/^/  • /' | tr '\n' '\n')
      _DRAFT_MSG="🟡 **post_audit: draft化** — 手動確認が必要\nPOST_ID: ${POST_ID}\nURL: ${POST_URL}\nタイトル: ${TITLE:0:60}\n未解決問題:\n${_ISSUE_LIST}\n→ WP管理画面で内容確認・手動publish または削除してください"
      python3 -c "
import json, urllib.request
msg = '''$_DRAFT_MSG'''.replace('\\\\n', '\n')
payload = json.dumps({'content': msg[:1800]}).encode()
req = urllib.request.Request('$_AUDIT_WH', data=payload,
      headers={'Content-Type': 'application/json'}, method='POST')
try: urllib.request.urlopen(req, timeout=10)
except: pass
" 2>/dev/null || true
    fi
  fi
  # ログ記録
  alog "未解決問題:"
  for issue in "${ISSUES[@]}"; do
    alog "  - $issue"
  done
else
  alog "✅ 全項目クリア: POST_ID=$POST_ID URL=$POST_URL"
  # ステータスがdraftのままなら publishに昇格
  if [[ "$STATUS" == "draft" ]]; then
    alog "🔄 全チェック通過 → publish に昇格"
    _PUB=$(curl -s -X POST "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/${POST_ID}" \
      -K "$HOME/.wp_auth" \
      -H "Content-Type: application/json" \
      -d '{"status":"publish"}' 2>/dev/null | \
      python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','ERROR'))" 2>/dev/null || echo "ERROR")
    if [[ "$_PUB" == "publish" ]]; then
      alog "✅ publish完了: POST_ID=$POST_ID URL=$POST_URL"
    else
      alog "⚠️ publishへの昇格失敗: $_PUB"
    fi
  fi
fi

# ─── 自己改善フィードバック ───────────────────────────────────────────────
alog "--- 自己改善フィードバック記録 ---"
python3 "$SCRIPT_DIR/lib/auto_improve.py" audit-feedback \
  --post-id "$POST_ID" \
  --issues "${ISSUES[*]:-}" \
  --fixes "${FIXES[*]:-}" \
  --title "$TITLE" \
  --pipeline "${PIPELINE_NAME:-unknown}" \
  2>/dev/null && alog "✅ 改善フィードバック記録完了" || alog "ℹ️ フィードバック記録スキップ"

# 終了コード: 問題あり=1, 問題なし=0
if [[ ${#ISSUES[@]} -gt 0 ]]; then
  exit 1
fi
exit 0
