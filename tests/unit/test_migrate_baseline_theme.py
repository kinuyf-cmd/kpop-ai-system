#!/usr/bin/env python3
"""baseline への theme 後付け移行の単体テスト (2026-07-10)。

絶対条件: baseline_pos / baseline_clicks を書き換えないこと。
実行: python3 -m pytest tests/unit/test_migrate_baseline_theme.py -v
"""
import tools.migrate_baseline_theme as m


BASELINE = {
    "created": "2026-05-26",
    "queries": {
        "ojogang メンバー": {"baseline_pos": 8.68, "baseline_clicks": 14,
                             "slug": "", "potential": 521},
        "golden 歌手": {"baseline_pos": 3.2, "baseline_clicks": 40,
                        "slug": "kpop-demon-hunters-golden-analysis", "potential": 3797},
    },
}
TARGETS = {
    "ojogang メンバー": {"slug": "", "potential": 521, "theme": "dance_show"},
    "golden 歌手": {"slug": "kpop-demon-hunters-golden-analysis",
                    "potential": 3797, "theme": "movie_anime"},
}


def test_migrate_adds_theme():
    out, n = m.migrate(BASELINE, TARGETS)
    assert out["queries"]["ojogang メンバー"]["theme"] == "dance_show"
    assert out["queries"]["golden 歌手"]["theme"] == "movie_anime"
    assert n == 2


def test_migrate_never_touches_baseline_pos_or_clicks():
    """絶対条件。baseline_pos を1つでも動かしたら計測の連続性が壊れる。"""
    out, _ = m.migrate(BASELINE, TARGETS)
    assert out["queries"]["ojogang メンバー"]["baseline_pos"] == 8.68
    assert out["queries"]["ojogang メンバー"]["baseline_clicks"] == 14
    assert out["queries"]["golden 歌手"]["baseline_pos"] == 3.2


def test_migrate_does_not_mutate_input():
    """入力を破壊しない。呼び出し側が diff を取れるようにするため。"""
    m.migrate(BASELINE, TARGETS)
    assert "theme" not in BASELINE["queries"]["ojogang メンバー"]


def test_migrate_defaults_to_unknown_when_query_not_in_targets():
    """queue から消えたクエリは unknown。落とさない。"""
    out, _ = m.migrate(BASELINE, {})
    assert out["queries"]["ojogang メンバー"]["theme"] == "unknown"


def test_migrate_is_idempotent():
    """2回流しても結果が変わらない。"""
    once, _ = m.migrate(BASELINE, TARGETS)
    twice, n = m.migrate(once, TARGETS)
    assert once == twice
    assert n == 2
