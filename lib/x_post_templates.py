#!/usr/bin/env python3
"""
X/Twitter投稿テンプレートシステム

Usage:
  python3 lib/x_post_templates.py "記事タイトル" "https://url" --genre breaking

Output: 完成したツイートテキスト（そのまま投稿可能）

テンプレート構造:
  Line 1: Hook（強い単語 + 主要事実）
  Line 2: 簡潔なコンテキスト（1文）
  Line 3: [空行]
  Line 4: URL
  Line 5: [空行]
  Line 6: #KPOP #アーティスト名（2-3ハッシュタグ）
"""
import argparse
import hashlib
import re
import sys

# --- アーティスト名抽出用パターン ---
KNOWN_ARTISTS = [
    "BTS", "BLACKPINK", "aespa", "SEVENTEEN", "Stray Kids", "NewJeans",
    "IVE", "LE SSERAFIM", "XG", "TWICE", "NCT", "ILLIT", "RIIZE",
    "BABYMONSTER", "ZEROBASEONE", "ITZY", "EXO", "BIGBANG", "MONSTA X",
    "TXT", "ENHYPEN", "ATEEZ", "TREASURE", "NMIXX", "(G)I-DLE",
    "Red Velvet", "MAMAMOO", "GOT7", "SHINee", "2NE1", "WINNER",
    "iKON", "BTOB", "ASTRO", "THE BOYZ", "ONEUS", "SF9",
    "ジミン", "テテ", "ジョングク", "RM", "SUGA", "J-HOPE", "JIN",
    "リサ", "ジェニ", "ロゼ", "ジス",
    "ウォニョン", "ユジン", "レイ", "ガウル", "リズ", "イソ",
    "ミンジ", "ハニ", "ダニエル", "ヘリン", "ヘイン",
    "カリナ", "ウィンター", "ジゼル", "ニンニン",
    "サクラ", "チェウォン", "カズハ", "ユンジン", "ホンウンチェ",
]

HOOKS = {
    "breaking": [
        "{artist}に衝撃の展開",
        "{artist}から緊急発表",
        "速報: {artist}の{event}が判明",
    ],
    "comeback": [
        "{artist}がついに復活",
        "待望の{artist}カムバック決定",
        "{artist}新曲解禁",
    ],
    "controversy": [
        "{artist}に何が起きたのか",
        "ファン騒然…{artist}の真相",
        "{artist}炎上の全貌",
    ],
    "beauty": [
        "{artist}の美肌の秘密が話題",
        "韓国コスメで{artist}肌になれる?",
        "ガラス肌の作り方が判明",
    ],
    "live": [
        "{artist}来日公演が決定",
        "{artist}ツアー情報解禁",
        "チケット争奪戦が始まる",
    ],
    "chart": [
        "{artist}が{number}冠の快挙",
        "Billboard記録更新の衝撃",
        "{artist}がチャート席巻",
    ],
    "default": [
        "{artist}の最新情報をチェック",
        "K-POPファン必見のニュース",
    ],
}

# CATEGORY_ID → genre マッピング
CATEGORY_TO_GENRE = {
    "71": "chart",
    "3": "comeback",
    "6": "comeback",
    "5": "live",
    "7": "breaking",
    "28": "chart",
    "8": "breaking",
    "27": "breaking",
    "10": "breaking",
    "15": "breaking",
    "13": "breaking",
    "12": "beauty",
    "11": "default",
    "14": "controversy",
    "9": "breaking",
    "4": "default",
    "2": "default",
}


def extract_artist(title: str) -> str:
    """タイトルからアーティスト名を抽出する"""
    for artist in KNOWN_ARTISTS:
        if artist.lower() in title.lower():
            return artist
    # 「○○の」「○○が」等のパターンで先頭名詞を抽出
    m = re.match(r'^([^のがはをにで、。!！?？\s]{2,10})[のがはをにで]', title)
    if m:
        return m.group(1)
    # フォールバック: タイトル先頭から短い単位を取る
    return title[:8].rstrip("のがはをにで、。")


