#!/usr/bin/env python3
"""page_one_tracker 計測ロジックの単体テスト (2026-07-10)。

背景: tracker が slug を空固定・theme を破棄・clicks_delta が時間経過を測っていた。
設計: docs/superpowers/specs/2026-07-10-page-one-tracker-measurement-fix-design.md

テストは GSC API を叩かない。実測7行を写した固定フィクスチャを純関数に渡す。
GSC の28日窓は毎週スライドするため、ライブ値をアサートすると時間経過で勝手に壊れる。

実行: python3 -m pytest tests/unit/test_page_one_tracker.py -v
"""
import json

import lib.page_one_tracker as t


def test_slug_of_strips_fragment():
    """GSC が返すアンカー付き URL からフラグメントを除去する。"""
    url = "https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/#kpop-h-0"
    assert t._slug_of(url) == "swf3-osaka-ojo-gang-members"


def test_slug_of_strips_query_string():
    """クエリ文字列を除去する。"""
    url = "https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/?utm_source=x"
    assert t._slug_of(url) == "swf3-osaka-ojo-gang-members"


def test_slug_of_handles_no_trailing_slash():
    """末尾スラッシュの有無どちらでも同じ slug を返す。"""
    assert t._slug_of("https://www.kpopjournal.tokyo/foo-bar") == "foo-bar"
    assert t._slug_of("https://www.kpopjournal.tokyo/foo-bar/") == "foo-bar"


def test_slug_of_returns_empty_for_external_domain():
    """外部ドメインは空文字。rollback が誤って他サイトの記事を差し戻さないため。"""
    assert t._slug_of("https://soompi.com/article/123") == ""


def test_slug_of_returns_empty_for_home_page():
    """トップページは記事ではないので空文字。"""
    assert t._slug_of("https://www.kpopjournal.tokyo/") == ""


# ojogang メンバー の GSC 実測7行を写したフィクスチャ。
# 本文 URL 1行(imp=92) + #kpop-h-0..6 のアンカー6行(各 imp=2)。
# imp 合計 104。加重平均 5.79 / 単純平均 9.74。
# position は GSC 表示値(小数2桁)。この定義がそのまま期待値を決める。
ROWS = [
    {"position": 5.18, "impressions": 92},
    *({"position": 10.50, "impressions": 2} for _ in range(6)),
]


def test_weighted_position_is_impression_weighted():
    """imp 加重平均。単純平均 9.74 に引きずられないこと。"""
    assert round(t._weighted_position(ROWS), 2) == 5.79


def test_weighted_position_differs_from_naive_mean():
    """単純平均との差を明示。この差こそが欠陥2の被害額。"""
    naive = sum(r["position"] for r in ROWS) / len(ROWS)
    assert round(naive, 2) == 9.74
    assert round(t._weighted_position(ROWS), 2) != round(naive, 2)


def test_weighted_position_falls_back_on_zero_impressions():
    """imp 合計 0 ならゼロ除算。単純平均にフォールバックする。"""
    rows = [{"position": 4.0, "impressions": 0}, {"position": 6.0, "impressions": 0}]
    assert t._weighted_position(rows) == 5.0


def test_weighted_position_empty_rows_returns_zero():
    """空行なら 0.0。呼び出し側は rows 非空を保証するが念のため。"""
    assert t._weighted_position([]) == 0.0


def _row(page_url, imp):
    """GSC query×page 応答の行を作る。keys = [query, page]。"""
    return {"keys": ["ojogang メンバー", page_url], "impressions": imp}


# 実測7行を GSC 応答形式で写したもの。全て同一 slug に集約され imp 104 になる。
SLUG_ROWS = [
    _row("https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/", 92),
    *(_row(f"https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/#kpop-h-{i}", 2)
      for i in range(6)),
]


def test_pick_slug_aggregates_fragments():
    """フラグメント別行を同一 slug に集約して選ぶ。"""
    assert t._pick_slug(SLUG_ROWS) == "swf3-osaka-ojo-gang-members"


def test_pick_slug_prefers_highest_aggregate_impressions():
    """集約 imp が最大の slug を選ぶ。行数ではなく imp 合計で決める。"""
    rows = [
        _row("https://www.kpopjournal.tokyo/loser/", 10),
        _row("https://www.kpopjournal.tokyo/loser/#kpop-h-0", 10),
        _row("https://www.kpopjournal.tokyo/winner/", 30),
    ]
    assert t._pick_slug(rows) == "winner"


def test_pick_slug_tie_break_is_deterministic():
    """imp 同数なら slug の辞書順で安定化。実行ごとに揺れると rollback 突合が壊れる。"""
    rows = [
        _row("https://www.kpopjournal.tokyo/zebra/", 50),
        _row("https://www.kpopjournal.tokyo/alpha/", 50),
    ]
    assert t._pick_slug(rows) == "alpha"
    # 入力順を反転しても同じ結果
    assert t._pick_slug(list(reversed(rows))) == "alpha"


def test_pick_slug_ignores_external_domains():
    """外部ドメイン行は slug 候補にしない。"""
    rows = [
        _row("https://soompi.com/article/123", 999),
        _row("https://www.kpopjournal.tokyo/mine/", 5),
    ]
    assert t._pick_slug(rows) == "mine"


def test_pick_slug_returns_empty_when_no_internal_page():
    """自サイト行が1つも無ければ空文字。theme は queue 由来なので生き残る。"""
    assert t._pick_slug([_row("https://soompi.com/a/1", 10)]) == ""


