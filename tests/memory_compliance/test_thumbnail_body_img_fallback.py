"""
2026-05-15: thumbnail_source_resolver の body-img fallback + low-quality-og
domain heuristics の機械検証。

事故 (5/14 監査): osen 系の og:image は意図的に 300px portrait しか返さない
ため、22809 Hyolyn / 23224 アイキー等の thumbnail が品質低下していた。
"""
import sys

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_low_quality_og_domain_constants():
    """osen 等が低品質 og domain として登録されていること"""
    from lib.thumbnail_source_resolver import _LOW_QUALITY_OG_DOMAINS
    assert 'osen.co.kr' in _LOW_QUALITY_OG_DOMAINS
    assert 'topstarnews.net' in _LOW_QUALITY_OG_DOMAINS


def test_is_low_quality_og_domain_detection():
    from lib.thumbnail_source_resolver import _is_low_quality_og_domain
    assert _is_low_quality_og_domain('https://www.osen.co.kr/article/G123') is True
    assert _is_low_quality_og_domain('http://file.osen.co.kr/article/x') is True
    assert _is_low_quality_og_domain('https://soompi.com/article') is False
    assert _is_low_quality_og_domain('') is False
    assert _is_low_quality_og_domain(None) is False


def test_extract_high_res_body_img_with_width_attr():
    """width 属性 ≥600 の img が抽出されること"""
    from lib.thumbnail_source_resolver import _extract_high_res_body_img
    html = '''
    <html><body>
      <header><img src="/logo.png" width="100" height="40"></header>
      <article>
        <img src="https://example.com/article_hero.jpg" width="1200" height="800">
        <img src="https://example.com/small.jpg" width="200" height="150">
      </article>
    </body></html>
    '''
    result = _extract_high_res_body_img(html)
    assert result == 'https://example.com/article_hero.jpg'


def test_extract_high_res_body_img_skips_icons_and_logos():
    from lib.thumbnail_source_resolver import _extract_high_res_body_img
    html = '''
    <article>
      <img src="https://example.com/icon-share.png" width="1024" height="1024">
      <img src="https://example.com/logo-site.png" width="1200" height="800">
      <img src="https://example.com/ad-banner.jpg" width="1200" height="800">
    </article>
    '''
    # 全て icon/logo/ad で除外、attr 無し fallback もできない (download 不能 URL)
    result = _extract_high_res_body_img(html)
    assert result is None, '除外パターン img が誤って抽出された'


def test_extract_high_res_body_img_empty_html():
    from lib.thumbnail_source_resolver import _extract_high_res_body_img
    assert _extract_high_res_body_img('') is None
    assert _extract_high_res_body_img(None) is None


def test_extract_high_res_body_img_relative_url_resolved():
    """相対URL (/path) が base_url で絶対化されること"""
    from lib.thumbnail_source_resolver import _extract_high_res_body_img
    html = '<article><img src="/uploads/hero.jpg" width="1200" height="800"></article>'
    result = _extract_high_res_body_img(html, 'https://news.example.com/article/123')
    assert result is not None
    assert result.startswith('https://news.example.com')
    assert '/uploads/hero.jpg' in result
