#!/usr/bin/env python3
"""サムネ2段fallback: ソース画像(引用) → DALL-E 3"""
import os, json, re, urllib.request
from urllib.parse import urlparse


# OG画像が動画プレーヤー/広告由来の場合に拒否するためのドメイン/パスパターン
_SUSPICIOUS_OG_HOST_PATTERNS = (
    'doubleclick.net', 'googlesyndication.com', 'googleadservices.com',
    'adsystem.', 'adservice.', 'adnxs.com', 'taboola.com', 'outbrain.com',
    'kaltura.com', 'jwplayer.com', 'jwpsrv.com', 'jwpcdn.com',
    'brightcove.net', 'brightcove.com', 'connatix.com', 'vidstat.com',
    'anyclip.com', '4dx.agkn.com', 'criteo.', 'rubiconproject.com',
)
_SUSPICIOUS_OG_PATH_PATTERNS = (
    '/ad/', '/ads/', '/advertisement', '/sponsor', '/preroll', '/midroll',
    'video-thumbnail', 'player-thumbnail',
)


def _registered_domain(host):
    """ホスト名から登録ドメイン（例: cdn.allkpop.com → allkpop.com）を抽出"""
    if not host:
        return ''
    parts = host.lower().lstrip('.').split('.')
    if len(parts) <= 2:
        return '.'.join(parts)
    # 単純な末尾2要素ヒューリスティック (co.jp/co.kr 等は最後3要素)
    if parts[-2] in ('co', 'or', 'ne', 'ac', 'go', 'com') and parts[-1] in ('jp', 'kr', 'uk', 'au'):
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:])


def _is_suspicious_og_image(og_url, source_url):
    """OG画像URLが広告/動画プレーヤー由来で記事と無関係の可能性が高いか判定

    判定基準:
      1. ホスト名が広告/動画プラットフォームのパターンに一致
      2. パスに広告/動画プレーヤーらしいキーワードを含む
      3. ソースURLと登録ドメインが異なる (CDN以外の他ドメインを参照)

    Returns (is_suspicious, reason)
    """
    try:
        og_host = (urlparse(og_url).hostname or '').lower()
        src_host = (urlparse(source_url).hostname or '').lower()
        og_path = (urlparse(og_url).path or '').lower()
    except Exception:
        return False, ''

    for pat in _SUSPICIOUS_OG_HOST_PATTERNS:
        if pat in og_host:
            return True, f'host blacklist: {pat}'
    for pat in _SUSPICIOUS_OG_PATH_PATTERNS:
        if pat in og_path:
            return True, f'path blacklist: {pat}'

    og_reg = _registered_domain(og_host)
    src_reg = _registered_domain(src_host)
    if og_reg and src_reg and og_reg != src_reg:
        return True, f'cross-domain (og={og_reg} vs src={src_reg})'
    return False, ''


def smart_crop(image_path, target_w=1200, target_h=675):
    """顔検出+保護型スマートクロップ (16:9)

    - 顔群を囲むbboxにマージン付与、全顔が入るようクロップ
    - 小画像(幅<600)はクロップせずリサイズのみ(拡大)
    - 16:9±0.05なら単純リサイズ
    """
    try:
        import cv2
        import numpy as np
        img = cv2.imread(image_path)
        if img is None:
            return False
        h, w = img.shape[:2]
        target_ratio = target_w / target_h

        # 小画像は拡大リサイズのみ (クロップすると情報量ロス)
        if w < 600:
            resized = cv2.resize(img, (target_w, target_h))
            cv2.imwrite(image_path, resized, [cv2.IMWRITE_JPEG_QUALITY, 92])
            return True

        # 16:9±0.05近似ならリサイズのみ
        if abs(w / h - target_ratio) < 0.05 and w >= target_w:
            resized = cv2.resize(img, (target_w, target_h))
            cv2.imwrite(image_path, resized, [cv2.IMWRITE_JPEG_QUALITY, 92])
            return True

        # 顔検出
        faces = []
        try:
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(30, 30))
        except Exception:
            pass

        if len(faces) > 0:
            # 全顔のbbox + マージン
            fx_min = max(0, min(f[0] for f in faces) - int(w * 0.05))
            fy_min = max(0, min(f[1] for f in faces) - int(h * 0.08))
            fx_max = min(w, max(f[0] + f[2] for f in faces) + int(w * 0.05))
            fy_max = min(h, max(f[1] + f[3] for f in faces) + int(h * 0.15))
            face_cx = (fx_min + fx_max) // 2
            face_cy = (fy_min + fy_max) // 2
        else:
            face_cx, face_cy = w // 2, int(h * 0.35)
            fx_min, fy_min, fx_max, fy_max = 0, 0, w, h

        # クロップサイズ
        if w / h > target_ratio:
            new_w = int(h * target_ratio)
            new_h = h
        else:
            new_w = w
            new_h = int(w / target_ratio)

        # 位置: 顔を上40%に配置、全顔が入るよう保護
        ideal_left = face_cx - new_w // 2
        ideal_top = face_cy - int(new_h * 0.4)

        if len(faces) > 0:
            left = max(max(0, fx_max - new_w), min(min(w - new_w, fx_min), ideal_left))
            top = max(max(0, fy_max - new_h), min(min(h - new_h, fy_min), ideal_top))
        else:
            left = max(0, min(w - new_w, ideal_left))
            top = max(0, min(h - new_h, ideal_top))

        cropped = img[top:top + new_h, left:left + new_w]
        resized = cv2.resize(cropped, (target_w, target_h))
        cv2.imwrite(image_path, resized, [cv2.IMWRITE_JPEG_QUALITY, 92])
        return True
    except Exception as e:
        print(f"  smart_crop error: {e}")
        return False


