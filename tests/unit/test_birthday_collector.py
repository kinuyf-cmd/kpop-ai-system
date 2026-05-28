"""birthday_collector の純粋関数ロジックのテスト。"""
from lib.birthday_collector import _normalize_birthday, _clean_member_name


def test_normalize_yyyymmdd():
    assert _normalize_birthday('19940912') == '1994-09-12'


def test_normalize_iso():
    assert _normalize_birthday('1994-09-12') == '1994-09-12'


def test_normalize_invalid():
    assert _normalize_birthday('') is None
    assert _normalize_birthday('xxxx') is None
    assert _normalize_birthday('199409') is None


def test_clean_name_strips_korean_paren():
    assert _clean_member_name('JISOO (김지수)') == 'JISOO'
    assert _clean_member_name('"JIMIN (박지민)"') == 'JIMIN'


def test_clean_name_filters_noise():
    assert _clean_member_name('TAEIL ※脱退済み(本JSON除外)') == ''
    assert _clean_member_name('TBD') == ''


def test_clean_name_plain():
    assert _clean_member_name('IU') == 'IU'
