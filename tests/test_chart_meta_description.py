#!/usr/bin/env python3
"""チャート記事の meta description のテスト。

背景 (2026-08-31):
  daily_health_check が「直近3日でメタdesc未設定1件」を指し、
  該当は当日のチャート記事(post 18889)だった。
  チャート経路には meta description を入れる処理が**そもそも無く**、
  他経路(unified_publisher が excerpt=meta_desc を渡す)と違って
  **毎週2本が恒常的にメタ欠落**していた。

  [[ctr-search-term-must-be-early-in-title]] の通り、検索語は前方に置く。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.chart_article import build_meta_description  # noqa: E402

CHART = {
    "title": "Soompi's K-Pop Music Chart 2026, August Week 4 | Soompi",
    "items": [
        {"rank": 1, "song": "Pop Off Pop Off", "artist": "KiiiKiii"},
        {"rank": 2, "song": "Foo", "artist": "IVE"},
        {"rank": 3, "song": "Bar", "artist": "aespa"},
    ],
}


def test_1位のアーティストと曲名が入る():
    d = build_meta_description(CHART)
    assert "KiiiKiii" in d and "Pop Off Pop Off" in d


def test_週の情報が入る():
    d = build_meta_description(CHART)
    assert "8月" in d and "第4週" in d


def test_検索語が前方にある():
    """[[ctr-search-term-must-be-early-in-title]]: 前方に置かないとCTRが落ちる。"""
    d = build_meta_description(CHART)
    assert d.index("K-POPチャート") < 15


def test_長さが検索結果の実効上限に収まる():
    d = build_meta_description(CHART)
    assert 60 <= len(d) <= 120, f"len={len(d)}"


def test_itemsが空でも例外を出さない():
    d = build_meta_description({"title": "x", "items": []})
    assert isinstance(d, str) and d


def test_週が読めなくても例外を出さない():
    d = build_meta_description({"title": "", "items": CHART["items"]})
    assert isinstance(d, str) and d
