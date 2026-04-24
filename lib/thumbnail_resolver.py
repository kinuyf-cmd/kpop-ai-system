#!/usr/bin/env python3
"""サムネ2段fallback: ソース画像(引用) → DALL-E 3"""
import os, json, re, urllib.request
from urllib.parse import urlparse


def fetch_source_image(source_url, output_path):
    """記事ソースURLから og:image 取得"""
    try:
        req = urllib.request.Request(source_url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) KPOPJournal/1.0',
        })
        html = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', errors='replace')

        img_url = None
        for pat in [
            r'<meta\s+property="og:image"\s+content="([^"]+)"',
            r'<meta\s+content="([^"]+)"\s+property="og:image"',
            r'<meta\s+name="twitter:image"\s+content="([^"]+)"',
        ]:
            m = re.search(pat, html)
            if m:
                img_url = m.group(1)
                break

        if not img_url:
            m = re.search(
                r'<article[^>]*>.*?<img[^>]+src="([^"]+\.(?:jpg|jpeg|png|webp))"',
                html, re.DOTALL | re.IGNORECASE,
            )
            if m:
                img_url = m.group(1)

        if not img_url:
            return None

        if img_url.startswith('//'):
            img_url = 'https:' + img_url
        elif img_url.startswith('/'):
            p = urlparse(source_url)
            img_url = f"{p.scheme}://{p.netloc}{img_url}"

        urllib.request.urlretrieve(img_url, output_path)
        if os.path.exists(output_path) and os.path.getsize(output_path) > 5000:
            return {'path': output_path, 'image_url': img_url, 'source_url': source_url}
    except Exception as e:
        print(f"  source image fetch error: {e}")
    return None


def resolve_thumbnail(source_url, title, body, post_id, output_dir='/tmp'):
    """2段fallback: ソース画像 → DALL-E 3"""
    os.makedirs(output_dir, exist_ok=True)

    # 段階1: ソース画像
    if source_url:
        src_out = os.path.join(output_dir, f'source_img_post{post_id}.jpg')
        r = fetch_source_image(source_url, src_out)
        if r:
            print(f"  source image OK: {r['image_url'][:60]}")
            return {
                'path': src_out,
                'source': 'source_site',
                'attribution': '画像: 元記事より',
                'image_url': r['image_url'],
                'source_url': r['source_url'],
            }

    # 段階2: DALL-E 3
    try:
        import sys
        sys.path.insert(0, '/home/aiuser/kpop-ai-system/lib')
        from dalle_thumbnail_gen import generate_thumbnail
        from make_thumbnail_v6 import _dalle_fallback
        r = _dalle_fallback(title, body or '', post_id, output_dir)
        if r.get('verdict') == 'PASS':
            # Compress for WP upload
            from PIL import Image
            png_path = r['output_path']
            jpg_path = png_path.rsplit('.', 1)[0] + '.jpg'
            img = Image.open(png_path).convert('RGB')
            if img.width > 1200:
                ratio = 1200 / img.width
                img = img.resize((1200, int(img.height * ratio)), Image.LANCZOS)
            img.save(jpg_path, 'JPEG', quality=82, optimize=True)
            print(f"  DALL-E OK: {jpg_path}")
            return {'path': jpg_path, 'source': 'dalle3', 'attribution': None}
    except Exception as e:
        print(f"  DALL-E error: {e}")

    return None


if __name__ == '__main__':
    import sys
    r = resolve_thumbnail(
        source_url=sys.argv[1] if len(sys.argv) > 1 else None,
        title='test', body='', post_id=0,
    )
    print(json.dumps(r, ensure_ascii=False, indent=2) if r else 'Failed')
