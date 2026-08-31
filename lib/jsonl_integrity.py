#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jsonl 破損の検知(2026-08-31)。

背景:
  ディスク満杯(2026-08-29)で追記が途中で切れ、**次のレコードが同じ行に連結**する
  破損が 8 ファイルで発生していた([[disk-full-silent-collector-loss]])。

なぜ検知が要るか:
  読み手の多くは `try: json.loads(l) except: continue` で握るため、
  壊れた行は**例外も出さず1行黙って欠落**する。
  processed_breaking.jsonl は速報の dedup キー、cost_ledger.jsonl は API 費の台帳で、
  黙って欠けると「分析の前提が壊れているのに気付かない」状態になる
  ([[api-cost-measurement-layer-pitfalls]] と同じ構図)。

  python3 -c "from lib.jsonl_integrity import find_broken; print(find_broken())"
"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SCAN_DIRS = [BASE / "logs", BASE / "data"]


def scan_file(path) -> int:
    """1ファイルの破損行数を返す。読めない/無い場合は 0(検知器が本体を止めない)。"""
    path = Path(path)
    bad = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    json.loads(line)
                except Exception:
                    bad += 1
    except OSError:
        return 0
    return bad


def find_broken(dirs=None):
    """[(Path, 破損行数)] を返す。健全なら空リスト。"""
    dirs = SCAN_DIRS if dirs is None else [Path(d) for d in dirs]
    out = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.jsonl")):
            n = scan_file(p)
            if n:
                out.append((p, n))
    return out
