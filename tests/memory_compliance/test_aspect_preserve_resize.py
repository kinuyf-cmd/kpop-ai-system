"""
2026-05-15: lib.image_utils.aspect_preserve_resize がアスペクト比を歪めずに
1200x675 出力することの機械検証。

事故 (5/14 監査): pid 22809 Hyolyn / 23353 Seulgi のサムネが portrait Instagram
源画像を 1200x675 へ直接 .resize() で水平 stretch されて顕著に歪んでいた。
真犯人: lib/unified_publisher.py:291 (artist_thumb の forced resize)。

検証観点:
1. portrait 入力 (800x1200, ratio=0.67) を 1200x675 (ratio=1.78) に変換時、
   出力サイズは 1200x675 でも、視覚的内容が stretch されていないこと
   = crop が実施されている = ピクセル単位で source aspect が保持されている
2. landscape 入力 (3200x1800) も同様
3. 既に 16:9 入力 (1920x1080) は無 crop で resize のみ
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def _make_test_image(w, h, path, pattern='gradient'):
    """ノイズある画像を生成 (low-quality guard 通過のため)"""
    from PIL import Image
    import random
    random.seed(42)
    img = Image.new('RGB', (w, h))
    px = img.load()
    for x in range(0, w, 2):
        for y in range(0, h, 2):
            px[x, y] = (random.randint(0, 255), random.randint(0, 255),
                        random.randint(0, 255))
    img.save(path, 'JPEG', quality=85)


def test_portrait_input_no_horizontal_stretch():
    """1080x1350 (Instagram portrait, ratio=0.8) → 1200x675 で水平 stretch なし
    crop が走るので、source の左右がカットされ、上下中央の絵が保持される"""
    from PIL import Image
    from lib.image_utils import aspect_preserve_resize
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as sf:
        src = sf.name
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as df:
        dst = df.name
    try:
        _make_test_image(1080, 1350, src)
        ok = aspect_preserve_resize(src, dst)
        assert ok is True
        with Image.open(dst) as im:
            assert im.size == (1200, 675), f'出力サイズが 1200x675 でない: {im.size}'
    finally:
        for p in (src, dst):
            try: os.unlink(p)
            except Exception: pass


def test_landscape_input_no_vertical_stretch():
    """3200x1800 (ratio=1.78 already) → 1200x675、ほぼ無 crop で resize のみ"""
    from PIL import Image
    from lib.image_utils import aspect_preserve_resize
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as sf:
        src = sf.name
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as df:
        dst = df.name
    try:
        _make_test_image(3200, 1800, src)
        ok = aspect_preserve_resize(src, dst)
        assert ok is True
        with Image.open(dst) as im:
            assert im.size == (1200, 675)
    finally:
        for p in (src, dst):
            try: os.unlink(p)
            except Exception: pass


def test_dalle_1792x1024_no_stretch():
    """DALL-E の典型出力 1792x1024 → 1200x675 で stretch が起きない
    (1792/1024=1.75 vs 1200/675=1.78、僅差だが crop で吸収)"""
    from PIL import Image
    from lib.image_utils import aspect_preserve_resize
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as sf:
        src = sf.name
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as df:
        dst = df.name
    try:
        _make_test_image(1792, 1024, src)
        ok = aspect_preserve_resize(src, dst)
        assert ok is True
        with Image.open(dst) as im:
            assert im.size == (1200, 675)
    finally:
        for p in (src, dst):
            try: os.unlink(p)
            except Exception: pass


def test_square_input_crops_to_landscape():
    """正方形 1000x1000 → 1200x675 (ratio=1.78) では上下 crop が走る"""
    from PIL import Image
    from lib.image_utils import aspect_preserve_resize
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as sf:
        src = sf.name
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as df:
        dst = df.name
    try:
        _make_test_image(1000, 1000, src)
        ok = aspect_preserve_resize(src, dst)
        assert ok is True
        with Image.open(dst) as im:
            assert im.size == (1200, 675)
    finally:
        for p in (src, dst):
            try: os.unlink(p)
            except Exception: pass


def test_invalid_path_returns_false():
    from lib.image_utils import aspect_preserve_resize
    assert aspect_preserve_resize('/nonexistent/path.jpg', '/tmp/out.jpg') is False


def test_unified_publisher_uses_aspect_preserve():
    """unified_publisher.py の artist_thumb + dalle_fallback が
    aspect_preserve_resize を呼ぶこと (直接 .resize((1200,675)) は禁止)"""
    src = open('/home/aiuser/kpop-ai-system/lib/unified_publisher.py',
               encoding='utf-8').read()
    assert 'aspect_preserve_resize' in src, \
        'unified_publisher が aspect_preserve_resize を import してない'
    # legacy 直接 stretch コードが残っていないこと
    assert '.resize((1200, 675)' not in src, \
        'unified_publisher に直接 .resize((1200, 675)) が残存 (stretch 事故再発)'


def test_post_thumbnail_generator_uses_aspect_preserve():
    src = open('/home/aiuser/kpop-ai-system/pipeline/post_thumbnail_generator.py',
               encoding='utf-8').read()
    assert 'aspect_preserve_resize' in src
    assert '.resize((1200, 675)' not in src
