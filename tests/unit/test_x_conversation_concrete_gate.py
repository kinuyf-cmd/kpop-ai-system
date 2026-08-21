#!/usr/bin/env python3
"""会話型にも具体ゲートを効かせる(既定OFF・段階導入)。

会話型のネタ元は具体が乏しく(実測 1/24)、いきなり必須化すると投稿が止まる。
X_REQUIRE_CONCRETE=1 のときだけ有効にし、まず流入投稿側で効果を測る。
"""
import sys, pathlib, importlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))


def _validate(text, monkeypatch, flag):
    monkeypatch.setenv("X_REQUIRE_CONCRETE", flag)
    import lib.x_conversation_starter as m
    importlib.reload(m)
    return m.validate({
        "text": text, "char_count": len(text),
        "has_url": False, "hashtag_count": 0,
    })


VAGUE = "NCT127のカムバックが近いって、これって期待しかないよね…新曲どうなるのか気になるなぁ。"
CONCRETE = "ファンミは8/23に生中継されます。日本語字幕付きで見られるかが分かれ目ですね。"


def test_off_by_default_lets_vague_through(monkeypatch):
    assert _validate(VAGUE, monkeypatch, "0") == []


def test_on_rejects_vague(monkeypatch):
    issues = _validate(VAGUE, monkeypatch, "1")
    assert any("具体" in i for i in issues), issues


def test_on_allows_concrete(monkeypatch):
    assert _validate(CONCRETE, monkeypatch, "1") == []