def _has_face(image_path):
    """OpenCV Haar Cascadeで顔が検出できるか判定"""
    try:
        import cv2
        img = cv2.imread(image_path)
        if img is None:
            return False
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        faces = cascade.detectMultiScale(gray, 1.1, 4, minSize=(30, 30))
        return len(faces) > 0
    except Exception:
        return False


def _normalize_url(img_url, source_url):
    """相対URL/プロトコル相対URLを絶対URLに変換"""
    if img_url.startswith('//'):
        return 'https:' + img_url
    elif img_url.startswith('/'):
        p = urlparse(source_url)
        return f"{p.scheme}://{p.netloc}{img_url}"
    return img_url


def _download_image(img_url, output_path):
    """画像をダウンロード、5KB以上なら成功"""
    try:
        img_req = urllib.request.Request(img_url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        })
        with urllib.request.urlopen(img_req, timeout=20) as resp:
            with open(output_path, 'wb') as f:
                f.write(resp.read())
        return os.path.exists(output_path) and os.path.getsize(output_path) > 5000
    except Exception:
        return False


def _validate_and_crop(output_path):
    """smart_crop適用 + 縦長チェック + 顔検出。成功ならTrue"""
    smart_crop(output_path)
    try:
        from PIL import Image as _PILimg
        _im = _PILimg.open(output_path)
        if _im.height > _im.width:
            print(f"  REJECT: 縦長画像 ({_im.width}x{_im.height})")
            os.remove(output_path)
            return False
    except Exception:
        pass
    return True


