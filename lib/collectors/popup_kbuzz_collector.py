#!/usr/bin/env python3
"""kbuzzlab.com からポップアップ情報を取得"""
import sys, os, json, re, urllib.request
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta

BASE = "https://kbuzzlab.com"
OUTPUT = '/home/aiuser/kpop-ai-system/data/popup_signals.jsonl'


def fetch(url):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 KPOPJournal-Collector/1.0'
        })
        return urllib.request.urlopen(req, timeout=20).read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"  fetch err: {e}")
        return ''


def detect_city_from_text(text):
    """都市判定"""
    kws = {
        'tokyo': ['東京', '渋谷', '原宿', '表参道', '新宿', '銀座', '六本木', '池袋'],
        'osaka': ['大阪', '梅田', '心斎橋', '難波'],
        'nagoya': ['名古屋', '栄'],
        'fukuoka': ['福岡', '博多', '天神'],
        'seoul-gangnam': ['江南', '新沙', '狎鴎亭', '蚕室', 'GANGNAM'],
        'seoul-seongsu': ['聖水', 'SEONGSU'],
        'seoul-hongdae': ['弘大', '新村', '合井', 'HONGDAE'],
        'seoul-myeongdong': ['明洞', '東大門', '龍山', '汝矣島', 'MYEONGDONG'],
    }
    for city_id, words in kws.items():
        for w in words:
            if w in text:
                return city_id
    return None


def parse_listing(html):
    """記事リスティングからURL+タイトル抽出"""
    items = []
    patterns = [
        r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
        r'<article[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
    ]
    for pat in patterns:
        for m in re.finditer(pat, html, re.DOTALL):
            if len(items) >= 30:
                break
            url = m.group(1)
            title = re.sub(r'\s+', ' ', m.group(2)).strip()
            if url.startswith('/'):
                url = BASE + url
            if 'kbuzzlab.com' not in url:
                continue
            items.append({'url': url, 'title': title[:200]})
    return items


def main():
    print("=== kbuzzlab.com 巡回 ===")
    html = fetch(BASE)
    if not html:
        print("トップページ取得失敗")
        return

    items = parse_listing(html)
    print(f"トップページ抽出: {len(items)}件")

    for path in ['/popup/', '/category/popup/', '/event/']:
        cat_html = fetch(BASE + path)
        if cat_html:
            items.extend(parse_listing(cat_html))

    # 重複排除
    seen = set()
    uniq = []
    for it in items:
        if it['url'] not in seen:
            seen.add(it['url'])
            uniq.append(it)

    for item in uniq:
        item['city'] = detect_city_from_text(item['title'])
        item['source'] = 'kbuzzlab'
        item['collected_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()

    with_city = [i for i in uniq if i['city']]

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, 'a', encoding='utf-8') as f:
        for item in with_city:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')

    print(f"kbuzzlab: {len(uniq)}件中、都市判定{len(with_city)}件保存")


if __name__ == '__main__':
    main()
