#!/usr/bin/env python3
"""
サムネイル文言テンプレート選択システム
Usage: python3 thumbnail_templates.py "記事タイトル" --genre breaking
Output: 1-2行のサムネイル文言（各行最大14文字）
"""

import argparse
import random
import re
import sys

TEMPLATES = {
    "breaking": [
        "{artist} 衝撃の{event}",
        "{artist}に何が起きた",
        "ついに判明した真相",
        "ファン騒然の理由",
        "{number}が衝撃すぎる",
    ],
    "comeback": [
        "{artist} ついに復活",
        "{artist} 新曲解禁",
        "{artist} カムバ決定",
        "待望の{artist}復帰",
        "{number}ぶりの復活",
    ],
    "controversy": [
        "{artist} 衝撃の真相",
        "炎上の全貌が判明",
        "{artist}がヤバい",
        "ファン騒然の事態",
    ],
    "beauty": [
        "{artist}の神肌が衝撃",
        "衝撃のコスメ{number}選",
        "{artist}メイクが神",
        "ガラス肌の神ワザ判明",
    ],
    "live": [
        "{artist} 来日決定",
        "争奪戦ついに決着",
        "{artist} {number}公演決定",
        "神セトリが判明",
    ],
    "chart": [
        "{artist} {number}冠の衝撃",
        "歴代記録更新の衝撃",
        "{artist}が1位独走",
    ],
    "analysis": [
        "なぜ{artist}は神なのか",
        "{artist}の戦略が神",
        "{artist}の真相が判明",
    ],
    "travel": [
        "ソウル推し活{number}選",
        "聖地巡礼 決定版ガイド",
        "ファン必見 神スポット",
    ],
    "fashion": [
        "{artist}着用で即完売",
        "{artist}の私服が神",
        "衝撃のコーデ{number}選",
    ],
    "default": [
        "{artist}に衝撃の展開",
        "衝撃の新情報が判明",
        "ファン必見の速報",
    ],
}

# アーティスト名リスト（表示名, 検索キーワード）
KNOWN_ARTISTS = [
    ("BTS", ["bts", "防弾少年団", "방탄"]),
    ("RM", ["rm"]),
    ("JIN", ["jin"]),
    ("SUGA", ["suga"]),
    ("J-HOPE", ["j-hope", "jhope"]),
    ("JIMIN", ["jimin"]),
    ("V", ["テヒョン", "テテ"]),
    ("JUNGKOOK", ["jungkook", "ジョングク"]),
    ("BIGBANG", ["bigbang"]),
    ("G-DRAGON", ["g-dragon", "gd", "ジードラゴン"]),
    ("BLACKPINK", ["blackpink", "black pink", "ブラックピンク", "ブルピン"]),
    ("JENNIE", ["jennie", "ジェニー"]),
    ("JISOO", ["jisoo", "ジス"]),
    ("ROSE", ["rosé", "rose", "ロゼ"]),
    ("LISA", ["lisa", "リサ"]),
    ("aespa", ["aespa", "エスパ"]),
    ("KARINA", ["karina", "カリナ"]),
    ("WINTER", ["winter", "ウィンター"]),
    ("BABYMONSTER", ["babymonster", "baby monster", "ベビモン"]),
    ("ILLIT", ["illit", "アイリット"]),
    ("IVE", ["ive", "アイヴ"]),
    ("ウォニョン", ["wonyoung", "ウォニョン"]),
    ("LE SSERAFIM", ["le sserafim", "lesserafim", "ルセラフィム"]),
    ("SAKURA", ["sakura", "サクラ", "宮脇咲良"]),
    ("CHAEWON", ["chaewon", "チェウォン"]),
    ("KAZUHA", ["kazuha", "カズハ"]),
    ("SEVENTEEN", ["seventeen", "svt", "セブチ"]),
    ("TWICE", ["twice", "トゥワイス"]),
    ("SANA", ["sana", "サナ"]),
    ("MOMO", ["momo", "モモ"]),
    ("Stray Kids", ["stray kids", "skz", "スキズ"]),
    ("NewJeans", ["newjeans", "new jeans", "ニュジ"]),
    ("MINJI", ["minji", "ミンジ"]),
    ("HANNI", ["hanni", "ハニ"]),
    ("RIIZE", ["riize", "ライズ"]),
    ("NCT", ["nct"]),
    ("XG", ["xg"]),
    ("EXO", ["exo"]),
    ("BAEKHYUN", ["baekhyun", "ベッキョン"]),
    ("ITZY", ["itzy", "イッチ"]),
    ("ENHYPEN", ["enhypen", "エナプ"]),
    ("TXT", ["txt", "tomorrow x together"]),
    ("ATEEZ", ["ateez", "アチズ"]),
    ("TREASURE", ["treasure", "トレジャー"]),
    ("NMIXX", ["nmixx"]),
    ("(G)I-DLE", ["g)i-dle", "gi-dle", "gidle", "アイドゥル"]),
    ("Red Velvet", ["red velvet", "レドベル"]),
    ("ZEROBASEONE", ["zerobaseone", "zb1"]),
    ("BOA", ["boa", "ボア"]),
]

