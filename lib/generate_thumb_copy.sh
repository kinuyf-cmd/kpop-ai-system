#!/bin/bash
# generate_thumb_copy.sh - サムネ2行コピー生成（全パイプライン共通）
#
# raikou_thumb agent → score_thumbnail_text.py (60点gate)
# → NGならテンプレ（lib/thumbnail_templates.py）→ 再度スコア判定
#
# Usage:
#   source lib/generate_thumb_copy.sh
#   generate_thumb_copy "<TITLE>" "<GENRE>" "<BODY_FILE_OR_EMPTY>"
#
# 返り値: 標準出力に2行のコピー（各6〜10文字）。失敗時もベストエフォートで何か返す。
# ログ: logs/thumb_copy_generation.jsonl に試行履歴を追記（学習用）

_THUMB_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 本文から数字候補を抽出（最大5個）
_extract_key_numbers() {
  local body_file="$1"
  [[ -z "$body_file" || ! -f "$body_file" ]] && echo "" && return
  python3 - "$body_file" <<'PY'
import sys, re
p = sys.argv[1]
try:
    t = open(p, encoding='utf-8').read()[:3000]
except Exception:
    print(""); sys.exit()
# HTMLタグ除去
t = re.sub(r'<[^>]+>', ' ', t)
nums = []
for m in re.finditer(r'\d[\d,，.]*(?:万|億|冠|ヶ月|か月|年|日|曲|公演|回|位|選|連|週|ぶり|枚|K|億円|万枚|名|人)', t):
    s = m.group(0)
    if s not in nums and not re.match(r'^20[2-3]\d$', s):
        nums.append(s)
    if len(nums) >= 5: break
print(",".join(nums))
PY
}

# 本文リード（最初のh2まで、max 200字）
_extract_body_lead() {
  local body_file="$1"
  [[ -z "$body_file" || ! -f "$body_file" ]] && echo "" && return
  python3 - "$body_file" <<'PY'
import sys, re
p = sys.argv[1]
try:
    t = open(p, encoding='utf-8').read()
except Exception:
    print(""); sys.exit()
m = re.split(r'<h2[^>]*>', t, maxsplit=1)
lead = m[0]
lead = re.sub(r'<[^>]+>', ' ', lead)
lead = re.sub(r'\s+', ' ', lead).strip()
print(lead[:200])
PY
}

# 出力から前置き・マークダウン装飾・キー行を剥がして最初の2行を取り出す
# NOTE: python3 <<PY 形式は stdin を heredoc で上書きしてパイプ入力を壊すため、
# 一時ファイル経由で確実に受け渡す。
_sanitize_thumb_output() {
  local _tmp
  _tmp=$(mktemp)
  cat > "$_tmp"
  python3 - "$_tmp" <<'PY'
import sys, re
raw = open(sys.argv[1], encoding='utf-8').read()
bad_prefix = re.compile(r'^(はい|了解|承知|以下|こちら|Here|Sure|---+|```|「|"|\*\*|\*)')
lines = []
for line in raw.splitlines():
    s = line.strip().strip('「」"\'`')
    s = re.sub(r'^\*\*(.+?)\*\*$', r'\1', s)
    s = re.sub(r'^__(.+?)__$', r'\1', s)
    s = re.sub(r'^`(.+?)`$', r'\1', s)
    s = re.sub(r'^[-・*>]+\s*', '', s)
    s = s.strip()
    if not s: continue
    if bad_prefix.match(s): continue
    if re.match(r'^[A-Za-z]+:\s', s): continue
    if re.match(r'^(テキスト|スコア|レイアウト|genre|pattern)\s*[:：]', s, re.I): continue
    if re.match(r'^[#>]', s): continue
    if ' / ' in s and '\n' not in s:
        parts = [p.strip() for p in s.split(' / ') if p.strip()]
        lines.extend(parts[:2])
    else:
        lines.append(s)
    if len(lines) >= 2: break
print("\n".join(lines[:2]))
PY
  rm -f "$_tmp"
}

