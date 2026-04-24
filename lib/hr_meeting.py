#!/usr/bin/env python3
"""
hr_meeting.py — 人事部会議
全社員スコアランキング・育成対象リスト・再発エラー確認。

Usage:
  python3 lib/hr_meeting.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
METRICS_PATH = BASE_DIR / "agent_metrics.json"
ERROR_PATTERNS_PATH = BASE_DIR / "config" / "error_patterns.json"
OUTPUT_DIR = BASE_DIR / "data" / "meetings" / "general"


def _load_json(path: Path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_agent_rankings() -> list[dict]:
    """Build agent ranking by success rate."""
    metrics = _load_json(METRICS_PATH)
    agents = metrics.get("agents", {})

    rankings = []
    for aid, info in agents.items():
        rankings.append({
            "id": aid,
            "name": info.get("name_ja", aid),
            "role": info.get("role", "不明"),
            "success_rate": info.get("success_rate", 0),
            "success_count": info.get("success_count", 0),
            "fail_count": info.get("fail_count", 0),
            "total_count": info.get("total_count", 0),
            "rank": info.get("rank", "?"),
            "status": info.get("status", "?"),
            "danger": info.get("danger", ""),
            "empty_output_count": info.get("empty_output_count", 0),
            "sabori_flag": info.get("sabori_flag", False),
        })
    return sorted(rankings, key=lambda x: (-x["success_rate"], -x["total_count"]))


def _get_training_candidates(rankings: list[dict]) -> list[dict]:
    """Identify agents that need training/improvement."""
    candidates = []
    for a in rankings:
        reasons = []
        if a["success_rate"] < 0.8 and a["total_count"] > 0:
            reasons.append(f"成功率 {a['success_rate']:.1%}")
        if a["empty_output_count"] > 3:
            reasons.append(f"空出力 {a['empty_output_count']} 回")
        if a["sabori_flag"]:
            reasons.append("サボり疑惑")
        if a["fail_count"] > 5:
            reasons.append(f"失敗 {a['fail_count']} 回")
        if reasons:
            candidates.append({**a, "reasons": reasons})
    return candidates


def _get_error_patterns() -> list[dict]:
    """Get recurring error patterns."""
    data = _load_json(ERROR_PATTERNS_PATH)
    patterns = data.get("patterns", {})
    result = []
    for pid, info in patterns.items():
        result.append({
            "id": pid,
            "count": info.get("count", 0),
            "last_seen": info.get("last_seen", "?"),
            "agent": info.get("agent", "?"),
            "example": info.get("example", ""),
            "fix": info.get("fix", ""),
            "resolved": info.get("resolved_at") is not None,
        })
    return sorted(result, key=lambda x: -x["count"])


def generate_meeting() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    rankings = _get_agent_rankings()
    training = _get_training_candidates(rankings)
    errors = _get_error_patterns()

    lines = [
        f"# 人事部会議 議事録 — {today}",
        "",
        "---",
        "",
        "## 1. 全社員スコアランキング",
        "",
        "| 順位 | 社員名 | ID | 役割 | 成功率 | 実行数 | ランク |",
        "|------|--------|-----|------|--------|--------|--------|",
    ]

    for i, a in enumerate(rankings, 1):
        name = a["name"]
        rate = f"{a['success_rate']:.1%}" if a["total_count"] > 0 else "N/A"
        lines.append(f"| {i} | {name} | {a['id']} | {a['role'][:20]} | {rate} | {a['total_count']} | {a['rank']} |")
    lines.append("")

    # Summary stats
    active = [a for a in rankings if a["total_count"] > 0]
    if active:
        avg_rate = sum(a["success_rate"] for a in active) / len(active)
        lines.extend([
            f"**アクティブ社員**: {len(active)} 名  ",
            f"**全社平均成功率**: {avg_rate:.1%}  ",
            f"**サボり疑惑**: {sum(1 for a in rankings if a['sabori_flag'])} 名",
            "",
        ])

    lines.extend([
        "## 2. 育成対象リスト",
        "",
    ])
    if training:
        lines.append("| 社員名 | ID | 成功率 | 理由 |")
        lines.append("|--------|-----|--------|------|")
        for t in training:
            reasons = ", ".join(t["reasons"])
            rate = f"{t['success_rate']:.1%}" if t["total_count"] > 0 else "N/A"
            lines.append(f"| {t['name']} | {t['id']} | {rate} | {reasons} |")
        lines.append("")
        lines.append(f"**育成対象**: {len(training)} 名")
    else:
        lines.append("育成対象なし。全社員が基準を満たしています。")
    lines.append("")

    lines.extend([
        "## 3. 再発エラー確認",
        "",
    ])
    unresolved = [e for e in errors if not e["resolved"]]
    resolved = [e for e in errors if e["resolved"]]

    if unresolved:
        lines.append("### 未解決エラー")
        lines.append("")
        for e in unresolved:
            lines.append(f"- **{e['id']}** (発生 {e['count']} 回, 最終: {e['last_seen']}, 担当: {e['agent']})")
            lines.append(f"  - {e['example']}")
        lines.append("")

    if resolved:
        lines.append(f"### 解決済みエラー: {len(resolved)} 件")
        lines.append("")
        for e in resolved[:5]:
            lines.append(f"- ~~{e['id']}~~ (解決済み, 発生 {e['count']} 回)")
        if len(resolved) > 5:
            lines.append(f"- ...他 {len(resolved) - 5} 件")
        lines.append("")

    if not unresolved and not resolved:
        lines.append("エラーパターンデータなし。")
        lines.append("")

    lines.extend([
        "---",
        f"*自動生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
    ])
    return "\n".join(lines)


def main():
    report = generate_meeting()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    out_path = OUTPUT_DIR / f"hr_{today}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[人事部会議] 議事録保存: {out_path}")
    print(report)


if __name__ == "__main__":
    main()
