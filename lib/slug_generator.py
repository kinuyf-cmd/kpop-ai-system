"""
SEOに強い英語スラッグ生成（日本語タイトル対応）

アーティスト名・ジャンルキーワードを優先抽出し、
stopwords除去・最大60文字・ハイフン区切り・小文字・末尾-YYYYを付与する。

Usage:
  python3 lib/slug_generator.py "BTSは初週比71%減でもYeに勝てたのか？ARIRANG 2週連続1位"
  → bts-arirang-billboard-2weeks-1-2026
"""

import re
import sys
from datetime import datetime

# ── アーティスト名マッピング ────────────────────────────────────────────────────
# key: 表記揺れパターン（正規表現）  value: スラッグトークン
ARTIST_PATTERNS: list[tuple[str, str]] = [
    (r"\bBTS\b", "bts"),
    (r"T\.O\.P", "top"),
    (r"\bTWICE\b", "twice"),
    (r"\bBLACKPINK\b", "blackpink"),
    (r"\bIVE\b", "ive"),
    (r"\bILLIT\b", "illit"),
    (r"\baespa\b", "aespa"),
    (r"\bNewJeans\b", "newjeans"),
    (r"\bENHYPEN\b", "enhypen"),
    (r"\bTXT\b", "txt"),
    (r"\bStray\s*Kids\b", "straykids"),
    (r"\bSEVENTEEN\b", "seventeen"),
    (r"\bMAMAMOO\b", "mamamoo"),
    (r"\bEXO\b", "exo"),
    (r"\bNCT\b", "nct"),
    (r"\bRIIZE\b", "riize"),
    (r"\bZERO\s*BASE\s*ONE\b", "zerobaseone"),
    (r"\b2\s*NE\s*1\b", "2ne1"),
    (r"\bNCT\s*127\b", "nct127"),
    (r"\bNCT\s*DREAM\b", "nct-dream"),
    (r"\bNCT\s*U\b", "nct-u"),
    (r"\bSUPER\s*M(?=[^A-Za-z]|$)", "superm"),
    (r"\bWayV\b", "wayv"),
    (r"\bLE\s*SSERAFIM", "lesserafim"),
    (r"\bRed\s*Velvet\b", "redvelvet"),
    (r"\bGOT7\b", "got7"),
    (r"\bMONSTA\s*X\b", "monstax"),
    (r"\bATEEZ\b", "ateez"),
    (r"\bTHE\s*BOYZ\b", "theboyz"),
    (r"\bTOMORROW\s*X\s*TOGETHER\b", "txt"),
]

# ── ジャンル・キーワードマッピング ─────────────────────────────────────────────
# key: 日本語キーワード  value: 英語スラッグトークン
KEYWORD_MAP: dict[str, str] = {
    "ガラス肌": "glass-skin",
    "スキンケア": "skincare",
    "カムバック": "comeback",
    "ライブ": "concert",
    "チャート": "chart",
    "ビルボード": "billboard",
    "訴訟": "lawsuit",
    "ツアー": "tour",
    "ソウル": "seoul",
    "旅行": "travel",
    # 追加マッピング
    "ARIRANG": "arirang-billboard",
    "7スキン法": "7skin",
    "サナ": "sana",
    "7選": "",
    "5選": "",
    "10選": "",
    "3選": "",
    "1位": "1",
    "2位": "2",
    "3位": "3",
    "1週連続": "1week",
    "2週連続": "2weeks",
    "3週連続": "3weeks",
    "4週連続": "4weeks",
    "5週連続": "5weeks",
    "連続": "consecutive",
    "コスメ": "cosmetics",
    "K-POPアイドル": "kpop-idol",
    "K-POP": "kpop",
    "アイドル": "idol",
    "韓国": "korean",
    "スキン法": "skin-method",
    "コンセプト": "concept",
    "解説": "guide",
    "2026年4月": "april",
    "2025年4月": "april",
    "2026年1月": "january",
    "2026年2月": "february",
    "2026年3月": "march",
    "2026年5月": "may",
    "2026年6月": "june",
    "2026年7月": "july",
    "2026年8月": "august",
    "2026年9月": "september",
    "2026年10月": "october",
    "2026年11月": "november",
    "2026年12月": "december",
    "2025年1月": "january",
    "2025年2月": "february",
    "2025年3月": "march",
    "2025年5月": "may",
    "2025年6月": "june",
    "2025年7月": "july",
    "2025年8月": "august",
    "2025年9月": "september",
    "2025年10月": "october",
    "2025年11月": "november",
    "2025年12月": "december",
    "4月": "april",
    "1月": "january",
    "2月": "february",
    "3月": "march",
    "5月": "may",
    "6月": "june",
    "7月": "july",
    "8月": "august",
    "9月": "september",
    "10月": "october",
    "11月": "november",
    "12月": "december",
}

# ── ストップワード ────────────────────────────────────────────────────────────
STOPWORDS_JA = {
    "の", "は", "が", "を", "に", "で", "と", "から", "まで", "より",
    "も", "や", "か", "な", "ね", "よ", "わ", "ぞ", "ぜ", "さ",
    "完全解説", "最新版", "まとめ", "速報", "徹底解説", "全解説",
    "とは", "について", "における", "による", "に関する",
    "する", "した", "して", "される", "された", "れる", "られる",
    "なぜ", "どう", "どの", "どんな", "なに", "いつ",
    "でも", "でも", "その", "この", "あの", "それ", "これ",
}

STOPWORDS_EN = {
    "the", "a", "an", "of", "in", "on", "at", "to", "for",
    "and", "or", "but", "is", "are", "was", "were",
    "vs", "why", "how",
}

