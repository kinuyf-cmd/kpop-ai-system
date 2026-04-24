#!/usr/bin/env python3
"""
marketing_meeting.py — マーケSNS部会議
SNS投稿パフォーマンス・エンゲージメント分析・投稿計画。

Usage:
  python3 lib/marketing_meeting.py
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
LOGS_DIR = BASE_DIR / "logs"
X_SCORES_LOG = LOGS_DIR / "x_post_scores.jsonl"
X_QUEUE = LOGS_DIR / "x_post_queue.jsonl"
X_HISTORY = LOGS_DIR / "x_post_history.jsonl"
OUTPUT_DIR = BASE_DIR / "data" / "meetings" / "marketing"


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


def _get_x_performance(days: int = 7) -> dict:
    """Analyze X post performance."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Scores
    scores = _load_jsonl(X_SCORES_LOG)
    recent_scores = [s for s in scores if s.get("date", s.get("timestamp", "")[:10]) >= cutoff]

    # History
    history = _load_jsonl(X_HISTORY)
    recent_history = [h for h in history if h.get("date", h.get("posted_at", h.get("timestamp", ""))[:10]) >= cutoff]

    # Queue
    queue = _load_jsonl(X_QUEUE)
    pending = [q for q in queue if q.get("status", "") in ("pending", "queued", "")]

    result = {
        "total_posts": len(recent_history) if recent_history else len(recent_scores),
        "scores": recent_scores,
        "history": recent_history,
        "pending_queue": len(pending),
    }

    if recent_scores:
        score_vals = [s.get("score", s.get("quality_score", 0)) for s in recent_scores]
        result["avg_score"] = round(sum(score_vals) / len(score_vals), 1) if score_vals else 0
        result["max_score"] = max(score_vals) if score_vals else 0
        result["min_score"] = min(score_vals) if score_vals else 0

    return result


def generate_meeting() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    perf = _get_x_performance(7)

    lines = [
        f"# マーケ・SNS部会議 議事録 — {today}",
        f"**対象期間**: 直近7日間",
        "",
        "---",
        "",
        "## 1. SNS投稿パフォーマンス",
        "",
        f"| 指標 | 値 |",
        f"|------|-----|",
        f"| 投稿数（7日間） | {perf['total_posts']} 件 |",
    ]

    if "avg_score" in perf:
        lines.extend([
            f"| 平均スコア | {perf['avg_score']} |",
            f"| 最高スコア | {perf['max_score']} |",
            f"| 最低スコア | {perf['min_score']} |",
        ])

    lines.extend([
        f"| 投稿キュー待ち | {perf['pending_queue']} 件 |",
        "",
    ])

    # Recent posts detail
    lines.extend(["## 2. エンゲージメント分析", ""])

    history = perf.get("history", [])
    if history:
        lines.append("### 直近投稿一覧")
        lines.append("")
        lines.append("| 日時 | 内容 | エンゲージメント |")
        lines.append("|------|------|----------------|")
        for h in history[-15:]:
            date = h.get("date", h.get("posted_at", "?"))[:10]
            content = h.get("text", h.get("tweet", h.get("content", "?")))[:40]
            engagement = h.get("engagement", h.get("likes", h.get("impressions", "N/A")))
            lines.append(f"| {date} | {content} | {engagement} |")
        lines.append("")
    else:
        scores = perf.get("scores", [])
        if scores:
            lines.append("### 投稿スコア一覧")
            lines.append("")
            lines.append("| 日付 | スコア | 記事 |")
            lines.append("|------|-------|------|")
            for s in scores[-15:]:
                date = s.get("date", "?")
                score = s.get("score", s.get("quality_score", "?"))
                article = s.get("title", s.get("article", "?"))[:50]
                lines.append(f"| {date} | {score} | {article} |")
            lines.append("")
        else:
            lines.append("投稿履歴データなし。X投稿パイプラインの実行状況を確認してください。")
            lines.append("")

    lines.extend([
        "## 3. 次週投稿計画",
        "",
        "### 投稿方針",
        "",
        "1. 新着記事の自動X投稿を継続",
        "2. 高CTR記事の再シェア（リサイクル投稿）",
        "3. トレンドキーワードに合わせたタイムリー投稿",
        "",
        "### 注意事項",
        "",
        "- 投稿テキストに内部メトリクスやHTMLエンティティが混入しないよう監視",
        "- 1日の投稿上限を遵守",
        "",
        "---",
        f"*自動生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
    ])
    return "\n".join(lines)


def main():
    report = generate_meeting()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    out_path = OUTPUT_DIR / f"marketing_{today}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[マーケSNS部会議] 議事録保存: {out_path}")
    print(report)


if __name__ == "__main__":
    main()
