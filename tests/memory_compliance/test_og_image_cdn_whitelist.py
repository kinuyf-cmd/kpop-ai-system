"""2026-05-11 og:image cross-domain 誤reject 事故の再発防止テスト

事故内容: 5/11 監査で 12時間以内 publish 20件中 4件 (21554/21360/21368/21541) が、
source 記事に og:image が利用可能だったにも関わらず artist_youtube/wikimedia/dalle3 に
fallback していた。memory feedback_artist_photo_absolute_rule の og:image>artist>DALL-E
鉄則違反。

真因: lib/thumbnail_resolver._is_suspicious_og_image() の cross-domain check が
画像 CDN ホスティング (kstyle.com→cdn.livedoor.jp, naver→pstatic.net, soompi→cdn.soompi.io 等)
を「他ドメイン参照」とみなして reject していた。

修正: 信頼できる image CDN を whitelist (_KNOWN_IMAGE_CDN_PATTERNS) に登録。
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_kstyle_cdn_image_allowed():
    """kstyle.com → cdn.livedoor.jp の正当な CDN 配置を reject しない"""
    from lib.thumbnail_resolver import _is_suspicious_og_image
    is_susp, reason = _is_suspicious_og_image(
        'https://cdn.livedoor.jp/kstyle/abc123.jpg',
        'https://www.kstyle.com/article.ksn?articleNo=2278986',
    )
    assert not is_susp, f'kstyle CDN og:image が reject された: {reason}'


def test_naver_cdn_image_allowed():
    """naver entertainment → pstatic.net の CDN を許可"""
    from lib.thumbnail_resolver import _is_suspicious_og_image
    is_susp, reason = _is_suspicious_og_image(
        'https://pstatic.net/news/abc.jpg',
        'https://m.entertain.naver.com/news/article/1',
    )
    assert not is_susp, f'naver pstatic CDN reject: {reason}'


def test_soompi_cdn_image_allowed():
    """soompi.com → cdn.soompi.io / wp.com CDN を許可"""
    from lib.thumbnail_resolver import _is_suspicious_og_image
    for og in ['https://cdn.soompi.io/x.jpg', 'https://i0.wp.com/soompi.com/x.jpg']:
        is_susp, reason = _is_suspicious_og_image(og, 'https://www.soompi.com/article/1')
        assert not is_susp, f'soompi CDN reject ({og}): {reason}'


def test_ad_network_still_blocked():
    """広告ネットワーク由来は引き続き reject される (regression防止)"""
    from lib.thumbnail_resolver import _is_suspicious_og_image
    is_susp, reason = _is_suspicious_og_image(
        'https://doubleclick.net/banner.jpg',
        'https://www.kstyle.com/article/1',
    )
    assert is_susp, '広告ネットワークが許可された'
    assert 'host blacklist' in reason


def test_unknown_cross_domain_still_blocked():
    """未知ドメインへの cross-domain は引き続き reject (safety net)"""
    from lib.thumbnail_resolver import _is_suspicious_og_image
    is_susp, reason = _is_suspicious_og_image(
        'https://random-evil.com/img.jpg',
        'https://www.kstyle.com/article/1',
    )
    assert is_susp, 'unknown cross-domain が許可された (potential security risk)'
    assert 'cross-domain' in reason


def test_known_cdn_patterns_listed():
    """主要 K-POPメディア CDN が whitelist に含まれていること"""
    from lib.thumbnail_resolver import _KNOWN_IMAGE_CDN_PATTERNS
    required = ['cdn.livedoor.jp', 'pstatic.net', 'cdn.soompi.io', 'wp.com',
                'pimg.allkpop.com', 'akamaihd.net']
    missing = [p for p in required if p not in _KNOWN_IMAGE_CDN_PATTERNS]
    assert not missing, f'whitelist 漏れ: {missing}'
