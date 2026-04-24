#!/usr/bin/env python3
"""
monthly_eval.py — 月次人事評価
全社員の総合評価レポートを生成。

Usage:
  python3 lib/monthly_eval.py
  python3 lib/monthly_eval.py --year 2026 --month 4
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
METRICS_PATH = BASE_DIR / "agent_metrics.json"
OUTPUT_DIR = BASE_DIR / "data" / "ai_staff" / "scores"


def _load_json(path: Path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _evaluate_agent(info: dict) -> dict:
    """Evaluate a single agent comprehensively."""
    scores = {}

    # 1. Success rate (0-10)
    rate = info.get("success_rate", 0)
    scores["成功率"] = min(10, round(rate * 10, 1))

    # 2. Error count penalty (10 - errors, min 0)
    fail_count = info.get("fail_count", 0)
    scores["エラー耐性"] = max(0, 10 - fail_count)

    # 3. Empty output penalty
    empty = info.get("empty_output_count", 0)
    scores["出力品質"] = max(0, 10 - empty * 2)

    # 4. Sabori flag
    scores["勤怠"] = 0 if info.get("sabori_flag") else 10

    # 5. Activity volume (based on total_count)
    total = info.get("total_count", 0)
    if total >= 100:
        scores["活動量"] = 10
    elif total >= 50:
        scores["活動量"] = 8
    elif total >= 20:
        scores["活動量"] = 6
    elif total >= 5:
        scores["活動量"] = 4
    elif total > 0:
        scores["活動量"] = 2
    else:
        scores["活動量"] = 0

    # 6. Danger level
    danger = info.get("danger", "")
    if "🟢" in danger or "低" in danger:
        scores["安定性"] = 10
    elif "🟡" in danger or "中" in danger:
        scores["安定性"] = 6
    elif "🔴" in danger or "高" in danger:
        scores["安定性"] = 2
    else:
        scores["安定性"] = 5

    # 7. Role class bonus
    role_class = info.get("role_class", "")
    if role_class == "CORE":
        scores["役割重要度"] = 10
    elif role_class == "SUPPORT":
        scores["役割重要度"] = 7
    else:
        scores["役割重要度"] = 5

    total_score = sum(scores.values())
    max_possible = len(scores) * 10
    percentage = round(total_score / max_possible * 100, 1)

    # Grade
    if percentage >= 90:
        grade = "S"
    elif percentage >= 80:
        grade = "A"
    elif percentage >= 70:
        grade = "B"
    elif percentage >= 60:
        grade = "C"
    elif percentage >= 50:
        grade = "D"
    else:
        grade = "E"

    return {
        "scores": scores,
        "total_score": total_score,
        "max_possible": max_possible,
        "percentage": percentage,
        "grade": grade,
    }


def generate_eval(year: int, month: int) -> str:
    metrics = _load_json(METRICS_PATH)
    agents = metrics.get("agents", {})
    summary = metrics.get("summary", {})

    evaluations = []
    for aid, info in agents.items():
        ev = _evaluate_agent(info)
        ev["id"] = aid
        ev["name"] = info.get("name_ja", aid)
        ev["role"] = info.get("role", "不明")
        ev["success_rate"] = info.get("success_rate", 0)
        ev["total_count"] = info.get("total_count", 0)
        evaluations.append(ev)

    evaluations.sort(key=lambda x: -x["percentage"])

    lines = [
        f"# 月次人事評価レポート — {year}年{month}月",
        f"**評価対象**: {len(evaluations)} 名",
        f"**全社成功率**: {summary.get('overall_success_rate', 0):.1%}",
        "",
        "---",
        "",
        "## 総合ランキング",
        "",
        "| 順位 | 社員名 | 役割 | 総合点 | 評価 | 成功率 | 実行数 |",
        "|------|--------|------|--------|------|--------|--------|",
    ]

    for i, ev in enumerate(evaluations, 1):
        lines.append(
            f"| {i} | {ev['name']} | {ev['role'][:20]} | "
            f"{ev['percentage']}% | {ev['grade']} | "
            f"{ev['success_rate']:.1%} | {ev['total_count']} |"
        )
    lines.append("")

    # Grade distribution
    grade_counts = {}
    for ev in evaluations:
        g = ev["grade"]
        grade_counts[g] = grade_counts.get(g, 0) + 1

    lines.extend([
        "## 評価分布",
        "",
        "| グレード | 人数 | 割合 |",
        "|---------|------|------|",
    ])
    for g in ["S", "A", "B", "C", "D", "E"]:
        cnt = grade_counts.get(g, 0)
        pct = round(cnt / len(evaluations) * 100, 1) if evaluations else 0
        bar = "█" * cnt
        lines.append(f"| {g} | {cnt} | {pct}% {bar} |")
    lines.append("")

    # Detailed evaluation for top and bottom agents
    lines.extend(["## 優秀社員（TOP 5）", ""])
    for ev in evaluations[:5]:
        lines.append(f"### {ev['name']} ({ev['id']}) — {ev['grade']}評価")
        lines.append("")
        for criterion, score in ev["scores"].items():
            bar = "█" * int(score)
            lines.append(f"- {criterion}: {score}/10 {bar}")
        lines.append("")

    lines.extend(["## 要改善社員（BOTTOM 5）", ""])
    for ev in evaluations[-5:]:
        lines.append(f"### {ev['name']} ({ev['id']}) — {ev['grade']}評価")
        lines.append("")
        for criterion, score in ev["scores"].items():
            bar = "█" * int(score)
            lines.append(f"- {criterion}: {score}/10 {bar}")
        lines.append("")

    lines.extend([
        "---",
        f"*自動生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="月次人事評価")
    now = datetime.now()
    parser.add_argument("--year", type=int, default=now.year)
    parser.add_argument("--month", type=int, default=now.month)
    args = parser.parse_args()

    report = generate_eval(args.year, args.month)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"eval_{args.year}_{args.month:02d}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[月次評価] レポート保存: {out_path}")
    print(report)


if __name__ == "__main__":
    main()
