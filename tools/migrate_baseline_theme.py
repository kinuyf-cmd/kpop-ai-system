#!/usr/bin/env python3
"""page_one_baseline.json に theme を後付けする(1回限りの移行)。

baseline_pos / baseline_clicks は絶対に書き換えない。theme のみ追加する。
実行前に必ずバックアップを取り、--dry-run で diff を目視すること。

使い方:
  venv_kpi/bin/python3 tools/migrate_baseline_theme.py --dry-run
  venv_kpi/bin/python3 tools/migrate_baseline_theme.py
"""
import os
import sys
import json
import copy
import shutil
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.page_one_tracker import BASELINE, _target_queries  # noqa: E402


def migrate(baseline, targets):
    """theme のみ後付けした新 baseline と更新件数を返す。入力は破壊しない。"""
    out = copy.deepcopy(baseline)
    n = 0
    for query, meta in out.get("queries", {}).items():
        meta["theme"] = targets.get(query, {}).get("theme", "unknown")
        n += 1
    return out, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="書き込まず差分のみ表示")
    args = ap.parse_args()

    if not os.path.exists(BASELINE):
        print(f"[migrate] baseline が無い: {BASELINE}", file=sys.stderr)
        return 1

    base = json.load(open(BASELINE, encoding="utf-8"))
    new, n = migrate(base, _target_queries())

    themes = {}
    for meta in new["queries"].values():
        themes[meta["theme"]] = themes.get(meta["theme"], 0) + 1
    print(f"[migrate] 対象 {n} クエリ / theme 分布: {themes}")

    if args.dry_run:
        print("[migrate] DRY-RUN — 書き込まない")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"{BASELINE}.bak_{stamp}"
    shutil.copy2(BASELINE, backup)
    print(f"[migrate] バックアップ: {backup}")

    json.dump(new, open(BASELINE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[migrate] theme を後付け: {n} クエリ → {BASELINE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
