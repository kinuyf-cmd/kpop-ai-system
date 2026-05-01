#!/usr/bin/env python3
"""画像URLをWPメディアライブラリに保存 (Fモード)"""
import os
import re
import json
import hashlib
import urllib.request
import base64

try:
    from dotenv import load_dotenv
    load_dotenv('/home/aiuser/kpop-ai-system/.env')
except Exception:
    pass

WP = "https://www.kpopjournal.tokyo"
WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()


def download_and_upload_to_wp(image_url, article_title=''):
    """画像をDLしてWPに保存、media_idとnew_urlを返す"""
    try:
        req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=20)
        img_bytes = resp.read()
        content_type = resp.headers.get('Content-Type', '')

        if len(img_bytes) < 1000 or len(img_bytes) > 10_000_000:
            return None

        # 拡張子判定
        ext = 'jpg'
        if '.png' in image_url.lower() or 'png' in content_type:
            ext = 'png'
        elif '.webp' in image_url.lower() or 'webp' in content_type:
            ext = 'webp'
        elif '.gif' in image_url.lower() or 'gif' in content_type:
            ext = 'gif'

        mime = f'image/{ext}' if ext != 'jpg' else 'image/jpeg'

        # ASCII-safeファイル名
        hash_ = hashlib.md5(image_url.encode()).hexdigest()[:8]
        safe_title = re.sub(r'[^a-zA-Z0-9_-]', '', re.sub(r'[^\x00-\x7F]', '', article_title[:30]))
        if not safe_title:
            safe_title = 'buzzlab'
        filename = f'buzzlab_{safe_title}_{hash_}.{ext}'

        req2 = urllib.request.Request(
            f"{WP}/wp-json/wp/v2/media",
            data=img_bytes, method='POST',
            headers={
                'Authorization': f'Basic {AUTH}',
                'Content-Type': mime,
                'Content-Disposition': f'attachment; filename="{filename}"',
            })
        r = json.loads(urllib.request.urlopen(req2, timeout=60).read())
        return {'media_id': r.get('id'), 'new_url': r.get('source_url')}
    except Exception as e:
        print(f"  image upload err: {e}")
        return None


def replace_external_images_in_html(body_html, domain_pattern, article_title=''):
    """body_html内の外部画像URLをすべてWP保存URLに置換 (Fモード)"""
    img_urls = re.findall(rf'src="(https?://[^"]*{domain_pattern}[^"]+)"', body_html)
    url_map = {}
    for u in set(img_urls):
        result = download_and_upload_to_wp(u, article_title)
        if result and result.get('new_url'):
            url_map[u] = result['new_url']
    new_html = body_html
    for old, new in url_map.items():
        new_html = new_html.replace(old, new)
    return new_html, list(url_map.values())
