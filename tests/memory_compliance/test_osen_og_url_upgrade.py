"""
2026-05-15: osen の og:image (300x portrait thumbnail) を本体記事の
full-resolution URL (650x357 landscape) へ変換する logic の機械検証。

発見 (5/15 監査): osen はファイルを 2 バージョン保持:
- og 用 file.osen.co.kr/article_thumb/{date}/{id}_300x.{ext} (300x portrait)
- 本体 file.osen.co.kr/article/{date}/{id}.{ext} (~650x357 landscape)

og URL を upgrade すれば osen でも editorial 品質の landscape を取得可能。
"""
import sys

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_upgrade_osen_thumb_url_to_full():
    """osen の article_thumb/{id}_300x.ext → article/{id}.ext 変換"""
    from lib.thumbnail_source_resolver import _upgrade_low_quality_og_url
    og = 'http://file.osen.co.kr/article_thumb/2026/05/14/202605142015771613_6a05b33abe6a6_300x.png'
    expected = 'http://file.osen.co.kr/article/2026/05/14/202605142015771613_6a05b33abe6a6.png'
    assert _upgrade_low_quality_og_url(og) == expected


def test_upgrade_osen_jpg_variant():
    """jpg suffix も同様に変換できること"""
    from lib.thumbnail_source_resolver import _upgrade_low_quality_og_url
    og = 'https://file.osen.co.kr/article_thumb/2026/05/13/202605131520779121_6a0421cf048fb_300x.jpg'
    expected = 'https://file.osen.co.kr/article/2026/05/13/202605131520779121_6a0421cf048fb.jpg'
    assert _upgrade_low_quality_og_url(og) == expected


def test_upgrade_non_osen_returns_none():
    """osen 以外の URL は None を返す"""
    from lib.thumbnail_source_resolver import _upgrade_low_quality_og_url
    assert _upgrade_low_quality_og_url('https://soompi.com/images/article.jpg') is None
    assert _upgrade_low_quality_og_url('https://example.com/article_thumb/x_300x.png') is None


def test_upgrade_already_full_resolution_returns_none():
    """既に article/ パス (= 変換不要) は None を返す"""
    from lib.thumbnail_source_resolver import _upgrade_low_quality_og_url
    already_full = 'http://file.osen.co.kr/article/2026/05/14/x.png'
    assert _upgrade_low_quality_og_url(already_full) is None


def test_upgrade_invalid_input():
    from lib.thumbnail_source_resolver import _upgrade_low_quality_og_url
    assert _upgrade_low_quality_og_url('') is None
    assert _upgrade_low_quality_og_url(None) is None


def test_resolver_uses_upgrade_path_in_resolve():
    """resolve_source_og_image が upgrade path を組み込んでいること"""
    import inspect
    from lib import thumbnail_source_resolver as tsr
    src = inspect.getsource(tsr.resolve_source_og_image)
    assert '_upgrade_low_quality_og_url' in src, \
        'resolve_source_og_image が upgrade を呼んでない'
    assert 'source_og_image_upgraded' in src, \
        'upgraded source ラベルが付いてない'
