#!/usr/bin/env python3
"""計測バグ由来の pending 提案を却下済みにマークする。

背景: tracker が theme を捨てていたため直近77件が 77/77 unknown になり、
      feedback_loop が「theme='unknown' は効果薄。enrich 対象から除外」を提案した。
      unknown は全件なので、これは実質「全記事を除外せよ」を意味する。却下する。

progress の過去行に theme が無い間、週次 feedback_loop は同じ提案を出し続ける
(3週後に窓から抜けて自然解消)。それまで本スクリプトを何度でも流せるよう、
既に rejects_ts で打ち消した提案は再検出しない(冪等)。

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
    """theme='unknown' の未却下 pending 提案を返す。

    jsonl は追記専用で元行の status は書き換わらない。既に rejects_ts で
    打ち消した提案を再検出すると、走らせるたびに却下レコードが増える。
    """
    if not os.path.exists(path):
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    rejected_ts = {d.get("rejects_ts") for d in records if d.get("status") == "rejected"}
    return [d for d in records
            if d.get("status") == "pending_owner_review"
            and d.get("theme") == "unknown"
            and d.get("ts") not in rejected_ts]


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
