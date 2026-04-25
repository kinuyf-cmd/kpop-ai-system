#!/usr/bin/env python3
"""popup_signals.jsonl から記事生成 → WP popup post type に投稿
   改修: 8項目構造化 + サムネOG取得 + extra_meta"""
import sys, os, json, re, urllib.request, base64
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from lib.cta_injector import inject_cta_into_content
load_dotenv()

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
SIGNALS = '/home/aiuser/kpop-ai-system/data/popup_signals.jsonl'
PROCESSED = '/home/aiuser/kpop-ai-system/data/popup_processed.jsonl'
JST = timezone(timedelta(hours=9))


def is_processed(url):
    if not os.path.exists(PROCESSED):
        return False
    with open(PROCESSED, encoding='utf-8') as f:
        for line in f:
            try:
                if json.loads(line).get('url') == url:
                    return True
            except:
                pass
    return False


def mark_processed(url, post_id, status):
    with open(PROCESSED, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'url': url, 'post_id': post_id, 'status': status,
            'ts': datetime.now(JST).isoformat()
        }, ensure_ascii=False) + '\n')


def fetch_full_content(url):
    """記事URLから全文取得"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', errors='ignore')
        for pat in [r'<article[^>]*>(.*?)</article>',
                    r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>',
                    r'<div[^>]*class="[^"]*post-content[^"]*"[^>]*>(.*?)</div>']:
            m = re.search(pat, html, re.DOTALL)
            if m:
                content = m.group(1)
                text = re.sub(r'<[^>]+>', ' ', content)
                text = re.sub(r'\s+', ' ', text).strip()
                if len(text) > 200:
                    return text[:3000]
        return None
    except Exception as e:
        print(f"  fetch err: {e}")
        return None


def extract_dates(text):
    """期間抽出"""
    patterns = [
        r'(\d{4})年(\d{1,2})月(\d{1,2})日.*?[~〜から至まで\-].*?(\d{1,2})月(\d{1,2})日',
        r'(\d{1,2})月(\d{1,2})日.*?[~〜\-].*?(\d{1,2})月(\d{1,2})日',
        r'(\d{4})/(\d{1,2})/(\d{1,2}).*?[~〜\-].*?(\d{4})/(\d{1,2})/(\d{1,2})',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            now = datetime.now(JST)
            year = now.year
            try:
                groups = m.groups()
                if len(groups) == 5:
                    sy = int(groups[0])
                    sm, sd, em, ed = map(int, groups[1:])
                    start = datetime(sy, sm, sd, tzinfo=JST)
                    end = datetime(sy, em, ed, tzinfo=JST)
                elif len(groups) == 6:
                    sy, sm, sd, ey, em, ed = map(int, groups)
                    start = datetime(sy, sm, sd, tzinfo=JST)
                    end = datetime(ey, em, ed, tzinfo=JST)
                else:
                    sm, sd, em, ed = map(int, groups[:4])
                    start = datetime(year, sm, sd, tzinfo=JST)
                    end = datetime(year, em, ed, tzinfo=JST)
                return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')
            except:
                pass
    return None, None


def determine_status(start_date, end_date):
    """開催予定/開催中/終了 判定"""
    if not start_date:
        return 'unknown'
    today = datetime.now(JST).date()
    try:
        s = datetime.strptime(start_date, '%Y-%m-%d').date()
        e = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else s
        if today < s:
            return 'upcoming'
        elif s <= today <= e:
            return 'ongoing'
        else:
            return 'ended'
    except:
        return 'unknown'


# === サムネ取得 ===

def fetch_og_image(url):
    """記事URLからOG画像取得"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8', errors='ignore')
        m = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html)
        if not m:
            m = re.search(r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:image["\']', html)
        if m:
            return m.group(1)
    except:
        pass
    return None


def upload_image_to_wp(image_url, title):
    """画像URLをDLしてWP media libraryにアップロード"""
    try:
        req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})
        img_data = urllib.request.urlopen(req, timeout=30).read()

        if len(img_data) < 1000 or len(img_data) > 5_000_000:
            return None

        ext = 'jpg'
        if '.png' in image_url.lower():
            ext = 'png'
        safe_title = re.sub(r'[^\w]', '_', title[:30])
        filename = f"popup_{safe_title}.{ext}"

        req2 = urllib.request.Request(
            "https://www.kpopjournal.tokyo/wp-json/wp/v2/media",
            data=img_data, method='POST',
            headers={
                'Authorization': f'Basic {AUTH}',
                'Content-Type': f'image/{ext}',
                'Content-Disposition': f'attachment; filename="{filename}"',
            })
        r = json.loads(urllib.request.urlopen(req2, timeout=60).read())
        return r.get('id')
    except Exception as e:
        print(f"  upload err: {e}")
        return None


def get_thumbnail(signal):
    """OG画像取得"""
    og = fetch_og_image(signal['url'])
    if og:
        media_id = upload_image_to_wp(og, signal.get('title', 'popup'))
        if media_id:
            print(f"  サムネ: OG画像 media_id={media_id}")
            return media_id
    return 0


# === 記事生成 ===

