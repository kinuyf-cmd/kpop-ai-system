#!/usr/bin/env python3
"""logs/*.log ローテーションのテスト。

背景 (2026-08-31):
  logs/ が 58M まで肥大。単体では小さいが、ディスクが逼迫している環境では
  削れる分は削っておきたい([[disk-full-silent-collector-loss]])。

安全側の制約(ここが本質):
  - **.jsonl は触らない**。unified_publish.jsonl 等は「ログ」ではなく
    下流が読む**データ**で、切ると履歴依存のロジックが壊れる。
  - .log でも読まれているものがある(post_watchdog が post_audit.log を
    **直近48h** 遡る)。よって保持は 48h よりずっと長く取る。
"""
import gzip
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.rotate_logs import rotate_dir, KEEP_DAYS, MIN_ROTATE_BYTES  # noqa: E402


def _mk(p: Path, size: int, age_days: float = 0.0):
    p.write_bytes(b"x" * size)
    if age_days:
        t = time.time() - age_days * 86400
        import os
        os.utime(p, (t, t))
    return p


def test_大きいlogは圧縮され本体が空になる(tmp_path):
    f = _mk(tmp_path / "big.log", MIN_ROTATE_BYTES + 10)
    rotate_dir(tmp_path)
    assert f.stat().st_size == 0, "ローテ後の本体は空(fdを握る常駐に配慮しtruncate)"
    gz = list(tmp_path.glob("big.log.*.gz"))
    assert len(gz) == 1
    assert len(gzip.decompress(gz[0].read_bytes())) == MIN_ROTATE_BYTES + 10


def test_小さいlogは触らない(tmp_path):
    f = _mk(tmp_path / "small.log", 100)
    rotate_dir(tmp_path)
    assert f.stat().st_size == 100
    assert not list(tmp_path.glob("*.gz"))


def test_jsonlは絶対に触らない(tmp_path):
    """下流が読むデータなので、サイズが大きくても対象外。"""
    f = _mk(tmp_path / "unified_publish.jsonl", MIN_ROTATE_BYTES * 3)
    rotate_dir(tmp_path)
    assert f.stat().st_size == MIN_ROTATE_BYTES * 3
    assert not list(tmp_path.glob("*.gz"))


def test_保持期限を過ぎたgzは削除される(tmp_path):
    old = _mk(tmp_path / "a.log.20260101.gz", 50, age_days=KEEP_DAYS + 1)
    new = _mk(tmp_path / "b.log.20260830.gz", 50, age_days=1)
    rotate_dir(tmp_path)
    assert not old.exists()
    assert new.exists()


def test_保持期間は48h遡る読み手より十分長い(tmp_path):
    """post_watchdog が post_audit.log を直近48h遡る。"""
    assert KEEP_DAYS >= 14


def test_dry_runは何も変更しない(tmp_path):
    f = _mk(tmp_path / "big.log", MIN_ROTATE_BYTES + 10)
    rotate_dir(tmp_path, dry_run=True)
    assert f.stat().st_size == MIN_ROTATE_BYTES + 10
    assert not list(tmp_path.glob("*.gz"))


def test_TAIL_KEEP対象は直近行を本体に残す(tmp_path, monkeypatch):
    """post_audit.log は post_watchdog が直近48h遡って読む。
    完全に空にすると「監査済み0件」となり、pipeline外記事の検知が
    **静かに無効化**される(誤検知でなく見逃しなので気付けない)。
    よって末尾は本体に残す。"""
    import tools.rotate_logs as rl
    monkeypatch.setattr(rl, "TAIL_KEEP_LINES", 5)
    f = tmp_path / "post_audit.log"
    f.write_text("".join(f"line{i}\n" for i in range(2000)) + "y" * rl.MIN_ROTATE_BYTES)
    rl.rotate_dir(tmp_path)
    body = f.read_text()
    assert "line1999" in body, "直近行が残っていない"
    assert "line0" not in body, "古い行は切られているべき"
    assert len(list(tmp_path.glob("post_audit.log.*.gz"))) == 1
