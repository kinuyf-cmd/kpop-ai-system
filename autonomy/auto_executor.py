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
DIRECTIVES_PATH = BASE_DIR / "config" / "agent_directives.json"
RELOAD_HISTORY_PATH = BASE_DIR / "data" / "config_reload_history.jsonl"
RELOAD_FLAG_PATH = Path("/tmp/kpop_config_reload_pending.flag")


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
    for pattern in [r"成功率(\d+)%", r"success rate[:\s]+(\d+)%", r"(\d+)%\s*(?:成功|success)"]:
        m = re.search(pattern, reason, re.IGNORECASE)
        if m:
            return float(m.group(1))
    return None


def classify_proposal(proposal: dict) -> str:
    """
    Classify a proposal into green/yellow/red zone.

    Rules (v2 - safety_class aware):
    - human_review_required=True or safety_class=REVIEW → red
    - pm2, deletion, main merge related → red
    - safety_class=SAFE + (prompt_fix|timeout_fix|monitor_continue) → green
    - monitor_continue → green
    - prompt_fix with success rate <60% → green
    - prompt_fix with success rate >=60% → yellow
    - timeout_fix with safety_class=SAFE → green
    - Default → yellow
    """
    improvement_type = proposal.get("improvement_type", "")
    reason = proposal.get("reason", "")
    human_review = proposal.get("human_review_required", False)
    safety_class = proposal.get("safety_class", "")

    # Red zone: human review required or dangerous actions
    if human_review or safety_class == "REVIEW":
        return "red"

    dangerous_keywords = ["pm2", "削除", "delete", "main マージ", "main merge"]
    proposed = proposal.get("proposed_change", "").lower()
    for kw in dangerous_keywords:
        if kw.lower() in proposed:
            return "red"

    # Green zone: safety_class=SAFE promotes safe improvement types
    if safety_class == "SAFE":
        if improvement_type in ("prompt_fix", "timeout_fix", "monitor_continue"):
            return "green"

    # Green zone: monitor_continue (always green regardless of safety_class)
    if improvement_type == "monitor_continue":
        return "green"

    # Prompt fix classification (fallback for records without safety_class)
    if improvement_type == "prompt_fix":
        rate = extract_success_rate(reason)
        if rate is not None and rate < 60:
            return "green"
        else:
            return "yellow"

    # Timeout fix without safety_class → yellow (config change, needs review)
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


def _agent_key(target_agent: str) -> str:
    """Derive a config key from a target_agent name.

    Tries to find an existing key in agent_directives.json that matches
    the target_agent display name.  Falls back to a slugified version.
    """
    # Mapping of known Japanese display names to config keys
    known_map = {
        "バタフリー": "butterfree",
        "デオキシス（K-POP編集長）": "deoxys_kpop",
        "メタモン（K-POPリライト）": "metamon_kpop",
        "X投稿": "x_post",
    }
    if target_agent in known_map:
        return known_map[target_agent]
    # fallback: lowercase ascii-safe slug
    return target_agent.lower().replace(" ", "_").replace("（", "_").replace("）", "")


def _record_reload_history(agent: str, change_type: str, old_value: str, new_value: str, source: str):
    """Append a record to data/config_reload_history.jsonl."""
    RELOAD_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "change_type": change_type,
        "old_value": (old_value or "")[:300],
        "new_value": (new_value or "")[:300],
        "source": source,
    }
    with open(RELOAD_HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _set_config_reload_flag():
    """Write a flag file so pipeline scripts know to reload config."""
    with open(RELOAD_FLAG_PATH, "w", encoding="utf-8") as f:
        f.write(datetime.now(timezone.utc).isoformat() + "\n")


def execute_green_proposal(proposal: dict) -> bool:
    """Actually apply a GREEN-zone proposal.

    Returns True if a config change was made, False otherwise.
    """
    improvement_type = proposal.get("improvement_type", "")
    target_agent = proposal.get("target_agent", "(system)")
    proposed_change = proposal.get("proposed_change", "")

    if improvement_type == "monitor_continue":
        # No config change needed - just observation
        print(f"    -> monitor_continue: no config change needed for {target_agent}")
        return False

    if improvement_type not in ("prompt_fix", "timeout_fix"):
        print(f"    -> unknown improvement_type '{improvement_type}', skipping execution")
        return False

    # Load current directives
    try:
        directives_data = load_json(DIRECTIVES_PATH)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"    -> ERROR: cannot load {DIRECTIVES_PATH}: {e}", file=sys.stderr)
        return False

    agent_directives = directives_data.get("agent_directives", {})
    key = _agent_key(target_agent)

    old_entry = agent_directives.get(key, {})
    old_value = ""

    if improvement_type == "prompt_fix":
        old_value = old_entry.get("action", "")
        # Build updated entry preserving existing fields
        updated_entry = dict(old_entry) if old_entry else {}
        updated_entry.update({
            "action": proposed_change,
            "set_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "source": "auto_executor_green",
            "target_agent": target_agent,
        })
        agent_directives[key] = updated_entry
        change_type = "prompt_fix"

    elif improvement_type == "timeout_fix":
        old_value = json.dumps(old_entry.get("timeout", old_entry.get("action", "")), ensure_ascii=False)
        updated_entry = dict(old_entry) if old_entry else {}
        updated_entry.update({
            "action": proposed_change,
            "set_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "source": "auto_executor_green",
            "target_agent": target_agent,
        })
        agent_directives[key] = updated_entry
        change_type = "timeout_fix"

    # Write back
    directives_data["agent_directives"] = agent_directives
    try:
        with open(DIRECTIVES_PATH, "w", encoding="utf-8") as f:
            json.dump(directives_data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"    -> applied {change_type} to {key} in agent_directives.json")
    except Exception as e:
        print(f"    -> ERROR writing {DIRECTIVES_PATH}: {e}", file=sys.stderr)
        return False

    # Record history and set reload flag
    _record_reload_history(
        agent=target_agent,
        change_type=change_type,
        old_value=old_value,
        new_value=proposed_change,
        source=proposal.get("source_action_type", "auto_executor"),
    )
    _set_config_reload_flag()

    return True


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
    config_changed = False
    print("--- GREEN ZONE (auto-applied) ---")
    for p in results["green"]:
        agent = p.get("target_agent", "(system)")
        print(f"  [AUTO] {p['improvement_type']} | {agent} | {p['proposed_change'][:60]}")
        if not args.dry_run:
            applied = execute_green_proposal(p)
            action = "auto-applied" if applied else "auto-applied-noop"
            log_execution(p, "green", action)
            if applied:
                config_changed = True

    if config_changed:
        print(f"\n  Config reload flag set at {RELOAD_FLAG_PATH}")

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
