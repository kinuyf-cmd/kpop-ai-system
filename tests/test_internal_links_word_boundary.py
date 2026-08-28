"""内部リンク注入のキーワード誤爆(部分文字列マッチ)を防ぐテスト。

2026-08-28: 実測で70記事/102リンクの誤リンクを検出。原因は
`re.search(re.escape("IVE"), text, re.IGNORECASE)` が単語境界を見ず、
"olive"/"live"/"drive" 等に一致していたこと。
過去にも同種事故(Gummy/MOMOLAND)があり、名前追加の対症療法で残っていた。
"""
import pytest

from lib.internal_links import _extract_keywords_from_text, _title_matches_keywords


@pytest.mark.parametrize("text", [
    "OLIVE BETTER 江南駅店ガイド",
    "TREASURE、ファンコンサート「NEW WAV : LIVE」で8都市ツアー",
    "ILLIT「Almond Chocolate」が再生数1億回突破",
    "Netflix Original Drive to Survive",
    "exclusive interview",
    "creative director",
])
def test_ive_does_not_match_inside_english_words(text):
    """IVE が olive/live/drive 等の内部に一致してはならない。"""
    assert "IVE" not in _extract_keywords_from_text(text)


@pytest.mark.parametrize("text", [
    "IVEのリセオ、可愛く清純な魅力披露",
    "IVE、ドームツアー12万7000人動員",
    "ive gaul tima absence",
    "【IVE】新曲リリース",
])
def test_ive_matches_as_a_real_word(text):
    """本物の IVE 表記には従来どおり一致する(退行防止)。"""
    assert "IVE" in _extract_keywords_from_text(text)


@pytest.mark.parametrize("name,text", [
    ("ROSE", "roses are red"),
    ("EXO", "exotic beauty"),
    ("NCT", "nctv channel"),
    ("LISA", "Lisawa store"),
])
def test_other_artist_names_no_substring_match(name, text):
    assert name not in _extract_keywords_from_text(text)


@pytest.mark.parametrize("name,text", [
    ("ROSE", "ROSE、ソロ曲を公開"),
    ("EXO", "EXO、カムバック決定"),
    ("NCT", "NCT DREAM 10周年"),
])
def test_other_artist_names_still_match_real(name, text):
    assert name in _extract_keywords_from_text(text)


def test_title_match_uses_word_boundary():
    """タイトル照合側も同じ境界規則で動くこと。"""
    assert not _title_matches_keywords("OLIVE BETTER おすすめ商品ガイド", ["IVE"])
    assert _title_matches_keywords("IVEガウル、TIMA欠席の理由", ["IVE"])
