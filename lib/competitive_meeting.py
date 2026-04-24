#!/usr/bin/env python3
"""
competitive_meeting.py — 競合・トレンド部会議
競合動向・トレンド予測・対応記事提案。

Usage:
  python3 lib/competitive_meeting.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
LOGS_DIR = BASE_DIR / "logs"
COMPETITOR_QUEUE = LOGS_DIR / "competitor_queue.jsonl"
TREND_LOG = LOGS_DIR / "trend_predictions.jsonl"
OUTPUT_DIR = BASE_DIR / "data" / "meetings" / "competitive"


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


def _load_json(path: Path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_competitor_data() -> dict:
    """Try to get data from competitor_monitor output."""
    result = {"queue": [], "stats": {}}

    # Read competitor queue
    queue = _load_jsonl(COMPETITOR_QUEUE)
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    recent = [q for q in queue if q.get("queued_at", q.get("date", "")) >= cutoff]
    result["queue"] = recent

    # Try to get stats from competitor_monitor
    stats_path = LOGS_DIR / "competitor_stats.json"
    stats = _load_json(stats_path)
    if stats:
        result["stats"] = stats

    return result


def _get_trend_data() -> list[dict]:
    """Try to get data from trend_predictor output."""
    predictions = _load_jsonl(TREND_LOG)
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    recent = [p for p in predictions if p.get("date", p.get("predicted_at", "")) >= cutoff]

    # Also check auto_directives for injected trends
    directives_path = BASE_DIR / "config" / "auto_directives.json"
    directives = _load_json(directives_path)
    if directives and "trend_topics" in directives:
        for t in directives["trend_topics"]:
            recent.append({"topic": t.get("topic", t.get("keyword", "?")),
                          "source": "auto_directives",
                          "score": t.get("buzz_score", t.get("priority", 0))})

    return recent


def generate_meeting() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    comp_data = _get_competitor_data()
    trend_data = _get_trend_data()

    lines = [
        f"# 競合・トレンド部会議 議事録 — {today}",
        f"**部長**: ゲンガー",
        "",
        "---",
        "",
        "## 1. 競合動向サマリ",
        "",
    ]

    queue = comp_data["queue"]
    if queue:
        lines.append(f"直近7日間の競合記事検出: **{len(queue)}** 件")
        lines.append("")
        lines.append("| 競合サイト | タイトル | 関連度 | 状態 |")
        lines.append("|-----------|---------|--------|------|")
        for q in queue[:15]:
            source = q.get("source", q.get("site", "?"))
            title = q.get("title", "?")[:50]
            relevance = q.get("relevance", q.get("score", "?"))
            status = q.get("status", "queued")
            lines.append(f"| {source} | {title} | {relevance} | {status} |")
        lines.append("")
    else:
        lines.append("直近7日間の競合記事検出はありません。")
        lines.append("（competitor_monitor.py の出力ログを確認してください）")
        lines.append("")

    if comp_data.get("stats"):
        stats = comp_data["stats"]
        lines.extend([
            "### 競合サイト統計",
            "",
            f"- 監視サイト数: {stats.get('sites_monitored', 'N/A')}",
            f"- 累計検出記事: {stats.get('total_detected', 'N/A')}",
            f"- 対抗記事生成数: {stats.get('articles_generated', 'N/A')}",
            "",
        ])

    lines.extend([
        "## 2. トレンドキーワード",
        "",
    ])
    if trend_data:
        lines.append("| トピック | ソース | バズスコア |")
        lines.append("|---------|--------|-----------|")
        seen_topics = set()
        for t in sorted(trend_data, key=lambda x: x.get("score", x.get("buzz_score", 0)), reverse=True)[:15]:
            topic = t.get("topic", t.get("keyword", "?"))
            if topic in seen_topics:
                continue
            seen_topics.add(topic)
            source = t.get("source", "?")
            score = t.get("score", t.get("buzz_score", "?"))
            lines.append(f"| {topic} | {source} | {score} |")
        lines.append("")
    else:
        lines.append("トレンドデータなし。trend_predictor.py を実行してください。")
        lines.append("")

    lines.extend([
        "## 3. 対応記事の提案",
        "",
    ])

    proposals = []
    # From competitor queue
    uncovered = [q for q in queue if q.get("status") in ("queued", "pending")]
    if uncovered:
        for q in uncovered[:5]:
            proposals.append(f"[競合対抗] {q.get('title', '?')[:60]} (from {q.get('source', '?')})")

    # From trends
    if trend_data:
        for t in sorted(trend_data, key=lambda x: x.get("score", 0), reverse=True)[:3]:
            topic = t.get("topic", t.get("keyword", "?"))
            proposals.append(f"[トレンド] {topic} に関する記事を企画")

    if proposals:
        for i, p in enumerate(proposals, 1):
            lines.append(f"{i}. {p}")
    else:
        lines.append("現時点で緊急の対応記事提案はありません。")
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
    out_path = OUTPUT_DIR / f"competitive_{today}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[競合・トレンド部会議] 議事録保存: {out_path}")
    print(report)


if __name__ == "__main__":
    main()
