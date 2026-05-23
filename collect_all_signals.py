#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全 RSS collector を1回で回す collect-all(2026-05-23 ソース多様化)。

背景: rebuild 後 soompi のみ cron 稼働で、移植した他 collector が自動実行されず
シグナルが soompi 単独だった。本スクリプトで全 RSS collector を順に実行し、
trend_signals.jsonl に複数ソースの signal を集める。breaking 生成 cron の前段に置く。

各 collector は lib.collectors.korean_base に依存し save_signals() で
data/trend_signals.jsonl に append(dedup は各 collector + 下流 cluster_dedup)。
1つが失敗しても他は続行(except で握って継続)。外部APIキー不要(RSS取得のみ)。

  python3 collect_all_signals.py
"""
import sys
import importlib
import traceback

sys.path.insert(0, "/home/aiuser/kpop-ai-system")

# 実績ある RSS collector(全て korean_base 依存・追加キー不要)。
# soompi は既存 cron でも回るが、collect-all に含めても dedup されるので無害。
COLLECTORS = [
    "soompi", "koreaboo", "allkpop", "mydaily", "osen",
    "kstyle", "koreaherald", "starnews", "newsen",
    "sportschosun", "xportsnews", "topstarnews", "wowkorea",
]


def main() -> int:
    total = 0
    ok = 0
    for name in COLLECTORS:
        mod_name = f"lib.collectors.{name}_collector"
        try:
            mod = importlib.import_module(mod_name)
            # 各 collector は main() を持つ(無ければ collect()/run() を試す)
            fn = getattr(mod, "main", None) or getattr(mod, "collect", None) or getattr(mod, "run", None)
            if fn is None:
                print(f"  [skip] {name}: 実行関数(main/collect/run)なし")
                continue
            n = fn()
            cnt = int(n) if isinstance(n, int) else 0
            total += cnt
            ok += 1
            print(f"  [ok] {name}: {cnt} signals")
        except Exception as e:
            print(f"  [fail] {name}: {type(e).__name__}: {str(e)[:80]}")
            # 1つの失敗で全体を止めない
            continue
    print(f"=== collect-all 完了: {ok}/{len(COLLECTORS)} collector・新規 signal 計 {total} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