# ジャンル自動判定キーワード
GENRE_KEYWORDS = {
    "chart": ["チャート", "ランキング", "1位", "top10", "billboard", "gaon",
              "spotify", "連覇", "記録", "冠", "circle chart"],
    "comeback": ["カムバック", "カムバ", "復帰", "新アルバム", "ミニアルバム",
                 "ep", "新曲", "mv公開", "リリース", "音源公開", "配信開始", "解禁"],
    "live": ["ライブ", "コンサート", "ツアー", "来日", "ファンミ", "チケット",
             "公演", "セトリ", "セットリスト", "ドーム"],
    "controversy": ["炎上", "騒動", "脱退", "訴訟", "事件", "問題", "謝罪",
                    "ゴシップ", "熱愛", "スキャンダル"],
    "beauty": ["美容", "コスメ", "スキンケア", "メイク", "ガラス肌", "韓国コスメ",
               "保湿", "美白", "ルーティン"],
    "fashion": ["ファッション", "私服", "コーデ", "着用", "完売", "ブランド",
                "アンバサダー", "モデル"],
    "travel": ["旅行", "ソウル", "釜山", "渡韓", "聖地巡礼", "カフェ", "観光"],
    "analysis": ["考察", "分析", "なぜ", "理由", "比較", "深掘り", "戦略"],
    "breaking": ["速報", "電撃", "緊急", "判明", "発覚", "衝撃"],
}


def extract_artist(title: str) -> str | None:
    """タイトルからアーティスト名を抽出"""
    title_lower = title.lower()
    for display_name, keywords in KNOWN_ARTISTS:
        for kw in keywords:
            if kw.lower() in title_lower:
                return display_name
    return None


def extract_number(title: str) -> str | None:
    """タイトルから数字表現を抽出（例: 6冠, 13年, 5万）"""
    # 数字＋単位のパターンを優先
    m = re.search(r'(\d+(?:\.\d+)?(?:万|億|冠|年|ヶ月|か月|日|曲|公演|回|位|選|連|週))', title)
    if m:
        return m.group(1)
    # 単純な数字
    m = re.search(r'(\d+)', title)
    if m:
        return m.group(1)
    return None


def extract_event(title: str) -> str:
    """タイトルからイベント要素を抽出"""
    event_words = ["発表", "復帰", "脱退", "結婚", "入隊", "除隊", "引退",
                   "デビュー", "卒業", "契約", "移籍", "活動休止", "活動再開",
                   "コラボ", "出演", "受賞"]
    title_lower = title.lower()
    for word in event_words:
        if word in title_lower:
            return word
    return "発表"


def detect_genre(title: str) -> str:
    """タイトルからジャンルを自動判定"""
    title_lower = title.lower()
    # スコア方式: キーワードが多くマッチしたジャンルを優先
    scores: dict[str, int] = {}
    for genre, keywords in GENRE_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in title_lower)
        if count > 0:
            scores[genre] = count
    if scores:
        return max(scores, key=scores.get)
    return "default"


def extract_bare_number(number_with_unit: str) -> str:
    """数字部分だけを取り出す（例: '10選' -> '10'）"""
    m = re.match(r'(\d+(?:\.\d+)?)', number_with_unit)
    return m.group(1) if m else number_with_unit


