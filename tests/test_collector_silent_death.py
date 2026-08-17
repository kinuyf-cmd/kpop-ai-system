#!/usr/bin/env python3
"""コレクタの「無言で0件死」を検知する仕組みのテスト。

背景 (2026-08-17):
  koreaherald の収集が、サイト構造変更で正規表現が1件もマッチせず
  **0件のまま無言で死んでいた**(commit c1b5de0 で根治)。
  0件でもログに何も出さないため、誰も気付けなかった。

  他16コレクタを点検したところ、同じ状態のものが更に2件見つかった
  (wowkorea / starnews)。偶然見つけただけで、仕組みが無ければ次も気付けない。

  そこで全コレクタの共通経路 lib/collectors/korean_base.py::save_signals に
  検知を入れる。ここを通れば1箇所で全コレクタに効く。

判定の考え方:
  「今回0件」だけでは異常と言えない(深夜で新着が無い、全部重複、等)。
  **連続して0件が続くこと**を異常とする。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.collectors.korean_base import (record_collect_result,  # noqa: E402
                                        consecutive_zero_count,
                                        ZERO_ALERT_THRESHOLD)


def test_0件が続くと連続回数が増える(tmp_path, monkeypatch):
    import lib.collectors.korean_base as kb
    monkeypatch.setattr(kb, "COLLECT_HEALTH", tmp_path / "h.jsonl")
    for _ in range(3):
        record_collect_result("wowkorea", 0)
    assert consecutive_zero_count("wowkorea") == 3


def test_1件でも取れたら連続回数がリセットされる(tmp_path, monkeypatch):
    import lib.collectors.korean_base as kb
    monkeypatch.setattr(kb, "COLLECT_HEALTH", tmp_path / "h.jsonl")
    record_collect_result("osen", 0)
    record_collect_result("osen", 0)
    record_collect_result("osen", 5)
    assert consecutive_zero_count("osen") == 0


def test_コレクタごとに独立して数える(tmp_path, monkeypatch):
    """1つが死んでいても他の成功でリセットされてはいけない。"""
    import lib.collectors.korean_base as kb
    monkeypatch.setattr(kb, "COLLECT_HEALTH", tmp_path / "h.jsonl")
    record_collect_result("wowkorea", 0)
    record_collect_result("osen", 7)
    record_collect_result("wowkorea", 0)
    assert consecutive_zero_count("wowkorea") == 2
    assert consecutive_zero_count("osen") == 0


def test_単発の0件では異常としない(tmp_path, monkeypatch):
    """深夜で新着が無い/全部重複、といった正常な0件がある。"""
    import lib.collectors.korean_base as kb
    monkeypatch.setattr(kb, "COLLECT_HEALTH", tmp_path / "h.jsonl")
    record_collect_result("kstyle", 0)
    assert consecutive_zero_count("kstyle") < ZERO_ALERT_THRESHOLD


def test_閾値は複数回に設定されている():
    """1回で鳴らすと誤報だらけになる。"""
    assert ZERO_ALERT_THRESHOLD >= 3


def test_記録が無いコレクタは0を返す(tmp_path, monkeypatch):
    import lib.collectors.korean_base as kb
    monkeypatch.setattr(kb, "COLLECT_HEALTH", tmp_path / "h.jsonl")
    assert consecutive_zero_count("never_ran") == 0


def test_壊れた行があっても落ちない(tmp_path, monkeypatch):
    import lib.collectors.korean_base as kb
    p = tmp_path / "h.jsonl"
    p.write_text("これはJSONではない\n" + json.dumps(
        {"source_id": "osen", "count": 0}) + "\n", encoding="utf-8")
    monkeypatch.setattr(kb, "COLLECT_HEALTH", p)
    assert consecutive_zero_count("osen") == 1


# ─── 一覧レポートの判定 ────────────────────────────────────────────────
def test_48hシグナルゼロは記録が浅くても疑いとして出す(tmp_path, monkeypatch):
    """導入直後は連続0件が1回しか無く閾値に届かないが、48hシグナルが0なら
    実際には壊れている(実測: wowkorea/starnews)。閾値待ちで見逃してはいけない。"""
    import lib.collectors.korean_base as kb
    import tools.check_collector_health as ch
    monkeypatch.setattr(kb, "COLLECT_HEALTH", tmp_path / "h.jsonl")
    monkeypatch.setattr(ch, "BASE", tmp_path)          # trend_signals を空に
    monkeypatch.setattr(ch, "known_collectors", lambda: ["wowkorea", "osen"])
    kb.record_collect_result("wowkorea", 0)
    kb.record_collect_result("osen", 12)
    r = ch.report()
    rows = {c["source_id"]: c for c in r["collectors"]}
    assert rows["wowkorea"]["suspect_dead"] is True
    assert rows["osen"]["suspect_dead"] is False
