#!/usr/bin/env python3
"""日本の主要商業施設の K-POP関連イベント情報源 (HTMLパース)

RSS調査結果 (2026-04-27):
  - RSS持ちの施設: 0件 (全て/feed/が404またはHTML返却)
  - HTMLパース可: PARCO渋谷/心斎橋, LUMINE, NEWoMan
  - 到達不可: 銀座SIX, 表参道ヒルズ, KITTE, ハルカス, 東京駅一番街, 阪急

K-POPフィルタ後の実取得率:
  - PARCO心斎橋: TAMBURINS等の韓国ブランド出店が稀にヒット
  - その他: ほぼ0件 (PR TIMESで先にカバーされている)
"""
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

K_POP_KW = [
    'K-POP', 'KPOP', 'BTS', 'BLACKPINK', 'NewJeans', 'aespa', 'TWICE',
    'SEVENTEEN', 'Stray Kids', 'IVE', 'LE SSERAFIM', 'ENHYPEN', 'ITZY',
    'TXT', 'NCT', 'RIIZE', 'ATEEZ', 'TWS', 'Hearts2Hearts',
    '韓国', 'OLIVE YOUNG', 'BT21', 'LINE FRIENDS',
    'TAMBURINS', 'タンバリンズ', 'rom&nd', 'ロムアンド',
    'innisfree', 'イニスフリー', 'ETUDE', 'エチュード',
    'GENTLE MONSTER', 'ジェントルモンスター', 'MUSINSA', 'ムシンサ',
]

# ニュース/イベントページ一覧 (domain, url, source_name, venue_label, city)
VENUE_PAGES = [
    ('https://shibuya.parco.jp/event/', 'parco_shibuya', '渋谷PARCO', 'tokyo'),
    ('https://shinsaibashi.parco.jp/news/', 'parco_shinsaibashi', '心斎橋PARCO', 'osaka'),
    ('https://shinsaibashi.parco.jp/event/', 'parco_shinsaibashi_ev', '心斎橋PARCO', 'osaka'),
    ('https://www.lumine.ne.jp/yurakucho/news/', 'lumine_yurakucho', 'LUMINE有楽町', 'tokyo'),
    ('https://www.lumine.ne.jp/shinjuku/news/', 'lumine_shinjuku', 'LUMINE新宿', 'tokyo'),
    ('https://www.newoman.jp/shinjuku/news/', 'newoman_shinjuku', 'NEWoMan新宿', 'tokyo'),
]


def _fetch(url):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        return urllib.request.urlopen(req, timeout=10).read().decode('utf-8', errors='ignore')
    except Exception as e:
        return ''


def _is_kpop_relevant(text):
    t = text.upper()
    return any(kw.upper() in t for kw in K_POP_KW)


def _extract_base_url(page_url):
    """ページURLからベースURLを生成 (相対パス解決用)"""
    parts = page_url.split('/')
    return '/'.join(parts[:3])


def collect_japan_venues():
    """全商業施設を巡回し K-POP関連のニュース/イベントを収集"""
    all_items = []

    for page_url, source_name, venue_label, city in VENUE_PAGES:
        html = _fetch(page_url)
        if not html:
            print(f"  {source_name}: fetch失敗")
            continue

        soup = BeautifulSoup(html, 'html.parser')
        base_url = _extract_base_url(page_url)
        items = []

        for a in soup.find_all('a', href=True):
            text = a.get_text(strip=True)
            # ナビゲーションリンクを除外 (短すぎ/長すぎ、ページ内リンクなど)
            if len(text) < 15 or len(text) > 200:
                continue
            # K-POPフィルタ
            if not _is_kpop_relevant(text):
                continue
            # 汎用ナビリンク/ノイズ除外
            noise = ['ポップアップ', 'イベント・ポップアップ', 'Delivery Services',
                     'Anniversary', 'ANNIVERSARY', 'ネオン食堂']
            if any(n in text for n in noise) and not any(
                k.upper() in text.upper() for k in [
                    'BTS', 'BLACKPINK', 'NewJeans', 'aespa', 'TWICE', 'SEVENTEEN',
                    'TAMBURINS', 'OLIVE YOUNG', 'K-POP', '韓国',
                ]):
                continue

            href = a['href']
            if href.startswith('/'):
                href = base_url + href
            elif not href.startswith('http'):
                continue

            items.append({
                'title': text[:200],
                'url': href,
                'source': source_name,
                'venue': venue_label,
                'city': city,
                'collected_at': datetime.now(JST).isoformat(),
            })

        # URL重複排除
        seen = set()
        dedup = []
        for it in items:
            if it['url'] not in seen:
                seen.add(it['url'])
                dedup.append(it)

        all_items.extend(dedup)
        print(f"  {source_name}: {len(dedup)}件")

    return all_items
