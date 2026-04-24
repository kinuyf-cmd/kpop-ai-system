#!/usr/bin/env python3
"""
cost_tracker.py -- Per-department API cost tracking.
Wraps API calls to log token usage with department attribution.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LEDGER_FILE = BASE / "data" / "cost_ledger.jsonl"
ORG_CHART = BASE / "config" / "org_chart.json"

JST = timezone(timedelta(hours=9))

# ── Model pricing (USD per 1K tokens) ──
MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-5":  {"input": 0.003,   "output": 0.015},
    "claude-haiku-4-5":   {"input": 0.001,   "output": 0.005},
    "gpt-4o":             {"input": 0.0025,  "output": 0.01},
    "gpt-4o-mini":        {"input": 0.00015, "output": 0.0006},
}

# Fallback pricing for unknown models
_DEFAULT_PRICING = {"input": 0.003, "output": 0.015}

# ── Agent-to-department mapping (lazily loaded) ──
_agent_dept_map: dict[str, str] | None = None


def _load_agent_dept_map() -> dict[str, str]:
    """Build agent_id -> department_key mapping from org_chart.json."""
    global _agent_dept_map
    if _agent_dept_map is not None:
        return _agent_dept_map

    _agent_dept_map = {}
    if ORG_CHART.exists():
        try:
            org = json.loads(ORG_CHART.read_text(encoding="utf-8"))

            # Map executives to 'executive' department
            for role, info in org.get("executives", {}).items():
                agent_id = info.get("id", "")
                if agent_id:
                    _agent_dept_map[agent_id] = "executive"

            # Map department agents
            for dept_key, dept_info in org.get("departments", {}).items():
                manager = dept_info.get("manager", {})
                if manager.get("id"):
                    _agent_dept_map[manager["id"]] = dept_key
                for agent_id in dept_info.get("agents", []):
                    _agent_dept_map[agent_id] = dept_key
        except (json.JSONDecodeError, TypeError):
            pass

    return _agent_dept_map


def _get_department(agent_name: str) -> str:
    """Resolve agent name to department key."""
    mapping = _load_agent_dept_map()
    # Try exact match first
    if agent_name in mapping:
        return mapping[agent_name]
    # Try lowercase
    lower = agent_name.lower()
    if lower in mapping:
        return mapping[lower]
    # Try stripping common suffixes like _kpop, _cosme
    base = lower.split("_")[0]
    if base in mapping:
        return mapping[base]
    return "unknown"


def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate USD cost for an API call."""
    pricing = MODEL_PRICING.get(model, _DEFAULT_PRICING)
    input_cost = (input_tokens / 1000) * pricing["input"]
    output_cost = (output_tokens / 1000) * pricing["output"]
    return round(input_cost + output_cost, 6)


def _get_exchange_rate() -> float:
    """Get JPY/USD rate via exchange_rate module."""
    try:
        from exchange_rate import get_jpy_per_usd
        return get_jpy_per_usd()
    except ImportError:
        pass
    # Inline fallback
    config_file = BASE / "config" / "exchange_rate.json"
    if config_file.exists():
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            return float(data.get("jpy_per_usd", 150.0))
        except Exception:
            pass
    return 150.0


