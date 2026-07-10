#!/usr/bin/env python3
"""計測バグ由来の pending 提案を却下済みにマークする(1回限り)。

背景: tracker が theme を捨てていたため直近77件が 77/77 unknown になり、
      feedback_loop が「theme='unknown' は効果薄。enrich 対象から除外」を提案した。
      unknown は全件なので、これは実質「全記事を除外せよ」を意味する。却下する。

jsonl は追記専用。既存行は書き換えず、却下レコードを追記する。

使い方:
  venv_kpi/bin/python3 tools/reject_stale_proposals.py --dry-run
  venv_kpi/bin/python3 tools/reject_stale_proposals.py
"""
import os
import sys
import json
import argparse
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROPOSALS = os.path.join(BASE_DIR, "logs", "seo_config_proposals.jsonl")

REASON = ("計測バグ由来。tracker が theme を破棄していたため全件 unknown だった。"
          "2026-07-10 の tracker 修正で theme は実値に分かれる。"
          "設計: docs/superpowers/specs/2026-07-10-page-one-tracker-measurement-fix-design.md")


def find_stale(path):
    """theme='unknown' の pending 提案を返す。"""
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("status") == "pending_owner_review" and d.get("theme") == "unknown":
                out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    stale = find_stale(PROPOSALS)
    print(f"[reject] 却下対象: {len(stale)} 件")
    for d in stale:
        print(f"  {d.get('ts')} theme={d.get('theme')} n={d.get('observed', {}).get('n')}")

    if not stale:
        return 0
    if args.dry_run:
        print("[reject] DRY-RUN — 追記しない")
        return 0

    now = datetime.now(timezone.utc).isoformat()
    with open(PROPOSALS, "a", encoding="utf-8") as f:
        for d in stale:
            f.write(json.dumps({
                "ts": now,
                "status": "rejected",
                "rejects_ts": d.get("ts"),
                "theme": d.get("theme"),
                "reason": REASON,
            }, ensure_ascii=False) + "\n")
    print(f"[reject] {len(stale)} 件を却下済みとして追記")
    return 0


if __name__ == "__main__":
    sys.exit(main())