generate_thumb_copy() {
  local title="$1"
  local genre="${2:-breaking}"
  local body_file="${3:-}"
  local log_file="$_THUMB_SCRIPT_DIR/logs/thumb_copy_generation.jsonl"
  mkdir -p "$(dirname "$log_file")"

  local key_numbers body_lead
  key_numbers="$(_extract_key_numbers "$body_file")"
  body_lead="$(_extract_body_lead "$body_file")"

  # 行長チェッカ（>10文字の行があれば 1 を返す。描画の切れを防ぐ）
  _has_overlong_line() {
    python3 -c "
import sys
for l in sys.argv[1].split(chr(10)):
    if len(l.strip()) > 10:
        sys.exit(1)
sys.exit(0)
" "$1"
  }

  # ---- 試行1〜3: raikou_thumb agent（10文字超なら最大2回リトライ）----
  # --allowedTools "" でツール呼び出しを禁止（純粋テキスト生成に限定）
  # </dev/null で stdin を切り離し heredoc 環境での衝突を回避
  local attempt1="" score1=0 pass1="NO" best_text="" best_score=0
  local try max_try=3
  for try in $(seq 1 "$max_try"); do
    local retry_hint=""
    if [[ "$try" -gt 1 ]] && [[ -n "$attempt1" ]]; then
      retry_hint="
【再試行 ${try}/${max_try}】前回の出力「${attempt1//$'\n'/ / }」は1行が11文字以上でした。
描画で末尾が切れます。**必ず各行10文字以内**で核心語のみに削ぎ落としてやり直せ。
「〜の衝撃」「〜の真相」「〜が示す覚悟」「〜を徹底」「〜が止まらない」など語尾修飾句は全削除。
アーティスト名＋具体数字 の最小構成を優先せよ。"
    fi
    local raw
    raw=$(claude --allowedTools "" --no-session-persistence --agent raikou_thumb -p "
TITLE: ${title}
GENRE: ${genre}
BODY_LEAD: ${body_lead}
KEY_NUMBERS: ${key_numbers}
${retry_hint}

2行のサムネコピーのみ出力せよ。各行**10文字以内**厳守。前置き・マークダウン装飾・ツール呼び出し一切禁止。
" </dev/null 2>/dev/null)
    attempt1=$(echo "$raw" | _sanitize_thumb_output)

    score1=$(python3 "$_THUMB_SCRIPT_DIR/google_metrics/score_thumbnail_text.py" "$attempt1" 2>/dev/null \
             | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('score',0))" 2>/dev/null || echo 0)
    pass1=$(python3 "$_THUMB_SCRIPT_DIR/google_metrics/score_thumbnail_text.py" "$attempt1" 2>/dev/null \
            | python3 -c "import json,sys;d=json.load(sys.stdin);print('YES' if not d.get('block') and d.get('pass') else 'NO')" 2>/dev/null || echo "NO")

    # 行長チェック
    local overlong="NO"
    if ! _has_overlong_line "$attempt1"; then overlong="YES"; fi

    python3 - "$log_file" "$title" "$genre" "raikou_thumb" "$attempt1" "$score1" "$pass1" "$try" "$overlong" <<'PY'
import json, sys, datetime
fp, title, genre, agent, text, score, ok, attempt, overlong = sys.argv[1:10]
with open(fp, 'a', encoding='utf-8') as f:
    f.write(json.dumps({
        "ts": datetime.datetime.now().isoformat(),
        "title": title[:120], "genre": genre, "agent": agent,
        "text": text, "score": int(score) if score.isdigit() else 0,
        "pass": ok == "YES", "attempt": int(attempt), "overlong": overlong == "YES",
    }, ensure_ascii=False) + "\n")
PY

    # ベスト保持（pass かつ行長OK の中で最高スコア）
    if [[ "$pass1" == "YES" ]] && [[ "$overlong" == "NO" ]]; then
      if [[ "$score1" -gt "$best_score" ]]; then
        best_text="$attempt1"; best_score="$score1"
      fi
      # 1回目で合格した場合は即採用
      echo "$attempt1"
      return 0
    fi
  done

  # ループ終了後、ベストがあれば採用
  if [[ -n "$best_text" ]]; then
    echo "$best_text"
    return 0
  fi

  # ---- 試行2: テンプレ ----
  local templated
  templated=$(python3 -c "
import sys
sys.path.insert(0, '$_THUMB_SCRIPT_DIR')
from lib.thumbnail_templates import select_thumbnail_text
print(select_thumbnail_text(sys.argv[1], sys.argv[2]))
" "$title" "$genre" 2>/dev/null)

  local score2 pass2
  score2=$(python3 "$_THUMB_SCRIPT_DIR/google_metrics/score_thumbnail_text.py" "$templated" 2>/dev/null \
           | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('score',0))" 2>/dev/null || echo 0)
  pass2=$(python3 "$_THUMB_SCRIPT_DIR/google_metrics/score_thumbnail_text.py" "$templated" 2>/dev/null \
          | python3 -c "import json,sys;d=json.load(sys.stdin);print('YES' if not d.get('block') and d.get('pass') else 'NO')" 2>/dev/null || echo "NO")

  python3 - "$log_file" "$title" "$genre" "template" "$templated" "$score2" "$pass2" <<'PY'
import json, sys, datetime
fp, title, genre, agent, text, score, ok = sys.argv[1:8]
with open(fp, 'a', encoding='utf-8') as f:
    f.write(json.dumps({
        "ts": datetime.datetime.now().isoformat(),
        "title": title[:120], "genre": genre, "agent": agent,
        "text": text, "score": int(score) if score.isdigit() else 0, "pass": ok == "YES",
    }, ensure_ascii=False) + "\n")
PY

  # どちらか高スコア側を採用（両方BLOCKでも高い方を返す）
  if [[ "$score1" -ge "$score2" ]] && [[ -n "$attempt1" ]]; then
    echo "$attempt1"
  else
    echo "$templated"
  fi
  return 0
}