def extract_event(title: str) -> str:
    """タイトルからイベント/出来事キーワードを抽出する"""
    event_words = [
        "カムバック", "復帰", "新曲", "MV", "アルバム", "ツアー", "来日",
        "コンサート", "脱退", "炎上", "熱愛", "結婚", "入隊", "除隊",
        "1位", "記録", "コラボ", "出演", "発表", "決定", "公開",
    ]
    for word in event_words:
        if word in title:
            return word
    return "動向"


def extract_number(title: str) -> str:
    """タイトルから数字情報を抽出する"""
    m = re.search(r'(\d+)', title)
    if m:
        return m.group(1)
    return "新"


def select_hook(genre: str, title: str, artist: str) -> str:
    """ジャンルに基づいてフックを選択し、プレースホルダを埋める"""
    hooks = HOOKS.get(genre, HOOKS["default"])
    # タイトルのハッシュで決定的に選択（同じタイトルなら同じテンプレート）
    idx = int(hashlib.md5(title.encode()).hexdigest(), 16) % len(hooks)
    hook = hooks[idx]

    event = extract_event(title)
    number = extract_number(title)

    hook = hook.replace("{artist}", artist)
    hook = hook.replace("{event}", event)
    hook = hook.replace("{number}", number)

    return hook


def build_context(title: str, artist: str) -> str:
    """タイトルからコンテキスト行を生成する"""
    # タイトル自体を簡潔なコンテキストとして利用（重複部分を除去）
    context = title.strip()
    # 長すぎる場合は切り詰め
    if len(context) > 60:
        context = context[:57] + "..."
    return context


def build_hashtags(artist: str, genre: str) -> str:
    """ハッシュタグを生成する（2-3個）"""
    tags = ["#KPOP"]

    # アーティスト名ハッシュタグ
    artist_tag = artist.replace(" ", "")
    if artist_tag and len(artist_tag) >= 2:
        tags.append(f"#{artist_tag}")

    # ジャンル別追加タグ
    genre_tags = {
        "breaking": "#速報",
        "comeback": "#カムバック",
        "controversy": "#韓国芸能",
        "beauty": "#韓国コスメ",
        "live": "#コンサート",
        "chart": "#チャート",
        "default": "#韓国",
    }
    extra = genre_tags.get(genre, "#韓国")
    if len(tags) < 3 and extra not in tags:
        tags.append(extra)
    # 重複除去しつつ順序を維持
    seen = set()
    tags = [t for t in tags if not (t in seen or seen.add(t))]

    return " ".join(tags)


def generate_tweet(title: str, url: str, genre: str) -> str:
    """完成したツイートテキストを生成する"""
    artist = extract_artist(title)
    hook = select_hook(genre, title, artist)
    context = build_context(title, artist)
    hashtags = build_hashtags(artist, genre)

    tweet = f"{hook}\n{context}\n\n{url}\n\n{hashtags}"
    return tweet


def main():
    parser = argparse.ArgumentParser(description="X/Twitter投稿テンプレート生成")
    parser.add_argument("title", help="記事タイトル")
    parser.add_argument("url", help="記事URL")
    parser.add_argument("--genre", default="default",
                        choices=list(HOOKS.keys()),
                        help="ジャンル (breaking/comeback/controversy/beauty/live/chart/default)")
    parser.add_argument("--category-id", default="",
                        help="CATEGORY_IDから自動でgenreを判定")
    args = parser.parse_args()

    genre = args.genre
    # category-idが指定されていればgenreを上書き
    if args.category_id:
        genre = CATEGORY_TO_GENRE.get(args.category_id, genre)

    tweet = generate_tweet(args.title, args.url, genre)
    print(tweet)


if __name__ == "__main__":
    main()
