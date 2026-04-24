#!/bin/bash
# 共通サニタイザ: 各エージェント出力ファイルから不要混入を除去
# - Claude CLIのJSONメタデータ
# - リテラル \n
# - エラー定型文
# - 許可要求の定型文
#
# Usage:
#   source lib/sanitize_output.sh
#   sanitize_output reports/0_butterfree.md

sanitize_output() {
  local file="$1"
  [[ -f "$file" ]] || return
  python3 - "$file" <<'PYEOF'
import sys, re
path = sys.argv[1]
with open(path, encoding="utf-8", errors="replace") as f:
    text = f.read()

# [1] Claude APIレスポンスJSONメタデータの除去
#     {"type":"result","subtype":"success",...} 形式
#     ネストされた {} を含むためバランスマッチで除去する
def _strip_claude_json_blob(t):
    """Find and remove complete JSON blobs starting with {"type":"result" or {"type":"content_block"."""
    result = []
    i = 0
    while i < len(t):
        # Look for the start of a Claude JSON blob
        m = re.search(r'\{"type"\s*:\s*"(?:result|content_block)', t[i:])
        if not m:
            result.append(t[i:])
            break
        start = i + m.start()
        result.append(t[i:start])
        # Balance braces to find the complete JSON object
        depth = 0
        j = start
        in_str = False
        escape = False
        while j < len(t):
            c = t[j]
            if escape:
                escape = False
            elif c == '\\' and in_str:
                escape = True
            elif c == '"' and not escape:
                in_str = not in_str
            elif not in_str:
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
            j += 1
        # Skip over the matched JSON blob
        i = j
    return ''.join(result)

text = _strip_claude_json_blob(text)

# HTML-encoded版も除去
text = re.sub(r'\{&#8220;type&#8221;.*?&#8221;terminal_reason&#8221;.*?\}', '', text, flags=re.DOTALL)
# modelUsage / session_id が単独で残った場合
text = re.sub(r'"modelUsage"\s*:\s*\{[^{]*(?:\{[^}]*\}[^{]*)*\}', '', text, flags=re.DOTALL)
text = re.sub(r'"session_id"\s*:\s*"[a-f0-9-]+"', '', text)

# [1b] Claude API token usage JSON（{input_tokens:..., output_tokens:...} 形式）
#      HTMLエンティティ版（&#8220; = ", &#8221; = "）も対応
text = re.sub(
    r'\{["\u201c&#][^{}]*(?:input_tokens|output_tokens|cache_creation_input_tokens|ephemeral_\d+h_input_tokens)[^{}]*\}',
    '', text)
# ネストされたtoken JSONブロブ（{...{...}...}形式）をバランスマッチで除去
def _strip_token_json(t):
    result = []
    i = 0
    while i < len(t):
        m = re.search(r'\{["\u201c](?:[^{}]|&#\d+;)*(?:input_tokens|output_tokens|cache_creation)', t[i:])
        if not m:
            result.append(t[i:])
            break
        start = i + m.start()
        result.append(t[i:start])
        depth = 0
        j = start
        while j < len(t):
            if t[j] == '{': depth += 1
            elif t[j] == '}':
                depth -= 1
                if depth == 0:
                    j += 1
                    break
            j += 1
        i = j
    return ''.join(result)
text = _strip_token_json(text)

# [1.5] U+FFFD (文字化け置換文字) の除去
#       errors="replace"によりU+FFFDが挿入される場合があるため、
#       ここで確実に除去する（全lib/*.pyはerrors="replace"を使用）
fffd_count = text.count('\ufffd')
if fffd_count > 0:
    import sys as _sys
    print(f"  ⚠️ [sanitize] U+FFFD {fffd_count}箇所検出 → 除去: {path}", file=_sys.stderr)
    text = text.replace('\ufffd', '')

# [2] リテラル \n の除去
text = text.replace('\\n', '')

# [3] Claudeエラーメッセージのインライン除去
claude_error_inline = re.compile(
    r'(Web tools are currently blocked\.?|'
    r'WebSearch requires a permission\.?|'
    r'I don\'t have access to web search\.?|'
    r'I\'m not able to (access|browse|search) the (web|internet)\.?|'
    r'I cannot (access|browse|search) the (web|internet)\.?|'
    r'I do not have (access to |the ability to )?(web |real-time |internet )?(search|access|browsing)\.?|'
    r'My training data only goes up to\.?.*?\.?|'
    r'Tool use is not available\.?|'
    r'I\'m unable to use tools right now\.?|'
    r'Search is not available\.?|'
    r'I can\'t perform web searches?\.?)',
    re.IGNORECASE
)
text = claude_error_inline.sub('', text)

lines = text.splitlines(keepends=True)

# [4a] ファイル先頭のHTMLコメント行を除去（デオキシスが <!-- article-type: NEWS --> 等を先頭に出力するケース）
#       正規の本文コメント（本文中の <!-- 要確認: ... --> 等）はそのまま残す
while lines and re.match(r'^\s*<!--.*?-->\s*$', lines[0]):
    lines = lines[1:]

# [4b] AI preamble行を先頭から除去（gardevoir HARD_FAIL誘発の主因）
#      "以下に完成記事を出力します。" 等の定型フレーズで始まる行
PREAMBLE_PAT = re.compile(
    r'(以下に完成記事|以下に記事を|以下が完成|以下の記事を出力|記事本文の内容に基づいてタイトル案を生成|'
    r'完成した記事を以下に|以下に出力します|以下がリライト|以下に示します)')
while lines and PREAMBLE_PAT.search(lines[0]):
    lines = lines[1:]

# [4] 許可要求・AI定型文・チャット定型文の行除去
pat = re.compile(
    r'(許可が必要|許可を?いただ|許可してください|WebSearchを使用|WebSearchの許可|'
    r'ウェブ検索の許可|確認させてください|お手伝いできますか|'
    r'どちらで進めますか|書き込み権限が必要|ファイル編集の許可|'
    r'ツール.*の許可|権限.*要求|許可.*いただけますか|'
    r'WebSearch.*許可|検索.*許可.*必要|'
    r'学習データの範囲外|知識カットオフ|情報源を確認できない|'
    r'記事の元情報.*貼り付け|このチャットに貼り付け|ドラフト文章.*貼り付け|'
    r'アーティスト名.*イベント詳細.*日付.*貼り付け|記事の元情報が貼り付けられていません|'
    r'チェック対象の記事本文を貼り付け|貼り付けられていません|タイトルを入力してください|'
    r'評価対象がありません|入力記事が見当たりません|記事の入力が見当たりません|'
    r'記事を生成します|一次ソース情報が確認できました|情報が確認できました。記事を|'
    r'以下に記事を生成|記事を作成します|記事を出力します|'
    r'記事の元原稿が提供されていません|リライト対象の記事本文を貼り付け|元原稿.*提供されていません|'
    r'リライト対象.*貼り付け|チャットに貼り付け|内容を貼り付けてください|本文を貼り付けてください)'  )
# HTMLタグで始まる行でも定型文パターンが含まれる場合は除去する
# （<p>記事の元情報が貼り付けられていません</p> のようなケース）
import re as _re
CHAT_UI_PATTERN = _re.compile(
    r'(記事の元情報.*貼り付け|このチャットに貼り付け|ドラフト文章.*貼り付け|'
    r'記事の元情報が貼り付けられていません|チェック対象の記事本文を貼り付け|'
    r'貼り付けられていません|タイトルを入力してください|評価対象がありません|'
    r'入力記事が見当たりません|記事の入力が見当たりません|'
    r'記事を生成します|一次ソース情報が確認できました|情報が確認できました。記事を|'
    r'以下に記事を生成|記事を作成します|記事を出力します|'
    r'記事の元原稿が提供されていません|リライト対象の記事本文を貼り付け|元原稿.*提供されていません|'
    r'リライト対象.*貼り付け|チャットに貼り付け|内容を貼り付けてください|本文を貼り付けてください)')
def should_keep(l):
    if not pat.search(l):
        return True  # パターン非マッチ → 保持
    # パターンマッチした行: HTMLタグで始まっていても定型文チェックを優先
    if CHAT_UI_PATTERN.search(l):
        return False  # チャット定型文 → 除去（HTMLタグ内でも）
    # その他のパターン（許可要求等）はHTMLタグ内なら保持
    return l.strip().startswith('<')
cleaned = [l for l in lines if should_keep(l)]
with open(path, 'w', encoding='utf-8') as f:
    f.writelines(cleaned)
PYEOF
}

