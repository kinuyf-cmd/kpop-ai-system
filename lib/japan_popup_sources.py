#!/usr/bin/env python3
"""日本のポップアップ情報源コレクター
対応ソース:
  1. Fashion Press (fashion-press.net) — 日本最大のファッション/イベントメディア
  2. Walker+ (walkerplus.com) — 全国イベント情報
  3. PR TIMES — プレスリリースからK-POP/韓国ポップアップ抽出
"""
import re
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

# ポップアップ判定キーワード
POPUP_KW = ['ポップアップ', 'POP-UP', 'POPUP', 'pop-up', 'popup',
            'コラボカフェ', '期間限定ストア', '期間限定ショップ', '期間限定イベント']

# K-POP/韓国関連キーワード (ブランド含む)
KPOP_KW = [
    # グループ名
    'K-POP', 'KPOP', 'BTS', 'BLACKPINK', 'NewJeans', 'aespa', 'TWICE',
    'SEVENTEEN', 'Stray Kids', 'IVE', 'LE SSERAFIM', 'ENHYPEN', 'ITZY',
    'TXT', 'ATEEZ', '(G)I-DLE', 'NCT', 'RIIZE', 'ZEROBASEONE', 'BOYNEXTDOOR',
    'BABYMONSTER', 'Hearts2Hearts', 'ILLIT', 'EXO', 'Red Velvet', 'NMIXX',
    'fromis_9', 'Stray Kids', 'TREASURE', 'ATEEZ',
    # 韓国ブランド・コスメ
    '韓国', 'OLIVE YOUNG', 'オリーブヤング', 'innisfree', 'イニスフリー',
    'ETUDE', 'エチュード', 'MISSHA', 'ミシャ', 'CLIO', 'クリオ',
    'rom&nd', 'ロムアンド', 'LANEIGE', 'ラネージュ', 'Sulwhasoo',
    'GENTLE MONSTER', 'ジェントルモンスター', 'MUSINSA', 'ムシンサ',
    # キャラクター
    'BT21', 'LINE FRIENDS', 'カカオフレンズ', 'KAKAO',
]

# 日本の都市判定
JP_CITIES = {
    'tokyo': ['東京', '渋谷', '原宿', '表参道', '新宿', '池袋', '銀座', '六本木',
              '秋葉原', '台場', '丸の内', 'PARCO', 'LUMINE', 'ラフォーレ', '丸井',
              'マルイ', 'SHIBUYA', '有楽町', '吉祥寺', '下北沢', '代官山'],
    'osaka': ['大阪', '梅田', '心斎橋', '難波', 'なんば', '天王寺', 'ハルカス',
              'ルクア', 'グランフロント'],
    'nagoya': ['名古屋', '栄', 'パルコ名古屋'],
    'fukuoka': ['福岡', '博多', '天神', 'キャナルシティ'],
    'yokohama': ['横浜', 'みなとみらい', 'ランドマーク'],
    'sapporo': ['札幌', '大通'],
    'sendai': ['仙台'],
    'hiroshima': ['広島'],
    'kyoto': ['京都'],
    'kobe': ['神戸', '三宮'],
}


def _fetch(url):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        data = urllib.request.urlopen(req, timeout=20).read()
        return data.decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"  fetch err ({url[:50]}): {e}")
        return ''


def detect_jp_city(text):
    for city_id, kws in JP_CITIES.items():
        for kw in kws:
            if kw in text:
                return city_id
    return 'tokyo'  # 日本ソースなのでデフォルトtokyo


def is_kpop_popup(title):
    text = title.upper()
    has_popup = any(k.upper() in text for k in POPUP_KW)
    has_kpop = any(k.upper() in text for k in KPOP_KW)
    # ポップアップ + K-POP の AND、または K-POPブランド名単体でポップアップを含む
    return has_popup and has_kpop


