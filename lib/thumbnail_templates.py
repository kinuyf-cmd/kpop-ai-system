#!/usr/bin/env python3
"""
サムネイル文言テンプレート選択システム v4

10パターン戦略対応。各行最大10文字。
感情を動かすコピーのみ。説明・抽象禁止。
"""

import argparse
import random
import re
import sys

# ── 10パターン × テンプレート ──
# ルール: 抽象禁止、強ワード or 数字必須、感情を動かす
TEMPLATES = {
    # ① 速報・衝撃
    "breaking": [
        "{artist}\n衝撃の展開",
        "{artist}\nまさかの{event}",
        "ついに判明\n{artist}の真相",
        "{artist}\n電撃{event}",
        "ファン騒然\n{artist}に何が",
    ],
    # ② カムバック
    "comeback": [
        "{artist}\nついに復活",
        "{artist}\n完全復帰",
        "{artist}\n新章始動",
        "待望の帰還\n{artist}",
        "{artist}\n{number}ぶり復活",
    ],
    # ③ 比較・ランキング
    "ranking": [
        "{artist}\n{number}冠の衝撃",
        "結論出た\n{artist}が最強",
        "{artist}\n記録更新の衝撃",
        "歴代最高\n{artist}",
    ],
    # ④ 裏側・暴露
    "expose": [
        "{artist}\n衝撃の真相",
        "裏側が判明\n{artist}",
        "{artist}\n闇が深すぎた",
        "ファン絶句\n真実はこれ",
        "{artist}\n暴露の全貌",
    ],
    # ⑤ 推し活・感情
    "oshikatsu": [
        "{artist}\n尊すぎた",
        "神すぎる\n{artist}",
        "{artist}\n沼が深すぎ",
        "推せる理由\n{artist}",
    ],
    # ⑥ 美容・ファッション
    "beauty": [
        "{artist}\n神肌の秘密",
        "真似したい\n{artist}メイク",
        "即完売コスメ\n{number}選",
        "{artist}\n美の秘密判明",
    ],
    # ⑦ ライブ・イベント
    "live": [
        "{artist}\n来日決定",
        "{artist}\n日本上陸",
        "争奪戦開始\n{artist}",
        "{artist}\n{number}公演決定",
        "神セトリ判明\n{artist}",
    ],
    # ⑧ 解説・分析
    "analysis": [
        "結論出た\n{artist}の実力",
        "{artist}\n完全解説",
        "なぜ{artist}は\n神なのか",
        "{artist}\n戦略が凄すぎ",
    ],
    # ⑨ 初心者向け
    "beginner": [
        "5分でわかる\n{artist}",
        "{artist}\n入門完全版",
        "無料で推せる\n{artist}",
        "これだけでOK\n{artist}入門",
    ],
    # ⑩ バズ狙い
    "buzz": [
        "{artist}\nレベチすぎた",
        "バグってる\n{artist}",
        "{artist}\nやばすぎ",
        "話題沸騰\n{artist}",
    ],
    # デフォルト（フォールバック）
    "default": [
        "{artist}\n衝撃の展開",
        "衝撃の新情報\n判明した",
        "ファン必見\n速報",
    ],
}

# アーティスト名リスト
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
    ("T.O.P", ["t.o.p", "top", "トップ"]),
    ("BLACKPINK", ["blackpink", "ブルピン"]),
    ("JENNIE", ["jennie", "ジェニー"]),
    ("JISOO", ["jisoo", "ジス"]),
    ("ROSE", ["rosé", "rose", "ロゼ"]),
    ("LISA", ["lisa", "リサ"]),
    ("aespa", ["aespa", "エスパ"]),
    ("KARINA", ["karina", "カリナ"]),
    ("WINTER", ["winter", "ウィンター"]),
    ("BABYMONSTER", ["babymonster", "ベビモン"]),
    ("ILLIT", ["illit", "アイリット"]),
    ("IVE", ["ive", "アイヴ"]),
    ("ウォニョン", ["wonyoung", "ウォニョン"]),
    ("LE SSERAFIM", ["le sserafim", "ルセラフィム"]),
    ("SAKURA", ["sakura", "サクラ", "宮脇咲良"]),
    ("SEVENTEEN", ["seventeen", "svt", "セブチ"]),
    ("TWICE", ["twice", "トゥワイス"]),
    ("SANA", ["sana", "サナ"]),
    ("Stray Kids", ["stray kids", "skz", "スキズ"]),
    ("NewJeans", ["newjeans", "ニュジ"]),
    ("MINJI", ["minji", "ミンジ"]),
    ("HANNI", ["hanni", "ハニ"]),
    ("RIIZE", ["riize", "ライズ"]),
    ("NCT", ["nct"]),
    ("Mark Lee", ["mark lee", "マーク"]),
    ("XG", ["xg"]),
    ("EXO", ["exo"]),
    ("ITZY", ["itzy", "イッチ"]),
    ("ENHYPEN", ["enhypen", "エナプ"]),
    ("TXT", ["txt", "tomorrow x together"]),
    ("ATEEZ", ["ateez", "アチズ"]),
    ("TREASURE", ["treasure", "トレジャー"]),
    ("NMIXX", ["nmixx"]),
    ("(G)I-DLE", ["gi-dle", "gidle", "アイドゥル"]),
    ("Red Velvet", ["red velvet", "レドベル"]),
    ("ZEROBASEONE", ["zerobaseone", "zb1"]),
    ("KISS OF LIFE", ["kiss of life", "キスオブライフ"]),
    ("PLAVE", ["plave"]),
    ("KATSEYE", ["katseye"]),
    ("BOA", ["boa", "ボア"]),
]

