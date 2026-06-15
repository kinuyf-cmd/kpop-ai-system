"""_pre_generation_gate の単体テスト(2026-06-16)
生成前に 重複→短文 を弾く。find_duplicate_published と read_sources をモック。
"""
import pipeline.breaking_news_detector as bnd


_SIGS = [{"title": "aespa Winter 新ビジュアル", "url": "https://x.com/a"}]


def test_blocks_on_duplicate(monkeypatch):
    monkeypatch.setattr(bnd, "find_duplicate_published", lambda kw: {"id": 7, "title": "既存"})
    monkeypatch.setattr(bnd, "read_sources", lambda sigs: "x" * 500)
    ok, reason, text = bnd._pre_generation_gate("aespa", _SIGS)
    assert ok is False
    assert "dup_pre_gen" in reason
    assert text == ""


def test_blocks_on_short_source(monkeypatch):
    monkeypatch.setattr(bnd, "find_duplicate_published", lambda kw: None)
    monkeypatch.setattr(bnd, "read_sources", lambda sigs: "短い" * 10)  # 20字 < 150
    ok, reason, text = bnd._pre_generation_gate("aespa", _SIGS)
    assert ok is False
    assert "short_source" in reason
    assert text == ""


def test_passes_when_unique_and_long(monkeypatch):
    monkeypatch.setattr(bnd, "find_duplicate_published", lambda kw: None)
    long_text = "あ" * 500
    monkeypatch.setattr(bnd, "read_sources", lambda sigs: long_text)
    ok, reason, text = bnd._pre_generation_gate("aespa", _SIGS)
    assert ok is True
    assert reason == ""
    assert text == long_text
