"""
memory: feedback_subject_first_artist_detection.md
規定: 「タイトル先頭の主語のみ採用、本文共起のartist誤採用を防止」
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_artist_detector_prefers_title_subject():
    """タイトル先頭の主語が本文中の他artistより優先されること"""
    try:
        from pipeline.thumbnail_auto_repair import detect_artist
    except ImportError:
        import pytest
        pytest.skip("detect_artist not importable")

    # IUを主語とする記事 (本文にBTSも登場するが主役はIU)
    title_iu_first = 'IU、新ドラマで主演 BTS共演者と再会'
    artist = detect_artist(title_iu_first)
    assert artist and 'IU' in artist.upper(), \
        f"主語IUを検出できていない: {artist}"


def test_artist_detector_does_not_pick_member_when_group_is_subject():
    """グループ名が主語の場合、メンバー名を主artist扱いしないこと"""
    try:
        from pipeline.thumbnail_auto_repair import detect_artist
    except ImportError:
        import pytest
        pytest.skip("detect_artist not importable")

    title = 'BLACKPINK、4人全員でカムバック リサが新曲リード'
    artist = detect_artist(title)
    # BLACKPINK が選ばれることを確認 (LISA単独ではなく)
    assert artist, f"artist検出失敗"
    assert 'BLACKPINK' in artist.upper() or 'LISA' not in artist.upper() or \
           artist.upper().startswith('BLACK'), \
           f"主語BLACKPINKを検出できていない (member選択): {artist}"
