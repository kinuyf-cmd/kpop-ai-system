#!/usr/bin/env python3
"""需要の大きい記事へ内部リンクを寄せる。

2026-08-23 実測: 鉄槌教師クラスタの需要は
  声優/吹替 10,962imp(70%) / 相関図 3,762imp(24%) / 完全ガイド ほぼ0
なのに被リンクは 声優3本 < 完全ガイド6本 と逆転していた。
サイト内の評価が、最大需要の記事に集まっていない。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from lib.internal_link_boost import add_link_sentence, already_links_to

HTML = ('<p>Netflixの韓国ドラマをもっと楽しみたい方は、あわせて'
        '<a href="https://www.kpopjournal.tokyo/tettsui-kyoshi-netflix-guide/">'
        '韓国ドラマ『鉄槌教師』完全ガイド</a>もチェックしてみてください。</p>')


class TestAlreadyLinks:
    def test_detects_existing_link(self):
        assert already_links_to(HTML, "tettsui-kyoshi-netflix-guide")

    def test_absent_link_is_false(self):
        assert not already_links_to(HTML, "tettsui-kyoshi-dub-episodes")


class TestAddLinkSentence:
    def test_appends_sentence_with_link(self):
        out = add_link_sentence(HTML, "tettsui-kyoshi-dub-episodes",
                                "『鉄槌教師』吹き替え声優一覧",
                                "日本語吹き替えで見るなら")
        assert "tettsui-kyoshi-dub-episodes" in out
        assert "日本語吹き替えで見るなら" in out

    def test_does_not_duplicate(self):
        once = add_link_sentence(HTML, "tettsui-kyoshi-dub-episodes", "A", "B")
        twice = add_link_sentence(once, "tettsui-kyoshi-dub-episodes", "A", "B")
        assert once == twice

    def test_preserves_original_content(self):
        out = add_link_sentence(HTML, "x-slug", "タイトル", "文脈")
        assert "完全ガイド" in out and "tettsui-kyoshi-netflix-guide" in out

    def test_returns_valid_html_paragraph(self):
        out = add_link_sentence(HTML, "x-slug", "タイトル", "文脈")
        assert out.count("<p") == out.count("</p>")

    def test_empty_html_is_safe(self):
        out = add_link_sentence("", "x", "y", "z")
        assert "x" in out
