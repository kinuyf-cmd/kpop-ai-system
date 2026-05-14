"""
2026-05-15: resolve_wikimedia が artist_master.json 未登録の名前で
Wikimedia API を叩かずに None を返すことの機械検証。

事故: artist_master 未登録の "See Ya" / "Aiki" 等で resolve_wikimedia が
F-16 戦闘機画像 (See ya later phrase でマッチ) を返した。下流の resolve()
が「artist photo 取得成功」と誤判断、22809 Hyolyn / 23224 アイキー の
サムネで誤マッチ事故発生。

対策: registry を allowlist として扱い、未登録 artist は次の fallback
(artist_cache / DALL-E) に進める。
"""
import sys

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_registered_artists_pass_guard():
    """artist_master.json に登録された名前は registry guard 通過"""
    from lib.thumbnail_source_resolver import _is_registered_artist
    # 既存登録 (BTS / BLACKPINK / aespa など)
    assert _is_registered_artist('BTS') is True
    assert _is_registered_artist('BLACKPINK') is True
    # 新規登録 (5/15 追加)
    assert _is_registered_artist('Hyolyn') is True
    assert _is_registered_artist('Aiki') is True
    assert _is_registered_artist('See Ya') is True


def test_unregistered_artists_blocked():
    """artist_master.json に無い名前は guard で False"""
    from lib.thumbnail_source_resolver import _is_registered_artist
    assert _is_registered_artist('UnknownRandomArtist') is False
    assert _is_registered_artist('XYZ_FakeArtist_123') is False
    assert _is_registered_artist('') is False
    assert _is_registered_artist(None) is False


def test_case_insensitive_match():
    """大小文字を無視してマッチ"""
    from lib.thumbnail_source_resolver import _is_registered_artist
    assert _is_registered_artist('bts') is True
    assert _is_registered_artist('BTS') is True
    assert _is_registered_artist('Bts') is True


def test_korean_name_match():
    """韓国語名でも registry hit"""
    from lib.thumbnail_source_resolver import _is_registered_artist
    assert _is_registered_artist('효린') is True       # Hyolyn
    assert _is_registered_artist('아이키') is True     # Aiki
    assert _is_registered_artist('씨야') is True       # See Ya


def test_member_name_match():
    """member 名 (BTS の RM/JIN 等) も registry hit"""
    from lib.thumbnail_source_resolver import _is_registered_artist
    assert _is_registered_artist('RM') is True
    assert _is_registered_artist('JIN') is True


def test_resolve_wikimedia_skips_unregistered():
    """resolve_wikimedia は未登録 artist で None を返す"""
    from lib.thumbnail_source_resolver import resolve_wikimedia
    result = resolve_wikimedia('CompletelyFakeArtistXYZ123')
    assert result is None


def test_resolve_wikimedia_empty_returns_none():
    from lib.thumbnail_source_resolver import resolve_wikimedia
    assert resolve_wikimedia('') is None
    assert resolve_wikimedia(None) is None
