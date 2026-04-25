#!/usr/bin/env python3
"""住所から緯度経度を自動取得 (OpenStreetMap Nominatim)"""
import os, json, re, urllib.request, urllib.parse, base64, time
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()

CITY_PREFIX = {
    'tokyo': '東京 ', 'osaka': '大阪 ', 'nagoya': '名古屋 ', 'fukuoka': '福岡 ',
    'seoul-gangnam': '서울 강남 ', 'seoul-seongsu': '서울 성수 ',
    'seoul-hongdae': '서울 홍대 ', 'seoul-myeongdong': '서울 명동 ',
}


def geocode(address):
    """OpenStreetMap Nominatim geocoding (1 req/sec rate limit)"""
    if not address or len(address) < 5:
        return None, None
    address = address.replace('〒', '').strip()
    url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(address)}&format=json&limit=1&accept-language=ja"
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'KPOPJournal-Geocoder/1.0 (kinu.yf@gmail.com)',
        })
        data = json.loads(urllib.request.urlopen(req, timeout=15).read())
        if data:
            return float(data[0]['lat']), float(data[0]['lon'])
    except Exception as e:
        print(f"  geocode err: {e}")
    return None, None


def main():
    url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/popup?per_page=100&_embed=true"
    req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
    try:
        popups = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        print(f"fetch err: {e}")
        return

    # 住所あり＋緯度経度なし
    targets = [p for p in popups
               if p.get('meta', {}).get('_popup_address')
               and not p.get('meta', {}).get('_popup_lat')]

    print(f"=== geocoder: 住所あり緯度経度なし {len(targets)}件 ===")

    success = 0
    for p in targets[:30]:
        pid = p['id']
        meta = p['meta']
        addr = meta.get('_popup_address', '')
        city_id = meta.get('_popup_city', '')
        prefix = CITY_PREFIX.get(city_id, '')
        full_addr = (prefix + addr) if prefix not in addr else addr

        lat, lng = geocode(full_addr)
        if lat and lng:
            body = json.dumps({'meta': {'_popup_lat': str(lat), '_popup_lng': str(lng)}}).encode()
            try:
                req2 = urllib.request.Request(
                    f"https://www.kpopjournal.tokyo/wp-json/wp/v2/popup/{pid}",
                    data=body, method='POST',
                    headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
                urllib.request.urlopen(req2, timeout=20)
                print(f"  id={pid}: ({lat:.4f}, {lng:.4f})")
                success += 1
            except Exception as e:
                print(f"  update err: {e}")
        else:
            print(f"  id={pid}: geocode失敗 '{full_addr[:40]}'")
        time.sleep(1.2)

    print(f"\n{success}/{len(targets)}件 緯度経度設定")


if __name__ == '__main__':
    main()
