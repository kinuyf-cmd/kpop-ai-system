#!/usr/bin/env python3
"""
Autonomy Auto-Executor
Reads CEO improvement proposals, classifies them by autonomy zone,
and executes/notifies accordingly.
"""

import json
import sys
import os
import argparse
import requests
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
QUEUE_PATH = BASE_DIR / "logs" / "ceo_improvement_queue.jsonl"
MATRIX_PATH = BASE_DIR / "config" / "autonomy_matrix.json"
WEBHOOKS_PATH = BASE_DIR / "config" / "discord_webhooks.json"
EXECUTIONS_LOG = BASE_DIR / "logs" / "autonomy_executions.jsonl"


def load_jsonl(path: Path) -> list:
    """Load a JSONL file into a list of dicts."""
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def load_json(path: Path) -> dict:
    """Load a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_success_rate(reason: str) -> float | None:
    """Extract success rate percentage from reason text like '成功率83%'."""
    import re
    m = re.search(r"成功率(\d+)%", reason)
    if m:
        return float(m.group(1))
    return None


def classify_proposal(proposal: dict) -> str:
    """
    Classify a proposal into green/yellow/red zone.

    Rules:
    - monitor_continue → green
    - prompt_fix with success rate <60% → green
    - prompt_fix with success rate >=60% → yellow
    - timeout_fix → yellow (config change)
    - human_review_required=True → red
    - pm2, deletion, main merge related → red
    """
    improvement_type = proposal.get("improvement_type", "")
    source_action = proposal.get("source_action_type", "")
    reason = proposal.get("reason", "")
    human_review = proposal.get("human_review_required", False)

    # Red zone: human review required or dangerous actions
    if human_review:
        return "red"

    dangerous_keywords = ["pm2", "削除", "delete", "main マージ", "main merge"]
    proposed = proposal.get("proposed_change", "").lower()
    for kw in dangerous_keywords:
        if kw.lower() in proposed:
            return "red"

    # Green zone: monitor_continue
    if improvement_type == "monitor_continue":
        return "green"

    # Prompt fix classification
    if improvement_type == "prompt_fix":
        rate = extract_success_rate(reason)
        if rate is not None and rate < 60:
            return "green"
        else:
            return "yellow"

    # Timeout fix = config change → yellow
    if improvement_type == "timeout_fix":
        return "yellow"

    # Default: yellow (safer default)
    return "yellow"


def send_discord(webhook_url: str, message: str, dry_run: bool = False) -> bool:
    """Send a message to Discord webhook."""
    if dry_run:
        return True
    try:
        resp = requests.post(
            webhook_url,
            json={"content": message[:2000]},
            timeout=10
        )
        return resp.status_code in (200, 204)
    except Exception as e:
        print(f"  [ERROR] Discord送信失敗: {e}", file=sys.stderr)
        return False


def log_execution(proposal: dict, zone: str, action_taken: str):
    """Append execution record to autonomy_executions.jsonl."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "zone": zone,
        "action_taken": action_taken,
        "target_agent": proposal.get("target_agent", ""),
        "improvement_type": proposal.get("improvement_type", ""),
        "proposed_change": proposal.get("proposed_change", ""),
        "source_action_type": proposal.get("source_action_type", ""),
    }
    with open(EXECUTIONS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Autonomy Auto-Executor")
    parser.add_argument("--dry-run", action="store_true",
                        help="Classify and report only, no Discord or execution")
    args = parser.parse_args()

    # Load data
    if not QUEUE_PATH.exists():
        print(f"ERROR: Queue file not found: {QUEUE_PATH}", file=sys.stderr)
        sys.exit(1)

    proposals = load_jsonl(QUEUE_PATH)
    matrix = load_json(MATRIX_PATH)
    webhooks = load_json(WEBHOOKS_PATH)

    daily_webhook = webhooks.get("daily_ceo_report", "")
    urgent_webhook = webhooks.get("urgent_errors", "")

    # Classify all proposals
    results = {"green": [], "yellow": [], "red": []}
    for p in proposals:
        zone = classify_proposal(p)
        results[zone].append(p)

    # Report
    print(f"=== Autonomy Executor {'[DRY-RUN]' if args.dry_run else ''} ===")
    print(f"Total proposals: {len(proposals)}")
    print(f"  GREEN  (auto-execute): {len(results['green'])}")
    print(f"  YELLOW (async notify): {len(results['yellow'])}")
    print(f"  RED    (owner approval): {len(results['red'])}")
    print()

    # Process GREEN zone
    print("--- GREEN ZONE (auto-applied) ---")
    for p in results["green"]:
        agent = p.get("target_agent", "(system)")
        print(f"  [AUTO] {p['improvement_type']} | {agent} | {p['proposed_change'][:60]}")
        if not args.dry_run:
            log_execution(p, "green", "auto-applied")

    # Process YELLOW zone
    print("\n--- YELLOW ZONE (async notify) ---")
    for p in results["yellow"]:
        agent = p.get("target_agent", "(system)")
        print(f"  [NOTIFY] {p['improvement_type']} | {agent} | {p['proposed_change'][:60]}")
        if not args.dry_run:
            log_execution(p, "yellow", "notified")
            msg = (f"[Yellow Zone] {p['improvement_type']} - {agent}\n"
                   f"理由: {p.get('reason', '')[:200]}\n"
                   f"提案: {p.get('proposed_change', '')[:200]}")
            send_discord(daily_webhook, msg, dry_run=args.dry_run)

    # Process RED zone
    print("\n--- RED ZONE (owner approval required) ---")
    for p in results["red"]:
        agent = p.get("target_agent", "(system)")
        print(f"  [BLOCKED] {p['improvement_type']} | {agent} | {p['proposed_change'][:60]}")
        if not args.dry_run:
            log_execution(p, "red", "queued_for_approval")
            msg = (f"[RED ZONE - 承認必須] {p['improvement_type']} - {agent}\n"
                   f"理由: {p.get('reason', '')[:200]}\n"
                   f"提案: {p.get('proposed_change', '')[:200]}\n"
                   f"⚠️ Yuta承認待ち")
            send_discord(urgent_webhook, msg, dry_run=args.dry_run)

    # Generate summary for dry-run output
    if args.dry_run:
        summary_path = Path("/tmp/phase6_autonomy_first_run.md")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("# Phase 6 Autonomy - First Run (Dry-Run)\n\n")
            f.write(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"**Total proposals**: {len(proposals)}\n\n")
            f.write(f"| Zone | Count |\n|------|-------|\n")
            f.write(f"| GREEN (auto-execute) | {len(results['green'])} |\n")
            f.write(f"| YELLOW (async notify) | {len(results['yellow'])} |\n")
            f.write(f"| RED (owner approval) | {len(results['red'])} |\n\n")

            f.write("## GREEN ZONE (auto-applied)\n\n")
            for p in results["green"]:
                agent = p.get("target_agent", "(system)")
                f.write(f"- **{p['improvement_type']}** | {agent} | {p['proposed_change'][:80]}\n")

            f.write("\n## YELLOW ZONE (async notify)\n\n")
            for p in results["yellow"]:
                agent = p.get("target_agent", "(system)")
                rate = extract_success_rate(p.get("reason", ""))
                rate_str = f" (成功率{int(rate)}%)" if rate else ""
                f.write(f"- **{p['improvement_type']}** | {agent}{rate_str} | {p['proposed_change'][:80]}\n")

            f.write("\n## RED ZONE (owner approval required)\n\n")
            for p in results["red"]:
                agent = p.get("target_agent", "(system)")
                f.write(f"- **{p['improvement_type']}** | {agent} | {p['reason'][:80]}\n")
                f.write(f"  - 提案: {p['proposed_change'][:100]}\n")

            f.write(f"\n---\n*Generated by auto_executor.py --dry-run*\n")

        print(f"\nDry-run summary saved to: {summary_path}")


if __name__ == "__main__":
    main()
