#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ディスク残量ガード(2026-08-31)。

背景:
  2026-08-29 に `/` が満杯になり、collect-all の 14 collector 中 8 件が
  `OSError: [Errno 28] No space left on device` で落ちた。
  collector は「1つ失敗しても他は続行」する設計なので全体は exit 0 で終わり、
  **その日の記事収集が欠損したことに誰も気付かなかった**
  ([[collector-silent-zero-death-guard]] と同じ「静かな死」の系譜)。

  容量を食っているのは kpop 側ではない(kpop-ai-system は全体で 1.3G)。
  こちらで掃除できない以上、せめて **踏む前に鳴らす** のがこの層の役割。

使い方:
  from lib.disk_guard import check_disk
  level, msg = check_disk()   # ("PASS"|"WARN"|"FAIL", 表示文)

設計方針:
  - ガード自身が本体を止めない。計測に失敗したら PASS を返して黙って通す。
  - 判定は残量の絶対値(GB)。使用率%だとディスク総量が変わった時に意味が変わる。
"""
import shutil

# 閾値: 2026-08-29 の事故時は残 0、平常は 8G 前後で推移している。
# collect-all 1回分 + 画像処理の一時ファイルが数百MB規模なので、
# 2G を割ったら実害が出る手前とみなす。
WARN_GB = 5.0   # 掃除を検討すべき水準
FAIL_GB = 2.0   # 収集欠損が起きうる水準

MOUNT = "/"


def free_gb(path: str = MOUNT) -> float:
    """指定パスの残容量(GB)。計測不能なら -1。"""
    try:
        return shutil.disk_usage(path).free / 2**30
    except Exception:
        return -1.0


def check_disk(path: str = MOUNT):
    """(level, message) を返す。level は PASS/WARN/FAIL。

    計測できなかった場合は PASS(ガードが本体を止めないため)。
    """
    gb = free_gb(path)
    if gb < 0:
        return ("PASS", f"ディスク残量: 計測不能 ({path})")
    if gb < FAIL_GB:
        return ("FAIL", f"ディスク残量: 残{gb:.1f}GB — 収集欠損の恐れ(閾値{FAIL_GB}GB)")
    if gb < WARN_GB:
        return ("WARN", f"ディスク残量: 残{gb:.1f}GB — 要整理(閾値{WARN_GB}GB)")
    return ("PASS", f"ディスク残量: 残{gb:.1f}GB")
