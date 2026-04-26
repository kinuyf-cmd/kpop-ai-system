#!/usr/bin/env python3
"""サムネなし記事にDALL-E 3でサムネ自動生成 (毎時25分・55分、最大3件/回)"""
import os, json, urllib.request, base64, re, sys, io, time
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
OPENAI_KEY = os.getenv('OPENAI_API_KEY', '')
MAX_PER_RUN = 3


def get_posts_without_thumbnail(per_page=20, post_types=None):
    if post_types is None:
        post_types = ['posts']
    posts = []
    for endpoint in post_types:
        try:
            url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}?per_page={per_page}&_fields=id,title,featured_media,date&orderby=date&order=desc"
            req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
            data = json.loads(urllib.request.urlopen(req, timeout=20).read())
            for p in data:
                if not p.get('featured_media') or p.get('featured_media') == 0:
                    p['_endpoint'] = endpoint
                    posts.append(p)
        except Exception as e:
            print(f"取得err {endpoint}: {e}")
    return posts


def generate_and_attach(post):
    pid = post['id']
    title = post.get('title', {}).get('rendered', '') if isinstance(post.get('title'), dict) else ''
    endpoint = post.get('_endpoint', 'posts')

    if not OPENAI_KEY:
        print(f"  OPENAI_API_KEY なし")
        return False

    print(f"  id={pid} {title[:50]}")

    try:
        from PIL import Image

        prompt = f"K-POP magazine style, vibrant pastel colors, high quality photo, no text, no logos, related to: {title[:80]}"
        body = json.dumps({
            'model': 'dall-e-3', 'prompt': prompt, 'n': 1,
            'size': '1792x1024', 'quality': 'standard',
        }).encode()

        req = urllib.request.Request('https://api.openai.com/v1/images/generations',
            data=body, headers={'Authorization': f'Bearer {OPENAI_KEY}', 'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=180).read())
        img_url = r['data'][0]['url']

        img_data = urllib.request.urlopen(img_url, timeout=60).read()
        img = Image.open(io.BytesIO(img_data))
        tw, th = 1200, 675
        sw, sh = img.size
        tr = tw / th
        sr = sw / sh
        if sr > tr:
            nw = int(sh * tr)
            off = (sw - nw) // 2
            img = img.crop((off, 0, off + nw, sh))
        else:
            nh = int(sw / tr)
            off = (sh - nh) // 2
            img = img.crop((0, off, sw, off + nh))
        img = img.resize((tw, th), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=85)
        img_bytes = buf.getvalue()
    except Exception as e:
        print(f"     生成err: {e}")
        return False

    try:
        boundary = f'kpjBoundary{pid}{int(time.time())}'
        parts = [
            f'--{boundary}'.encode(),
            f'Content-Disposition: form-data; name="file"; filename="thumb_{pid}.jpg"'.encode(),
            b'Content-Type: image/jpeg', b'', img_bytes,
            f'--{boundary}--'.encode(), b'',
        ]
        upload_body = b'\r\n'.join(parts)
        req = urllib.request.Request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/media',
            data=upload_body, method='POST',
            headers={
                'Authorization': f'Basic {AUTH}',
                'Content-Type': f'multipart/form-data; boundary={boundary}',
            })
        r = json.loads(urllib.request.urlopen(req, timeout=60).read())
        media_id = r.get('id')
    except Exception as e:
        print(f"     WP media err: {e}")
        return False

    try:
        body = json.dumps({'featured_media': media_id}).encode()
        req = urllib.request.Request(
            f'https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}/{pid}',
            data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=30)
        print(f"     OK media_id={media_id}")
        return True
    except Exception as e:
        print(f"     update err: {e}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--post-type', default=None, help='posts or popup')
    parser.add_argument('--limit', type=int, default=MAX_PER_RUN)
    args = parser.parse_args()

    post_types = [args.post_type] if args.post_type else ['posts']
    limit = args.limit

    print(f"=== post_thumbnail_generator {datetime.now(timezone.utc).isoformat()} types={post_types} limit={limit} ===")
    posts = get_posts_without_thumbnail(per_page=50, post_types=post_types)
    targets = posts[:limit]

    if not targets:
        print("  対象なし")
        return

    print(f"  対象: {len(targets)}件 (全{len(posts)}件から)")
    success = 0
    for post in targets:
        if generate_and_attach(post):
            success += 1
        time.sleep(2)

    print(f"\n{success}/{len(targets)}件 サムネ生成完了")

    log = '/home/aiuser/kpop-ai-system/logs/thumbnail_generator.jsonl'
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': datetime.now(timezone.utc).isoformat(),
            'attempted': len(targets), 'success': success,
            'pending': len(posts) - success,
        }, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
