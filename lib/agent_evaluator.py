#!/usr/bin/env python3
"""
agent_evaluator.py — 社員スコア評価システム（10項目×10点 = 100点満点）

評価項目:
  1. エラーハンドリング — スクリプトにtry/exceptがあるか
  2. ログ出力 — 直近7日間にログエントリがあるか
  3. リトライ — スクリプトにリトライロジックがあるか
  4. Discord通知 — Discord通知機能があるか
  5. 品質ゲート通過率 — kpi_posts.jsonl のスコア
  6. KPI達成率 — agent_metrics.json の成功率
  7. 再発エラー0件 — error_patterns.json で未解決があるか
  8. 学習適用率 — agents/*.md の AUTO-LEARNED セクション
  9. 記事品質スコア平均 — kpi_posts.jsonl
  10. 投稿成功率 — agent_metrics.json

Usage:
  python3 lib/agent_evaluator.py
  python3 lib/agent_evaluator.py --agent deoxys
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
LOGS_DIR = BASE_DIR / "logs"
AGENTS_DIR = BASE_DIR / "agents"
METRICS_PATH = BASE_DIR / "agent_metrics.json"
ERROR_PATTERNS_PATH = BASE_DIR / "config" / "error_patterns.json"
POSTS_LOG = LOGS_DIR / "kpi_posts.jsonl"
OUTPUT_PATH = BASE_DIR / "data" / "ai_staff" / "scores" / "agent_scores.json"


def _load_json(path: Path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_jsonl(path: Path) -> list[dict]:
    entries = []
    if not path.exists():
        return entries
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _find_agent_scripts(agent_id: str) -> list[Path]:
    """Find Python scripts that may belong to an agent."""
    patterns = [
        BASE_DIR / "lib" / f"{agent_id}*.py",
        BASE_DIR / "lib" / f"*{agent_id}*.py",
    ]
    scripts = []
    for pattern in patterns:
        scripts.extend(Path(p) for p in glob.glob(str(pattern)))

    # Also check the agent's md file for script references
    md_path = AGENTS_DIR / f"{agent_id}.md"
    if md_path.exists():
        scripts.append(md_path)
    # Try kpop variant
    kpop_md = AGENTS_DIR / f"{agent_id}_kpop.md"
    if kpop_md.exists():
        scripts.append(kpop_md)

    return scripts


def _check_try_except(scripts: list[Path]) -> int:
    """Score 0-10 for error handling (try/except presence)."""
    if not scripts:
        return 5  # neutral if no scripts found
    has_try = False
    for s in scripts:
        if not s.exists():
            continue
        try:
            content = s.read_text(encoding="utf-8", errors="ignore")
            if "try:" in content or "except " in content or "except:" in content:
                has_try = True
                break
        except Exception:
            continue
    return 10 if has_try else 3


def _check_recent_logs(agent_id: str) -> int:
    """Score 0-10 for recent log activity."""
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    # Check multiple log files
    log_files = [
        LOGS_DIR / "kpi_posts.jsonl",
        LOGS_DIR / "kpi_errors.jsonl",
        LOGS_DIR / "agents_auto_applied.jsonl",
        LOGS_DIR / "admin_actions.jsonl",
    ]

    total_entries = 0
    for lf in log_files:
        entries = _load_jsonl(lf)
        for e in entries:
            if e.get("date", e.get("timestamp", "")[:10]) >= cutoff:
                if agent_id in str(e.get("agent", "")) or agent_id in str(e.get("pipeline", "")):
                    total_entries += 1

    if total_entries >= 10:
        return 10
    elif total_entries >= 5:
        return 8
    elif total_entries >= 1:
        return 5
    return 0


def _check_retry_logic(scripts: list[Path]) -> int:
    """Score 0-10 for retry logic."""
    if not scripts:
        return 5
    for s in scripts:
        if not s.exists():
            continue
        try:
            content = s.read_text(encoding="utf-8", errors="ignore")
            retry_patterns = ["retry", "リトライ", "max_retries", "backoff", "attempt", "MAX_RETRY"]
            if any(p in content for p in retry_patterns):
                return 10
        except Exception:
            continue
    return 3


def _check_discord_notification(scripts: list[Path]) -> int:
    """Score 0-10 for Discord notification."""
    if not scripts:
        return 5
    for s in scripts:
        if not s.exists():
            continue
        try:
            content = s.read_text(encoding="utf-8", errors="ignore")
            if "discord" in content.lower() or "webhook" in content.lower() or "send_discord" in content:
                return 10
        except Exception:
            continue
    return 3


def _check_quality_gate(agent_id: str) -> int:
    """Score 0-10 for quality gate pass rate."""
    posts = _load_jsonl(POSTS_LOG)
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    recent = [p for p in posts if p.get("date", "") >= cutoff and p.get("event") == "post_published"]

    if not recent:
        return 5

    high_quality = sum(1 for p in recent if p.get("score", 0) >= 70)
    rate = high_quality / len(recent) if recent else 0
    return min(10, round(rate * 10, 1))


def _check_kpi_achievement(agent_id: str, metrics: dict) -> int:
    """Score 0-10 for KPI achievement from agent_metrics."""
    agents = metrics.get("agents", {})
    info = agents.get(agent_id, {})
    rate = info.get("success_rate", 0)
    return min(10, round(rate * 10, 1))


def _check_recurring_errors(agent_id: str) -> int:
    """Score 0-10 (10 = no recurring errors)."""
    data = _load_json(ERROR_PATTERNS_PATH)
    patterns = data.get("patterns", {})

    unresolved = 0
    for pid, info in patterns.items():
        if info.get("agent") == agent_id and info.get("resolved_at") is None:
            unresolved += info.get("count", 1)

    if unresolved == 0:
        return 10
    elif unresolved <= 2:
        return 6
    elif unresolved <= 5:
        return 3
    return 0


def _check_learning_applied(agent_id: str) -> int:
    """Score 0-10 for AUTO-LEARNED sections in agent .md."""
    md_files = list(AGENTS_DIR.glob(f"{agent_id}*.md"))
    if not md_files:
        return 5

    total_learned = 0
    for md in md_files:
        try:
            content = md.read_text(encoding="utf-8", errors="ignore")
            # Count AUTO-LEARNED markers
            total_learned += len(re.findall(r"AUTO-LEARNED|自動学習|LEARNED|<!-- learned", content, re.IGNORECASE))
        except Exception:
            continue

    if total_learned >= 5:
        return 10
    elif total_learned >= 3:
        return 8
    elif total_learned >= 1:
        return 6
    return 3


def _check_article_quality_avg() -> int:
    """Score 0-10 for average article quality score."""
    posts = _load_jsonl(POSTS_LOG)
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    recent = [p for p in posts if p.get("date", "") >= cutoff and p.get("event") == "post_published"]

    if not recent:
        return 5

    scores = [p.get("score", 0) for p in recent]
    avg = sum(scores) / len(scores) if scores else 0
    return min(10, round(avg / 10, 1))


def _check_post_success_rate(agent_id: str, metrics: dict) -> int:
    """Score 0-10 for post success rate."""
    agents = metrics.get("agents", {})
    info = agents.get(agent_id, {})
    total = info.get("total_count", 0)
    success = info.get("success_count", 0)
    if total == 0:
        return 5
    rate = success / total
    return min(10, round(rate * 10, 1))


def evaluate_agent(agent_id: str, metrics: dict) -> dict:
    """Evaluate a single agent on all 10 criteria."""
    scripts = _find_agent_scripts(agent_id)

    criteria = {
        "1_エラーハンドリング": _check_try_except(scripts),
        "2_ログ出力": _check_recent_logs(agent_id),
        "3_リトライ": _check_retry_logic(scripts),
        "4_Discord通知": _check_discord_notification(scripts),
        "5_品質ゲート通過率": _check_quality_gate(agent_id),
        "6_KPI達成率": _check_kpi_achievement(agent_id, metrics),
        "7_再発エラー0件": _check_recurring_errors(agent_id),
        "8_学習適用率": _check_learning_applied(agent_id),
        "9_記事品質スコア平均": _check_article_quality_avg(),
        "10_投稿成功率": _check_post_success_rate(agent_id, metrics),
    }

    total = sum(criteria.values())

    return {
        "agent_id": agent_id,
        "criteria": criteria,
        "total_score": round(total, 1),
        "max_score": 100,
        "percentage": round(total / 100 * 100, 1),
        "evaluated_at": datetime.now().isoformat(),
    }


def evaluate_all() -> dict:
    """Evaluate all agents."""
    metrics = _load_json(METRICS_PATH)
    agents = metrics.get("agents", {})

    results = {}
    for agent_id in agents:
        results[agent_id] = evaluate_agent(agent_id, metrics)

    return {
        "evaluated_at": datetime.now().isoformat(),
        "agent_count": len(results),
        "agents": results,
    }


def main():
    parser = argparse.ArgumentParser(description="社員スコア評価")
    parser.add_argument("--agent", help="特定エージェントのみ評価")
    args = parser.parse_args()

    metrics = _load_json(METRICS_PATH)

    if args.agent:
        result = evaluate_agent(args.agent, metrics)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        results = evaluate_all()

        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[社員評価] スコア保存: {OUTPUT_PATH}")

        # Print summary
        agents = results["agents"]
        ranked = sorted(agents.values(), key=lambda x: -x["total_score"])
        print(f"\n全 {len(ranked)} 名の評価完了:")
        print(f"{'順位':>4} {'ID':<20} {'スコア':>6} {'%':>6}")
        print("-" * 40)
        for i, a in enumerate(ranked, 1):
            print(f"{i:>4} {a['agent_id']:<20} {a['total_score']:>5.1f} {a['percentage']:>5.1f}%")


if __name__ == "__main__":
    main()
