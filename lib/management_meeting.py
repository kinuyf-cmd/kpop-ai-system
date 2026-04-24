#!/usr/bin/env python3
"""
management_meeting.py — 経営管理部会議
全KPIデータの横断集計・経営判断支援レポート。

Usage:
  python3 lib/management_meeting.py
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
LOGS_DIR = BASE_DIR / "logs"
METRICS_PATH = BASE_DIR / "agent_metrics.json"
GSC_METRICS = BASE_DIR / "google_metrics" / "metrics_yesterday.json"
POSTS_LOG = LOGS_DIR / "kpi_posts.jsonl"
ERRORS_LOG = LOGS_DIR / "kpi_errors.jsonl"
ROI_REPORT = LOGS_DIR / "article_roi_report.json"
OUTPUT_DIR = BASE_DIR / "data" / "meetings" / "management"


def _load_json(path: Path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_jsonl(path: Path, date_filter: str | None = None) -> list[dict]:
    entries = []
    if not path.exists():
        return entries
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if date_filter and obj.get("date") != date_filter:
                    continue
                entries.append(obj)
            except json.JSONDecodeError:
                continue
    return entries


def _recent_posts(days: int) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    all_posts = _load_jsonl(POSTS_LOG)
    return [p for p in all_posts if p.get("date", "") >= cutoff and p.get("event") == "post_published"]


def generate_meeting() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Agent metrics
    agent_metrics = _load_json(METRICS_PATH) or {}
    summary = agent_metrics.get("summary", {})

    # GSC metrics
    gsc = _load_json(GSC_METRICS) or {}
    ga4_summary = gsc.get("ga4", {}).get("summary", {})
    gsc_summary = gsc.get("gsc", {}).get("summary", {})

    # Posts
    week_posts = _recent_posts(7)
    month_posts = _recent_posts(30)
    yesterday_posts = [p for p in _load_jsonl(POSTS_LOG, yesterday) if p.get("event") == "post_published"]
    yesterday_errors = _load_jsonl(ERRORS_LOG, yesterday)

    # ROI
    roi = _load_json(ROI_REPORT)

    lines = [
        f"# 経営管理部会議 議事録 — {today}",
        f"**部長**: フーディン",
        "",
        "---",
        "",
        "## 1. 経営ダッシュボード",
        "",
        "### 全社KPI",
        "",
        "| 指標 | 値 |",
        "|------|-----|",
        f"| 全社成功率 | {summary.get('overall_success_rate', 0):.1%} |",
        f"| アクティブ社員 | {summary.get('active_agents', 0)}/{summary.get('total_agents_defined', 0)} |",
        f"| 優秀社員 | {summary.get('excellent_agents', 0)} |",
        f"| 要注意社員 | {summary.get('warning_agents', 0) + summary.get('critical_agents', 0)} |",
        f"| サボり社員 | {summary.get('sabori_agents', 0)} |",
        "",
        "### コンテンツKPI",
        "",
        "| 指標 | 昨日 | 週間 | 月間 |",
        "|------|------|------|------|",
        f"| 投稿数 | {len(yesterday_posts)} | {len(week_posts)} | {len(month_posts)} |",
        f"| エラー数 | {len(yesterday_errors)} | - | - |",
    ]

    if week_posts:
        avg_score = sum(p.get("score", 0) for p in week_posts) / len(week_posts)
        avg_chars = sum(p.get("char_count", 0) for p in week_posts) / len(week_posts)
        thumb_rate = sum(1 for p in week_posts if p.get("has_thumbnail")) / len(week_posts) * 100
        cta_rate = sum(1 for p in week_posts if p.get("has_cta")) / len(week_posts) * 100
        lines.extend([
            f"| 平均品質スコア | - | {avg_score:.1f} | - |",
            f"| 平均文字数 | - | {avg_chars:,.0f} | - |",
            f"| サムネ設定率 | - | {thumb_rate:.0f}% | - |",
            f"| CTA設定率 | - | {cta_rate:.0f}% | - |",
        ])
    lines.append("")

    # Traffic KPI
    lines.extend(["### トラフィックKPI", ""])
    if ga4_summary:
        lines.extend([
            "| 指標 | 値 |",
            "|------|-----|",
            f"| セッション | {ga4_summary.get('sessions', 'N/A')} |",
            f"| ユーザー | {ga4_summary.get('users', 'N/A')} |",
            f"| PV | {ga4_summary.get('pageviews', 'N/A')} |",
            f"| エンゲージドセッション | {ga4_summary.get('engaged_sessions', 'N/A')} |",
            "",
        ])
    if gsc_summary:
        lines.extend([
            "| GSC指標 | 値 |",
            "|---------|-----|",
            f"| クリック | {gsc_summary.get('total_clicks', 'N/A')} |",
            f"| インプレッション | {gsc_summary.get('total_impressions', 'N/A')} |",
            f"| 平均CTR | {gsc_summary.get('avg_ctr', 0) * 100:.2f}% |" if gsc_summary.get('avg_ctr') else "| 平均CTR | N/A |",
            f"| 平均順位 | {gsc_summary.get('avg_position', 'N/A')} |",
            "",
        ])

    # Revenue KPI
    lines.extend(["### 収益KPI", ""])
    if roi:
        roi_summary = roi.get("summary", roi)
        if isinstance(roi_summary, dict):
            for k, v in list(roi_summary.items())[:6]:
                lines.append(f"- {k}: {v}")
        lines.append("")
    else:
        lines.append("収益データなし")
        lines.append("")

    # Issues and action items
    lines.extend([
        "## 2. 課題・アクションアイテム",
        "",
    ])
    issues = []
    if summary.get("critical_agents", 0) > 0:
        issues.append(f"危険社員 {summary['critical_agents']} 名の即時対応")
    if summary.get("sabori_agents", 0) > 3:
        issues.append(f"サボり社員 {summary['sabori_agents']} 名 — 原因調査と対策")
    if len(yesterday_errors) > 5:
        issues.append(f"昨日のエラー {len(yesterday_errors)} 件 — パイプライン安定性改善")
    if week_posts and sum(1 for p in week_posts if not p.get("has_cta")) > len(week_posts) * 0.3:
        issues.append("CTA未設定率が高い — 収益化機会損失")

    if issues:
        for i, issue in enumerate(issues, 1):
            lines.append(f"{i}. {issue}")
    else:
        lines.append("重大な課題なし。現状維持。")
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
    out_path = OUTPUT_DIR / f"management_{today}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[経営管理部会議] 議事録保存: {out_path}")
    print(report)


if __name__ == "__main__":
    main()
