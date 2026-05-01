"""韓国K-POPニュース複数ソース統合収集 (RSS方式)

2026-04-28 改修: Naver HTML scraping → RSS方式に全面切替
- Soompi RSS: 英語K-POP記事 (最大60件/回)
- Donga RSS: 韓国語芸能ニュース (最大50件/回)
- Naver entertain: React(SDS)化済みでHTML取得不可、RSS廃止 → 除外
"""
import requests
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from html import unescape

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/120.0.0.0 Safari/537.36'
}

# K-POP関連フィルタキーワード (Donga RSSは芸能全般なのでフィルタ)
KPOP_KEYWORDS = [
    'BTS', 'BLACKPINK', 'NewJeans', 'aespa', 'TWICE', 'LE SSERAFIM', 'IVE',
    'SEVENTEEN', 'Stray Kids', 'ENHYPEN', 'TWS', 'Hearts2Hearts', 'RIIZE',
    'BABYMONSTER', 'ITZY', 'TXT', 'ILLIT', 'NMIXX', 'EXO', 'NCT', 'Red Velvet',
    'KISS OF LIFE', 'BOYNEXTDOOR', 'izna', 'P1Harmony', 'EVNNE',
    '방탄소년단', '블랙핑크', '뉴진스', '에스파', '트와이스', '아이브',
    '세븐틴', '스트레이키즈', '엔하이픈', '라이즈', '아이들',
    'K-POP', 'KPOP', 'K팝', '아이돌', '컴백', '뮤직뱅크', '인기가요',
    '엠카운트다운', 'KCON', '음원', '차트', '빌보드',
]


def _parse_rss(xml_text):
    """RSS XML → list of {title, url, pub_date, description}"""
    items = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.iter('item'):
            title_el = item.find('title')
            link_el = item.find('link')
            pub_el = item.find('pubDate')
            desc_el = item.find('description')
            if title_el is None or link_el is None:
                continue
            title = unescape(re.sub(r'<!\[CDATA\[|\]\]>', '', title_el.text or '').strip())
            items.append({
                'title': title,
                'url': (link_el.text or '').strip(),
                'pub_date': (pub_el.text or '').strip() if pub_el is not None else '',
                'description': unescape(re.sub(r'<[^>]+>', '', (desc_el.text or '')))[:200] if desc_el is not None else '',
            })
    except ET.ParseError as e:
        print(f'  RSS parse err: {e}')
    return items


def fetch_soompi_rss(limit=60):
    """Soompi RSS - 英語K-POP記事"""
    try:
        r = requests.get('https://www.soompi.com/feed', headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        items = _parse_rss(r.text)[:limit]
        for it in items:
            it['source'] = 'soompi_rss'
            it['fetched_at'] = datetime.now().isoformat()
        return items
    except Exception as e:
        print(f'soompi_rss err: {e}')
        return []


def fetch_donga_rss(limit=50, kpop_only=True):
    """Donga Sports Entertainment RSS - 韓国語芸能"""
    try:
        r = requests.get('https://rss.donga.com/entertainment.xml', headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        items = _parse_rss(r.text)[:limit]
        for it in items:
            it['source'] = 'donga_rss'
            it['fetched_at'] = datetime.now().isoformat()

        if kpop_only:
            filtered = []
            for it in items:
                text = (it['title'] + ' ' + it.get('description', '')).upper()
                if any(kw.upper() in text for kw in KPOP_KEYWORDS):
                    filtered.append(it)
            return filtered
        return items
    except Exception as e:
        print(f'donga_rss err: {e}')
        return []


def collect_all():
    """全ソース収集 (統合エントリポイント)"""
    all_items = []
    for fn, name in [
        (fetch_soompi_rss, 'soompi_rss'),
        (lambda: fetch_donga_rss(kpop_only=True), 'donga_rss'),
    ]:
        try:
            items = fn()
            all_items.extend(items)
            print(f'  {name}: {len(items)}件')
        except Exception as e:
            print(f'  {name} err: {e}')

    # 重複排除 (urlベース)
    seen = set()
    dedup = []
    for it in all_items:
        u = it.get('url', '')
        if u and u not in seen:
            dedup.append(it)
            seen.add(u)
    return dedup


# 後方互換 (pipeline/korea_official_collector.py が旧APIを呼んでいる場合)
def fetch_naver_kpop_news(limit=20):
    """非推奨: Naver HTML取得不可のため soompi_rss にフォールバック"""
    return fetch_soompi_rss(limit)


def fetch_artist_official_news(artist_keyword, limit=10):
    """非推奨: Naver検索 SDS化のため donga_rss フィルタにフォールバック"""
    items = fetch_donga_rss(limit=50, kpop_only=False)
    filtered = [it for it in items if artist_keyword.upper() in (it['title'] + ' ' + it.get('description', '')).upper()]
    return filtered[:limit]
