from lib.unified_publisher import _artist_named_in_title


def test_named():
    assert _artist_named_in_title("BIGBANG", "BIGBANG、新曲を公開")
    assert _artist_named_in_title("Stray Kids", "StrayKids、1位")
    assert _artist_named_in_title("fromis_9", "fromis9、カムバック")


def test_not_named_signal_artist():
    # 2026-11-24 post 28703: 信号=BIGBANG、記事の主役=2xFE
    assert not _artist_named_in_title("BIGBANG", "2xFEが韓国進出記念ショーケースを開催")
    assert not _artist_named_in_title("", "何か")


def test_signal_artist_supported():
    from lib.unified_publisher import _signal_artist_supported as f
    assert f("BIGBANG", "BIGBANG、新曲を公開")
    assert f("TWICE", "ジョンヨン、新作映画で軍看護将校役")      # メンバー名の題は許す
    assert not f("BIGBANG", "2xFEが韓国進出記念ショーケースを開催")
    assert not f("BTS", "イ・ジョンソク、釜山映画祭でゲリラデート秘話")
