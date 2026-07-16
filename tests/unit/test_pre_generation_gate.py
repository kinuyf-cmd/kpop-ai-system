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


def test_hangul_artist_normalized_before_dedup_search(monkeypatch):
    """ハングルのアーティスト名は辞書で正規名(Red Velvet)へ変換され、
    その正規名で find_duplicate_published が呼ばれること。

    公開済み記事タイトルは日本語/英語表記なので、ハングルのまま WP 検索しても
    ヒットしない。従来は kw=[] または ハングルのままで空振りし、生成前 dedup を
    すり抜けて生成コストを浪費していた(公開率低下の実測根因)。
    正規化により既存記事(例 ID=8187 Red Velvet)にヒットして事前ブロックできる。"""
    captured = {}

    def _capture(kw):
        captured["kw"] = kw
        return None

    monkeypatch.setattr(bnd, "find_duplicate_published", _capture)
    monkeypatch.setattr(bnd, "read_sources", lambda sigs: "あ" * 500)
    sigs = [{"title": "레드벨벳, 8월 컴백 확정", "url": "https://x.com/a"}]
    bnd._pre_generation_gate("레드벨벳", sigs)
    kw = captured.get("kw", [])
    assert kw, "ハングルアーティストで kw が空になってはならない"
    # 辞書変換で Red / Velvet が英字キーワードとして載る(WP 日本語DBにヒット可能)
    assert "Red" in kw and "Velvet" in kw, f"正規名が抽出されていない: {kw}"
