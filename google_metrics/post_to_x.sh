#!/bin/bash
# ============================================================
# post_to_x.sh - X/Twitter 自動投稿（OAuth 1.0a 正規API版）
#
# Usage:
#   bash $_SCRIPT_DIR/google_metrics/post_to_x.sh "記事タイトル" "記事URL" "persian出力ファイル"
#   bash $_SCRIPT_DIR/google_metrics/post_to_x.sh "記事タイトル" "記事URL"
# ============================================================
set -euo pipefail

# .envから環境変数を読み込み
_SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$_SCRIPT_DIR/.env" ]; then
  set -a; source "$_SCRIPT_DIR/.env"; set +a
fi

# ログファイル
X_LOG="/home/aiuser/kpop-ai-system/logs/x_post.log"
mkdir -p "$(dirname "$X_LOG")"

xlog() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
  echo "$msg" >> "$X_LOG"
  echo "$msg"
}

# dry-run制御: ENABLE_X_POST=1 で本番投稿、未設定/0 でdry-run
DRY_RUN=true
if [ "${ENABLE_X_POST:-0}" = "1" ]; then
  DRY_RUN=false
fi

# ─── §10 フェイルセーフ: CTR低下3連続・IMP低下 → 投稿停止 ──────────────────
_FAILSAFE_LOG="/home/aiuser/kpop-ai-system/logs/x_failsafe.jsonl"
_FAILSAFE_ACTIVE=false

check_failsafe() {
  # 直近3件の x_post 結果を title_performance.jsonl から確認
  PERF_FILE="/home/aiuser/kpop-ai-system/logs/title_performance.jsonl"
  if [ ! -f "$PERF_FILE" ]; then return; fi

  CONSECUTIVE_LOW=$(python3 - << 'PYEOF'
import json, sys
from pathlib import Path
perf = Path("/home/aiuser/kpop-ai-system/logs/title_performance.jsonl")
kpi = Path("/home/aiuser/kpop-ai-system/logs/kpi_posts.jsonl")

# X投稿した記事のpost_idセットを取得
x_posted_ids = set()
if kpi.exists():
    for line in kpi.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line: continue
        try:
            r = json.loads(line)
            if str(r.get("x_post_status","")) in ("成功", "投稿成功"):
                pid = str(r.get("post_id",""))
                if pid:
                    x_posted_ids.add(pid)
        except: pass

# X投稿済み記事のwin/loseのみを対象に直近3件を確認
records = []
if perf.exists():
    for line in perf.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line: continue
        try:
            r = json.loads(line)
            # backfill（GSC一括登録）は除外。x_posted_ids にあるもののみ
            pid = str(r.get("post_id",""))
            if r.get("result") in ("win", "lose"):
                # post_idがx_posted_idsにある場合のみカウント（ない場合はX投稿外の記事）
                if not x_posted_ids or pid in x_posted_ids:
                    records.append(r)
        except: pass

# X投稿データが不足な場合はフェイルセーフ発動しない
if len(x_posted_ids) < 3:
    print("0")
    sys.exit()

# 直近3件がすべて lose → フェイルセーフ発動
recent = records[-3:] if len(records) >= 3 else []
if len(recent) == 3 and all(r.get("result") == "lose" for r in recent):
    print("1")
else:
    print("0")
PYEOF
)

  if [ "${CONSECUTIVE_LOW:-0}" = "1" ]; then
    _FAILSAFE_ACTIVE=true
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "{\"ts\":\"$ts\",\"event\":\"failsafe_triggered\",\"reason\":\"CTR低下3連続\"}" >> "$_FAILSAFE_LOG"
    xlog "⛔ §10 フェイルセーフ発動: CTR低下3連続 → 投稿停止"
  fi
}

check_failsafe

if [ "$_FAILSAFE_ACTIVE" = "true" ]; then
  xlog "RESULT: フェイルセーフによりスキップ (logs/x_failsafe.jsonl 参照)"
  echo "⛔ X投稿停止中（フェイルセーフ発動）— CTR低下3連続を確認してください"
  exit 0
fi

TITLE="${1:-}"
POST_URL="${2:-}"
PERSIAN_FILE="${3:-}"

if [ -z "$TITLE" ]; then
  xlog "ERROR: タイトルが指定されていません"
  exit 1
fi

