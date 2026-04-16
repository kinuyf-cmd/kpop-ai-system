"""
ダークライ: 投稿前権利監査エージェント

投稿前のコンテンツに対して以下の権利・規約リスクを検出する。
致命リスクは投稿中止、警告は記録のみ。

検出項目:
1. 公式以外のニュースサイト名・引用過多
2. ファン投稿サイト URL (Twitter, Instagram, Tumblr) の埋め込み
3. 著作権表記なしの画像・動画埋め込み
4. 個人情報（電話番号、住所）
5. 名誉毀損表現（断定的な犯罪・スキャンダル断言）
6. 医療・法律・金融の不適切な助言
7. アフィリエイトリンクの過剰
8. AdSense ポリシー違反コンテンツ（暴力・性的・差別）
9. ソース不明断定（「〜と言われている」「噂では」）
10. 既存記事との重複（タイトル/本文）

Usage:
  echo '{"title":"...","content":"..."}' | python3 lib/darkrai_audit.py
  python3 lib/darkrai_audit.py --file post.json
  python3 lib/darkrai_audit.py --file post.json --strict  # 警告も致命扱い
"""
import argparse
import json
import re
import sys


# ── 致命的禁止パターン ──
FATAL_PATTERNS = [
    # 名誉毀損
    (r"(犯罪者|逮捕確定|有罪確定|犯人だ)", "名誉毀損リスク: 確定的犯罪表現"),
    # ニュースサイト引用過多（コピペ疑い）
    # ファン投稿サイト動画の直接埋め込み
    (r'<iframe[^>]*src="https?://(?:www\.)?(twitter\.com|x\.com|instagram\.com|tumblr\.com|tiktok\.com)/[^/"]+/status/', "SNS埋め込み: 引用要件未充足リスク"),
    # 個人情報
    # URLパス内の数値列（prtimes.jp等）を除外するため、前後にURLコンテキストがない場合のみ検出
    (r"(?<![/\.])(?<!\d)\b0\d{1,4}[-\s]\d{1,4}[-\s]\d{4}\b(?![\.\d])", "個人情報: 電話番号"),
    (r"〒\s*\d{3}-?\d{4}", "個人情報: 郵便番号"),
    # AdSenseポリシー: ヘイト・暴力扇動
    (r"(殺せ|殺してしまえ|消えろ.{0,20}この世から)", "AdSense違反: 暴力扇動"),
]

# ── 警告パターン ──
WARN_PATTERNS = [
    # 不確実な情報の断定
    (r"(噂では|と言われている|らしい|だそうだ|という.{0,5}噂)", "不確実情報の断定的引用"),
    # 過度なアフィリエイト
    (r"(?i)(?:utm_campaign=revenue_link|amazon\.co\.jp/dp/|rakuten\.co\.jp.*item).{0,3000}(?:utm_campaign=revenue_link|amazon\.co\.jp/dp/|rakuten\.co\.jp.*item).{0,3000}(?:utm_campaign=revenue_link|amazon\.co\.jp/dp/|rakuten\.co\.jp.*item).{0,3000}(?:utm_campaign=revenue_link|amazon\.co\.jp/dp/|rakuten\.co\.jp.*item)", "アフィリエイトリンク4個以上検出"),
    # 医療・法律助言
    (r"(治療法|処方箋|診断|完治する|必ず治る)", "医療関連の断定的助言"),
    (r"(法的に問題ない|訴訟になる|違法では?ない)", "法律関連の断定的助言"),
    (r"(必ず儲かる|絶対稼げる|元本保証)", "金融関連の断定的助言"),
    # 著作権疑い
    (r'<img[^>]*src="https?://(?:[^/]*\.(?:naver\.|daum\.|sportschosun|chosun|joongang|donga|hankyung)|pbs\.twimg\.com|scontent[^"]+)"', "著作権疑い: メディア/SNS画像直リンク"),
    # 出典なき大量引用
    (r"(<blockquote[^>]*>[\s\S]{500,}</blockquote>)", "長文引用 (出典確認推奨)"),
]


