#!/usr/bin/env python3
"""
editorial_meeting.py — 編集部会議
直近記事の品質分析・リライトキュー管理・次回テーマ提案。

Usage:
  python3 lib/editorial_meeting.py
  python3 lib/editorial_meeting.py --days 7
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
LOGS_DIR = BASE_DIR / "logs"
POSTS_LOG = LOGS_DIR / "kpi_posts.jsonl"
OUTPUT_DIR = BASE_DIR / "data" / "meetings" / "editorial"

REWRITE_THRESHOLD = 70


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


def _recent_posts(days: int) -> list[dict]:
    """Get posts from the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    all_posts = _load_jsonl(POSTS_LOG)
    return [p for p in all_posts if p.get("date", "") >= cutoff and p.get("event") == "post_published"]


def _score_distribution(posts: list[dict]) -> dict:
    """Calculate quality score distribution."""
    if not posts:
        return {"total": 0, "buckets": {}, "avg": 0, "min": 0, "max": 0}
    scores = [p.get("score", 0) for p in posts]
    buckets = {"0-29 (低品質)": 0, "30-49": 0, "50-69": 0, "70-89 (合格)": 0, "90-100 (優秀)": 0}
    for s in scores:
        if s < 30:
            buckets["0-29 (低品質)"] += 1
        elif s < 50:
            buckets["30-49"] += 1
        elif s < 70:
            buckets["50-69"] += 1
        elif s < 90:
            buckets["70-89 (合格)"] += 1
        else:
            buckets["90-100 (優秀)"] += 1
    return {
        "total": len(scores),
        "buckets": buckets,
        "avg": round(sum(scores) / len(scores), 1),
        "min": min(scores),
        "max": max(scores),
    }


def _rewrite_candidates(posts: list[dict]) -> list[dict]:
    """Find articles that need rewriting (score < threshold)."""
    candidates = []
    for p in posts:
        score = p.get("score", 0)
        if score < REWRITE_THRESHOLD:
            candidates.append({
                "post_id": p.get("post_id", "?"),
                "title": p.get("title", "不明"),
                "score": score,
                "char_count": p.get("char_count", 0),
                "date": p.get("date", ""),
                "has_cta": p.get("has_cta", False),
                "has_thumbnail": p.get("has_thumbnail", False),
            })
    return sorted(candidates, key=lambda x: x["score"])


def _suggest_themes(posts: list[dict]) -> list[str]:
    """Suggest next article themes based on gaps."""
    pipelines = Counter(p.get("pipeline", "unknown") for p in posts)
    types = Counter(p.get("article_type", "unknown") for p in posts)

    suggestions = []
    if pipelines.get("speed", 0) > pipelines.get("strategy", 0) * 2:
        suggestions.append("戦略記事（strategy pipeline）の比率が低下。中長期コンテンツの増産を検討")
    if types.get("flow", 0) > types.get("stock", 0) * 3:
        suggestions.append("ストック記事の不足。エバーグリーンコンテンツの企画を推奨")

    no_cta = sum(1 for p in posts if not p.get("has_cta"))
    if no_cta > len(posts) * 0.3:
        suggestions.append(f"CTA未設定記事が {no_cta}/{len(posts)} 件。収益化機会の損失あり")

    no_thumb = sum(1 for p in posts if not p.get("has_thumbnail"))
    if no_thumb > 0:
        suggestions.append(f"サムネイル未設定記事 {no_thumb} 件。CTR改善のためサムネ設定を優先")

    if not suggestions:
        suggestions.append("現状のバランスは良好。引き続き品質維持を")

    return suggestions


def generate_meeting(days: int) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    posts = _recent_posts(days)
    dist = _score_distribution(posts)
    rewrites = _rewrite_candidates(posts)
    themes = _suggest_themes(posts)

    lines = [
        f"# 編集部会議 議事録 — {today}",
        f"**対象期間**: 直近 {days} 日間",
        f"**対象記事数**: {len(posts)} 件",
        "",
        "---",
        "",
        "## 1. 品質スコア分布",
        "",
        f"| 指標 | 値 |",
        f"|------|-----|",
        f"| 記事数 | {dist['total']} |",
        f"| 平均スコア | {dist['avg']} |",
        f"| 最低スコア | {dist['min']} |",
        f"| 最高スコア | {dist['max']} |",
        "",
        "### スコア帯別分布",
        "",
    ]
    for bucket, cnt in dist["buckets"].items():
        bar = "█" * cnt
        lines.append(f"- **{bucket}**: {cnt} 件 {bar}")
    lines.append("")

    lines.extend([
        f"## 2. リライトキュー（スコア {REWRITE_THRESHOLD} 未満）",
        "",
    ])
    if rewrites:
        lines.append("| ID | タイトル | スコア | 文字数 | 日付 |")
        lines.append("|-----|---------|-------|--------|------|")
        for r in rewrites[:20]:
            title_short = r["title"][:40] + ("..." if len(r["title"]) > 40 else "")
            lines.append(f"| {r['post_id']} | {title_short} | {r['score']} | {r['char_count']:,} | {r['date']} |")
    else:
        lines.append("リライト候補なし（全記事がスコア基準を満たしています）")
    lines.append("")

    lines.extend([
        "## 3. 次回記事テーマ提案",
        "",
    ])
    for i, t in enumerate(themes, 1):
        lines.append(f"{i}. {t}")
    lines.append("")

    lines.extend([
        "---",
        f"*自動生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="編集部会議 議事録生成")
    parser.add_argument("--days", type=int, default=7, help="対象日数 (default: 7)")
    args = parser.parse_args()

    report = generate_meeting(args.days)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    out_path = OUTPUT_DIR / f"editorial_{today}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[編集部会議] 議事録保存: {out_path}")
    print(report)


if __name__ == "__main__":
    main()
