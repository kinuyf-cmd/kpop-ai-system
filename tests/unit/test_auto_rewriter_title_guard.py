#!/usr/bin/env python3
"""LLMの応答文をそのまま本番タイトルにしないためのガード。

2026-08-23 事故: post 13501 のタイトルが
「元タイトルとカテゴリが空欄のため、改善対象を特定できません。元タイトルを
教えてください。」に書き換えられ、本番で公開された。
原因は (1) original_title が空のまま LLM に投げた (2) 応答を無検証で採用した。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from lib.auto_rewriter import is_valid_new_title


class TestRejectsLLMChatter:
    """LLMが「できません」と返した文をタイトルにしない。"""

    def test_rejects_actual_incident_text(self):
        t = "元タイトルとカテゴリが空欄のため、改善対象を特定できません。元タイトルを教えてください。"
        assert not is_valid_new_title(t, "『恋は飴模様』キャスト・相関図まとめ")

    def test_rejects_asking_back(self):
        assert not is_valid_new_title("元タイトルを教えてください", "何かの記事")

    def test_rejects_apology(self):
        assert not is_valid_new_title("申し訳ありませんが、情報が不足しています", "何かの記事")

    def test_rejects_meta_commentary(self):
        assert not is_valid_new_title("以下のように改善しました:", "何かの記事")


class TestRejectsStructurallyBad:
    def test_rejects_empty(self):
        assert not is_valid_new_title("", "元タイトル")

    def test_rejects_too_short(self):
        assert not is_valid_new_title("速報", "元タイトル")

    def test_rejects_too_long(self):
        assert not is_valid_new_title("あ" * 80, "元タイトル")

    def test_rejects_same_as_original(self):
        assert not is_valid_new_title("同じタイトル", "同じタイトル")

    def test_rejects_when_original_is_empty(self):
        """元タイトルが空なら、そもそも改善対象を特定できない=変更しない。"""
        assert not is_valid_new_title("なにか良さそうなタイトル", "")


class TestAcceptsGoodTitles:
    def test_accepts_normal_improvement(self):
        assert is_valid_new_title(
            "『恋は飴模様』相関図|チョン・ヘイン×ハヨンの関係を図解",
            "『恋は飴模様』キャスト・相関図・配信日まとめ")

    def test_accepts_with_numbers(self):
        assert is_valid_new_title(
            "鉄槌教師の声優10人を一覧|日本語吹き替えキャスト",
            "韓国ドラマ『鉄槌教師』は何話まで?")


class TestTitleFallbackFromDB:
    """キューに title が無い時は DB から補完する。

    事故の根本原因は item["title"] が空だったこと。ガードで止めるだけでなく、
    そもそも正しい元タイトルを渡せるようにする。
    """

    def test_fetch_title_returns_string(self, monkeypatch):
        import lib.auto_rewriter as m
        monkeypatch.setattr(m, "_db_title", lambda pid: "DBのタイトル")
        assert m.resolve_title({"post_id": 1}, 1) == "DBのタイトル"

    def test_queue_title_wins_when_present(self, monkeypatch):
        import lib.auto_rewriter as m
        monkeypatch.setattr(m, "_db_title", lambda pid: "DBのタイトル")
        assert m.resolve_title({"title": "キューのタイトル"}, 1) == "キューのタイトル"

    def test_returns_empty_when_both_missing(self, monkeypatch):
        import lib.auto_rewriter as m
        monkeypatch.setattr(m, "_db_title", lambda pid: "")
        assert m.resolve_title({}, None) == ""
