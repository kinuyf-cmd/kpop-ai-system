#!/usr/bin/env python3
"""ディスク残量ガードのテスト。

背景 (2026-08-29):
  `/` が満杯になり `OSError: [Errno 28] No space left on device` が多発。
  collect-all の 14 collector 中 8 件が落ちて **その日の記事収集が欠損**した。
  dashboard / daily_health_check も途中でクラッシュしている。

  問題は「落ちたこと」ではなく **誰も気付かなかったこと**。
  collector は1つ失敗しても続行する設計(意図的)なので、
  容量起因の全滅もログの中に埋もれて静かに流れていく。

  そこで実行の**前段**で残量を見て、閾値を割っていたら Discord に鳴らす。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.disk_guard import check_disk, WARN_GB, FAIL_GB  # noqa: E402


def _fake_usage(monkeypatch, free_gb):
    import lib.disk_guard as dg
    import collections
    U = collections.namedtuple("U", "total used free")
    monkeypatch.setattr(dg.shutil, "disk_usage",
                        lambda p: U(100 * 2**30, 0, int(free_gb * 2**30)))


def test_余裕があればPASS(monkeypatch):
    _fake_usage(monkeypatch, WARN_GB + 5)
    level, msg = check_disk()
    assert level == "PASS"


def test_WARN閾値を割るとWARN(monkeypatch):
    _fake_usage(monkeypatch, WARN_GB - 0.5)
    level, msg = check_disk()
    assert level == "WARN"
    assert "残" in msg


def test_FAIL閾値を割るとFAIL(monkeypatch):
    _fake_usage(monkeypatch, FAIL_GB - 0.5)
    level, msg = check_disk()
    assert level == "FAIL"


def test_閾値は境界を含まない(monkeypatch):
    """ちょうど閾値ならまだ正常(割り込んで初めて警告)。"""
    _fake_usage(monkeypatch, WARN_GB)
    assert check_disk()[0] == "PASS"


def test_メッセージに実残量GBが入る(monkeypatch):
    _fake_usage(monkeypatch, 3.0)
    level, msg = check_disk()
    assert "3.0" in msg


def test_計測不能でも例外を投げない(monkeypatch):
    """ガード自身が本体を止めては本末転倒。"""
    import lib.disk_guard as dg
    def boom(p):
        raise OSError("nope")
    monkeypatch.setattr(dg.shutil, "disk_usage", boom)
    level, msg = check_disk()
    assert level == "PASS"
