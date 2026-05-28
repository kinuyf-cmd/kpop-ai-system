"""daily_brief_v2 の純粋関数ロジックのテスト。"""
from lib.daily_brief_v2 import _achievement, _kpi_row


def test_achievement_full():
    sym, pct = _achievement(5, 5)
    assert sym == '✅' and pct == 100


def test_achievement_over():
    sym, pct = _achievement(10, 5)
    assert sym == '✅' and pct == 200


def test_achievement_green():
    sym, pct = _achievement(7, 10)
    assert sym == '🟢' and pct == 70


def test_achievement_yellow():
    sym, pct = _achievement(5, 10)
    assert sym == '🟡' and pct == 50


def test_achievement_red():
    sym, pct = _achievement(2, 10)
    assert sym == '🔴' and pct == 20


def test_achievement_zero_target():
    sym, pct = _achievement(5, 0)
    assert sym == '—' and pct == 0


def test_kpi_row_format():
    row = _kpi_row('記事公開', 5, 5, '本')
    assert '✅' in row and '記事公開' in row and '5/5本' in row and '100%' in row