GENRE_KEYWORDS = {
    "ranking": ["チャート", "ランキング", "1位", "billboard", "記録", "冠",
                "比較", "vs", "どっち", "順位"],
    "comeback": ["カムバック", "カムバ", "復帰", "新アルバム", "新曲", "リリース",
                 "解禁", "配信開始", "復活", "新章", "ファッション", "着用",
                 "即完売", "コーデ", "ブランド"],
    "live": ["ライブ", "コンサート", "ツアー", "来日", "ファンミ", "チケット",
             "公演", "セトリ", "ドーム", "日本上陸", "旅行", "ソウル", "聖地巡礼"],
    "expose": ["暴露", "裏側", "真相", "告白", "闇", "炎上", "騒動",
               "脱退", "訴訟", "事件", "スキャンダル", "ゴシップ"],
    "beauty": ["美容", "コスメ", "スキンケア", "メイク", "ガラス肌", "韓国コスメ",
               "真似したい", "神肌"],
    "oshikatsu": ["推し", "尊い", "沼", "感動", "号泣", "泣ける", "鳥肌"],
    "analysis": ["考察", "分析", "なぜ", "理由", "解説", "深掘り", "結論"],
    "beginner": ["初心者", "入門", "5分で", "無料", "簡単", "ハウツー", "ガイド"],
    "buzz": ["バズ", "レベチ", "バグ", "やばい", "ヤバい", "話題"],
    "breaking": ["速報", "電撃", "緊急", "判明", "発覚", "衝撃", "まさか"],
}


def extract_artist(title: str) -> str | None:
    title_lower = title.lower()
    for display_name, keywords in KNOWN_ARTISTS:
        for kw in keywords:
            if kw.lower() in title_lower:
                return display_name
    return None


def extract_number(title: str) -> str | None:
    m = re.search(r'(\d+(?:\.\d+)?(?:万|億|冠|年|ヶ月|か月|日|曲|公演|回|位|選|連|週|ぶり))', title)
    if m:
        return m.group(1)
    m = re.search(r'(\d+)', title)
    if m:
        return m.group(1)
    return None


def extract_event(title: str) -> str:
    event_words = ["発表", "復帰", "脱退", "結婚", "入隊", "除隊", "引退",
                   "デビュー", "卒業", "契約", "移籍", "活動休止", "活動再開",
                   "コラボ", "出演", "受賞"]
    for word in event_words:
        if word in title:
            return word
    return "発表"


def detect_genre(title: str) -> str:
    title_lower = title.lower()
    scores: dict[str, int] = {}
    for g, keywords in GENRE_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in title_lower)
        if count > 0:
            scores[g] = count
    if scores:
        return max(scores, key=scores.get)
    return "default"


def fill_template(template: str, artist: str | None, number: str | None, event: str) -> str:
    result = template
    if artist:
        result = result.replace("{artist}", artist)
    if number:
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
    return bool(re.search(r'\{(artist|number|event)\}', text))


def is_semantically_valid(template: str, number: str | None) -> bool:
    TIME_UNITS = ("年", "ヶ月", "か月", "日", "週")
    if "{number}ぶり" in template:
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


def validate_line_length(text: str, max_chars: int = 10) -> str:
    """各行を最大10文字に。超えたら切り詰め。"""
    lines = text.split("\n")
    result = []
    for line in lines[:2]:
        line = line.strip()
        if len(line) > max_chars:
            line = line[:max_chars - 1] + "…"
        if line:
            result.append(line)
    return "\n".join(result)


def select_thumbnail_text(title: str, genre: str | None = None) -> str:
    artist = extract_artist(title)
    number = extract_number(title)
    event = extract_event(title)

    if genre is None or genre not in TEMPLATES:
        genre = detect_genre(title)

    templates = TEMPLATES.get(genre, TEMPLATES["default"])

    candidates = []
    for tmpl in templates:
        if not is_semantically_valid(tmpl, number):
            continue
        filled = fill_template(tmpl, artist, number, event)
        if not has_unfilled_placeholders(filled):
            candidates.append(filled)

    if not candidates:
        for tmpl in TEMPLATES["default"]:
            if not is_semantically_valid(tmpl, number):
                continue
            filled = fill_template(tmpl, artist, number, event)
            if not has_unfilled_placeholders(filled):
                candidates.append(filled)

    if not candidates:
        if artist:
            if len(artist) <= 10:
                candidates = [f"{artist}\n衝撃の展開"]
            else:
                # アーティスト名が長い場合は1行目に収める工夫
                candidates = [f"衝撃の展開\n{artist[:9]}…"]
        else:
            candidates = ["衝撃の新情報\n判明した"]

    chosen = random.choice(candidates)
    return validate_line_length(chosen)


def main():
    parser = argparse.ArgumentParser(description="サムネイル文言テンプレート選択 v4")
    parser.add_argument("title", help="記事タイトル")
    parser.add_argument("--genre", default=None, help="ジャンル")
    args = parser.parse_args()

    result = select_thumbnail_text(args.title, args.genre)
    print(result)


if __name__ == "__main__":
    main()
