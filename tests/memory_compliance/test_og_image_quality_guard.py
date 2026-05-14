"""
2026-05-14: og:image の品質ガード (low-byte placeholder + near-monochrome reject)
22606 (topstarnews 匿名「?」シルエット) / 22663 (Shrek 広告) 等の事故への根治。
"""
import os
import sys
import tempfile

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_check_low_quality_rejects_tiny_file():
    """5KB 未満の画像は reject (placeholder/アイコンの可能性大)"""
    from lib.thumbnail_source_resolver import _check_low_quality_og
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
        # PIL で書き出さず empty に近い 1KB 適当バイト列
        f.write(b'\xff\xd8\xff\xe0' + b'\x00' * 1000)
        path = f.name
    try:
        assert _check_low_quality_og(path) is True
    finally:
        try: os.unlink(path)
        except Exception: pass


def test_check_low_quality_rejects_near_monochrome():
    """画像中央 80% が単色に近い (stddev<15) → reject"""
    from PIL import Image
    from lib.thumbnail_source_resolver import _check_low_quality_og
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
        path = f.name
    img = Image.new('RGB', (1200, 675), color=(128, 128, 128))
    img.save(path, 'JPEG', quality=85)
    try:
        # 5KB 以上だが完全単色なので near-monochrome として reject
        assert os.path.getsize(path) >= 5120
        assert _check_low_quality_og(path) is True
    finally:
        try: os.unlink(path)
        except Exception: pass


def test_check_low_quality_passes_real_photo_like():
    """ノイズある (= 実写相当の) 画像は pass"""
    from PIL import Image
    import random
    from lib.thumbnail_source_resolver import _check_low_quality_og
    random.seed(42)
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
        path = f.name
    img = Image.new('RGB', (1200, 675))
    pixels = img.load()
    for x in range(0, 1200, 4):
        for y in range(0, 675, 4):
            pixels[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    # 残り穴埋めを Gaussian-ish に
    img = img.resize((1200, 675))
    img.save(path, 'JPEG', quality=85)
    try:
        assert os.path.getsize(path) >= 5120
        assert _check_low_quality_og(path) is False, \
            'ノイズある実写相当画像が誤って reject された'
    finally:
        try: os.unlink(path)
        except Exception: pass


def test_resolve_source_og_image_chains_quality_guard():
    """resolve_source_og_image が _check_low_quality_og を呼ぶこと"""
    import inspect
    from lib import thumbnail_source_resolver as tsr
    src = inspect.getsource(tsr.resolve_source_og_image)
    assert '_check_low_quality_og' in src, \
        'resolve_source_og_image が _check_low_quality_og を呼んでない'


def test_thumbnail_resolver_passes_post_id():
    """thumbnail_resolver.resolve_thumbnail が _tsr_resolve に post_id を渡す"""
    src = open('/home/aiuser/kpop-ai-system/lib/thumbnail_resolver.py',
               encoding='utf-8').read()
    # _tsr_resolve(... post_id=...) パターンの存在
    assert 'post_id=str(post_id)' in src or 'post_id=post_id' in src, \
        'thumbnail_resolver が _tsr_resolve に post_id を渡してない'
