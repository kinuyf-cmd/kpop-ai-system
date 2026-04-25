#!/usr/bin/env python3
"""PR TIMES から K-POP/韓国ブランド ポップアップ情報を収集 (RSS + カテゴリ併用)"""
import sys, os, json, re, urllib.request, urllib.parse
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET

BASE = "https://prtimes.jp"
OUTPUT = '/home/aiuser/kpop-ai-system/data/popup_signals.jsonl'

# ポップアップ判定キーワード
POPUP_KW = ['ポップアップ', 'POP-UP', 'POPUP', 'コラボカフェ', '期間限定ストア', '期間限定ショップ']
# K-POP/韓国判定キーワード
KPOP_KW = ['K-POP', 'KPOP', '韓国', 'BTS', 'BLACKPINK', 'NewJeans', 'aespa',
           'SEVENTEEN', 'TWICE', 'IVE', 'LE SSERAFIM', 'Stray Kids', 'ENHYPEN',
           'TXT', 'ATEEZ', '(G)I-DLE', 'ITZY', 'NCT', 'RIIZE', 'ZEROBASEONE']

# PR TIMES カテゴリページ (Next.js SSRでHTML含むもの)
CATEGORY_URLS = [
    f"{BASE}/entertainment/",
    f"{BASE}/fashion/",
]


def fetch_rss():
    """RSSフィードから収集"""
    items = []
    try:
        req = urllib.request.Request(f"{BASE}/index.rdf", headers={
            'User-Agent': 'Mozilla/5.0 KPOPJournal-Collector/1.0'
        })
        data = urllib.request.urlopen(req, timeout=20).read()
        root = ET.fromstring(data)
        ns = {'rss': 'http://purl.org/rss/1.0/'}
        for it in root.findall('.//rss:item', ns):
            title = (it.find('rss:title', ns).text or '').strip()
            link = (it.find('rss:link', ns).text or '').strip()
            desc = (it.find('rss:description', ns).text or '').strip() if it.find('rss:description', ns) is not None else ''
            if link:
                items.append({'url': link, 'title': title, 'desc': desc})
    except Exception as e:
        print(f"  RSS err: {e}")
    return items


def fetch_category(url):
    """カテゴリページからリンク抽出"""
    items = []
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 KPOPJournal-Collector/1.0'
        })
        html = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', errors='ignore')
        # Next.js __NEXT_DATA__ JSONから抽出
        m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                releases = data.get('props', {}).get('pageProps', {}).get('releases', [])
                for r in releases:
                    title = r.get('title', '')
                    rid = r.get('release_id', '')
                    cid = r.get('company_id', '')
                    if rid and cid:
                        link = f"{BASE}/main/html/rd/p/{cid:09d}.{rid:09d}.html"
                        items.append({'url': link, 'title': title, 'desc': ''})
            except json.JSONDecodeError:
                pass
        # フォールバック: aタグ直接抽出
        for m2 in re.finditer(r'href="(/main/html/rd/p/[^"]+\.html)"[^>]*title="([^"]*)"', html):
            items.append({'url': BASE + m2.group(1), 'title': m2.group(2).strip()[:200], 'desc': ''})
    except Exception as e:
        print(f"  category fetch err {url}: {e}")
    return items


def is_popup_and_kpop(item):
    """ポップアップかつK-POP/韓国関連か"""
    text = f"{item.get('title', '')} {item.get('desc', '')}"
    has_popup = any(k in text for k in POPUP_KW)
    has_kpop = any(k in text for k in KPOP_KW)
    return has_popup and has_kpop


def detect_city(text):
    """記事テキストから都市判定"""
    cities_kw = {
        'tokyo': ['東京', '渋谷', '原宿', '表参道', '新宿', '池袋', '銀座', '六本木'],
        'osaka': ['大阪', '梅田', '心斎橋', '難波'],
        'nagoya': ['名古屋', '栄'],
        'fukuoka': ['福岡', '博多', '天神'],
        'seoul-gangnam': ['江南', '新沙', '狎鴎亭', '蚕室', 'ガンナム'],
        'seoul-seongsu': ['聖水', 'ソンス'],
        'seoul-hongdae': ['弘大', '新村', '合井', 'ホンデ'],
        'seoul-myeongdong': ['明洞', '東大門', '龍山', '汝矣島', 'ミョンドン'],
    }
    for city_id, kws in cities_kw.items():
        for kw in kws:
            if kw in text:
                return city_id
    return None


def main():
    all_items = []

    # RSS
    rss_items = fetch_rss()
    print(f"  RSS: {len(rss_items)}件取得")
    all_items.extend(rss_items)

    # カテゴリページ
    for url in CATEGORY_URLS:
        cat_items = fetch_category(url)
        print(f"  {url}: {len(cat_items)}件")
        all_items.extend(cat_items)

    # URL重複排除
    seen = set()
    uniq = []
    for it in all_items:
        if it['url'] not in seen:
            seen.add(it['url'])
            uniq.append(it)

    # ポップアップ+K-POP関連フィルタ
    relevant = [i for i in uniq if is_popup_and_kpop(i)]

    # ポップアップだけど都市は本文から推定 (タイトルに都市なければtokyo想定)
    for item in relevant:
        item['city'] = detect_city(f"{item.get('title', '')} {item.get('desc', '')}") or 'tokyo'
        item['source'] = 'prtimes'
        item['collected_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
        item.pop('desc', None)

    # 既存signals重複チェック
    existing_urls = set()
    if os.path.exists(OUTPUT):
        with open(OUTPUT, encoding='utf-8') as f:
            for line in f:
                try:
                    existing_urls.add(json.loads(line).get('url', ''))
                except:
                    pass

    new_items = [i for i in relevant if i['url'] not in existing_urls]

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, 'a', encoding='utf-8') as f:
        for item in new_items:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')

    print(f"PR TIMES: {len(uniq)}件中 関連{len(relevant)}件、新規{len(new_items)}件保存")


if __name__ == '__main__':
    main()
