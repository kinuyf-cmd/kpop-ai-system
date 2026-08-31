#!/usr/bin/env python3
"""jsonl 破損検知のテスト。

背景 (2026-08-31):
  ディスク満杯(2026-08-29)で追記が途中で切れ、**次のレコードが同じ行に連結**する
  破損が 8 ファイルで発生していた(health_check / cost_ledger / processed_breaking /
  trend_signals 等)。json.loads が落ちるだけで、多くの読み手は try/except で
  握って continue するため **1行黙って欠落する**。

  processed_breaking.jsonl は速報の dedup キー、cost_ledger.jsonl は API 費の台帳。
  黙って欠けると [[api-cost-measurement-layer-pitfalls]] のような
  「分析の前提が壊れているのに気付かない」状態を作る。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.jsonl_integrity import scan_file, find_broken  # noqa: E402


def test_健全なファイルは0件(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text('{"a":1}\n{"b":2}\n')
    assert scan_file(p) == 0


def test_空行は破損としない(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text('{"a":1}\n\n{"b":2}\n')
    assert scan_file(p) == 0


def test_連結破損を検出する(tmp_path):
    """ディスク満杯で起きた実際の形: 途中で切れた行に次レコードが続く。"""
    p = tmp_path / "a.jsonl"
    p.write_text('{"a":1}\n{"ts":"x","dig{"ts":"y","ok":1}\n')
    assert scan_file(p) == 1


def test_非JSON行を検出する(tmp_path):
    """シェルのエラー出力が混入したケース。"""
    p = tmp_path / "a.jsonl"
    p.write_text('{"a":1}\nSyntaxError: unterminated string literal\n')
    assert scan_file(p) == 1


def test_存在しないファイルは0件(tmp_path):
    assert scan_file(tmp_path / "nope.jsonl") == 0


def test_find_brokenは破損ファイルのみ返す(tmp_path):
    (tmp_path / "ok.jsonl").write_text('{"a":1}\n')
    (tmp_path / "ng.jsonl").write_text('{"a":1}\nbroken\n')
    got = dict(find_broken([tmp_path]))
    assert set(got) == {tmp_path / "ng.jsonl"}
    assert got[tmp_path / "ng.jsonl"] == 1


def test_本番のjsonlが全て健全である():
    """回帰ガード: logs/ と data/ の jsonl に破損を残さない。"""
    broken = find_broken([ROOT / "logs", ROOT / "data"])
    assert broken == [], f"破損あり: {[(str(p), n) for p, n in broken]}"