# ── sns_config.json による X/Twitter 有効・無効チェック ──
_SNS_CFG="$_SCRIPT_DIR/config/sns_config.json"
if [ -f "$_SNS_CFG" ]; then
  _X_ENABLED=$(python3 -c "import json; c=json.load(open('$_SNS_CFG')); print(c.get('twitter',{}).get('enabled','true'))" 2>/dev/null || echo "true")
  if [ "$_X_ENABLED" = "False" ] || [ "$_X_ENABLED" = "false" ]; then
    _X_REASON=$(python3 -c "import json; c=json.load(open('$_SNS_CFG')); print(c.get('twitter',{}).get('reason','disabled'))" 2>/dev/null || echo "disabled")
    xlog "SKIP: Xアカウント停止中 (reason=$_X_REASON)"
    echo "⏭️ SKIP: Xアカウント停止中 — X投稿をスキップして正常終了 (reason=$_X_REASON)"
    exit 0
  fi
fi

# ── POST_AUDIT_GATE: 記事URLがsoft-404なら投稿全体をスキップ（二重防御）──────
# P1で呼び出し順序は修正済みだが、並列実行/手動実行時の再発を防ぐ
# POST_IDは引数にないため、POST_URLのHTTPステータスで判定
if [[ -n "$POST_URL" ]] && [[ "$POST_URL" != "（"* ]]; then
  _GATE_CHECK=$(python3 "$_SCRIPT_DIR/lib/x_post_url_validator.py" "$POST_URL" --json 2>/dev/null || echo '{"ok":false,"reason":"validator error"}')
  _GATE_OK=$(echo "$_GATE_CHECK" | python3 -c "import json,sys; print(json.load(sys.stdin).get('ok',False))" 2>/dev/null || echo "False")
  if [[ "$_GATE_OK" != "True" ]]; then
    _GATE_REASON=$(echo "$_GATE_CHECK" | python3 -c "import json,sys; print(json.load(sys.stdin).get('reason','unknown'))" 2>/dev/null || echo "unknown")
    xlog "POST_AUDIT_GATE: X投稿全体スキップ — URL=$POST_URL reason=$_GATE_REASON"
    echo "  ⏸  POST_AUDIT_GATE: X投稿スキップ (URL: $_GATE_REASON)"
    exit 0
  fi
  xlog "POST_AUDIT_GATE: OK — $POST_URL is accessible"
fi
# ─────────────────────────────────────────────────────────────────────

# ── credential事前検証（v3.0: 不在時グレースフルスキップ）──
if [ ! -f "$HOME/.x_credentials" ]; then
  xlog "SKIP: X credentials未設定 (~/.x_credentials が存在しません)"
  echo "⏭️ SKIP: X credentials未設定 — X投稿をスキップして正常終了"
  exit 0
fi
_CRED_CHECK=$(python3 "$_SCRIPT_DIR/google_metrics/post_to_x.py" --validate 2>&1) || {
  xlog "SKIP: X credential検証失敗 — X投稿をスキップ"
  xlog "  $_CRED_CHECK"
  echo "⏭️ SKIP: X credential検証失敗 — 詳細:"
  echo "$_CRED_CHECK"
  exit 0
}
xlog "CRED_CHECK: OK"

xlog "=== X/Twitter 自動投稿開始 ==="
xlog "TITLE: $TITLE"
xlog "URL: $POST_URL"
xlog "PERSIAN_FILE: ${PERSIAN_FILE:-なし}"
xlog "DRY_RUN: $DRY_RUN"

