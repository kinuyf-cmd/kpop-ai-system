#!/usr/bin/env python3
"""feedback_loop が progress の theme を直読みすることの単体テスト (2026-07-10)。

背景: _slug_theme_map() が slug 経由で theme を引き直していたが、
      tracker が slug を空固定していたため直近77件が 77/77 で unknown だった。
実行: python3 -m pytest tests/unit/test_seo_feedback_loop_theme.py -v
"""
import lib.seo_feedback_loop as fb


ROWS = [
    {"week": "2026-07-17", "query": "golden 歌手", "slug": "kpop-demon-hunters-golden-analysis",
     "theme": "movie_anime", "crossed_10": True, "clicks_delta": 3,
     "clicks_abs": 5, "delta_basis": "prev_week", "current_pos": 4.0, "baseline_pos": 11.0},
    {"week": "2026-07-17", "query": "ojogang メンバー", "slug": "swf3-osaka-ojo-gang-members",
     "theme": "dance_show", "crossed_10": False, "clicks_delta": 0,
     "clicks_abs": 0, "delta_basis": "prev_week", "current_pos": 5.8, "baseline_pos": 8.68},
]


def test_slug_theme_map_is_removed():
    """slug 経由の引き直しは構造的に不要。関数ごと消えていること。"""
    assert not hasattr(fb, "_slug_theme_map")


def test_aggregate_reads_theme_directly(monkeypatch):
    """progress 行の theme を直読みし、unknown 単一に潰れないこと。

    aggregate() は (summary, rows) のタプルを返す。summary が theme 別の dict。
    """
    monkeypatch.setattr(fb, "_recent_progress", lambda *a, **k: ROWS)
    summary, rows = fb.aggregate()
    assert set(summary.keys()) == {"movie_anime", "dance_show"}
    assert "unknown" not in summary
    assert len(rows) == 2


def test_aggregate_unknown_disappears(monkeypatch):
    """回帰: 直近77件が 77/77 unknown だった。"""
    monkeypatch.setattr(fb, "_recent_progress", lambda *a, **k: ROWS)
    summary, _ = fb.aggregate()
    assert list(summary.keys()) != ["unknown"]


def test_aggregate_keeps_summary_shape(monkeypatch):
    """summary の各値は n / crossed_10_rate / clicks_delta_avg。下流が依存する。"""
    monkeypatch.setattr(fb, "_recent_progress", lambda *a, **k: ROWS)
    summary, _ = fb.aggregate()
    assert summary["movie_anime"] == {"n": 1, "crossed_10_rate": 1.0, "clicks_delta_avg": 3.0}
    assert summary["dance_show"] == {"n": 1, "crossed_10_rate": 0.0, "clicks_delta_avg": 0.0}


def test_aggregate_falls_back_to_unknown_for_legacy_rows(monkeypatch):
    """theme を持たない過去行は unknown。落とさない。"""
    legacy = [{"week": "2026-07-03", "query": "旧", "slug": "",
               "crossed_10": False, "clicks_delta": -14, "current_pos": 5.11,
               "baseline_pos": 8.68}]
    monkeypatch.setattr(fb, "_recent_progress", lambda *a, **k: legacy)
    summary, _ = fb.aggregate()
    assert "unknown" in summary


# ── 2026-10-11: 未施策の記事と「既に10位以内」の記事を効果薄に数えない ──────────

def _other_rows():
    """実測の再現: theme='other' は未施策の pos65 と、pos7→3 に上がった施策済みの2本。"""
    rows = []
    for w in ("2026-09-18", "2026-09-25", "2026-10-02", "2026-10-09"):
        rows.append({"week": w, "slug": "untreated", "theme": "other", "crossed_10": False,
                     "clicks_delta": 0, "current_pos": 65.0, "baseline_pos": 69.5})
        rows.append({"week": w, "slug": "treated", "theme": "other", "crossed_10": False,
                     "clicks_delta": 0, "current_pos": 3.0, "baseline_pos": 7.26})
    return rows


def _summary(rows, monkeypatch):
    monkeypatch.setattr(fb, "_recent_progress", lambda *a, **k: rows)
    return fb.aggregate()[0]


def test_no_proposal_when_treated_samples_are_too_few(monkeypatch):
    rows = _other_rows()
    monkeypatch.setattr(fb, "_route_map", lambda: {("slug", "treated"): "enrich"})
    assert fb.build_proposals(_summary(rows, monkeypatch), rows) == []


def test_no_proposal_when_treated_article_is_on_page_one(monkeypatch):
    rows = _other_rows() + _other_rows()
    monkeypatch.setattr(fb, "_route_map", lambda: {("slug", "treated"): "enrich"})
    assert fb.build_proposals(_summary(rows, monkeypatch), rows) == []


def test_proposal_when_treated_articles_stay_off_page_one(monkeypatch):
    rows = _other_rows() + _other_rows()
    monkeypatch.setattr(fb, "_route_map", lambda: {("slug", "untreated"): "enrich"})
    props = fb.build_proposals(_summary(rows, monkeypatch), rows)
    assert [p["theme"] for p in props] == ["other"]
    assert props[0]["observed"]["page_one_rate"] == 0.0