def log_api_call(
    agent_name: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    department: str | None = None,
) -> dict:
    """
    Log a single API call with cost attribution.

    Args:
        agent_name: Agent identifier (e.g. 'eevee', 'butterfree')
        model: Model name (e.g. 'claude-sonnet-4-5')
        input_tokens: Number of input tokens consumed
        output_tokens: Number of output tokens consumed
        department: Override department (auto-resolved from org_chart if None)

    Returns:
        The logged entry dict.
    """
    if department is None:
        department = _get_department(agent_name)

    cost_usd = _calc_cost(model, input_tokens, output_tokens)
    rate = _get_exchange_rate()
    cost_jpy = round(cost_usd * rate, 2)

    entry = {
        "timestamp": datetime.now(JST).isoformat(),
        "date": date.today().isoformat(),
        "agent": agent_name,
        "department": department,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "cost_jpy": cost_jpy,
        "exchange_rate": rate,
    }

    # Ensure data directory exists
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(LEDGER_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def _load_ledger(days: int | None = None) -> list[dict]:
    """Load ledger entries, optionally filtered to recent N days."""
    if not LEDGER_FILE.exists():
        return []

    cutoff = None
    if days is not None:
        cutoff = (date.today() - timedelta(days=days)).isoformat()

    entries = []
    for line in LEDGER_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if cutoff and entry.get("date", "") < cutoff:
                continue
            entries.append(entry)
        except json.JSONDecodeError:
            continue
    return entries


def get_daily_summary(date_str: str | None = None) -> dict:
    """
    Aggregate today's (or specified date's) costs by department.

    Returns:
        {
            "date": "2026-04-23",
            "total_usd": 1.23,
            "total_jpy": 184.5,
            "departments": {"editorial": {"usd": 0.5, "jpy": 75.0, "calls": 10}, ...},
            "top_agents": [{"agent": "eevee", "cost_usd": 0.3, "calls": 5}, ...],
        }
    """
    if date_str is None:
        date_str = date.today().isoformat()

    entries = [e for e in _load_ledger() if e.get("date") == date_str]

    dept_agg: dict[str, dict] = {}
    agent_agg: dict[str, dict] = {}

    for e in entries:
        dept = e.get("department", "unknown")
        agent = e.get("agent", "unknown")
        cost_usd = e.get("cost_usd", 0)
        cost_jpy = e.get("cost_jpy", 0)

        if dept not in dept_agg:
            dept_agg[dept] = {"usd": 0.0, "jpy": 0.0, "calls": 0}
        dept_agg[dept]["usd"] += cost_usd
        dept_agg[dept]["jpy"] += cost_jpy
        dept_agg[dept]["calls"] += 1

        if agent not in agent_agg:
            agent_agg[agent] = {"agent": agent, "cost_usd": 0.0, "calls": 0}
        agent_agg[agent]["cost_usd"] += cost_usd
        agent_agg[agent]["calls"] += 1

    # Round department values
    for d in dept_agg.values():
        d["usd"] = round(d["usd"], 4)
        d["jpy"] = round(d["jpy"], 2)

    # Top agents by cost
    top_agents = sorted(agent_agg.values(), key=lambda x: x["cost_usd"], reverse=True)[:5]
    for a in top_agents:
        a["cost_usd"] = round(a["cost_usd"], 4)

    total_usd = round(sum(d["usd"] for d in dept_agg.values()), 4)
    total_jpy = round(sum(d["jpy"] for d in dept_agg.values()), 2)

    return {
        "date": date_str,
        "total_usd": total_usd,
        "total_jpy": total_jpy,
        "departments": dept_agg,
        "top_agents": top_agents,
    }


def get_department_costs(days: int = 7) -> dict:
    """
    Aggregate costs per department over the last N days.

    Returns:
        {
            "period_days": 7,
            "start_date": "2026-04-16",
            "end_date": "2026-04-23",
            "total_usd": 12.34,
            "total_jpy": 1851.0,
            "departments": {
                "editorial": {"usd": 5.0, "jpy": 750.0, "calls": 100, "avg_daily_usd": 0.71},
                ...
            },
            "daily_totals": {"2026-04-23": {"usd": 1.5, "jpy": 225.0}, ...},
        }
    """
    entries = _load_ledger(days=days)

    dept_agg: dict[str, dict] = {}
    daily_totals: dict[str, dict] = {}

    for e in entries:
        dept = e.get("department", "unknown")
        entry_date = e.get("date", "")
        cost_usd = e.get("cost_usd", 0)
        cost_jpy = e.get("cost_jpy", 0)

        if dept not in dept_agg:
            dept_agg[dept] = {"usd": 0.0, "jpy": 0.0, "calls": 0}
        dept_agg[dept]["usd"] += cost_usd
        dept_agg[dept]["jpy"] += cost_jpy
        dept_agg[dept]["calls"] += 1

        if entry_date not in daily_totals:
            daily_totals[entry_date] = {"usd": 0.0, "jpy": 0.0}
        daily_totals[entry_date]["usd"] += cost_usd
        daily_totals[entry_date]["jpy"] += cost_jpy

    # Round and compute averages
    for d in dept_agg.values():
        d["usd"] = round(d["usd"], 4)
        d["jpy"] = round(d["jpy"], 2)
        d["avg_daily_usd"] = round(d["usd"] / max(days, 1), 4)

    for d in daily_totals.values():
        d["usd"] = round(d["usd"], 4)
        d["jpy"] = round(d["jpy"], 2)

    total_usd = round(sum(d["usd"] for d in dept_agg.values()), 4)
    total_jpy = round(sum(d["jpy"] for d in dept_agg.values()), 2)
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=days)).isoformat()

    return {
        "period_days": days,
        "start_date": start_date,
        "end_date": end_date,
        "total_usd": total_usd,
        "total_jpy": total_jpy,
        "departments": dept_agg,
        "daily_totals": dict(sorted(daily_totals.items())),
    }


if __name__ == "__main__":
    # Quick test
    print("=== Cost Tracker Test ===")
    entry = log_api_call("eevee", "claude-sonnet-4-5", 2000, 800)
    print(f"Logged: {json.dumps(entry, ensure_ascii=False, indent=2)}")
    summary = get_daily_summary()
    print(f"\nDaily summary: {json.dumps(summary, ensure_ascii=False, indent=2)}")