def fill_template(template: str, artist: str | None, number: str | None, event: str) -> str:
    """テンプレートのプレースホルダーを埋める"""
    result = template
    if artist:
        result = result.replace("{artist}", artist)
    if number:
        # テンプレートの{number}直後に単位がある場合、numberから単位を除去して重複回避
        # 例: template="{number}選", number="10選" -> "10選" (not "10選選")
        for suffix in ["万", "億", "冠", "年", "ヶ月", "か月", "日", "曲", "公演", "回", "位", "選", "連", "週", "ぶり"]:
            placeholder_with_suffix = "{number}" + suffix
            if placeholder_with_suffix in result and number.endswith(suffix):
                result = result.replace(placeholder_with_suffix, number)
                break
        else:
            result = result.replace("{number}", number)
    result = result.replace("{event}", event)
    return result


def has_unfilled_placeholders(text: str) -> bool:
    """未置換のプレースホルダーが残っているか"""
    return bool(re.search(r'\{(artist|number|event)\}', text))


def is_semantically_valid(template: str, number: str | None) -> bool:
    """テンプレートと数字の組み合わせが意味的に正しいかチェック"""
    TIME_UNITS = ("年", "ヶ月", "か月", "日", "週")
    if "{number}ぶり" in template:
        # 「Xぶり」は時間単位の数字のみ有効
        if number is None:
            return False
        return any(number.endswith(u) for u in TIME_UNITS)
    if "{number}冠" in template:
        if number and not (number.isdigit() or number.endswith("冠")):
            return False
    if "{number}公演" in template:
        if number and not (number.isdigit() or number.endswith("公演")):
            return False
    if "{number}選" in template:
        if number and not (number.isdigit() or number.endswith("選")):
            return False
    return True


def format_output(text: str, max_chars: int = 14) -> str:
    """
    14文字以内なら1行、超えたら2行に分割。
    各行最大14文字を厳守。
    """
    text = text.strip()
    if len(text) <= max_chars:
        return text

    # 自然な区切り位置で分割を試みる
    best_split = None
    # スペースで分割
    if " " in text:
        parts = text.split(" ", 1)
        if len(parts[0]) <= max_chars and len(parts[1]) <= max_chars:
            best_split = (parts[0], parts[1])

    if best_split is None:
        # 14文字で強制分割
        line1 = text[:max_chars]
        line2 = text[max_chars:]
        if len(line2) > max_chars:
            line2 = line2[:max_chars - 1] + "…"
        best_split = (line1, line2)

    return f"{best_split[0]}\n{best_split[1]}"


def select_thumbnail_text(title: str, genre: str | None = None) -> str:
    """メイン処理: タイトルとジャンルからサムネイル文言を選択"""
    artist = extract_artist(title)
    number = extract_number(title)
    event = extract_event(title)

    if genre is None or genre not in TEMPLATES:
        genre = detect_genre(title)

    templates = TEMPLATES.get(genre, TEMPLATES["default"])

    # テンプレートをフィルタ: プレースホルダーが埋められ、意味的に正しいもののみ
    candidates = []
    for tmpl in templates:
        if not is_semantically_valid(tmpl, number):
            continue
        filled = fill_template(tmpl, artist, number, event)
        if not has_unfilled_placeholders(filled):
            candidates.append(filled)

    # 候補がなければdefaultから
    if not candidates:
        for tmpl in TEMPLATES["default"]:
            if not is_semantically_valid(tmpl, number):
                continue
            filled = fill_template(tmpl, artist, number, event)
            if not has_unfilled_placeholders(filled):
                candidates.append(filled)

    # それでもなければフォールバック
    if not candidates:
        if artist:
            candidates = [f"{artist} 衝撃の{event}"]
        else:
            candidates = ["衝撃の新情報"]

    # ランダム選択（再現性のためseed使用可）
    chosen = random.choice(candidates)
    return format_output(chosen)


def main():
    parser = argparse.ArgumentParser(description="サムネイル文言テンプレート選択")
    parser.add_argument("title", help="記事タイトル")
    parser.add_argument("--genre", default=None, help="ジャンル (breaking, comeback, etc.)")
    args = parser.parse_args()

    result = select_thumbnail_text(args.title, args.genre)
    print(result)


if __name__ == "__main__":
    main()
