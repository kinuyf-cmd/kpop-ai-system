#!/usr/bin/env python3
"""
knowledge_base.py — 知識蓄積システム
会議議事録・意思決定・週次サマリの管理。

Usage:
  python3 lib/knowledge_base.py --save editorial "2026-04-18の編集部会議"
  python3 lib/knowledge_base.py --query seo "CTR改善"
  python3 lib/knowledge_base.py --weekly-summary
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
KNOWLEDGE_DIR = BASE_DIR / "data" / "knowledge"
MEETINGS_DIR = BASE_DIR / "data" / "meetings"

DEPARTMENTS = [
    "company", "audit", "editorial", "publishing", "design",
    "marketing", "seo", "revenue", "management", "competitive",
]


def save_meeting_minutes(department: str, content: str,
                         date: str | None = None, title: str | None = None) -> Path:
    """Save meeting minutes as markdown knowledge entry."""
    if department not in DEPARTMENTS and department != "general":
        raise ValueError(f"Unknown department: {department}")

    date = date or datetime.now().strftime("%Y-%m-%d")
    dept_dir = KNOWLEDGE_DIR / department
    dept_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{department}_{date}.md"
    if title:
        safe_title = re.sub(r'[^\w\-]', '_', title)[:50]
        filename = f"{department}_{date}_{safe_title}.md"

    path = dept_dir / filename
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    # Update index
    _update_index(department, date, str(path), title)

    return path


def _update_index(department: str, date: str, path: str, title: str | None = None):
    """Update the knowledge index for a department."""
    index_path = KNOWLEDGE_DIR / department / "_index.jsonl"
    entry = {
        "date": date,
        "path": path,
        "title": title or f"{department} meeting {date}",
        "indexed_at": datetime.now().isoformat(),
    }
    with open(index_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def extract_decisions(content: str) -> list[str]:
    """Extract key decisions from meeting notes."""
    decisions = []

    # Look for decision markers
    patterns = [
        r"(?:決定|決議|合意|承認|採用)[:：]\s*(.+)",
        r"→\s*(.+)",
        r"アクション[:：]\s*(.+)",
        r"\*\*(.+?)\*\*",
    ]

    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        for pattern in patterns:
            matches = re.findall(pattern, line)
            for m in matches:
                m = m.strip()
                if len(m) > 10 and len(m) < 200:
                    decisions.append(m)

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for d in decisions:
        if d not in seen:
            seen.add(d)
            unique.append(d)

    return unique[:20]  # Cap at 20 decisions


def create_weekly_summary(target_date: str | None = None) -> str:
    """Create a weekly knowledge summary from all departments."""
    end_date = target_date or datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")

    lines = [
        f"# 週次ナレッジサマリ — {start_date} ~ {end_date}",
        "",
        "---",
        "",
    ]

    for dept in DEPARTMENTS:
        dept_dir = KNOWLEDGE_DIR / dept
        if not dept_dir.exists():
            continue

        # Also check meetings dir
        meetings_dept_dir = MEETINGS_DIR / dept
        if dept == "general":
            meetings_dept_dir = MEETINGS_DIR / "general"

        md_files = []
        for d in [dept_dir, meetings_dept_dir]:
            if d.exists():
                for f in sorted(d.glob("*.md")):
                    # Check if file date is within range
                    fname = f.stem
                    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", fname)
                    if date_match:
                        fdate = date_match.group(1)
                        if start_date <= fdate <= end_date:
                            md_files.append(f)

        if not md_files:
            continue

        lines.append(f"## {dept.upper()}")
        lines.append("")
        lines.append(f"文書数: {len(md_files)}")
        lines.append("")

        for md_file in md_files:
            try:
                content = md_file.read_text(encoding="utf-8")
                decisions = extract_decisions(content)
                lines.append(f"### {md_file.name}")
                lines.append("")
                if decisions:
                    for d in decisions[:5]:
                        lines.append(f"- {d}")
                else:
                    lines.append("- (重要決定事項なし)")
                lines.append("")
            except Exception:
                continue

    lines.extend([
        "---",
        f"*自動生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
    ])

    summary = "\n".join(lines)

    # Save the summary
    company_dir = KNOWLEDGE_DIR / "company"
    company_dir.mkdir(parents=True, exist_ok=True)
    out_path = company_dir / f"weekly_summary_{end_date}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(summary)

    return summary


def get_knowledge(department: str, topic: str, limit: int = 10) -> list[dict]:
    """Query relevant knowledge for a department and topic.

    Returns matching knowledge entries with content snippets.
    """
    results = []
    search_dirs = [KNOWLEDGE_DIR / department]
    if department != "general":
        meetings_dept = MEETINGS_DIR / department
        if meetings_dept.exists():
            search_dirs.append(meetings_dept)

    topic_lower = topic.lower()
    topic_keywords = topic_lower.split()

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for md_file in sorted(search_dir.glob("*.md"), reverse=True):
            try:
                content = md_file.read_text(encoding="utf-8")
                content_lower = content.lower()

                # Score relevance
                score = 0
                for kw in topic_keywords:
                    score += content_lower.count(kw)

                if score > 0:
                    # Extract relevant snippet
                    snippet = ""
                    for line in content.split("\n"):
                        if any(kw in line.lower() for kw in topic_keywords):
                            snippet = line.strip()[:200]
                            break

                    results.append({
                        "file": str(md_file),
                        "department": department,
                        "score": score,
                        "snippet": snippet,
                        "date": re.search(r"(\d{4}-\d{2}-\d{2})", md_file.stem).group(1)
                               if re.search(r"(\d{4}-\d{2}-\d{2})", md_file.stem) else "unknown",
                    })
            except Exception:
                continue

    results.sort(key=lambda x: -x["score"])
    return results[:limit]


def main():
    parser = argparse.ArgumentParser(description="知識蓄積システム")
    parser.add_argument("--save", nargs=2, metavar=("DEPT", "TITLE"),
                        help="Save meeting minutes")
    parser.add_argument("--query", nargs=2, metavar=("DEPT", "TOPIC"),
                        help="Query knowledge base")
    parser.add_argument("--weekly-summary", action="store_true",
                        help="Generate weekly summary")
    parser.add_argument("--extract-decisions", type=str,
                        help="Extract decisions from a markdown file")
    parser.add_argument("--content", type=str, help="Content for --save (reads stdin if omitted)")
    args = parser.parse_args()

    if args.save:
        dept, title = args.save
        if args.content:
            content = args.content
        else:
            import sys
            content = sys.stdin.read()
        path = save_meeting_minutes(dept, content, title=title)
        print(f"[知識] 保存完了: {path}")

    elif args.query:
        dept, topic = args.query
        results = get_knowledge(dept, topic)
        if results:
            print(f"[知識] {dept}/{topic} の検索結果: {len(results)} 件")
            for r in results:
                print(f"  [{r['date']}] score={r['score']} {r['file']}")
                if r["snippet"]:
                    print(f"    → {r['snippet']}")
        else:
            print(f"[知識] {dept}/{topic} に該当するナレッジなし")

    elif args.weekly_summary:
        summary = create_weekly_summary()
        print(summary)

    elif args.extract_decisions:
        path = Path(args.extract_decisions)
        if path.exists():
            content = path.read_text(encoding="utf-8")
            decisions = extract_decisions(content)
            print(f"[知識] {len(decisions)} 件の意思決定を抽出:")
            for d in decisions:
                print(f"  - {d}")
        else:
            print(f"ファイルが見つかりません: {path}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