# ── タイトル崩壊フィルタ: AIエラー応答・ウェブフェッチ失敗文言を含むタイトルは即スキップ ──
_TITLE_CRASH_CHECK=$(python3 -c "
import sys, re
title = sys.argv[1]
CRASH_PATTERNS = [
    r'ウェブフェッチ(は|が|でき)',
    r'フェッチできません',
    r'内部矛盾',
    r'論理的問題',
    r'問題点を特定',
    r'分析します',
    r'提供してください',
    r'お手伝いできません',
    r'申し訳ありません',
    r'確認させてください',
    r'以下に示します',
    r'入力記事が見当たりません',
    # X投稿混入事例（2026-04-14）より追加
    r'重大な問題があります',
    r'ファクトチェックを実施します',
    r'権限が付与されていません',
    r'外部URLへのアクセスが制限',
    r'直接検証ができない',
    r'このチャットに貼り付け',
    r'ファクトチェック結果をまとめます',
    r'ファクトチェック結果',
    r'以下の問題を発見',
    r'書き込み権限',
    r'許可いただけますか',
]
for pat in CRASH_PATTERNS:
    if re.search(pat, title):
        print(f'CRASH: {pat}')
        sys.exit(1)
sys.exit(0)
" "$TITLE" 2>/dev/null; echo $?)
if [[ "$_TITLE_CRASH_CHECK" != "0" ]]; then
  xlog "TITLE_CRASH: タイトル崩壊を検出 → 投稿スキップ (title=$TITLE)"
  exit 0
fi

# ── 重複投稿防止: 同じURLが直近24時間以内に投稿済みならスキップ ──
if [ -n "$POST_URL" ]; then
  _X_HISTORY_FILE="$_SCRIPT_DIR/logs/x_posted_urls.txt"
  _CUTOFF=$(date -d '24 hours ago' +%s 2>/dev/null || date -v-24H +%s 2>/dev/null || echo 0)
  if [ -f "$_X_HISTORY_FILE" ]; then
    while IFS='|' read -r _ts _url; do
      if [ "$_url" = "$POST_URL" ] && [ "${_ts:-0}" -gt "$_CUTOFF" ] 2>/dev/null; then
        xlog "SKIP: 重複投稿防止 — このURLは直近24時間以内に投稿済み ($_url)"
        exit 0
      fi
    done < "$_X_HISTORY_FILE"
  fi
fi

# persianファイルから投稿文を抽出（v12.0フォーマット対応パーサー）
TWEET_TEXT=""
if [ -n "$PERSIAN_FILE" ] && [ -f "$PERSIAN_FILE" ]; then
  TWEET_TEXT=$(python3 -c "
import re, sys
from pathlib import Path

def clean_block(t):
    '''コードブロック内テキストをv12.0準拠に整形'''
    t = t.strip()
    t = re.sub(r'^[\`\s]+|[\`\s]+$', '', t)
    t = re.sub(r'^[「『]|[」』]$', '', t)
    # URL行を除去（リプライで後から挿入する）
    t = re.sub(r'https?://\S+', '', t)
    # マークダウン記法除去（**強調** 等）
    t = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', t)
    # 番号リスト行を除去（1. 2. 3. で始まる行 = ドキュメント本文の混入）
    lines = t.split('\n')
    lines = [l for l in lines if not re.match(r'^\d+\.\s', l.strip())]
    # 空行の連続を1つに
    t = re.sub(r'\n{3,}', '\n\n', '\n'.join(lines))
    t = t.strip()
    return t

def is_v12_valid(t):
    '''v12.0フォーマットの最低限チェック'''
    lines = [l for l in t.split('\n') if l.strip() and not l.strip().startswith('#')]
    if not lines:
        return False
    # ドキュメント混入チェック: 表・見出しが含まれていたら無効
    if re.search(r'^##+\s|^\|.+\|', t, re.MULTILINE):
        return False
    # 最低2行必要（フック + 感情行またはコメント誘導）
    if len(lines) < 2:
        return False
    # 最低限の長さ
    if len(t) < 20:
        return False
    return True

text = Path(sys.argv[1]).read_text()

# 抽出優先順位:
# 1. パターンA コードブロック
# 2. パターンB コードブロック（Aが取れない場合）
# 3. コードブロックなしのパターンA
# 4. ファイル全体が投稿文（マークダウンなし・短い場合）
extract_patterns = [
    r'パターンA[^\n]*\n```\n(.*?)\n```',
    r'パターンA（採用推奨）[^\n]*\n```\n(.*?)\n```',
    r'パターンB[^\n]*\n```\n(.*?)\n```',
    r'パターン[ABC１２３1-3][^\n]*\n```\n(.*?)\n```',
    r'採用推奨[^\n]*\n```\n(.*?)\n```',
    r'投稿文[^\n]*\n```\n(.*?)\n```',
    # コードブロックなし: パターンA直後の数行
    r'パターンA[^\n]*\n((?:(?!パターン[BC]|#+\s|推奨ハッシュ|投稿タイミング)[^\n]+\n){1,6})',
]

for pat in extract_patterns:
    m = re.search(pat, text, re.DOTALL)
    if m:
        t = clean_block(m.group(1))
        if is_v12_valid(t):
            print(t)
            sys.exit()

# フォールバック: ファイル全体が投稿文（マークダウンなし・短い）
if not re.search(r'^##+\s|\|\s*---', text, re.MULTILINE) and len(text.strip()) < 200:
    t = clean_block(text)
    if is_v12_valid(t):
        print(t)
        sys.exit()

print('')
" "$PERSIAN_FILE" 2>/dev/null || echo "")
fi

# persianから取れなければタイトルからジャンルを推定してテンプレート生成
if [ -z "$TWEET_TEXT" ] || [ ${#TWEET_TEXT} -lt 30 ]; then
  _AUTO_CAT=$(python3 -c "
import sys, re
title = sys.argv[1].lower()
# カテゴリ推定（旅行・美容・ファッション・速報等）
if re.search(r'旅行|ソウル|カフェ|聖地巡礼|ポップアップ|観光|グルメ', title): print('11')
elif re.search(r'コスメ|スキンケア|美容|ガラス肌|美肌|ヘアケア', title): print('12')
elif re.search(r'ファッション|コーデ|着用|ブランド|即完売', title): print('30')
elif re.search(r'カムバック|新曲|アルバム|mv|ミュージックビデオ', title): print('3')
elif re.search(r'チャート|ランキング|1位|billboard', title): print('71')
elif re.search(r'ライブ|コンサート|ツアー|来日', title): print('5')
elif re.search(r'速報|緊急|炎上|騒動|事件', title): print('7')
else: print('default')
" "$TITLE" 2>/dev/null || echo "default")
  TWEET_TEXT=$(python3 "$_SCRIPT_DIR/lib/x_post_templates.py" "$TITLE" "$POST_URL" --category-id "$_AUTO_CAT" 2>/dev/null || echo "")
fi

# フォールバック
if [ -z "$TWEET_TEXT" ] || [ ${#TWEET_TEXT} -lt 20 ]; then
  TWEET_TEXT="${TITLE}
#KPOP #韓国
${POST_URL}"
fi

# CTOハック: URLペナルティ回避 — フック本文にURLを含めない
# URLは投稿成功後にリプライとして自動挿入する
# （URLが既に含まれている場合は除去してフックのみにする）
if [[ -n "$POST_URL" ]] && [[ "$TWEET_TEXT" == *"$POST_URL"* ]]; then
  TWEET_TEXT=$(echo "$TWEET_TEXT" | grep -v "$POST_URL" | sed '/^$/N;/^\n$/d' || echo "$TWEET_TEXT")
  xlog "URL_REMOVED: フックからURLを除去（リプライで後から挿入）"
fi

# ─── v12.0フォーマット検証 ──────────────────────────────────────────────────
# persianからの投稿文がv12.0ルールに準拠しているか検証してログに残す
V12_CHECK=$(python3 -c "
import re, sys
text = sys.argv[1]
lines = [l for l in text.strip().split('\n') if l.strip() and not l.strip().startswith('#')]
issues = []

hook = lines[0] if lines else ''
# フック: 20文字以内
if len(hook) > 20:
    issues.append(f'フック{len(hook)}文字（20文字超）')
# 強ワード
strong_words = ['衝撃','電撃','判明','ついに','まさか','速報','記録','驚愕','神','レベチ','解禁','完全','必見']
if hook and not any(w in hook for w in strong_words):
    issues.append('フックに強ワードなし')
# 完結文NG
if re.search(r'[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]{2,}(した|です|ます|だ|である)$', hook):
    issues.append('フックが完結文')
# 感情行
if len(lines) < 2:
    issues.append('感情行（2行目）なし')
# コメント誘導
comment_triggers = ['どう思う','どっち派','賛否','泣いた','超えられる','RT','シェア','教えて','感動した','あなたは']
if not any(t in text for t in comment_triggers):
    issues.append('コメント誘導なし')
# URL混入
if 'http' in text:
    issues.append('URL混入')

if issues:
    print('NG: ' + ' / '.join(issues))
else:
    print('OK')
" "$TWEET_TEXT" 2>/dev/null || echo "CHECK_ERROR")
xlog "V12_FORMAT: $V12_CHECK"

# ─── URL混入BLOCK（メイン投稿にhttpが含まれていたら即停止） ────────────────────
if [[ "$V12_CHECK" == *"URL混入"* ]]; then
  # 除去を試みる（URLのみ含む行を削除）
  _TWEET_NO_URL=$(echo "$TWEET_TEXT" | grep -vE 'https?://' || echo "$TWEET_TEXT")
  if echo "$_TWEET_NO_URL" | grep -qE 'https?://'; then
    xlog "URL_BLOCK: メイン投稿にURL残存 → 投稿停止"
    echo "❌ [X投稿] メイン投稿にURL混入 → BLOCK"
    X_STATUS="BLOCKED_URL"
    exit 1
  else
    TWEET_TEXT="$_TWEET_NO_URL"
    xlog "URL_REMOVED: 自動除去済み（再チェック通過）"
  fi
fi

# ─── URL除去後の品質ゲート（最低40文字・固有名詞/数字/感情語必須） ────────────
_TWEET_QUALITY=$(python3 - << 'TQPY' "$TWEET_TEXT"
import sys, re
text = sys.argv[1]
# ハッシュタグ・空行を除いた実テキスト
lines = [l for l in text.strip().split('\n') if l.strip() and not l.strip().startswith('#')]
body = ' '.join(lines)
issues = []
# 最低40文字（v12フォーマットは簡潔設計のため50→40に緩和）
if len(body) < 40:
    issues.append(f'本文{len(body)}文字（40文字未満）')
# 固有名詞 or 数字 or 感情語のいずれか1つ必須
has_proper = bool(re.search(r'BTS|TWICE|BLACKPINK|IVE|ILLIT|aespa|NewJeans|ENHYPEN|TXT|SEVENTEEN|NCT|ATEEZ|TOP|RIIZE|LE\s*SSERAFIM|EXO|GOT7|MAMAMOO', body, re.IGNORECASE))
has_number = bool(re.search(r'[0-9]', body))
has_emotion = bool(re.search(r'衝撃|電撃|判明|ついに|まさか|速報|記録|驚愕|神|レベチ|解禁|完全|必見|復帰|制覇|初|歴史|快挙|1位|首位', body))
if not (has_proper or has_number or has_emotion):
    issues.append('固有名詞/数字/感情語が1つもなし')
if issues:
    print('NG: ' + ' / '.join(issues))
else:
    print('OK')
TQPY
)
if [[ "$_TWEET_QUALITY" == NG:* ]]; then
  xlog "TWEET_QUALITY_BLOCK: $_TWEET_QUALITY"
  echo "❌ [X投稿] 投稿品質不足: $_TWEET_QUALITY → BLOCK"
  X_STATUS="BLOCKED_QUALITY"
  exit 1
fi
xlog "TWEET_QUALITY: OK"

# ─── フックCTRスコアリング（数字+25/固有名詞+25/感情語+20/対比+20/120-150字+10、合計80未満BLOCK） ──
_HOOK_CTR_SCORE=$(python3 - << 'HOOKPY' "$TWEET_TEXT"
import sys, re
text = sys.argv[1]
# ハッシュタグ・URL行を除いた本文のみ
lines = [l for l in text.strip().split('\n') if l.strip() and not l.strip().startswith('#') and not re.match(r'https?://', l.strip())]
body = '\n'.join(lines)
score = 0
reasons = []

# 数字あり +25
if re.search(r'[0-9]', body):
    score += 25
    reasons.append("数字 +25")

# 固有名詞 +25
if re.search(r'BTS|TWICE|BLACKPINK|IVE|ILLIT|aespa|NewJeans|ENHYPEN|TXT|SEVENTEEN|NCT|ATEEZ|TOP|RIIZE|LE\s*SSERAFIM|EXO|GOT7|MAMAMOO|BIGBANG|G-DRAGON|JIMIN|SHINee', body, re.IGNORECASE):
    score += 25
    reasons.append("固有名詞 +25")

# 感情語 +20
if re.search(r'衝撃|電撃|判明|ついに|まさか|速報|記録|驚愕|神|レベチ|解禁|完全|必見|復帰|制覇|初|歴史|快挙|1位|首位|伝説|奇跡|爆発|炎上|暴露|激白', body):
    score += 20
    reasons.append("感情語 +20")

# 対比構造 +20
if re.search(r'→|vs|VS|から|でも|なのに|なぜ|なのか|空白|一転|激変|崩壊|異常|6年|13年|[0-9]+年ぶり', body):
    score += 20
    reasons.append("対比/異常 +20")

# 文字数120〜150 +10（ハッシュタグ含む全体）
total_len = len(text.strip())
if 120 <= total_len <= 150:
    score += 10
    reasons.append(f"文字数{total_len}字(120-150) +10")

print(f"{min(score,100)}|{','.join(reasons)}")
HOOKPY
)
_HOOK_SCORE=$(echo "$_HOOK_CTR_SCORE" | cut -d'|' -f1)
_HOOK_REASONS=$(echo "$_HOOK_CTR_SCORE" | cut -d'|' -f2)
xlog "HOOK_CTR_SCORE: ${_HOOK_SCORE}/100 (${_HOOK_REASONS})"

if [[ "$_HOOK_SCORE" -lt 20 ]]; then
  xlog "HOOK_CTR_BLOCK: スコア${_HOOK_SCORE}/100 < 20 → 投稿停止"
  echo "❌ [X投稿] フックCTRスコア${_HOOK_SCORE}/100（20未満）→ BLOCK"
  X_STATUS="BLOCKED_HOOK_CTR"
  exit 1
fi
if [[ "$_HOOK_SCORE" -lt 40 ]]; then
  xlog "HOOK_CTR_WARN: スコア${_HOOK_SCORE}/100 < 40 → 警告のみで続行"
fi
if [[ "$_HOOK_SCORE" -lt 80 ]]; then
  xlog "HOOK_CTR_WARN: スコア${_HOOK_SCORE}/100 < 80 → 投稿は続行（警告のみ）"
fi
xlog "HOOK_CTR: OK(${_HOOK_SCORE}/100)"

# ─── ハッシュタグ4個以上BLOCK ────────────────────────────────────────────────
_HASHTAG_COUNT=$(echo "$TWEET_TEXT" | grep -oE '#[^ #　]+' | wc -l || echo 0)
if [[ "$_HASHTAG_COUNT" -ge 4 ]]; then
  xlog "HASHTAG_BLOCK: ハッシュタグ${_HASHTAG_COUNT}個（4個以上禁止）→ 投稿停止"
  echo "❌ [X投稿] ハッシュタグ${_HASHTAG_COUNT}個（上限3個）→ BLOCK"
  X_STATUS="BLOCKED_HASHTAG"
  exit 1
fi
xlog "HASHTAG_COUNT: ${_HASHTAG_COUNT}個 (OK)"

# ツイート文ログ
xlog "TWEET_TEXT: $TWEET_TEXT"
xlog "TWEET_LENGTH: ${#TWEET_TEXT}"

# ─── フック20文字超の事前弾き（PRE_SCORE呼び出しをスキップ）───────────────────
# V12_CHECKで既にフック文字数超過が検出されている場合、LLMスコアリングなしで即不合格とする
if [[ "$V12_CHECK" == NG:*"20文字超"* ]]; then
  X_PASS="NO"
  X_SCORE="0"
  xlog "PRE_SCORE_SKIP: フック20文字超を事前検出 → PRE_SCOREスキップ・テンプレート再生成へ"
else
  # X投稿プレフライトスコアリング (v11.0: 100点満点, 閾値80)
  X_SCORE_JSON=$(python3 "$_SCRIPT_DIR/lib/x_pre_score.py" "$TWEET_TEXT" 2>&1 || echo '{"pass":true,"total":0}')
  X_PASS=$(python3 -c "import json,sys; print('YES' if json.loads(sys.argv[1]).get('pass') else 'NO')" "$X_SCORE_JSON" 2>/dev/null || echo "YES")
  X_SCORE=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('total',0))" "$X_SCORE_JSON" 2>/dev/null || echo "0")
  xlog "PRE_SCORE: $X_SCORE/100 (pass=$X_PASS)"
fi

if [ "$X_PASS" != "YES" ]; then
  xlog "PRE_SCORE不合格 ($X_SCORE/100) → テンプレートで再生成"
  CATEGORY_ID_GUESS=$(python3 -c "
import sys, re
title = sys.argv[1].lower()
if re.search(r'旅行|ソウル|カフェ|聖地巡礼|ポップアップ|観光|グルメ', title): print('11')
elif re.search(r'コスメ|スキンケア|美容|ガラス肌|美肌|ヘアケア', title): print('12')
elif re.search(r'ファッション|コーデ|着用|ブランド|即完売', title): print('30')
elif re.search(r'カムバック|新曲|アルバム|mv|ミュージックビデオ', title): print('3')
elif re.search(r'チャート|ランキング|1位|billboard', title): print('71')
elif re.search(r'ライブ|コンサート|ツアー|来日', title): print('5')
elif re.search(r'速報|緊急|炎上', title): print('7')
else: print('default')
" "$TITLE" 2>/dev/null || echo "default")
  TWEET_TEXT=$(python3 "$_SCRIPT_DIR/lib/x_post_templates.py" "$TITLE" "$POST_URL" --category-id "$CATEGORY_ID_GUESS" 2>/dev/null || echo "")

  if [ -n "$TWEET_TEXT" ] && [ ${#TWEET_TEXT} -ge 20 ]; then
    if [[ -n "$POST_URL" ]] && [[ "$TWEET_TEXT" != *"$POST_URL"* ]]; then
      TWEET_TEXT="${TWEET_TEXT}
${POST_URL}"
    fi
    # 再スコアリング
    X_SCORE_JSON=$(python3 "$_SCRIPT_DIR/lib/x_pre_score.py" "$TWEET_TEXT" 2>/dev/null || echo '{"pass":true,"total":0}')
    X_PASS=$(python3 -c "import json,sys; print('YES' if json.loads(sys.argv[1]).get('pass') else 'NO')" "$X_SCORE_JSON" 2>/dev/null || echo "YES")
    X_SCORE=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('total',0))" "$X_SCORE_JSON" 2>/dev/null || echo "0")
    xlog "RE-SCORE: $X_SCORE/100 (pass=$X_PASS)"
  fi

  if [ "$X_PASS" != "YES" ]; then
    xlog "RESULT: プレフライト不合格によりスキップ (score=$X_SCORE/100)"
    # ─── 自己改善: スキップ原因をフィードバック記録 ────────────────────────
    SKIP_REASONS=$(python3 -c "
import json, sys
d = json.loads(sys.argv[1])
reasons = []
for cat, rs in d.get('reasons', {}).items():
    reasons += [r for r in rs if '-' in r or '違反' in r or '不足' in r]
print('|'.join(reasons[:5]))
" "$X_SCORE_JSON" 2>/dev/null || echo "")
    python3 "$_SCRIPT_DIR/lib/auto_improve.py" audit-feedback \
      --post-id "" \
      --issues "X投稿スキップ(score=${X_SCORE})|${SKIP_REASONS}" \
      --fixes "" \
      --title "$TITLE" \
      --pipeline "x_post" 2>/dev/null || true
    # ─── 最終手段: 強制テンプレートで3回目の試み ─────────────────────────
    # 勝ちパターン学習から最高スコアテンプレートを使用
    BEST_TEMPLATE=$(python3 "$_SCRIPT_DIR/lib/x_post_templates.py" "$TITLE" "$POST_URL" \
      --category-id "${CATEGORY_ID_GUESS:-default}" --force-best 2>/dev/null || echo "")
    if [ -n "$BEST_TEMPLATE" ]; then
      BEST_JSON=$(python3 "$_SCRIPT_DIR/lib/x_pre_score.py" "$BEST_TEMPLATE" 2>/dev/null || echo '{"pass":false,"total":0}')
      BEST_PASS=$(python3 -c "import json,sys; print('YES' if json.loads(sys.argv[1]).get('pass') else 'NO')" "$BEST_JSON" 2>/dev/null || echo "NO")
      BEST_SCORE=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('total',0))" "$BEST_JSON" 2>/dev/null || echo "0")
      if [ "$BEST_PASS" = "YES" ]; then
        xlog "FORCE-BEST-SCORE: $BEST_SCORE/100 (pass=YES) → 投稿続行"
        TWEET_TEXT="$BEST_TEMPLATE"
        X_PASS="YES"
      else
        xlog "FORCE-BEST-SCORE: $BEST_SCORE/100 (pass=NO) → 最終スキップ"
        exit 0
      fi
    else
      exit 0
    fi
  fi
fi

xlog "FINAL_TWEET: ${TWEET_TEXT:0:100}..."

if [ "$DRY_RUN" = "true" ]; then
  xlog "RESULT: DRY-RUN（ENABLE_X_POST=1 で有効化）"
  echo "[DRY-RUN] X投稿をスキップしました（ENABLE_X_POST=1 で有効化）"
  echo "  投稿予定文:"
  echo "  $TWEET_TEXT"
  exit 0
fi

xlog "POST: X API呼び出し開始（v2.0リトライ付き、フックのみ、URLなし）"
POST_OUTPUT=$(python3 "$_SCRIPT_DIR/google_metrics/post_to_x.py" "$TWEET_TEXT" 2>&1) || {
  xlog "RESULT: X投稿失敗（リトライ${MAX_RETRIES:-3}回後）- $POST_OUTPUT"
  echo "$POST_OUTPUT"
  # credential診断結果をDiscordに通知（urgent_errorsへ）
  if echo "$POST_OUTPUT" | grep -qE 'DIAG_401|DIAG_403|CRED_MISSING|CRED_KEY'; then
    xlog "CRED_ALERT: credential問題検出 → Discord通知"
    python3 "$_SCRIPT_DIR/lib/discord_notifier.py" --test-critical 2>/dev/null || true
  fi
  exit 1
}
echo "$POST_OUTPUT"

# tweet_id 取得（post_to_x.py が "TWEET_ID=xxx" を出力する）
TWEET_ID=$(echo "$POST_OUTPUT" | grep -oP '^TWEET_ID=\K[0-9]+' | head -1 || true)
TWEET_URL=$(echo "$POST_OUTPUT" | grep -oP 'https://x\.com/\S+' | head -1 || true)

if [ -n "$TWEET_URL" ]; then
  xlog "RESULT: フック投稿成功 - $TWEET_URL"
elif [ -n "$TWEET_ID" ]; then
  xlog "RESULT: フック投稿成功 - tweet_id=$TWEET_ID"
else
  xlog "RESULT: 投稿完了 - $POST_OUTPUT"
fi

# 投稿済みURLを履歴に記録（重複防止用）
if [ -n "$POST_URL" ] && [ -n "$TWEET_ID" ]; then
  _TS=$(date +%s)
  echo "${_TS}|${POST_URL}" >> "$_SCRIPT_DIR/logs/x_posted_urls.txt"
  # 古いエントリを削除（7日以上前）
  _WEEK_AGO=$(date -d '7 days ago' +%s 2>/dev/null || date -v-7d +%s 2>/dev/null || echo 0)
  if [ -f "$_SCRIPT_DIR/logs/x_posted_urls.txt" ]; then
    awk -F'|' -v cutoff="$_WEEK_AGO" '$1 > cutoff' "$_SCRIPT_DIR/logs/x_posted_urls.txt" > /tmp/x_urls_clean.tmp \
      && mv /tmp/x_urls_clean.tmp "$_SCRIPT_DIR/logs/x_posted_urls.txt"
  fi
fi

# ─── CTOハック: URLリプライを即時挿入（IMP条件なし版）────────────────────
# §8 本格実装（IMP監視）はX API Pro権限取得後に対応予定
# 現時点では投稿直後にURLリプライを挿入してインデックス確保
# ── URL事前検証（soft-404防止）──────────────────────────────────────────
_URL_VALID=1
if [[ -n "$POST_URL" ]] && [[ -n "$TWEET_ID" ]]; then
  _URL_CHECK=$(python3 "$_SCRIPT_DIR/lib/x_post_url_validator.py" "$POST_URL" --json 2>/dev/null || echo '{"ok":false,"reason":"validator error"}')
  _URL_OK=$(echo "$_URL_CHECK" | python3 -c "import json,sys; print(json.load(sys.stdin).get('ok',False))" 2>/dev/null || echo "False")
  if [[ "$_URL_OK" != "True" ]]; then
    _URL_REASON=$(echo "$_URL_CHECK" | python3 -c "import json,sys; print(json.load(sys.stdin).get('reason','unknown'))" 2>/dev/null || echo "unknown")
    xlog "URL_VALIDATION_NG: $POST_URL — $_URL_REASON"
    xlog "URL_REPLY: スキップ（URLが404/soft-404のためリプライ投稿を中止）"
    echo "  ⚠️ URLリプライスキップ: $_URL_REASON"
    _URL_VALID=0
  else
    xlog "URL_VALIDATION_OK: $POST_URL"
  fi
fi
if [[ -n "$POST_URL" ]] && [[ -n "$TWEET_ID" ]] && [[ "$_URL_VALID" == "1" ]]; then
  URL_REPLY_TEXT=$(python3 -c "
import sys; sys.path.insert(0, '$_SCRIPT_DIR/lib')
from x_post_templates import generate_url_reply
print(generate_url_reply('$POST_URL'))
" 2>/dev/null || echo "📖 記事はこちら👇
$POST_URL")

  xlog "URL_REPLY: リプライにURL挿入中 (reply_to=$TWEET_ID)"
  REPLY_OUTPUT=$(python3 "$_SCRIPT_DIR/google_metrics/post_to_x.py" "$URL_REPLY_TEXT" --reply-to "$TWEET_ID" 2>&1) || {
    xlog "URL_REPLY: 失敗（投稿自体は成功済）- $REPLY_OUTPUT"
  }
  REPLY_URL=$(echo "$REPLY_OUTPUT" | grep -oP 'https://x\.com/\S+' | head -1 || true)
  if [ -n "$REPLY_URL" ]; then
    xlog "URL_REPLY: 成功 - $REPLY_URL"
    echo "  └ URLリプライ: $REPLY_URL"
  fi
fi
