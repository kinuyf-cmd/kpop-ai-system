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
#     {"type":"result","subtype":"success",...,"terminal_reason":"completed",...} 形式
text = re.sub(r'\{"type"\s*:\s*"result".*?"terminal_reason"\s*:\s*"[^"]*"[^}]*\}', '', text, flags=re.DOTALL)
# HTML-encoded版も除去
text = re.sub(r'\{&#8220;type&#8221;.*?&#8221;terminal_reason&#8221;.*?\}', '', text, flags=re.DOTALL)
# modelUsage単独でも除去（途中で切れた場合）
text = re.sub(r'"modelUsage"\s*:\s*\{.*?"costUSD"\s*:\s*[\d.]+[^}]*\}[^}]*\}', '', text, flags=re.DOTALL)
# session_idダンプ
text = re.sub(r'"session_id"\s*:\s*"[a-f0-9-]+"[^}]*\}', '', text, flags=re.DOTALL)

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

export -f sanitize_output 2>/dev/null || true
