#!/usr/bin/env python3
"""
cost_daily_aggregator.py -- Daily aggregation of per-department API costs.
Reads data/cost_ledger.jsonl and outputs to data/cost_summary_daily.jsonl.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LEDGER_FILE = BASE / "data" / "cost_ledger.jsonl"
SUMMARY_FILE = BASE / "data" / "cost_summary_daily.jsonl"
ORG_CHART = BASE / "config" / "org_chart.json"

JST = timezone(timedelta(hours=9))


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def _get_department_labels() -> dict[str, str]:
    """Load department key -> label mapping from org_chart.json."""
    labels = {}
    if ORG_CHART.exists():
        try:
            org = json.loads(ORG_CHART.read_text(encoding="utf-8"))
            for key, info in org.get("departments", {}).items():
                labels[key] = info.get("label", key)
        except (json.JSONDecodeError, TypeError):
            pass
    labels["executive"] = "経営陣"
    labels["unknown"] = "不明"
    return labels


def aggregate_date(target_date: str | None = None) -> dict:
    """
    Aggregate a single day's costs from the ledger.

    Args:
        target_date: ISO date string (defaults to today).

    Returns:
        Daily summary dict ready for cost_summary_daily.jsonl.
    """
    if target_date is None:
        target_date = date.today().isoformat()

    entries = [e for e in _load_jsonl(LEDGER_FILE) if e.get("date") == target_date]
    labels = _get_department_labels()

    dept_agg: dict[str, dict] = defaultdict(
        lambda: {"usd": 0.0, "jpy": 0.0, "calls": 0, "input_tokens": 0, "output_tokens": 0}
    )
    agent_agg: dict[str, float] = defaultdict(float)

    for e in entries:
        dept = e.get("department", "unknown")
        agent = e.get("agent", "unknown")
        cost_usd = e.get("cost_usd", 0)
        cost_jpy = e.get("cost_jpy", 0)

        dept_agg[dept]["usd"] += cost_usd
        dept_agg[dept]["jpy"] += cost_jpy
        dept_agg[dept]["calls"] += 1
        dept_agg[dept]["input_tokens"] += e.get("input_tokens", 0)
        dept_agg[dept]["output_tokens"] += e.get("output_tokens", 0)

        agent_agg[agent] += cost_usd

    # Build department breakdowns with labels
    departments = {}
    for dept_key, agg in dept_agg.items():
        departments[dept_key] = {
            "label": labels.get(dept_key, dept_key),
            "cost_usd": round(agg["usd"], 4),
            "cost_jpy": round(agg["jpy"], 2),
            "api_calls": agg["calls"],
            "input_tokens": agg["input_tokens"],
            "output_tokens": agg["output_tokens"],
        }

    # Top 5 agents by cost
    top_agents = sorted(agent_agg.items(), key=lambda x: -x[1])[:5]
    top_agents_list = [
        {"agent": agent, "cost_usd": round(cost, 4)}
        for agent, cost in top_agents
    ]

    total_usd = round(sum(d["cost_usd"] for d in departments.values()), 4)
    total_jpy = round(sum(d["cost_jpy"] for d in departments.values()), 2)

    return {
        "date": target_date,
        "aggregated_at": datetime.now(JST).isoformat(),
        "total_usd": total_usd,
        "total_jpy": total_jpy,
        "total_api_calls": len(entries),
        "departments": departments,
        "top_agents": top_agents_list,
    }


def run_aggregation(target_date: str | None = None) -> dict:
    """
    Run aggregation for a date and append to cost_summary_daily.jsonl.
    Skips if this date already exists in the summary file.
    """
    if target_date is None:
        target_date = date.today().isoformat()

    # Check if already aggregated
    existing = _load_jsonl(SUMMARY_FILE)
    existing_dates = {e.get("date") for e in existing}
    if target_date in existing_dates:
        print(f"  [skip] {target_date} already aggregated")
        return [e for e in existing if e.get("date") == target_date][0]

    summary = aggregate_date(target_date)

    # Append
    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SUMMARY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")

    print(f"  [done] {target_date}: ${summary['total_usd']:.4f} "
          f"({summary['total_api_calls']} calls, "
          f"{len(summary['departments'])} depts)")
    return summary


def backfill(days: int = 7):
    """Aggregate the last N days (backfill mode)."""
    today = date.today()
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        run_aggregation(d)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Daily cost aggregator")
    parser.add_argument("--date", type=str, default=None,
                        help="Target date (YYYY-MM-DD), defaults to today")
    parser.add_argument("--backfill", type=int, default=0,
                        help="Backfill last N days")
    args = parser.parse_args()

    now_s = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    print(f"[{now_s}] Cost daily aggregator")

    if args.backfill > 0:
        backfill(args.backfill)
    else:
        run_aggregation(args.date)


if __name__ == "__main__":
    main()
