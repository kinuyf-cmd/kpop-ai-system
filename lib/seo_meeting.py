#!/usr/bin/env python3
"""
seo_meeting.py — SEO部会議
GSCメトリクス分析・CTR改善候補・検索順位変動レポート。

Usage:
  python3 lib/seo_meeting.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
METRICS_PATH = BASE_DIR / "google_metrics" / "metrics_yesterday.json"
LOW_CTR_PATH = BASE_DIR / "google_metrics" / "low_ctr_pages.json"
OUTPUT_DIR = BASE_DIR / "data" / "meetings" / "seo"


def _load_json(path: Path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _format_ctr(ctr: float) -> str:
    return f"{ctr * 100:.2f}%"


def generate_meeting() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    metrics = _load_json(METRICS_PATH) or {}
    low_ctr = _load_json(LOW_CTR_PATH) or []

    # Parse GA4 / GSC data
    ga4 = metrics.get("ga4", {})
    ga4_summary = ga4.get("summary", {})
    gsc = metrics.get("gsc", {})
    gsc_summary = gsc.get("summary", {})
    top_queries = gsc.get("top_queries", [])
    top_pages = gsc.get("top_pages", [])
    metrics_date = metrics.get("date", "不明")

    lines = [
        f"# SEO部会議 議事録 — {today}",
        f"**データ日付**: {metrics_date}",
        "",
        "---",
        "",
        "## 1. GSCメトリクス概要",
        "",
    ]

    if gsc_summary:
        lines.extend([
            "| 指標 | 値 |",
            "|------|-----|",
            f"| 総クリック数 | {gsc_summary.get('total_clicks', 'N/A')} |",
            f"| 総インプレッション | {gsc_summary.get('total_impressions', 'N/A')} |",
            f"| 平均CTR | {_format_ctr(gsc_summary['avg_ctr']) if 'avg_ctr' in gsc_summary else 'N/A'} |",
            f"| 平均順位 | {gsc_summary.get('avg_position', 'N/A')} |",
            "",
        ])
    else:
        lines.append("GSCデータが取得できませんでした。")
        lines.append("")

    if ga4_summary:
        lines.extend([
            "### GA4サマリ",
            "",
            "| 指標 | 値 |",
            "|------|-----|",
            f"| セッション数 | {ga4_summary.get('sessions', 'N/A')} |",
            f"| ユーザー数 | {ga4_summary.get('users', 'N/A')} |",
            f"| PV数 | {ga4_summary.get('pageviews', 'N/A')} |",
            f"| エンゲージドセッション | {ga4_summary.get('engaged_sessions', 'N/A')} |",
            "",
        ])

    # Top queries
    lines.extend(["## 2. 検索クエリ TOP10", ""])
    if top_queries:
        lines.append("| クエリ | クリック | 表示 | CTR | 順位 |")
        lines.append("|--------|---------|------|-----|------|")
        for q in top_queries[:10]:
            query = q.get("query", "?")
            clicks = q.get("clicks", 0)
            impressions = q.get("impressions", 0)
            ctr = _format_ctr(q.get("ctr", 0))
            pos = f"{q.get('position', 0):.1f}"
            lines.append(f"| {query} | {clicks} | {impressions} | {ctr} | {pos} |")
        lines.append("")
    else:
        lines.append("クエリデータなし")
        lines.append("")

    # CTR improvement candidates
    lines.extend(["## 3. CTR改善候補", ""])
    if low_ctr:
        lines.append("| ページ | クリック | 表示 | CTR | 順位 |")
        lines.append("|--------|---------|------|-----|------|")
        for page in low_ctr[:15]:
            url = page.get("page", "?")
            # Extract slug from URL
            slug = url.rstrip("/").split("/")[-1] if "/" in url else url
            slug_short = slug[:50] + ("..." if len(slug) > 50 else "")
            clicks = int(page.get("clicks", 0))
            impressions = int(page.get("impressions", 0))
            ctr = _format_ctr(page.get("ctr", 0))
            pos = f"{page.get('position', 0):.1f}"
            lines.append(f"| {slug_short} | {clicks} | {impressions} | {ctr} | {pos} |")
        lines.append("")
        lines.append(f"**CTR改善対象**: {len(low_ctr)} ページ")
        high_imp_low_ctr = [p for p in low_ctr if p.get("impressions", 0) > 1000 and p.get("ctr", 0) < 0.02]
        if high_imp_low_ctr:
            lines.append(f"**高インプレッション低CTR（優先対応）**: {len(high_imp_low_ctr)} ページ")
    else:
        lines.append("CTR改善候補データなし")
    lines.append("")

    # Top pages performance
    lines.extend(["## 4. 検索順位変動（トップページ）", ""])
    if top_pages:
        lines.append("| ページ | クリック | 表示 | 順位 |")
        lines.append("|--------|---------|------|------|")
        for p in top_pages[:10]:
            page_url = p.get("page", "?")
            slug = page_url.rstrip("/").split("/")[-1] if "/" in page_url else page_url
            slug_short = slug[:50] + ("..." if len(slug) > 50 else "")
            lines.append(f"| {slug_short} | {int(p.get('clicks', 0))} | {int(p.get('impressions', 0))} | {p.get('position', 0):.1f} |")
        lines.append("")
    else:
        lines.append("ページ別データなし")
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
    out_path = OUTPUT_DIR / f"seo_{today}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[SEO部会議] 議事録保存: {out_path}")
    print(report)


if __name__ == "__main__":
    main()
