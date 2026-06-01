"""アーティスト名正規化のテスト(2026-06-01 サムネ歩留まり改善)

サムネ resolver が Wikimedia/YouTube 検索前にハングル/カタカナ表記を
正規英語名へ正規化する。調査でサムネAI生成降格49%の主因が
「아이오아이/레드벨벳 等が未正規化のまま検索ヒットせず降格」と判明。

辞書: data/artist_aliases.json
"""
from lib.thumbnail_source_resolver import normalize_artist_name


class TestHangulNormalization:
    def test_ioi_hangul(self):
        assert normalize_artist_name("아이오아이") == "I.O.I"

    def test_red_velvet_hangul(self):
        assert normalize_artist_name("레드벨벳") == "Red Velvet"

    def test_taeyeon_hangul(self):
        assert normalize_artist_name("태연") == "TAEYEON"

    def test_treasure_hangul(self):
        assert normalize_artist_name("트레저") == "TREASURE"


class TestPassthrough:
    def test_english_name_unchanged(self):
        # 既に英語名なら変えない
        assert normalize_artist_name("BLACKPINK") == "BLACKPINK"

    def test_unknown_name_unchanged(self):
        # 辞書にない名前はそのまま返す(降格は許容、誤変換しない)
        assert normalize_artist_name("UnknownNewGroup123") == "UnknownNewGroup123"

    def test_empty_name(self):
        assert normalize_artist_name("") == ""

    def test_none_safe(self):
        # None でも例外を出さない
        assert normalize_artist_name(None) in (None, "")
