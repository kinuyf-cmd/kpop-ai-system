#!/usr/bin/env python3
"""Autonomous Learning Loop - detects recurring errors and proposes/applies fixes."""

import json
import os
import sys
import argparse
import re
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter, defaultdict

BASE_DIR = Path("/home/aiuser/kpop-ai-system")
GARDEVOIR_LOG = BASE_DIR / "logs" / "gardevoir_hook.jsonl"
QUALITY_LOG = BASE_DIR / "logs" / "quality_issues.jsonl"
ERROR_PATTERNS_PATH = BASE_DIR / "config" / "error_patterns.json"
AUTONOMY_MATRIX_PATH = BASE_DIR / "config" / "autonomy_matrix.json"
LEARNING_HISTORY_PATH = BASE_DIR / "logs" / "learning_history.jsonl"
LEARNING_APPLIED_PATH = BASE_DIR / "logs" / "learning_applied.jsonl"

DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1490413245561831576/qVFL6bUBVxVnqcJxBiwaTGueezDUO8fltoCQbl-_uQ5Om6uTOlyVZ_7UNwomZ_0dFUIv"

# Patterns that indicate prompt/LLM issues
PROMPT_ISSUE_PATTERNS = [
    r"メタ応答",
    r"English\s+leak",
    r"LLM残骸",
    r"meta.?commentary",
    r"ファクトチェック結果",
    r"書き込み権限",
    r"ウェブフェッチ",
    r"hit your limit",
    r"以下(が|に)改善内容",
]

# Patterns that indicate input validation issues
VALIDATION_ISSUE_PATTERNS = [
    r"文字数(不足|超過)",
    r"h2(不足|見出し)",
    r"内部リンク不足",
    r"BLOCK",
    r"スコア.*閾値",
]

# Patterns that indicate pipeline flow issues
PIPELINE_ISSUE_PATTERNS = [
    r"パイプライン停止",
    r"exit\s*\(\s*1\s*\)",
    r"連続BLOCK",
    r"cascade",
    r"stall",
]


