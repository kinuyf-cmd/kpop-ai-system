#!/usr/bin/env python3
"""
design_meeting.py — デザイン部会議
UI品質・サムネイル・モバイル表示の分析レポート。

Usage:
  python3 lib/design_meeting.py
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
LOGS_DIR = BASE_DIR / "logs"
UI_TRACKER = LOGS_DIR / "ui_cta_tracker.jsonl"
POSTS_LOG = LOGS_DIR / "kpi_posts.jsonl"
OUTPUT_DIR = BASE_DIR / "data" / "meetings" / "design"


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


def _recent_posts(days: int = 7) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    all_posts = _load_jsonl(POSTS_LOG)
    return [p for p in all_posts if p.get("date", "") >= cutoff and p.get("event") == "post_published"]


def _analyze_thumbnails(posts: list[dict]) -> dict:
    total = len(posts)
    with_thumb = sum(1 for p in posts if p.get("has_thumbnail"))
    without_thumb = [p for p in posts if not p.get("has_thumbnail")]
    return {
        "total": total,
        "with_thumbnail": with_thumb,
        "without_thumbnail": len(without_thumb),
        "rate": round(with_thumb / total * 100, 1) if total else 0,
        "missing_list": without_thumb[:10],
    }


def _analyze_cta(posts: list[dict]) -> dict:
    total = len(posts)
    with_cta = sum(1 for p in posts if p.get("has_cta"))
    return {
        "total": total,
        "with_cta": with_cta,
        "without_cta": total - with_cta,
        "rate": round(with_cta / total * 100, 1) if total else 0,
    }


def _analyze_ui_tracker() -> dict:
    """Analyze UI/CTA tracker if it exists."""
    entries = _load_jsonl(UI_TRACKER)
    if not entries:
        return {"available": False}

    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    recent = [e for e in entries if e.get("date", "") >= cutoff]

    issues = [e for e in recent if e.get("status") == "issue" or e.get("type") == "error"]
    return {
        "available": True,
        "total_entries": len(recent),
        "issues": len(issues),
        "entries": recent[:10],
    }


def generate_meeting() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    posts = _recent_posts(7)
    thumb_stats = _analyze_thumbnails(posts)
    cta_stats = _analyze_cta(posts)
    ui_data = _analyze_ui_tracker()

    lines = [
        f"# デザイン部会議 議事録 — {today}",
        f"**対象期間**: 直近7日間",
        f"**対象記事数**: {len(posts)} 件",
        "",
        "---",
        "",
        "## 1. UI品質スコア",
        "",
        "### サムネイル設定状況",
        "",
        f"| 指標 | 値 |",
        f"|------|-----|",
        f"| サムネイル設定率 | {thumb_stats['rate']}% ({thumb_stats['with_thumbnail']}/{thumb_stats['total']}) |",
        f"| 未設定記事 | {thumb_stats['without_thumbnail']} 件 |",
        "",
    ]

    if thumb_stats["missing_list"]:
        lines.append("#### サムネイル未設定記事")
        lines.append("")
        for p in thumb_stats["missing_list"]:
            lines.append(f"- [{p.get('post_id', '?')}] {p.get('title', '不明')[:60]}")
        lines.append("")

    lines.extend([
        "### CTA設定状況",
        "",
        f"| 指標 | 値 |",
        f"|------|-----|",
        f"| CTA設定率 | {cta_stats['rate']}% ({cta_stats['with_cta']}/{cta_stats['total']}) |",
        f"| 未設定記事 | {cta_stats['without_cta']} 件 |",
        "",
    ])

    lines.extend([
        "## 2. モバイル表示の問題点",
        "",
    ])
    if ui_data.get("available"):
        lines.append(f"UI/CTAトラッカーから {ui_data['total_entries']} 件のデータを検出。")
        if ui_data["issues"]:
            lines.append(f"問題点: {ui_data['issues']} 件")
        else:
            lines.append("現在モバイル表示の重大な問題は検出されていません。")
    else:
        lines.append("UI/CTAトラッカーデータなし。モバイル表示チェックを推奨。")
    lines.append("")

    # Improvement suggestions
    lines.extend([
        "## 3. 改善提案",
        "",
    ])
    suggestions = []
    if thumb_stats["rate"] < 100:
        suggestions.append(f"サムネイル未設定記事 {thumb_stats['without_thumbnail']} 件の対応（CTRに直結）")
    if cta_stats["rate"] < 80:
        suggestions.append(f"CTA設定率 {cta_stats['rate']}% → 80%以上を目標に改善")

    short_articles = [p for p in posts if p.get("char_count", 0) < 3000 and p.get("char_count", 0) > 0]
    if short_articles:
        suggestions.append(f"短文記事（3000字未満）が {len(short_articles)} 件。読了体験向上のためコンテンツ充実を検討")

    if not suggestions:
        suggestions.append("現状のデザイン品質は良好。引き続き品質維持を。")

    for i, s in enumerate(suggestions, 1):
        lines.append(f"{i}. {s}")
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
    out_path = OUTPUT_DIR / f"design_{today}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[デザイン部会議] 議事録保存: {out_path}")
    print(report)


if __name__ == "__main__":
    main()