def fetch_source_image(source_url, output_path):
    """記事ソースURLから画像取得 (顔切れ検出付き)

    1. og:image を取得
    2. 顔検出 → 顔なしなら記事内の他の画像候補を順に試行
    3. 全候補で顔なしなら最初の画像(og:image)を採用
    """
    try:
        req = urllib.request.Request(source_url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        })
        html = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', errors='replace')

        # --- og:image / twitter:image 取得 ---
        og_url = None
        for pat in [
            r'<meta\s+property="og:image"\s+content="([^"]+)"',
            r'<meta\s+content="([^"]+)"\s+property="og:image"',
            r'<meta\s+property="og:image"[^>]*\s+content="([^"]+)"',
            r'<meta[^>]*\s+content="([^"]+)"[^>]*\s+property="og:image"',
            r'<meta\s+name="twitter:image"\s+content="([^"]+)"',
            r'<meta\s+name="twitter:image"[^>]*\s+content="([^"]+)"',
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                og_url = m.group(1)
                break

        # --- 記事内の画像URL候補を収集 ---
        article_imgs = []
        for m in re.finditer(r'<img[^>]+src="([^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', html, re.IGNORECASE):
            url = m.group(1)
            if not any(skip in url.lower() for skip in ['avatar', 'logo', 'icon', 'emoji', 'ad-', 'banner']):
                article_imgs.append(url)

        # og:imageが広告/動画プレーヤー由来なら拒否し、記事内画像にフォールバック
        if og_url:
            suspicious, reason = _is_suspicious_og_image(_normalize_url(og_url, source_url), source_url)
            if suspicious:
                print(f"  REJECT og:image ({reason}): {og_url[:80]}")
                og_url = None

        # og:imageがない/拒否された場合は記事内の最初の画像をフォールバック
        if not og_url:
            if not article_imgs:
                return None
            og_url = article_imgs[0]

        og_url = _normalize_url(og_url, source_url)

        # --- og:image をダウンロード & 処理 ---
        if _download_image(og_url, output_path) and _validate_and_crop(output_path):
            if _has_face(output_path):
                return {'path': output_path, 'image_url': og_url, 'source_url': source_url}
            else:
                print(f"  WARN: og:image に顔検出なし、記事内画像を試行")
                # og:imageを一旦保持 (全候補失敗時のフォールバック)
                og_backup = output_path + '.og_backup'
                os.rename(output_path, og_backup)

                # --- 記事内画像を順に試行 ---
                for candidate_url in article_imgs[:5]:
                    candidate_url = _normalize_url(candidate_url, source_url)
                    if candidate_url == og_url:
                        continue
                    if _download_image(candidate_url, output_path) and _validate_and_crop(output_path):
                        if _has_face(output_path):
                            print(f"  OK: 顔検出成功 (記事内画像: {candidate_url[:60]})")
                            if os.path.exists(og_backup):
                                os.remove(og_backup)
                            return {'path': output_path, 'image_url': candidate_url, 'source_url': source_url}
                    if os.path.exists(output_path):
                        os.remove(output_path)

                # 全候補で顔なし → og:imageを採用 (顔切れでも画像なしよりマシ)
                print(f"  WARN: 全候補で顔検出なし、og:imageを採用")
                if os.path.exists(og_backup):
                    os.rename(og_backup, output_path)
                    return {'path': output_path, 'image_url': og_url, 'source_url': source_url}
        return None
    except Exception as e:
        print(f"  source image fetch error: {e}")
    return None


def resolve_thumbnail(source_url, title, body, post_id, output_dir='/tmp'):
    """3段fallback: ソース画像 → アーティスト写真 → DALL-E 3

    鉄則: アイドル記事にはアイドルの写真。DALL-Eは写真が取得できなかった場合のみ。
    """
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

    # 段階2: アーティスト写真 (YouTube/Wikimedia/cache)
    try:
        import sys
        sys.path.insert(0, '/home/aiuser/kpop-ai-system/lib')
        from thumbnail_source_resolver import resolve as _tsr_resolve
        from article_topic_classifier import classify

        classification = classify(title, body or '')
        subjects = classification.get('subjects', [])
        artist = subjects[0] if subjects else ''

        if artist:
            print(f"  アーティスト検出: {artist} → 本人写真を優先取得")
            _tsr = _tsr_resolve(artist_name=artist, article_type='concrete')
            if _tsr and _tsr.get('image_path') and os.path.exists(_tsr['image_path']):
                print(f"  artist photo OK: {_tsr.get('source')} ({artist})")
                return {
                    'path': _tsr['image_path'],
                    'source': f"artist_{_tsr.get('source', 'unknown')}",
                    'attribution': _tsr.get('attribution', ''),
                }
    except Exception as e:
        print(f"  artist photo fallback error: {e}")

    # 段階3: DALL-E 3 (アーティスト写真も取得できなかった場合のみ)
    try:
        from dalle_thumbnail_gen import generate_thumbnail
        from make_thumbnail_v6 import _dalle_fallback
        from article_topic_classifier import classify_theme
        _tr = classify_theme(title, body or '')
        _theme_prompt = _tr.get('theme_config', {}).get('dalle_prompt', '')
        r = _dalle_fallback(title, body or '', post_id, output_dir,
                            theme_dalle_prompt=_theme_prompt)
        if r.get('verdict') == 'PASS':
            from PIL import Image
            png_path = r['output_path']
            jpg_path = png_path.rsplit('.', 1)[0] + '.jpg'
            img = Image.open(png_path).convert('RGB')
            if img.width > 1200:
                ratio = 1200 / img.width
                img = img.resize((1200, int(img.height * ratio)), Image.LANCZOS)
            img.save(jpg_path, 'JPEG', quality=82, optimize=True)
            print(f"  DALL-E OK (fallback): {jpg_path}")
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
