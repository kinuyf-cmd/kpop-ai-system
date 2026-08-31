#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""logs/*.log の圧縮ローテーション(2026-08-31)。

背景:
  logs/ が 58M まで肥大。kpop 側の占有としては小さいが、
  ホストのディスクが逼迫しているため削れる分は削る
  ([[disk-full-silent-collector-loss]])。

安全側の制約(ここが設計の本体):
  1. **.jsonl は対象外**。unified_publish.jsonl / pre_publish_gate.jsonl 等は
     「ログ」ではなく下流が読む**データ**であり、切ると履歴依存の判定が壊れる
     (dedup・公開率・skip率の集計が全部ここを読む)。
  2. .log にも読み手がいる。post_watchdog は post_audit.log を**直近48h**遡る。
     よって保持期間はそれよりずっと長い 30 日を取る。
  3. rename せず **copy + truncate**。cron 実行中のプロセスが追記用 fd を
     握ったままだと、rename しても書き込みは旧 inode に続き新ファイルが育たない。

  python3 tools/rotate_logs.py --dry-run
"""
import argparse
import datetime
import gzip
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"

KEEP_DAYS = 30              # .gz の保持日数(48h遡る読み手より十分長く)
MIN_ROTATE_BYTES = 1 << 20  # 1MB 未満は放置(細かく刻んでも意味がない)
TAIL_KEEP_LINES = 3000      # TAIL_KEEP 対象で本体に残す末尾行数

# 「本体を空にすると読み手が壊れる」ログ。
# post_audit.log: post_watchdog が直近48h遡って「監査済みID」を集める。
# 空にすると監査済み0件となり、pipeline外記事の検知が**静かに無効化**される
# (誤検知ではなく見逃しなので、鳴らないことに誰も気付けない)。
TAIL_KEEP = {"post_audit.log"}


def rotate_dir(d: Path, dry_run: bool = False):
    """ディレクトリ内の *.log をローテートし、期限切れ *.gz を消す。

    戻り値: (ローテートしたファイル数, 削除した .gz 数, 回収バイト数)
    """
    d = Path(d)
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    rotated = removed = freed = 0

    for f in sorted(d.glob("*.log")):
        try:
            size = f.stat().st_size
        except OSError:
            continue
        if size < MIN_ROTATE_BYTES:
            continue
        gz = d / f"{f.name}.{stamp}.gz"
        if dry_run:
            print(f"  [dry] rotate {f.name} ({size/2**20:.1f}MB)")
            rotated += 1
            continue
        try:
            # copy+truncate: 追記用 fd を握った常駐プロセスを取りこぼさない
            with open(f, "rb") as src, gzip.open(gz, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if f.name in TAIL_KEEP:
                # 直近行だけ本体に残す(読み手の48h窓を割らないため)
                tail = f.read_text(errors="replace").splitlines(keepends=True)[-TAIL_KEEP_LINES:]
                with open(f, "w", encoding="utf-8") as fh:
                    fh.writelines(tail)
            else:
                with open(f, "r+b") as fh:
                    fh.truncate(0)
            rotated += 1
            freed += size - gz.stat().st_size
            print(f"  rotate {f.name} ({size/2**20:.1f}MB) → {gz.name}")
        except OSError as e:
            print(f"  [fail] {f.name}: {e}")

    cutoff = datetime.datetime.now().timestamp() - KEEP_DAYS * 86400
    for g in sorted(d.glob("*.log.*.gz")):
        try:
            if g.stat().st_mtime >= cutoff:
                continue
            sz = g.stat().st_size
            if dry_run:
                print(f"  [dry] remove {g.name}")
            else:
                g.unlink()
                freed += sz
                print(f"  remove {g.name} (保持{KEEP_DAYS}日超)")
            removed += 1
        except OSError:
            continue

    return rotated, removed, freed


def main():
    ap = argparse.ArgumentParser(description="logs/*.log の圧縮ローテーション")
    ap.add_argument("--dry-run", action="store_true", help="実行せず対象を表示")
    args = ap.parse_args()

    ts = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    print(f"[{ts}] rotate-logs {LOGS}")
    r, rm, freed = rotate_dir(LOGS, dry_run=args.dry_run)
    print(f"=== 完了: rotate {r}件 / 削除 {rm}件 / 回収 {freed/2**20:.1f}MB ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