# ─── WP投稿直前の最終サニタイズ ───────────────────────────────────
# sanitize_output はエージェント出力(reports/*.md)向け。
# sanitize_wp_content は /tmp/kpop_content.txt に書き出した後の
# HTML本文を対象とする最終防壁。リテラル\n・JSONメタデータ・空段落を除去。
sanitize_wp_content() {
  local file="$1"
  [[ -f "$file" ]] || return
  python3 - "$file" <<'SANITIZE_WP_EOF'
import sys, re
path = sys.argv[1]
with open(path, encoding="utf-8", errors="ignore") as f:
    text = f.read()
orig_len = len(text)

# [1] リテラル \n の除去（バックスラッシュ+n）
#     HTML内に残ったClaude出力のリテラル\nを除去
#     ただし <script> / <style> 内の \n は保持する
def _strip_literal_backslash_n(html):
    """Remove literal \\n outside <script>/<style> tags."""
    # Split by script/style tags, only process non-script parts
    parts = re.split(r'(<script[^>]*>.*?</script>|<style[^>]*>.*?</style>)', html, flags=re.DOTALL|re.IGNORECASE)
    for i, part in enumerate(parts):
        if not re.match(r'<(?:script|style)', part, re.IGNORECASE):
            parts[i] = part.replace('\\n', '')
    return ''.join(parts)
text = _strip_literal_backslash_n(text)

# [2] Claude APIメタデータJSON除去
#     (a) 通常のJSON: {"type":"result",...} / {..."input_tokens":...}
#     (b) HTMLエンティティ版: &#8220;type&#8221; etc.

# (a) プレーンJSON
def _strip_json_blob(t, start_pat):
    result = []
    i = 0
    while i < len(t):
        m = re.search(start_pat, t[i:])
        if not m:
            result.append(t[i:])
            break
        start = i + m.start()
        result.append(t[i:start])
        depth = 0
        j = start
        in_str = False
        esc = False
        while j < len(t):
            c = t[j]
            if esc:
                esc = False
            elif c == '\\' and in_str:
                esc = True
            elif c == '"' and not esc:
                in_str = not in_str
            elif not in_str:
                if c == '{': depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
            j += 1
        i = j
    return ''.join(result)

text = _strip_json_blob(text, r'\{"type"\s*:\s*"(?:result|content_block)')
text = _strip_json_blob(text, r'\{["\u201c](?:[^{}]|&#\d+;)*(?:input_tokens|output_tokens|cache_creation|stop_reason|session_id)')

# (b) HTMLエンティティ版（&#8220;=", &#8221;="）
text = re.sub(
    r'(?:&#8220;|&#8221;|&\#8220;|&\#8221;|"|")(?:type|stop_reason|session_id|total_cost_usd|usage)(?:&#8220;|&#8221;|&\#8220;|&\#8221;|"|").*?(?:terminal_reason|server_tool_use)(?:&#8220;|&#8221;|&\#8220;|&\#8221;|"|").*?\}',
    '', text, flags=re.DOTALL)
# session_id単独残留
text = re.sub(r'(?:&#8220;|")session_id(?:&#8221;|")\s*:\s*(?:&#8220;|")[a-f0-9-]+(?:&#8221;|")', '', text)
# stop_reason単独残留
text = re.sub(r'(?:&#8220;|")stop_reason(?:&#8221;|")\s*:\s*(?:&#8220;|")end_turn(?:&#8221;|")', '', text)
# total_cost_usd残留
text = re.sub(r'(?:&#8220;|")total_cost_usd(?:&#8221;|")\s*:\s*[\d.]+', '', text)

# [3] 空段落の整理
#     <p>\n\n</p> / <p></p> / <p> </p> を除去
text = re.sub(r'<p>\s*</p>', '', text)
# 連続空行を2つまでに
text = re.sub(r'\n{3,}', '\n\n', text)

# [4] U+FFFD除去
text = text.replace('\ufffd', '')

changed = orig_len - len(text)
if changed > 0:
    print(f"  ✅ [sanitize_wp] {changed}文字除去: {path}", file=sys.stderr)
with open(path, 'w', encoding='utf-8') as f:
    f.write(text)
SANITIZE_WP_EOF
}

export -f sanitize_output 2>/dev/null || true
export -f sanitize_wp_content 2>/dev/null || true
