#!/usr/bin/env python3
"""サムネ2段fallback: ソース画像(引用) → DALL-E 3"""
import os, json, re, urllib.request
from urllib.parse import urlparse


def smart_crop(image_path, target_w=1200, target_h=675):
    """顔検出ベースのスマートクロップ (16:9)"""
    try:
        import cv2
        import numpy as np
        img = cv2.imread(image_path)
        if img is None:
            return False
        h, w = img.shape[:2]
        target_ratio = target_w / target_h

        # 既に近いサイズなら リサイズのみ
        if abs(w / h - target_ratio) < 0.1 and w >= target_w:
            resized = cv2.resize(img, (target_w, target_h))
            cv2.imwrite(image_path, resized, [cv2.IMWRITE_JPEG_QUALITY, 92])
            return True

        # 顔検出
        try:
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(40, 40))
        except Exception:
            faces = []

        if len(faces) > 0:
            fy = int(np.mean([f[1] + f[3] / 2 for f in faces]))
            fx = int(np.mean([f[0] + f[2] / 2 for f in faces]))
        else:
            fx, fy = w // 2, h // 3

        if w / h > target_ratio:
            new_w = int(h * target_ratio)
            left = max(0, min(w - new_w, fx - new_w // 2))
            cropped = img[0:h, left:left + new_w]
        else:
            new_h = int(w / target_ratio)
            top = max(0, min(h - new_h, fy - int(new_h * 0.35)))
            cropped = img[top:top + new_h, 0:w]

        resized = cv2.resize(cropped, (target_w, target_h))
        cv2.imwrite(image_path, resized, [cv2.IMWRITE_JPEG_QUALITY, 92])
        return True
    except Exception as e:
        print(f"  smart_crop error: {e}")
        return False


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
            smart_crop(output_path)
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