# ── 汎用スラッグ判定 ──────────────────────────────────────────────────────────
_GENERIC_SLUG_RE = re.compile(
    r"^(pop-|kpop-news-|\d{8}$|\d{8}-\d{4}$)"
)


def is_generic_slug(slug: str) -> bool:
    """汎用的（SEO弱）スラッグかどうかを判定する"""
    if not slug:
        return True
    return bool(_GENERIC_SLUG_RE.match(slug))


# ── メイン生成関数 ────────────────────────────────────────────────────────────

def generate_slug(title: str, year: int | None = None, max_len: int = 60) -> str:
    """
    日本語タイトルからSEOに強い英語スラッグを生成する。

    Parameters
    ----------
    title   : 日本語（または混在）記事タイトル
    year    : 末尾に付与する年（省略時は現在年）
    max_len : 最大文字数（末尾の -YYYY を含む）

    Returns
    -------
    小文字・ハイフン区切り・末尾-YYYY のスラッグ文字列
    """
    if not title:
        return _fallback(year)

    year = year or datetime.now().year
    year_suffix = f"-{year}"

    collected_tokens: list[str] = []  # 順序付きで収集、後で重複除去

    # ─ Step 1: アーティスト名を優先抽出（位置順）─────────────────────────────
    artist_hit_spans: list[tuple[int, int, str]] = []
    for pattern, token in ARTIST_PATTERNS:
        for m in re.finditer(pattern, title, re.IGNORECASE):
            artist_hit_spans.append((m.start(), m.end(), token))

    # 位置順ソート → 前から出現順にトークンを収集
    artist_hit_spans.sort(key=lambda x: x[0])

    # ─ Step 2: 日本語キーワードマッピング（位置情報付きで収集）─────────────────
    kw_hit_spans: list[tuple[int, int, str]] = []
    masked = list(title)
    for kw in sorted(KEYWORD_MAP.keys(), key=len, reverse=True):
        start_idx = 0
        while True:
            idx = title.find(kw, start_idx)
            if idx == -1:
                break
            if all(masked[idx + i] != "\x00" for i in range(len(kw))):
                kw_hit_spans.append((idx, idx + len(kw), KEYWORD_MAP[kw]))
                for i in range(len(kw)):
                    masked[idx + i] = "\x00"
            start_idx = idx + 1

    # ─ Step 3: 残りのASCII単語を抽出（アーティスト名・KWマッチ範囲を除外）───────
    # アーティスト名・キーワードマッチ済み範囲を潰す
    ascii_source = list(title)
    for start, end, _ in artist_hit_spans + kw_hit_spans:
        for i in range(start, end):
            if i < len(ascii_source):
                ascii_source[i] = " "
    ascii_source = "".join(ascii_source)

    raw_ascii_spans: list[tuple[int, int, str]] = []
    # 数字始まりの英数字混在トークン（2NE1, NCT127等）も1単語として扱う
    for m in re.finditer(r"\d*[A-Za-z][A-Za-z0-9']*|\d+", ascii_source):
        tok = m.group()
        clean = re.sub(r"[^a-z0-9]", "", tok.lower())
        if not clean:
            continue
        if clean in STOPWORDS_EN:
            continue
        if len(clean) < 2 and not clean.isdigit():
            continue
        # 年数字（4桁で年っぽい数字）はスキップ（末尾year_suffixで付与するため）
        if clean.isdigit() and len(clean) == 4 and 2000 <= int(clean) <= 2099:
            continue
        raw_ascii_spans.append((m.start(), m.end(), clean))

    # ─ Step 4: すべてのトークンを出現位置順にソートして結合 ─────────────────────
    all_spans = artist_hit_spans + kw_hit_spans + raw_ascii_spans
    all_spans.sort(key=lambda x: x[0])
    for _, _, token in all_spans:
        # 空トークン（除外マッピング）はスキップ
        if token:
            collected_tokens.append(token)

    # ─ Step 5: 重複除去（順序保持） ───────────────────────────────────────────
    seen: set[str] = set()
    unique_tokens: list[str] = []
    for tok in collected_tokens:
        # ハイフンを含むトークン（glass-skin等）は全体をキーにする
        key = tok
        if key not in seen:
            seen.add(key)
            unique_tokens.append(tok)

    if not unique_tokens:
        return _fallback(year)

    # ─ Step 6: 結合・長さ制限 ─────────────────────────────────────────────────
    slug_body = "-".join(unique_tokens)

    # 長さ制限: year_suffix 分を先に確保
    body_max = max_len - len(year_suffix)
    if len(slug_body) > body_max:
        slug_body = slug_body[:body_max].rstrip("-")
        # 末尾に中途半端なトークンが残らないよう最後のハイフンで切る
        last_hyphen = slug_body.rfind("-")
        if last_hyphen > body_max // 2:
            slug_body = slug_body[:last_hyphen]

    # ─ Step 7: 末尾に年を付与 ────────────────────────────────────────────────
    slug = f"{slug_body}{year_suffix}"

    # ─ Step 8: 最終クリーニング ──────────────────────────────────────────────
    slug = re.sub(r"-+", "-", slug).strip("-").lower()

    return slug or _fallback(year)


def _fallback(year: int | None = None) -> str:
    y = year or datetime.now().year
    return f"kpop-news-{datetime.now().strftime('%m%d')}-{y}"


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 slug_generator.py <title> [year]")
        sys.exit(1)
    _title = sys.argv[1]
    _year = int(sys.argv[2]) if len(sys.argv) >= 3 else None
    print(generate_slug(_title, year=_year))