def fetch_fashionpress():
    """Fashion Press — ポップアップ/イベント記事"""
    items = []
    import urllib.parse as _up
    # Fashion Pressの検索はキーワード一致だがタイトルではなく本文マッチのため
    # K-POPキーワードフィルタが効きにくい。複数キーワードで試行。
    search_keywords = ['K-POP ポップアップ', '韓国 ポップアップストア', 'BTS ポップアップ']
    for kw in search_keywords:
        search_url = 'https://www.fashion-press.net/news?keyword=' + _up.quote(kw)
        html = _fetch(search_url)
        if not html:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.select('a[href*="/news/"]')[:30]:
            title = a.get_text(strip=True)
            href = a.get('href', '')
            if not title or len(title) < 10:
                continue
            if href.startswith('/'):
                href = 'https://www.fashion-press.net' + href
            if not any(k in title for k in POPUP_KW + KPOP_KW):
                continue
            items.append({
                'title': title[:200],
                'url': href,
                'source': 'fashionpress',
            })
    # 重複排除
    seen = set()
    dedup = []
    for it in items:
        if it['url'] not in seen:
            seen.add(it['url'])
            dedup.append(it)
    return dedup


def fetch_walkerplus():
    """Walker+ — K-POP/韓国関連イベント"""
    items = []
    for kw in ['K-POP+ポップアップ', '韓国+ポップアップ', 'K-POP+コラボカフェ']:
        url = f'https://www.walkerplus.com/event_list/?keyword={urllib.request.quote(kw)}'
        html = _fetch(url)
        if not html:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.select('a[href*="/event/"], a[href*="/article/"]')[:20]:
            title = a.get_text(strip=True)
            href = a.get('href', '')
            if not title or len(title) < 10:
                continue
            if href.startswith('/'):
                href = 'https://www.walkerplus.com' + href
            items.append({
                'title': title[:200],
                'url': href,
                'source': 'walkerplus',
            })
    seen = set()
    dedup = []
    for it in items:
        if it['url'] not in seen:
            seen.add(it['url'])
            dedup.append(it)
    return dedup


def fetch_prtimes_search():
    """PR TIMES — K-POPポップアップのプレスリリース検索"""
    items = []
    search_queries = [
        # ポップアップ
        'K-POP ポップアップ', '韓国 ポップアップストア', 'K-POP コラボカフェ',
        'BTS ポップアップ', 'BLACKPINK ポップアップ', 'NewJeans ポップアップ',
        'aespa ポップアップ', 'TWICE ポップアップ', 'SEVENTEEN ポップアップ',
        'OLIVE YOUNG ポップアップ', '韓国コスメ ポップアップ',
        # ライブ・イベント (2026-05-01追加)
        'K-POP ライブ 日本', 'K-POP コンサート 来日', 'K-POP ファンミーティング',
        'BTS ライブ', 'BLACKPINK ツアー', 'SEVENTEEN ライブ',
        'Stray Kids ツアー', 'aespa コンサート', 'ENHYPEN ライブ',
        'IVE コンサート', 'LE SSERAFIM ライブ', 'TWICE ライブ',
        'K-POP フェス 2026', 'K-POP イベント',
    ]
    for q in search_queries:
        url = f'https://prtimes.jp/main/action.php?run=html&page=searchkey&search_word={urllib.request.quote(q)}'
        html = _fetch(url)
        if not html:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.select('a[href*="/main/html/rd/"]')[:10]:
            title = a.get_text(strip=True)
            href = a.get('href', '')
            if not title or len(title) < 10:
                continue
            if href.startswith('/'):
                href = 'https://prtimes.jp' + href
            items.append({
                'title': title[:200],
                'url': href,
                'source': 'prtimes_search',
            })
    seen = set()
    dedup = []
    for it in items:
        if it['url'] not in seen:
            seen.add(it['url'])
            dedup.append(it)
    return dedup


def collect_japan():
    """全日本ソースから収集して統合"""
    all_items = []
    for fn, name in [
        (fetch_fashionpress, 'fashionpress'),
        (fetch_walkerplus, 'walkerplus'),
        (fetch_prtimes_search, 'prtimes_search'),
    ]:
        try:
            items = fn()
            # 都市判定を付与
            for it in items:
                it['city'] = detect_jp_city(it['title'])
                it['collected_at'] = datetime.now(JST).isoformat()
            all_items.extend(items)
            print(f"  {name}: {len(items)}件")
        except Exception as e:
            print(f"  {name} err: {e}")
    return all_items
