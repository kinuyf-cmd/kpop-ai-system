"""
memory: feedback_artist_photo_absolute_rule.md
規定: 「公開時サムネ解決はソース先og:image > アーティスト写真 > DALL-Eの順」
2026-05-11違反: thumbnail_source_resolver.resolve() がartist写真を最優先にしていた
"""
import sys, os
from unittest.mock import patch, MagicMock
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_resolver_tries_og_image_before_artist_photo():
    """concrete記事で source_url がある場合、og:image取得が artist写真より先に試行されること"""
    from lib import thumbnail_source_resolver as tsr

    call_order = []

    def fake_og(source_url, post_id=''):
        call_order.append('og_image')
        return {'image_path': '/tmp/og.jpg', 'source': 'source_og_image', 'source_url': 'https://example.com/og.jpg'}

    def fake_yt(*args, **kwargs):
        call_order.append('youtube_artist')
        return {'image_path': '/tmp/yt.jpg', 'source': 'youtube_official'}

    def fake_wiki(*args, **kwargs):
        call_order.append('wikimedia_artist')
        return None

    with patch.object(tsr, 'resolve_source_og_image', side_effect=fake_og), \
         patch.object(tsr, 'resolve_youtube', side_effect=fake_yt), \
         patch.object(tsr, 'resolve_wikimedia', side_effect=fake_wiki):
        result = tsr.resolve(
            artist_name='BLACKPINK',
            article_type='concrete',
            source_url='https://www.koreaboo.com/news/sample/',
        )

    # 最初に呼ばれたのは og_image でなければならない
    assert call_order, "no resolver called"
    assert call_order[0] == 'og_image', \
        f"memory違反: 最初に呼ばれたのは {call_order[0]} (期待: og_image)"
    assert result.get('source') == 'source_og_image'


def test_resolver_falls_back_to_artist_when_og_image_fails():
    """og:image取得失敗時 (None返却) は artist写真にfallbackすること"""
    from lib import thumbnail_source_resolver as tsr

    call_order = []

    def fake_og(*args, **kwargs):
        call_order.append('og_image')
        return None  # og:image取得失敗

    def fake_yt(*args, **kwargs):
        call_order.append('youtube_artist')
        return {'image_path': '/tmp/yt.jpg', 'source': 'youtube_official', 'attribution': 'BLACKPINK'}

    with patch.object(tsr, 'resolve_source_og_image', side_effect=fake_og), \
         patch.object(tsr, 'resolve_youtube', side_effect=fake_yt), \
         patch.object(tsr, 'resolve_wikimedia', return_value=None):
        result = tsr.resolve(
            artist_name='BLACKPINK',
            article_type='concrete',
            source_url='https://www.koreaboo.com/news/sample/',
        )

    assert 'og_image' in call_order, "og_image is not tried"
    assert call_order.index('og_image') < call_order.index('youtube_artist'), \
        "og_image must be tried before artist"
    assert result.get('source') == 'youtube_official'


def test_resolver_does_not_use_dalle_when_artist_photo_available():
    """artist写真が取得できている場合、DALL-Eにfall throughしないこと"""
    from lib import thumbnail_source_resolver as tsr

    dalle_called = []

    def fake_yt(*args, **kwargs):
        return {'image_path': '/tmp/yt.jpg', 'source': 'youtube_official', 'attribution': 'aespa'}

    def fake_dalle(*args, **kwargs):
        dalle_called.append(True)
        return {'image_path': '/tmp/dalle.jpg', 'source': 'dalle'}

    with patch.object(tsr, 'resolve_source_og_image', return_value=None), \
         patch.object(tsr, 'resolve_youtube', side_effect=fake_yt), \
         patch.object(tsr, 'resolve_wikimedia', return_value=None), \
         patch.object(tsr, 'resolve_ai_prompt', side_effect=fake_dalle):
        result = tsr.resolve(
            artist_name='aespa',
            article_type='concrete',
            source_url='',
        )

    assert not dalle_called, "DALL-E was called even though artist photo is available"
    assert result.get('source') == 'youtube_official'


def test_no_source_url_falls_back_to_artist():
    """source_url が空の場合は og:image スキップして artist写真へ"""
    from lib import thumbnail_source_resolver as tsr

    call_order = []

    def fake_og(*args, **kwargs):
        call_order.append('og_image')
        return None

    def fake_yt(*args, **kwargs):
        call_order.append('youtube_artist')
        return {'image_path': '/tmp/yt.jpg', 'source': 'youtube_official', 'attribution': 'aespa'}

    with patch.object(tsr, 'resolve_source_og_image', side_effect=fake_og), \
         patch.object(tsr, 'resolve_youtube', side_effect=fake_yt), \
         patch.object(tsr, 'resolve_wikimedia', return_value=None):
        result = tsr.resolve(
            artist_name='aespa',
            article_type='concrete',
            source_url='',  # empty
        )

    # source_url が空でも artist photo は返ること
    assert result.get('source') == 'youtube_official'
