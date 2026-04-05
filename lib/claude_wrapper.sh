#!/bin/bash
# ============================================================
# claude_wrapper.sh - Claude CLI トークン使用量トラッキング
#
# Usage:
#   source lib/claude_wrapper.sh   # claude コマンドをラップ
#   既存の claude 呼び出しは自動的にトラッキングされる
# ============================================================

TOKEN_LOG="${TOKEN_LOG:-/tmp/token_usage.jsonl}"

# 元の claude パスを保存
CLAUDE_ORIGINAL=$(command -v claude)

# claude コマンドをラップ（既存パイプラインの呼び出しをそのまま計測）
claude() {
  local step_name="unknown"
  # --agent 引数からステップ名を抽出
  local args=("$@")
  for ((i=0; i<${#args[@]}; i++)); do
    if [[ "${args[$i]}" == "--agent" ]] && [[ $((i+1)) -lt ${#args[@]} ]]; then
      step_name="${args[$((i+1))]}"
      break
    fi
  done

  local tmp_json
  tmp_json=$(mktemp /tmp/claude_tracked_XXXXXX.json)

  # --output-format json で呼び出し
  if "$CLAUDE_ORIGINAL" "$@" --output-format json > "$tmp_json" 2>/dev/null; then
    # テキスト結果を stdout に出力 + usage をログに追記
    python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print(d.get('result', ''))
    u = d.get('usage', {})
    entry = {
        'step': sys.argv[2],
        'input_tokens': u.get('input_tokens', 0),
        'output_tokens': u.get('output_tokens', 0),
        'cost_usd': d.get('total_cost_usd', 0)
    }
    with open(sys.argv[3], 'a') as f:
        f.write(json.dumps(entry) + '\n')
except Exception as e:
    # JSON解析失敗時はファイル内容をそのまま出力
    try:
        with open(sys.argv[1]) as f:
            print(f.read())
    except: pass
" "$tmp_json" "$step_name" "$TOKEN_LOG"
  else
    # --output-format json が失敗した場合、通常モードにフォールバック
    rm -f "$tmp_json"
    "$CLAUDE_ORIGINAL" "$@"
    return
  fi

  rm -f "$tmp_json"
}

token_total() {
  # TOKEN_LOG からトークン合計を出力
  python3 -c "
import json, sys
total = 0
log_file = sys.argv[1] if len(sys.argv) > 1 else '$TOKEN_LOG'
try:
    with open(log_file) as f:
        for line in f:
            d = json.loads(line.strip())
            total += d.get('input_tokens', 0) + d.get('output_tokens', 0)
except: pass
print(total)
" "${1:-$TOKEN_LOG}"
}

token_cost_usd() {
  # TOKEN_LOG からコスト合計(USD)を出力
  python3 -c "
import json, sys
total = 0.0
try:
    with open(sys.argv[1]) as f:
        for line in f:
            d = json.loads(line.strip())
            total += d.get('cost_usd', 0)
except: pass
print(f'{total:.4f}')
" "${1:-$TOKEN_LOG}"
}
