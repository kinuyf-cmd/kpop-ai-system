#!/usr/bin/env python3
"""tools/seo/gsc_snapshot.py のテスト(GSC/DB を叩かない純ロジック部分)。

守りたい仕様:
  - 単日スパイクで膨らんだ候補を「機会」として出さない
    (2026-09-28: /artists/cortis/ imp1409 の 918 が 09-07 の単日。
     memory: gsc-7d-window-and-fragment-artifacts で2度踏んだ)
  - 既に対策済み(AIOSEO title 設定済 / 本文に schema あり)の記事に印を付ける
    (同日、推奨した2件が対策済みだった)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.seo.gsc_snapshot import (  # noqa: E402
    SPIKE_SHARE, spike_share, split_spikes, slug_from_page, parse_treatment,
    treatment_label,
)


def test_単日スパイクの占有率():
    # cortis 実測: 09-07 918 / 合計 1409
    daily = [918] + [15] * 32 + [11]
    assert spike_share(daily) > SPIKE_SHARE


def test_定常需要はスパイク扱いしない():
    daily = [20, 26, 16, 7, 13, 30, 25]
    assert spike_share(daily) < SPIKE_SHARE


def test_データ無しは0():
    assert spike_share([]) == 0
    assert spike_share([0, 0]) == 0


def test_スパイク候補は本表から除外し別枠に残す():
    items = [{"page": "/artists/cortis/", "imp": 1409},
             {"page": "/steady/", "imp": 500}]
    daily = {"/artists/cortis/": [918, 15, 15, 461], "/steady/": [100, 100, 150, 150]}
    kept, spikes = split_spikes(items, "page", daily)
    assert [r["page"] for r in kept] == ["/steady/"]
    assert [r["page"] for r in spikes] == ["/artists/cortis/"]
    assert spikes[0]["spike_share"] > SPIKE_SHARE


def test_日次が取れない候補は捨てずに残す():
    kept, spikes = split_spikes([{"query": "x", "imp": 300}], "query", {})
    assert len(kept) == 1 and spikes == []


def test_slug抽出はフラグメントを落とす():
    assert slug_from_page("/tettsui-kyoshi-dub-episodes/#kpop-h-0") == "tettsui-kyoshi-dub-episodes"
    assert slug_from_page("/artists/cortis/") == "cortis"
    assert slug_from_page("https://www.kpopjournal.tokyo/foo-bar/") == "foo-bar"


def test_slug抽出はSQLに危険な文字を拒否():
    assert slug_from_page("/") is None
    assert slug_from_page("/a'b/") is None
    assert slug_from_page("/a\\b/") is None


def test_DB出力のパース():
    out = ("post_name\ttitle_set\tupdated\tfaq\ttvseries\tldjson\n"
           "tettsui-kyoshi-dub-episodes\t1\t2026-09-11 16:10:46\t4763\t8132\t4880\n"
           "cortis\t0\tNULL\t0\t0\t0\n")
    t = parse_treatment(out)
    assert t["tettsui-kyoshi-dub-episodes"] == {
        "title_set": True, "updated": "2026-09-11", "schema": ["FAQPage", "TVSeries"]}
    assert t["cortis"] == {"title_set": False, "updated": None, "schema": []}


def test_対策済みラベル():
    assert treatment_label({"title_set": True, "updated": "2026-09-11",
                            "schema": ["TVSeries"]}) == "[対策済 title+TVSeries 09-11]"
    assert treatment_label({"title_set": False, "updated": None, "schema": []}) == ""
    assert treatment_label(None) == ""
