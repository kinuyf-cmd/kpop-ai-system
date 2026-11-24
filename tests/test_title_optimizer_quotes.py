from lib.title_optimizer import _strip_wrapping_quotes, _balance_brackets


def test_keeps_closing_bracket_of_inner_quote():
    t = 'BoA、日本で連日ステージ出撃「楽しい」'
    assert _strip_wrapping_quotes(t) == t


def test_strips_wrapping_pair():
    assert _strip_wrapping_quotes('「BTS、新曲を公開」') == 'BTS、新曲を公開'


def test_does_not_strip_when_inner_has_same_bracket():
    t = '「A」と「B」'
    assert _strip_wrapping_quotes(t) == t


def test_balance_brackets_closes_open():
    assert _balance_brackets('G-DRAGON「代父') == 'G-DRAGON「代父」'
