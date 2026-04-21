#!/usr/bin/env python3
"""Weekly Autonomy Report Generator - summarizes learning loop activity."""

import json
import sys
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter

BASE_DIR = Path("/home/aiuser/kpop-ai-system")
LEARNING_HISTORY_PATH = BASE_DIR / "logs" / "learning_history.jsonl"
EXECUTIONS_LOG = BASE_DIR / "logs" / "autonomy_executions.jsonl"
REPORT_OUTPUT = BASE_DIR / "reports" / "autonomy_weekly.md"


def load_jsonl(path, days=7):
    """Load JSONL entries from the last N days."""
    if not path.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = []

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts_str = entry.get("timestamp") or entry.get("ts", "")
                ts = _parse_ts(ts_str)
                if ts and ts >= cutoff:
                    entries.append(entry)
            except (json.JSONDecodeError, KeyError):
                continue

    return entries


def _parse_ts(ts_str):
    """Parse timestamp string to datetime."""
    if not ts_str:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ):
        try:
            dt = datetime.strptime(ts_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def generate_report(days=7):
    """Generate the weekly autonomy report as markdown."""
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    week_end = now.strftime("%Y-%m-%d")

    # Load data
    history = load_jsonl(LEARNING_HISTORY_PATH, days=days)
    executions = load_jsonl(EXECUTIONS_LOG, days=days)

    # Categorize
    auto_applied = [h for h in history if h.get("applied") is True]
    notified = [h for h in history if h.get("decision") == "notified_pending"]
    needs_review = [h for h in history if h.get("decision") == "needs_review"]
    failed = [h for h in history if h.get("decision") == "apply_failed"]

    # Success rate
    total_proposals = len(history)
    successful = len(auto_applied) + len(notified)
    success_rate = (successful / total_proposals * 100) if total_proposals > 0 else 0

    # Build report
    lines = []
    lines.append(f"# Autonomy Weekly Report")
    lines.append(f"")
    lines.append(f"**Period**: {week_start} ~ {week_end}")
    lines.append(f"**Generated**: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")

    # Summary
    lines.append(f"## Summary")
    lines.append(f"")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Problems detected | {total_proposals} |")
    lines.append(f"| Auto-applied (green_zone) | {len(auto_applied)} |")
    lines.append(f"| Notified/pending (yellow_zone) | {len(notified)} |")
    lines.append(f"| Needs review | {len(needs_review)} |")
    lines.append(f"| Apply failed | {len(failed)} |")
    lines.append(f"| Autonomous executions | {len(executions)} |")
    lines.append(f"| Success rate | {success_rate:.1f}% |")
    lines.append(f"")

    # Problems detected
    if history:
        lines.append(f"## Problems Detected This Week")
        lines.append(f"")
        for h in history[:20]:
            pattern = h.get("error_pattern", "unknown")
            count = h.get("count", 0)
            fix_type = h.get("fix_type", "unknown")
            lines.append(f"- **{pattern}** (x{count}) - {fix_type}")
        lines.append(f"")

    # Auto-applied fixes
    if auto_applied:
        lines.append(f"## Auto-Applied Fixes")
        lines.append(f"")
        for h in auto_applied:
            ts = h.get("timestamp", "")[:10]
            desc = h.get("proposed_fix", "")
            improvement = h.get("shadow_test_result", 0)
            lines.append(f"- [{ts}] {desc} (improvement: {improvement:.0%})")
        lines.append(f"")

    # Notified (Yuta-approved)
    if notified:
        lines.append(f"## Pending Approval (Yellow Zone)")
        lines.append(f"")
        for h in notified:
            ts = h.get("timestamp", "")[:10]
            desc = h.get("proposed_fix", "")
            improvement = h.get("shadow_test_result", 0)
            lines.append(f"- [{ts}] {desc} (improvement: {improvement:.0%})")
        lines.append(f"")

    # Needs review
    if needs_review:
        lines.append(f"## Needs Manual Review")
        lines.append(f"")
        for h in needs_review[:10]:
            pattern = h.get("error_pattern", "unknown")
            desc = h.get("proposed_fix", "")
            lines.append(f"- **{pattern}**: {desc}")
        if len(needs_review) > 10:
            lines.append(f"- ... and {len(needs_review) - 10} more")
        lines.append(f"")

    # Autonomous executions summary
    if executions:
        lines.append(f"## Autonomous Executions")
        lines.append(f"")
        zone_counts = Counter(e.get("zone", "unknown") for e in executions)
        status_counts = Counter(e.get("status", "unknown") for e in executions)
        lines.append(f"| Zone | Count |")
        lines.append(f"|------|-------|")
        for zone, count in zone_counts.most_common():
            lines.append(f"| {zone} | {count} |")
        lines.append(f"")
        lines.append(f"| Status | Count |")
        lines.append(f"|--------|-------|")
        for status, count in status_counts.most_common():
            lines.append(f"| {status} | {count} |")
        lines.append(f"")

    # Success rate trend
    lines.append(f"## Success Rate Trend")
    lines.append(f"")
    lines.append(f"Current week: **{success_rate:.1f}%** ({successful}/{total_proposals} proposals actionable)")
    lines.append(f"")
    if total_proposals == 0:
        lines.append(f"No proposals this week - system may be stable or learning loop not yet active.")
    elif success_rate >= 80:
        lines.append(f"Excellent autonomous handling rate.")
    elif success_rate >= 50:
        lines.append(f"Good progress. Some patterns still need manual intervention.")
    else:
        lines.append(f"Many patterns need review. Consider expanding green_zone coverage.")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"*Generated by autonomy/weekly_report.py*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Weekly Autonomy Report Generator")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print report to stdout instead of writing file")
    parser.add_argument("--days", type=int, default=7,
                        help="Report period in days (default: 7)")
    args = parser.parse_args()

    report = generate_report(days=args.days)

    if args.dry_run:
        print(report)
    else:
        REPORT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        REPORT_OUTPUT.write_text(report, encoding="utf-8")
        print(f"[Weekly Report] Written to {REPORT_OUTPUT}")


if __name__ == "__main__":
    main()
