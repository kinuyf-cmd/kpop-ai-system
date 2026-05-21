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
text = ''.join(cleaned)

# ────────────────────────────────────────────────────────────
# [5] C-Y 矯正: インライン style="color:..." / "background:..." の処理
#     ホワイトリスト色（M3 段階3.5.1 で確定した AA達成済み色）は保持。
#     それ以外は属性ごと削除し、対応する class を残す（kpop_pipeline.sh が出す CTA は元から class 付き）。
# [6] C-Z 矯正: <table> に scope/caption が無ければ後付け。
# どちらも矯正ログを ~/.kpop_recovery/sanitize_log.jsonl に追記。
# ────────────────────────────────────────────────────────────
import json, datetime, pathlib, os

# AA達成済み色（M1 段階1-8 + M3 段階3.5.1 で確定）
AA_WHITELIST_COLORS = {
    "#c2185b", "#8a4a63", "#0b5ed7",         # CTA AA色（M3 3.5.1）
    "#1a1a2e", "#fff0f5", "#f0f8ff", "#f9f9f9",  # 背景色（dark/淡色、対 white/text コントラスト確認済）
    "#fff", "#ffffff", "#000", "#000000",    # 白黒
    "#ffb6c1", "#87ceeb", "#7c3aed",         # 装飾(border のみで本文文字色には使わない前提)
}
# ブランド色「危険」リスト（M1 罠リスト由来。検出されたら必ず矯正）
BRAND_DANGER_COLORS = {"#b8889a", "#e91e63", "#ff0060", "#ff69b4", "#1e90ff"}

corrections = []  # ログ用

# (5) インライン color/background style の検出と矯正
# style="...color:#XXX...;..." or style="...background:...;..." を扱う
def normalize_color(v):
    v = v.strip().lower()
    if v.startswith("#") and (len(v) == 4 or len(v) == 7):
        return v
    return v  # rgb()/rgba()/keyword は別途扱う（簡易: keep）

style_attr_re = re.compile(r'style\s*=\s*"([^"]*)"', re.IGNORECASE)
hex_color_re  = re.compile(r'(color|background(?:-color)?)\s*:\s*([#\w\(\),\.\s%]+?)\s*(?:;|$)', re.IGNORECASE)

def fix_style_attr(m):
    body = m.group(1)
    changed = False
    def repl(cm):
        nonlocal changed
        prop = cm.group(1).lower()
        val  = cm.group(2).strip()
        nv   = normalize_color(val)
        # ホワイトリスト保持
        if nv in AA_WHITELIST_COLORS:
            return cm.group(0)
        # 危険色 → 矯正（color は class に逃がし、background は削除）
        if nv in BRAND_DANGER_COLORS:
            changed = True
            corrections.append({"type": "inline_brand_color", "prop": prop, "value": nv})
            return ""  # この宣言を削除
        # それ以外の任意色: AA計測できないため安全側で削除（class運用を強制）
        if nv.startswith("#"):
            changed = True
            corrections.append({"type": "inline_unknown_color", "prop": prop, "value": nv})
            return ""
        return cm.group(0)
    new_body = hex_color_re.sub(repl, body)
    # 余分なセミコロン整形
    new_body = re.sub(r';\s*;+', ';', new_body).strip().strip(';').strip()
    if not new_body:
        return ""  # 属性まるごと削除
    if changed:
        return f'style="{new_body}"'
    return m.group(0)

text_before_c_y = text
text = style_attr_re.sub(fix_style_attr, text)
n_cy = len(corrections)

# (6) C-Z: <table> に scope/caption 後付け
table_re = re.compile(r'(<table\b[^>]*>)(.*?)(</table>)', re.IGNORECASE | re.DOTALL)
def fix_table(m):
    open_tag, body, close_tag = m.group(1), m.group(2), m.group(3)
    fixed_body = body
    table_fixed = False
    # caption が無ければ先頭に追加
    if not re.search(r'<caption\b', body, re.IGNORECASE):
        fixed_body = '<caption>記事内のデータ表</caption>' + fixed_body
        corrections.append({"type": "table_caption_added"})
        table_fixed = True
    # 1行目セル（<tr>...<td/th>...）の <td> を <th scope="col"> に昇格
    # 既に <th> が見出し行に存在するなら scope だけ補う
    def fix_first_row(tr_m):
        tr_content = tr_m.group(0)
        # 既存 <th> に scope が無ければ追加
        if re.search(r'<th\b(?![^>]*scope=)', tr_content, re.IGNORECASE):
            tr_content2 = re.sub(r'<th\b(?![^>]*scope=)', '<th scope="col"', tr_content, flags=re.IGNORECASE)
            if tr_content2 != tr_content:
                corrections.append({"type": "table_th_scope_added"})
            return tr_content2
        # <th> が無く <td> しかない → 最初の <tr> 内の <td> を <th scope="col"> に昇格
        if '<th' not in tr_content.lower() and '<td' in tr_content.lower():
            tr_content2 = re.sub(r'<td\b', '<th scope="col"', tr_content, flags=re.IGNORECASE)
            tr_content2 = re.sub(r'</td>', '</th>', tr_content2, flags=re.IGNORECASE)
            corrections.append({"type": "table_td_to_th"})
            return tr_content2
        return tr_content
    # 最初の <tr>...</tr> だけ対象
    first_tr = re.search(r'<tr\b[^>]*>.*?</tr>', fixed_body, re.IGNORECASE | re.DOTALL)
    if first_tr:
        fixed_body = fixed_body[:first_tr.start()] + fix_first_row(first_tr) + fixed_body[first_tr.end():]
    return open_tag + fixed_body + close_tag

text_before_c_z = text
text = table_re.sub(fix_table, text)
n_cz = len(corrections) - n_cy

# 書き込み
with open(path, 'w', encoding='utf-8') as f:
    f.write(text)

# ログ出力（矯正があった場合のみ）
if corrections:
    log_dir = pathlib.Path(os.path.expanduser('~/.kpop_recovery'))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / 'sanitize_log.jsonl'
        entry = {
            "ts": datetime.datetime.now().isoformat(timespec='seconds'),
            "file": path,
            "n_cy_inline_style": n_cy,
            "n_cz_table_fix": n_cz,
            "corrections": corrections[:20],  # 最初の20件まで
        }
        with log_file.open('a', encoding='utf-8') as lf:
            lf.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass  # ログ失敗は本処理に影響させない
PYEOF
}

export -f sanitize_output 2>/dev/null || true