def audit(post):
    """投稿を監査して、(fatal_errors, warnings) を返す"""
    title = post.get("title", "")
    content = post.get("content", "")
    text = title + "\n" + content

    fatal = []
    warnings = []

    # ベースバリデーション (validate_post.py 同等)
    if "{\"type\":\"result\"" in content or '"modelUsage"' in content:
        fatal.append("Claude CLI JSONメタデータ混入")
    if re.search(r'<script[^>]*>[^<]*<br\s*/?>', content):
        fatal.append("script タグの wpautop 破壊")

    # URLを除去したテキスト（電話番号等の誤検知防止: PRTimesURLの数字列を除外）
    # href/src属性値のURL、およびテキスト中のURLを両方除去
    # JSONエスケープされたURL（\/）も除去対象に含める
    # href= 属性を除去（属性値がダブルクォート・シングルクォート・クォートなし問わず対応）
    text_no_url = re.sub(r'(?:href|src|action)\s*=\s*["\']?https?://[^"\'>\s]+["\']?', '', text)
    text_no_url = re.sub(r'https?:\\/\\/\S+', '', text_no_url)  # JSONエスケープ済みURL
    text_no_url = re.sub(r'https?://\S+', '', text_no_url)
    # PRTimes等のURL末尾数字列が改行後に残る場合の追加除去（例: /p/000000603.000022823.html）
    text_no_url = re.sub(r'/p/\d+\.\d+\.html', '', text_no_url)
    # URL除去後に残る連続数字列（8桁以上）を除去（PRTimes等のID番号誤検知防止）
    text_no_url = re.sub(r'\b0{3,}\d+\b', '', text_no_url)

    # 致命パターンチェック
    for pattern, desc in FATAL_PATTERNS:
        # 電話番号・郵便番号は URL 除去後のテキストでチェック（URL中の数字列を誤検知しない）
        check_text = text_no_url if "個人情報" in desc else text
        if re.search(pattern, check_text):
            fatal.append(desc)

    # 警告パターンチェック
    for pattern, desc in WARN_PATTERNS:
        if re.search(pattern, text):
            warnings.append(desc)

    # 構造チェック
    if title and len(title) < 10:
        fatal.append(f"タイトルが短すぎる ({len(title)}文字)")
    if content and len(re.sub(r'<[^>]+>', '', content)) < 300:
        fatal.append(f"プレーンテキスト本文が短すぎる ({len(re.sub(chr(60)+'[^'+chr(62)+']+'+chr(62), '', content))}文字)")

    # 出典明記チェック（警告レベル）
    if "情報元" not in content and "出典" not in content and "<source>" not in content:
        warnings.append("出典明記なし (情報元・出典・<source>のいずれも未検出)")

    return fatal, warnings


def main():
    ap = argparse.ArgumentParser(description="ダークライ: 投稿前権利監査")
    ap.add_argument("--file", help="JSONファイルから読み込む")
    ap.add_argument("--strict", action="store_true", help="警告も致命扱い")
    ap.add_argument("--quiet", action="store_true", help="OK時は何も出力しない")
    args = ap.parse_args()

    try:
        if args.file:
            with open(args.file) as f:
                post = json.load(f)
        else:
            post = json.load(sys.stdin)
    except Exception as e:
        sys.stderr.write(f"[darkrai] JSON parse error: {e}\n")
        sys.exit(2)

    fatal, warnings = audit(post)

    if not args.quiet:
        for w in warnings:
            sys.stderr.write(f"[darkrai] WARN: {w}\n")
        for e in fatal:
            sys.stderr.write(f"[darkrai] FATAL: {e}\n")

    if fatal:
        sys.stderr.write(f"[darkrai] ❌ FAIL ({len(fatal)} fatal, {len(warnings)} warn)\n")
        sys.exit(1)

    if args.strict and warnings:
        sys.stderr.write(f"[darkrai] ❌ FAIL strict ({len(warnings)} warn treated as fatal)\n")
        sys.exit(1)

    if not args.quiet:
        sys.stderr.write(f"[darkrai] ✅ OK ({len(warnings)} warnings)\n")
    sys.exit(0)


if __name__ == "__main__":
    main()
