"""GSC フラグメント(#kpop-h-N)行の正規化テスト。

背景（2026-07-31 実測）:
  テーマの目次 JS (themes/generatepress-kpop/functions.php) が h2/h3 に
  id="kpop-h-N" を振るため、Google は同一 SERP 枠を本体 URL とアンカー URL の
  複数行に分割して返す。同一日・同一クエリで imp も pos も本体行と同値であり、
  クリックだけが本体行に計上される（= 実害ではなく計測アーティファクト）。

  実測では 28日で imp の 33.7%(38,679) がアンカー行で、サイト平均 CTR が
  4.41% → 2.93% に見かけ上押し下げられていた。これを未除去のまま扱うと
  「imp は大きいが CTR 0%」の幽霊ページが勝ち負け判定・Lane C 候補に混入する。

  page_one_tracker は 2026-07-10 に対策済みだが、weekly_win_report と
  seo_lane_c_bridge は未対策だった。
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SITE = "https://www.kpopjournal.tokyo/"


def _load_weekly_win_report():
    """gsc_snapshot（Google SDK 依存）を stub して単体で読み込む。"""
    stub = types.ModuleType("gsc_snapshot")
    stub._svc = lambda *a, **k: None
    stub._query = lambda *a, **k: []
    sys.modules["gsc_snapshot"] = stub

    path = ROOT / "tools" / "seo" / "weekly_win_report.py"
    spec = importlib.util.spec_from_file_location("weekly_win_report", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wwr = _load_weekly_win_report()


def _row(page, clicks, imp, pos):
    return {"keys": [page], "clicks": clicks, "impressions": imp,
            "position": pos, "ctr": (clicks / imp if imp else 0.0)}


# 2026-07-01 の実測値そのまま: 本体とアンカーで imp/pos が完全一致し、
# クリックは本体行にのみ載る。
BASE_URL = SITE + "kpop-demon-hunters-cast-characters/"
REAL_ROWS = [
    _row(BASE_URL, 4, 36, 7.17),
    _row(BASE_URL + "#kpop-h-0", 0, 36, 7.17),
    _row(BASE_URL + "#kpop-h-2", 0, 36, 7.17),
    _row(BASE_URL + "#kpop-h-12", 0, 33, 7.24),
    _row(BASE_URL + "#kpop-h-5", 0, 33, 7.24),
]


def test_strip_fragment_removes_anchor():
    assert wwr._strip_fragment(BASE_URL + "#kpop-h-0") == BASE_URL
    assert wwr._strip_fragment(BASE_URL) == BASE_URL


def test_strip_fragment_handles_empty():
    assert wwr._strip_fragment("") == ""
    assert wwr._strip_fragment(None) is None


def test_merge_collapses_anchor_rows_into_one_page():
    merged = wwr._merge_by_page(REAL_ROWS)
    assert list(merged) == [BASE_URL], "アンカー行が本体に集約されていない"


def test_merge_does_not_inflate_impressions():
    """imp は重複計上なので合算してはいけない（36+36+36+33+33=174 は誤り）。"""
    merged = wwr._merge_by_page(REAL_ROWS)
    assert merged[BASE_URL]["impressions"] == 36


def test_merge_preserves_clicks():
    merged = wwr._merge_by_page(REAL_ROWS)
    assert merged[BASE_URL]["clicks"] == 4


def test_merge_ctr_is_not_diluted():
    """集約前は 4/174=2.3% に希釈される。正しくは 4/36=11.1%。"""
    merged = wwr._merge_by_page(REAL_ROWS)
    assert merged[BASE_URL]["ctr"] == pytest.approx(4 / 36)


def test_merge_keeps_best_position():
    merged = wwr._merge_by_page(REAL_ROWS)
    assert merged[BASE_URL]["position"] == pytest.approx(7.17)


def test_merge_keeps_distinct_pages_separate():
    other = SITE + "tettsui-kyoshi-cast-chart/"
    merged = wwr._merge_by_page(REAL_ROWS + [_row(other, 19, 2351, 5.94)])
    assert set(merged) == {BASE_URL, other}
    assert merged[other]["clicks"] == 19


def test_bridge_does_not_select_anchor_url(monkeypatch):
    """seo_lane_c_bridge が本体 URL を返すこと（WP 更新先が壊れないため）。"""
    from lib import seo_lane_c_bridge as bridge

    class FakeSvc:
        def searchanalytics(self):
            return self

        def query(self, siteUrl=None, body=None):
            return self

        def execute(self):
            # アンカー行を先頭・同 imp で返す最悪ケース
            return {"rows": [
                {"keys": [BASE_URL + "#kpop-h-0"], "clicks": 0, "impressions": 36,
                 "position": 7.17, "ctr": 0.0},
                {"keys": [BASE_URL], "clicks": 4, "impressions": 36,
                 "position": 7.17, "ctr": 4 / 36},
            ]}

    got = bridge.fetch_page_for_query(FakeSvc(), "デーモンハンターズ キャラクター")
    assert "#" not in got["url"], f"アンカー URL を選んでいる: {got['url']}"
    assert got["url"] == BASE_URL
    assert got["clicks"] == 4
    assert got["impressions"] == 36


def test_bridge_returns_none_without_rows(monkeypatch):
    from lib import seo_lane_c_bridge as bridge

    class EmptySvc:
        def searchanalytics(self):
            return self

        def query(self, siteUrl=None, body=None):
            return self

        def execute(self):
            return {"rows": []}

    assert bridge.fetch_page_for_query(EmptySvc(), "nope") is None
