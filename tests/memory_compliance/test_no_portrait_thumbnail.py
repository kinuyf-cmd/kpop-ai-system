"""
memory: feedback_no_portrait_thumbnail.md
規定: 「height>widthの縦長画像はcompositorで即REJECT、validatorでscore=0」
"""
import sys, os, tempfile
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def _make_test_image(w, h, path):
    """ノイズ入り画像 (2026-05-14: near-monochrome guard を通過するため)"""
    from PIL import Image
    import random
    random.seed(0)
    img = Image.new('RGB', (w, h))
    px = img.load()
    for x in range(0, w, 2):
        for y in range(0, h, 2):
            px[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    img.save(path, 'JPEG', quality=85)


def test_portrait_image_rejected_by_resolve_source_og_image():
    """resolve_source_og_image は portrait画像 (h>w) を None で返すこと"""
    from lib import thumbnail_source_resolver as tsr
    from unittest.mock import patch
    from PIL import Image

    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tf:
        _make_test_image(600, 1200, tf.name)  # portrait
        portrait_path = tf.name

    # _download をmockして portrait画像を返す
    def fake_download(url, dest):
        Image.open(portrait_path).save(dest, 'JPEG')
        return True

    with patch.object(tsr, '_download', side_effect=fake_download), \
         patch('urllib.request.urlopen') as mu:
        mu.return_value.__enter__.return_value.read.return_value = (
            b'<meta property="og:image" content="https://example.com/p.jpg">'
        )
        result = tsr.resolve_source_og_image('https://example.com/article')

    os.unlink(portrait_path)
    assert result is None, f"portrait画像が拒否されていない: {result}"


def test_landscape_image_accepted():
    """landscape画像 (w>h) は採用されること"""
    from lib import thumbnail_source_resolver as tsr
    from unittest.mock import patch
    from PIL import Image

    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tf:
        _make_test_image(1200, 675, tf.name)  # 16:9 landscape
        landscape_path = tf.name

    def fake_download(url, dest):
        Image.open(landscape_path).save(dest, 'JPEG')
        return True

    with patch.object(tsr, '_download', side_effect=fake_download), \
         patch('urllib.request.urlopen') as mu:
        mu.return_value.__enter__.return_value.read.return_value = (
            b'<meta property="og:image" content="https://example.com/l.jpg">'
        )
        result = tsr.resolve_source_og_image('https://example.com/article')

    os.unlink(landscape_path)
    assert result is not None, "landscape画像が拒否された"
    assert result.get('source') == 'source_og_image'
