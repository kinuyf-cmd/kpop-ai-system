#!/usr/bin/env python3
"""記事タイトル+本文から収益化ジャンルを自動判定"""
import json, re

CONFIG_PATH = '/home/aiuser/kpop-ai-system/config/affiliate/cta_genre_map.json'


def load_genre_map():
    with open(CONFIG_PATH, encoding='utf-8') as f:
        return json.load(f)


def classify_article(title, content):
    """記事のジャンル判定 (複数該当時はスコア最高)"""
    text = f"{title} {content}"
    plain_text = re.sub(r'<[^>]+>', '', text)

    genre_map = load_genre_map()
    scores = {}

    for genre, rule in genre_map['genre_rules'].items():
        score = 0
        for kw in rule.get('keywords', []):
            if kw.lower() in plain_text.lower():
                score += plain_text.lower().count(kw.lower())
        if score > 0:
            scores[genre] = score

    if not scores:
        return 'general_news'

    return max(scores, key=scores.get)


def get_cta_programs_for_article(title, content):
    """記事に挿入すべきCTA案件リストを返す"""
    genre = classify_article(title, content)
    genre_map = load_genre_map()
    rule = genre_map['genre_rules'].get(genre, genre_map['genre_rules']['general_news'])

    excluded = set()
    plain_text = re.sub(r'<[^>]+>', '', f"{title} {content}").lower()

    # 重大ニュース時はCTAゼロ
    serious_kws = genre_map.get('exclusion_rules', {}).get('if_genre_is_serious_news', {}).get('keywords', [])
    if any(kw in plain_text for kw in serious_kws):
        return {'genre': genre, 'programs': [], 'cta_max': 0, 'reason': 'serious_news'}

    programs = [p for p in rule['cta_programs'] if p not in excluded]
    return {
        'genre': genre,
        'programs': programs[:rule.get('cta_max', 3)],
        'cta_max': rule.get('cta_max', 3),
    }


if __name__ == '__main__':
    test_cases = [
        ("BTS Vの新曲MVが公開！カムバックの全貌", "BTSのVが新曲をリリース。MVは...", 'comeback'),
        ("BLACKPINKジェニーの最新私服コーデ", "ジェニーがインスタで公開した私服コーデは...", 'fashion'),
        ("ソウル聖地巡礼3日間モデルコース", "推しの聖地を巡る韓国旅行のモデルコースを...", 'travel_korea'),
        ("ニュージーンズ風メイク完全ガイド", "ニュージーンズのメンバーのメイクをコピーする方法...", 'makeup'),
        ("セブチ K-POP速報 新規メンバー", "SEVENTEENが新メンバーを発表...", 'general_news'),
    ]
    for title, content, expected in test_cases:
        result = get_cta_programs_for_article(title, content)
        match = "OK" if result['genre'] == expected else "NG"
        print(f"{match} '{title[:30]}': {result['genre']} (期待: {expected})")
        print(f"   CTA: {result['programs']}")
