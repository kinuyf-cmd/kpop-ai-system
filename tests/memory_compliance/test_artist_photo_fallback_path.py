"""
2026-05-11新ルール: og:image失敗時のartist photoへのfallback merge ロジック検証
"""
import sys
from unittest.mock import patch
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_og_failure_then_artist_via_youtube():
    """og:image失敗 → artist photo (YouTube official) へfallback"""
    from lib import thumbnail_source_resolver as tsr

    sequence = []

    def fake_og(*a, **k):
        sequence.append('og_attempt')
        return None  # 失敗

    def fake_yt(artist, prefer='viewCount'):
        sequence.append(f'yt_{artist}')
        return {'image_path': '/tmp/y.jpg', 'source': 'youtube_official', 'attribution': artist.lower()}

    with patch.object(tsr, 'resolve_source_og_image', side_effect=fake_og), \
         patch.object(tsr, 'resolve_youtube', side_effect=fake_yt), \
         patch.object(tsr, 'resolve_wikimedia', return_value=None):
        result = tsr.resolve(
            artist_name='aespa', article_type='concrete',
            source_url='https://example.com/article',
        )
    assert sequence[0] == 'og_attempt', f"og試行が最初でない: {sequence}"
    assert any('yt_' in s for s in sequence), f"artist試行されていない: {sequence}"
    assert result.get('source') == 'youtube_official'


def test_og_failure_artist_failure_then_unsplash():
    """og:image + artist 両方失敗 → Unsplash fallback"""
    from lib import thumbnail_source_resolver as tsr

    with patch.object(tsr, 'resolve_source_og_image', return_value=None), \
         patch.object(tsr, 'resolve_youtube', return_value=None), \
         patch.object(tsr, 'resolve_wikimedia', return_value=None), \
         patch.object(tsr, 'resolve_unsplash', return_value={'image_path':'/tmp/u.jpg','source':'unsplash'}):
        result = tsr.resolve(
            artist_name='UnknownArtist', article_type='concrete',
            source_url='https://example.com/article',
        )
    assert result.get('source') == 'unsplash'


def test_solo_artist_uses_solo_cache_before_group():
    """is_solo=True メンバーは soloキャッシュ → groupfallback 順"""
    from lib import thumbnail_source_resolver as tsr

    with patch.object(tsr, 'resolve_source_og_image', return_value=None), \
         patch.object(tsr, 'resolve_youtube', return_value=None), \
         patch.object(tsr, 'resolve_wikimedia', return_value=None):
        # LISA は is_solo=True で artist_profiles登録済
        # resolve_fallback_photo で solo キャッシュを試す挙動を verify
        called = []

        def fake_fb(artist):
            called.append(artist)
            if artist == 'LISA':
                return {'image_path': '/tmp/lisa.jpg', 'source': 'fallback_cache', 'attribution': 'LISA'}
            return None

        with patch.object(tsr, 'resolve_fallback_photo', side_effect=fake_fb):
            result = tsr.resolve(
                artist_name='LISA', article_type='concrete', source_url='',
            )
        # 'LISA' が group BLACKPINK より先に試行されたか
        assert 'LISA' in called, f"LISA solo cache試行されていない: {called}"
        if 'BLACKPINK' in called:
            assert called.index('LISA') < called.index('BLACKPINK'), \
                "soloより先にgroup試行 (順序逆)"