def load_recent_errors(days=7):
    """Load errors from the last N days from all sources."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    errors = []

    # Load gardevoir hook failures
    if GARDEVOIR_LOG.exists():
        with open(GARDEVOIR_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = _parse_ts(entry.get("ts", ""))
                    if ts and ts >= cutoff:
                        if entry.get("verdict") in ("ERROR", "HARD_FAIL"):
                            errors.append({
                                "source": "gardevoir_hook",
                                "ts": entry["ts"],
                                "type": entry.get("verdict", "ERROR"),
                                "detail": entry.get("must_fix", ""),
                                "score": entry.get("score", 0),
                                "agent": entry.get("agent", "gardevoir_hook_critic"),
                            })
                except (json.JSONDecodeError, KeyError):
                    continue

    # Load quality issues
    if QUALITY_LOG.exists():
        with open(QUALITY_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = _parse_ts(entry.get("ts", ""))
                    if ts and ts >= cutoff:
                        for problem in entry.get("problems", []):
                            errors.append({
                                "source": "quality_issues",
                                "ts": entry["ts"],
                                "type": "QUALITY",
                                "detail": problem,
                                "score": entry.get("score", 0),
                                "agent": "quality_audit",
                                "post_id": entry.get("post_id"),
                            })
                except (json.JSONDecodeError, KeyError):
                    continue

    return errors


def _parse_ts(ts_str):
    """Parse various timestamp formats to datetime."""
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


def _extract_ngrams(text, n=3):
    """Extract character n-grams from text for pattern matching."""
    if not text or len(text) < n:
        return [text] if text else []
    return [text[i:i+n] for i in range(len(text) - n + 1)]


def detect_recurring_patterns(errors, min_count=3):
    """Find error patterns that occurred min_count+ times in the window."""
    # Group by normalized detail pattern
    pattern_groups = defaultdict(list)

    for err in errors:
        detail = err.get("detail", "")
        # Normalize: extract the core pattern by removing numbers/IDs
        normalized = re.sub(r"\d+", "N", detail)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        key = f"{err['type']}::{normalized[:80]}"
        pattern_groups[key].append(err)

    # Filter to recurring patterns
    recurring = []
    for key, group in pattern_groups.items():
        if len(group) >= min_count:
            recurring.append({
                "pattern_key": key,
                "count": len(group),
                "examples": group[:5],
                "first_seen": min(e["ts"] for e in group),
                "last_seen": max(e["ts"] for e in group),
                "error_type": group[0]["type"],
                "detail_sample": group[0].get("detail", ""),
            })

    # Sort by count descending
    recurring.sort(key=lambda x: x["count"], reverse=True)
    return recurring


def _classify_issue(detail):
    """Classify an error detail into a fix category."""
    for pat in PROMPT_ISSUE_PATTERNS:
        if re.search(pat, detail, re.IGNORECASE):
            return "prompt_issue"
    for pat in VALIDATION_ISSUE_PATTERNS:
        if re.search(pat, detail, re.IGNORECASE):
            return "validation_issue"
    for pat in PIPELINE_ISSUE_PATTERNS:
        if re.search(pat, detail, re.IGNORECASE):
            return "pipeline_flow"
    return "unknown"


def generate_fix_proposal(pattern):
    """Generate a proposed fix for a recurring pattern."""
    detail = pattern.get("detail_sample", "")
    category = _classify_issue(detail)

    proposal = {
        "pattern_key": pattern["pattern_key"],
        "category": category,
        "count": pattern["count"],
        "detail_sample": detail,
    }

    if category == "prompt_issue":
        # Propose agent directive update
        proposal["fix_type"] = "agent_directive_update"
        proposal["description"] = (
            f"Add filter pattern to agent directives: '{detail[:60]}'"
        )
        proposal["action"] = {
            "file": "config/auto_directives.json",
            "operation": "add_pattern",
            "pattern": detail[:100],
        }
    elif category == "validation_issue":
        # Propose error_patterns.json addition
        proposal["fix_type"] = "error_pattern_addition"
        proposal["description"] = (
            f"Register new validation pattern in error_patterns.json: '{detail[:60]}'"
        )
        proposal["action"] = {
            "file": "config/error_patterns.json",
            "operation": "add_pattern",
            "pattern_key": re.sub(r"[^a-z0-9_]", "_", detail[:30].lower()),
            "example": detail,
        }
    elif category == "pipeline_flow":
        # Propose pipeline guard
        proposal["fix_type"] = "pipeline_guard"
        proposal["description"] = (
            f"Add pipeline guard for: '{detail[:60]}'"
        )
        proposal["action"] = {
            "file": "lib/post_guard.py",
            "operation": "add_guard",
            "condition": detail[:100],
        }
    else:
        proposal["fix_type"] = "needs_investigation"
        proposal["description"] = f"Unknown pattern requires manual investigation: '{detail[:60]}'"
        proposal["action"] = None

    return proposal


def shadow_test(proposal, recent_failures):
    """
    Shadow-test a proposed fix against recent failures.
    Returns improvement rate (0.0 to 1.0).
    """
    if not proposal.get("action") or not recent_failures:
        return 0.0

    category = proposal.get("category", "")
    detail_sample = proposal.get("detail_sample", "")

    # Simulate: would this fix have caught the failures?
    caught = 0
    total = len(recent_failures)

    for failure in recent_failures:
        failure_detail = failure.get("detail", "")

        if category == "prompt_issue":
            # Check if the pattern would match
            pattern = proposal["action"].get("pattern", "")
            if pattern and _pattern_matches(pattern, failure_detail):
                caught += 1

        elif category == "validation_issue":
            # Check if the validation pattern would have blocked
            normalized_proposal = re.sub(r"\d+", "N", detail_sample)
            normalized_failure = re.sub(r"\d+", "N", failure_detail)
            if _ngram_similarity(normalized_proposal, normalized_failure) > 0.5:
                caught += 1

        elif category == "pipeline_flow":
            # Check if the guard condition matches
            condition = proposal["action"].get("condition", "")
            if condition and _pattern_matches(condition, failure_detail):
                caught += 1

    return caught / total if total > 0 else 0.0


def _pattern_matches(pattern, text):
    """Check if a pattern (as substring or regex) matches text."""
    if not pattern or not text:
        return False
    # Try substring match first
    if pattern[:30] in text:
        return True
    # Try regex
    try:
        if re.search(re.escape(pattern[:50]), text):
            return True
    except re.error:
        pass
    return False


def _ngram_similarity(a, b, n=3):
    """Compute n-gram similarity between two strings."""
    if not a or not b:
        return 0.0
    ngrams_a = set(_extract_ngrams(a, n))
    ngrams_b = set(_extract_ngrams(b, n))
    if not ngrams_a or not ngrams_b:
        return 0.0
    intersection = ngrams_a & ngrams_b
    union = ngrams_a | ngrams_b
    return len(intersection) / len(union) if union else 0.0


def _get_autonomy_zone(action_description):
    """Determine if an action is green_zone, yellow_zone, or red_zone."""
    if not AUTONOMY_MATRIX_PATH.exists():
        return "red_zone"

    try:
        matrix = json.loads(AUTONOMY_MATRIX_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "red_zone"

    green_actions = matrix.get("green_zone_autonomous", {}).get("allowed_actions", [])
    yellow_actions = matrix.get("yellow_zone_async_notify", {}).get("actions", [])

    desc_lower = action_description.lower()

    # Check green zone
    for action in green_actions:
        if any(keyword in desc_lower for keyword in action.lower().split("/")):
            return "green_zone"

    # Check yellow zone
    for action in yellow_actions:
        if any(keyword in desc_lower for keyword in action.lower().split("/")):
            return "yellow_zone"

    return "red_zone"


def apply_fix(proposal):
    """
    Apply a fix to the system.
    Returns True if applied successfully.
    """
    action = proposal.get("action")
    if not action:
        return False

    fix_type = proposal.get("fix_type", "")
    target_file = BASE_DIR / action.get("file", "")

    try:
        if fix_type == "error_pattern_addition" and target_file.exists():
            data = json.loads(target_file.read_text(encoding="utf-8"))
            patterns = data.get("patterns", {})
            pattern_key = action.get("pattern_key", f"auto_{int(datetime.now().timestamp())}")
            if pattern_key not in patterns:
                patterns[pattern_key] = {
                    "count": proposal.get("count", 1),
                    "last_seen": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "example": action.get("example", ""),
                    "fix": "Auto-detected by learning_loop. Investigation needed.",
                    "agent": "learning_loop",
                }
                data["patterns"] = patterns
                data["updated_at"] = datetime.now(timezone.utc).isoformat()
                target_file.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                return True

        elif fix_type == "agent_directive_update" and target_file.exists():
            data = json.loads(target_file.read_text(encoding="utf-8"))
            # Add pattern to block list if structure supports it
            if "filter_patterns" not in data:
                data["filter_patterns"] = []
            pattern = action.get("pattern", "")
            if pattern and pattern not in data["filter_patterns"]:
                data["filter_patterns"].append(pattern)
                target_file.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                return True

        # pipeline_guard and others: log proposal but don't auto-modify code
        return False

    except (json.JSONDecodeError, OSError, KeyError) as e:
        print(f"[ERROR] apply_fix failed: {e}", file=sys.stderr)
        return False


def notify_discord(message, webhook_url=None):
    """Send a notification to Discord."""
    url = webhook_url or DISCORD_WEBHOOK
    payload = {
        "content": message[:2000],
        "username": "Learning Loop",
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code in (200, 204)
    except requests.RequestException as e:
        print(f"[WARN] Discord notification failed: {e}", file=sys.stderr)
        return False


def _log_history(entry):
    """Append an entry to learning_history.jsonl."""
    LEARNING_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEARNING_HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _log_applied(entry):
    """Append an entry to learning_applied.jsonl."""
    LEARNING_APPLIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEARNING_APPLIED_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Autonomous Learning Loop")
    parser.add_argument("--shadow-test", action="store_true",
                        help="Run shadow tests on proposals without applying")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print proposals without applying or logging")
    parser.add_argument("--days", type=int, default=7,
                        help="Look back N days for errors (default: 7)")
    parser.add_argument("--min-count", type=int, default=3,
                        help="Minimum occurrences to consider recurring (default: 3)")
    args = parser.parse_args()

    print(f"[Learning Loop] {datetime.now(timezone.utc).isoformat()}")
    print(f"  Looking back {args.days} days, min_count={args.min_count}")

    # Step 1: Load recent errors
    errors = load_recent_errors(days=args.days)
    print(f"  Loaded {len(errors)} error entries")

    if not errors:
        print("  No recent errors found. Exiting.")
        return

    # Step 2: Detect recurring patterns
    recurring = detect_recurring_patterns(errors, min_count=args.min_count)
    print(f"  Detected {len(recurring)} recurring patterns")

    if not recurring:
        print("  No recurring patterns found. Exiting.")
        return

    # Step 3: Generate fix proposals
    for pattern in recurring:
        proposal = generate_fix_proposal(pattern)
        print(f"\n  Pattern: {pattern['pattern_key']}")
        print(f"    Count: {pattern['count']}")
        print(f"    Category: {proposal['category']}")
        print(f"    Fix: {proposal['description']}")

        # Step 4: Shadow test
        improvement = 0.0
        if args.shadow_test or not args.dry_run:
            recent_failures = pattern.get("examples", [])[:5]
            improvement = shadow_test(proposal, recent_failures)
            print(f"    Shadow test improvement: {improvement:.0%}")

        if args.dry_run:
            continue

        # Step 5: Auto-apply logic
        zone = _get_autonomy_zone(proposal.get("description", ""))
        decision = "needs_review"

        if improvement >= 0.10 and zone == "green_zone":
            applied = apply_fix(proposal)
            if applied:
                decision = "auto_applied"
                _log_applied({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "pattern_key": pattern["pattern_key"],
                    "fix_type": proposal["fix_type"],
                    "description": proposal["description"],
                    "improvement": improvement,
                    "zone": zone,
                })
                print(f"    -> AUTO-APPLIED (green_zone, improvement={improvement:.0%})")
            else:
                decision = "apply_failed"
                print(f"    -> Apply failed")

        elif improvement >= 0.10 and zone == "yellow_zone":
            decision = "notified_pending"
            msg = (
                f"**[Learning Loop] Fix Proposal (yellow_zone)**\n"
                f"Pattern: `{pattern['pattern_key']}`\n"
                f"Count: {pattern['count']} in {args.days} days\n"
                f"Fix: {proposal['description']}\n"
                f"Shadow test: {improvement:.0%} improvement\n"
                f"Action needed: Review and approve"
            )
            notify_discord(msg)
            print(f"    -> NOTIFIED (yellow_zone, improvement={improvement:.0%})")

        else:
            print(f"    -> NEEDS REVIEW (zone={zone}, improvement={improvement:.0%})")

        # Step 6: Log to history
        _log_history({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error_pattern": pattern["pattern_key"],
            "count": pattern["count"],
            "proposed_fix": proposal["description"],
            "fix_type": proposal.get("fix_type"),
            "shadow_test_result": improvement,
            "decision": decision,
            "applied": decision == "auto_applied",
            "zone": zone,
        })

    print(f"\n[Learning Loop] Complete. Processed {len(recurring)} patterns.")


if __name__ == "__main__":
    main()