def test_clicks_delta_returns_zero_when_no_prev():
    """初回は前週が無い。差分ゼロ = 判断保留。誤って「悪化」と読まれないため。"""
    assert t._clicks_delta(0, None) == 0
    assert t._clicks_delta(37, None) == 0


def test_clicks_delta_is_week_over_week():
    """前週比。累積 baseline との差ではない。"""
    assert t._clicks_delta(5, {"clicks_abs": 3}) == 2
    assert t._clicks_delta(3, {"clicks_abs": 5}) == -2


def test_clicks_delta_ojogang_escapes_minus_14():
    """回帰: ojogang は baseline_clicks=14 に対し cur=0 で -14 固着していた。
    前週も 0 なら delta は 0。順位改善が「劣化」と誤読されない。"""
    assert t._clicks_delta(0, {"clicks_abs": 0}) == 0


def test_last_progress_row_returns_latest_by_week(tmp_path):
    """同一 query の最終行を week 順で返す。"""
    p = tmp_path / "progress.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        {"week": "2026-07-03", "query": "ojogang メンバー", "clicks_abs": 5},
        {"week": "2026-07-10", "query": "ojogang メンバー", "clicks_abs": 2},
        {"week": "2026-07-10", "query": "別クエリ", "clicks_abs": 99},
    ]) + "\n", encoding="utf-8")
    row = t._last_progress_row("ojogang メンバー", str(p))
    assert row["clicks_abs"] == 2


def test_last_progress_row_ignores_legacy_rows_without_clicks_abs(tmp_path):
    """過去122行に clicks_abs は無い。それらは前週比の基準にできないので無視。"""
    p = tmp_path / "progress.jsonl"
    p.write_text(json.dumps(
        {"week": "2026-07-03", "query": "ojogang メンバー", "clicks_delta": -14},
        ensure_ascii=False) + "\n", encoding="utf-8")
    assert t._last_progress_row("ojogang メンバー", str(p)) is None


def test_last_progress_row_returns_none_when_file_missing(tmp_path):
    """progress が無ければ None。初回実行で落ちない。"""
    assert t._last_progress_row("何か", str(tmp_path / "nope.jsonl")) is None


def _full_row(page_url, pos, imp, clicks=0):
    """GSC query×page 応答の完全な行。"""
    return {"keys": ["ojogang メンバー", page_url],
            "position": pos, "impressions": imp, "clicks": clicks}


# 実測7行の完全版。clicks は全行 0(ojogang の実測どおり)。
FULL_ROWS = [
    _full_row("https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/", 5.18, 92),
    *(_full_row(f"https://www.kpopjournal.tokyo/swf3-osaka-ojo-gang-members/#kpop-h-{i}",
                10.50, 2) for i in range(6)),
]


def test_rows_to_metrics_ojogang_fixture():
    """実測7行 → clicks 0 / imp 104 / pos 5.79(加重) / slug 逆引き成功。"""
    m = t._rows_to_metrics(FULL_ROWS)
    assert m["clicks"] == 0
    assert m["impressions"] == 104
    assert round(m["position"], 2) == 5.79
    assert m["slug"] == "swf3-osaka-ojo-gang-members"


def test_rows_to_metrics_sums_clicks_across_fragments():
    """clicks はアンカー分割を合算する。過小評価を防ぐ。"""
    rows = [
        _full_row("https://www.kpopjournal.tokyo/a/", 3.0, 10, clicks=4),
        _full_row("https://www.kpopjournal.tokyo/a/#kpop-h-0", 3.0, 10, clicks=3),
    ]
    assert t._rows_to_metrics(rows)["clicks"] == 7


def test_rows_to_metrics_empty_returns_none():
    """圏外(空行)は None。従来どおりその週をスキップする。既存挙動を変えない。"""
    assert t._rows_to_metrics([]) is None


def test_target_queries_carries_theme(tmp_path, monkeypatch):
    """enrich_queue と seo_opportunity_queue の双方から theme を meta に載せる。"""
    eq = tmp_path / "enrich_queue.json"
    eq.write_text(json.dumps([
        {"query": "golden 歌手", "slug": "kpop-demon-hunters-golden-analysis",
         "potential": 3797, "theme": "movie_anime"},
    ], ensure_ascii=False), encoding="utf-8")

    oq = tmp_path / "opportunity.json"
    oq.write_text(json.dumps({
        "lane_C_rewrite": [{"query": "ojogang メンバー", "potential": 521,
                            "theme": "dance_show"}],
        "lane_B_new": [{"query": "新規クエリ", "potential": 100, "theme": "artist"}],
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(t, "ENRICH_QUEUE", str(eq))
    monkeypatch.setattr(t, "QUEUE_IN", str(oq))

    qs = t._target_queries()
    assert qs["golden 歌手"]["theme"] == "movie_anime"
    assert qs["ojogang メンバー"]["theme"] == "dance_show"
    assert qs["新規クエリ"]["theme"] == "artist"


def test_target_queries_theme_defaults_to_unknown_when_absent(tmp_path, monkeypatch):
    """theme 欠落は実測ゼロだが、フォールバックは残す(落とさない)。"""
    oq = tmp_path / "opportunity.json"
    oq.write_text(json.dumps({
        "lane_C_rewrite": [{"query": "theme無し", "potential": 1}],
        "lane_B_new": [],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(t, "ENRICH_QUEUE", str(tmp_path / "nope.json"))
    monkeypatch.setattr(t, "QUEUE_IN", str(oq))

    assert t._target_queries()["theme無し"]["theme"] == "unknown"