def generate_article_with_gpt(signal, full_text):
    """GPTで構造化記事生成 (8項目対応)"""
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        print("  OPENAI_API_KEY未設定")
        return None, {}

    prompt = f"""以下のポップアップ情報から、K-POPファン向けのSEO最適化記事を生成してください。

【元情報】
タイトル: {signal['title']}
本文抜粋: {(full_text[:2000] if full_text else 'なし')}
都市: {signal.get('city', '不明')}
情報源: {signal.get('source', '不明')}

【出力要件】
- HTMLで本文500-900字
- 必須h2セクション:
  <h2>イベント概要</h2> (何のポップアップか、見どころ)
  <h2>開催詳細</h2> (期間/営業時間/会場)
  <h2>特典・限定アイテム</h2> (グッズ/購入特典/フォトスポット)
  <h2>アクセス</h2> (最寄り駅/徒歩時間)
- 文末バリエーション: ~開催/~オープン/~登場/~実施
- 末尾に必ず:
  <p class="kpj-disclaimer">※情報は変更になる場合があります。最新情報は公式SNSをご確認ください。</p>

加えて、以下JSON形式で構造化メタを抽出し、本文末尾に <!--META--> ブロックで埋め込んでください:
<!--META
{{"hours": "営業時間", "address": "住所", "reservation": "予約要否", "perks": "特典概要", "sns": "SNS情報"}}
-->

【出力】HTML本文 + METAブロック (説明・前置き不要)"""

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.7,
        'max_tokens': 1800,
    }).encode()

    try:
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
            data=body, headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=90).read())
        content = r['choices'][0]['message']['content'].strip()

        # METAブロック抽出
        meta_match = re.search(r'<!--META\s*(\{.*?\})\s*-->', content, re.DOTALL)
        extra_meta = {}
        if meta_match:
            try:
                extra_meta = json.loads(meta_match.group(1))
            except:
                pass
            content = re.sub(r'<!--META.*?-->', '', content, flags=re.DOTALL).strip()

        return content, extra_meta
    except Exception as e:
        print(f"  GPT err: {e}")
        return None, {}


def post_to_wp_popup(signal, content, status, extra_meta=None, featured_media=0):
    """WP popup post type に投稿 (拡張meta対応)"""
    title = signal.get('title', '')[:60]

    meta = {
        '_popup_city': signal.get('city', ''),
        '_popup_official_url': signal.get('url', ''),
        '_popup_status': status,
    }
    if signal.get('start_date'):
        meta['_popup_start_date'] = signal['start_date']
    if signal.get('end_date'):
        meta['_popup_end_date'] = signal['end_date']

    if extra_meta:
        for key in ('hours', 'address', 'reservation', 'perks', 'sns'):
            val = extra_meta.get(key, '')
            if val:
                meta[f'_popup_{key}'] = val

    # 住所から緯度経度を自動取得
    if meta.get('_popup_address') and not meta.get('_popup_lat'):
        try:
            import urllib.parse as _up
            import time as _t
            city_prefix = {'tokyo': '東京 ', 'osaka': '大阪 ', 'nagoya': '名古屋 ',
                           'fukuoka': '福岡 ', 'seoul-gangnam': '서울 강남 ',
                           'seoul-seongsu': '서울 성수 ', 'seoul-hongdae': '서울 홍대 ',
                           'seoul-myeongdong': '서울 명동 '}.get(signal.get('city', ''), '')
            addr = city_prefix + meta['_popup_address']
            geo_url = f"https://nominatim.openstreetmap.org/search?q={_up.quote(addr)}&format=json&limit=1"
            geo_req = urllib.request.Request(geo_url, headers={'User-Agent': 'KPOPJournal-Pub/1.0'})
            geo_data = json.loads(urllib.request.urlopen(geo_req, timeout=15).read())
            if geo_data:
                meta['_popup_lat'] = str(float(geo_data[0]['lat']))
                meta['_popup_lng'] = str(float(geo_data[0]['lon']))
                print(f"  geocode: ({geo_data[0]['lat']}, {geo_data[0]['lon']})")
            _t.sleep(1.2)
        except Exception as e:
            print(f"  geocode err: {e}")

    body_data = {
        'title': title,
        'content': content,
        'status': 'publish',
        'meta': meta,
    }
    if featured_media:
        body_data['featured_media'] = featured_media

    body = json.dumps(body_data).encode()

    try:
        req = urllib.request.Request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup',
            data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return r.get('id')
    except Exception as e:
        print(f"  WP err: {e}")
        return None


def main(max_articles=10):
    if not os.path.exists(SIGNALS):
        print("popup_signals.jsonl なし")
        return

    signals = []
    with open(SIGNALS, encoding='utf-8') as f:
        for line in f:
            try:
                s = json.loads(line)
                if not is_processed(s['url']):
                    signals.append(s)
            except:
                pass

    print(f"未処理signals: {len(signals)}件")

    created = 0
    for sig in signals[:max_articles]:
        print(f"\n処理中: {sig['title'][:50]}")

        full_text = fetch_full_content(sig['url'])

        start, end = extract_dates(f"{sig['title']} {full_text or ''}")
        if start:
            sig['start_date'] = start
        if end:
            sig['end_date'] = end
        status = determine_status(start, end)

        content, extra_meta = generate_article_with_gpt(sig, full_text)
        if content:
            try:
                content = inject_cta_into_content(sig.get('title', ''), content)
            except Exception as e:
                print(f"  CTA inject err: {e}")
        if not content or len(content) < 200:
            print(f"  記事生成失敗、スキップ")
            mark_processed(sig['url'], None, 'gen_failed')
            continue

        featured_id = get_thumbnail(sig)

        post_id = post_to_wp_popup(sig, content, status,
                                   extra_meta=extra_meta, featured_media=featured_id)
        if post_id:
            print(f"  post_id={post_id} status={status} thumb={featured_id}")
            mark_processed(sig['url'], post_id, 'published')
            created += 1
        else:
            mark_processed(sig['url'], None, 'wp_failed')

    print(f"\n公開: {created}件")


if __name__ == '__main__':
    main(max_articles=10)
