#!/usr/bin/env python3
"""
revenue_meeting.py — 収益化部会議
収益レポート・API費用・施策提案。

Usage:
  python3 lib/revenue_meeting.py
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
LOGS_DIR = BASE_DIR / "logs"
ROI_JSONL = LOGS_DIR / "article_roi.jsonl"
ROI_REPORT = LOGS_DIR / "article_roi_report.json"
ROI_WEEKLY = LOGS_DIR / "article_roi_weekly.jsonl"
AFFILIATE_LOG = LOGS_DIR / "affiliate_links.jsonl"
REVENUE_CONFIG = BASE_DIR / "config" / "revenue_config.json"
OUTPUT_DIR = BASE_DIR / "data" / "meetings" / "revenue"


def _load_json(path: Path):
    if not path.exists():
        return None
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


def _get_revenue_summary() -> dict:
    """Aggregate revenue data from multiple sources."""
    result = {"roi_report": None, "weekly_roi": [], "affiliate_stats": {}}

    # ROI report
    roi = _load_json(ROI_REPORT)
    if roi:
        result["roi_report"] = roi

    # Weekly ROI entries
    weekly = _load_jsonl(ROI_WEEKLY)
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    result["weekly_roi"] = [w for w in weekly if w.get("date", w.get("week_start", "")) >= cutoff]

    # Affiliate link stats
    affiliates = _load_jsonl(AFFILIATE_LOG)
    recent = [a for a in affiliates if a.get("date", a.get("timestamp", "")[:10]) >= cutoff]
    providers: dict[str, int] = {}
    for a in recent:
        provider = a.get("provider", a.get("type", "unknown"))
        providers[provider] = providers.get(provider, 0) + 1
    result["affiliate_stats"] = {"total_links": len(recent), "by_provider": providers}

    return result


def generate_meeting() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    rev_config = _load_json(REVENUE_CONFIG) or {}
    rev_data = _get_revenue_summary()

    lines = [
        f"# 収益化部会議 議事録 — {today}",
        "",
        "---",
        "",
        "## 1. 収益レポートサマリ",
        "",
    ]

    # ROI report
    roi = rev_data.get("roi_report")
    if roi:
        lines.append("### 記事ROI分析")
        lines.append("")
        summary = roi.get("summary", roi)
        if isinstance(summary, dict):
            for k, v in list(summary.items())[:10]:
                lines.append(f"- **{k}**: {v}")
        lines.append("")

    # Weekly ROI trend
    weekly = rev_data.get("weekly_roi", [])
    if weekly:
        lines.extend([
            "### 週次ROI推移",
            "",
            "| 期間 | 記事数 | 推定収益 | API費用 |",
            "|------|--------|---------|---------|",
        ])
        for w in weekly[-8:]:
            period = w.get("week_start", w.get("date", "?"))
            count = w.get("article_count", w.get("count", "?"))
            revenue = w.get("estimated_revenue", w.get("revenue", "?"))
            cost = w.get("api_cost", w.get("cost", "?"))
            lines.append(f"| {period} | {count} | {revenue} | {cost} |")
        lines.append("")

    # Affiliate stats
    aff = rev_data.get("affiliate_stats", {})
    if aff.get("total_links", 0) > 0:
        lines.extend([
            "### アフィリエイトリンク統計（直近30日）",
            "",
            f"- 総リンク設置数: {aff['total_links']}",
        ])
        for provider, cnt in sorted(aff.get("by_provider", {}).items(), key=lambda x: -x[1]):
            lines.append(f"- {provider}: {cnt} 件")
        lines.append("")

    # Revenue config summary
    lines.extend(["## 2. API費用の状況", ""])
    asp_providers = rev_config.get("asp_providers", {})
    if asp_providers:
        lines.append("### 収益化プロバイダ設定")
        lines.append("")
        lines.append("| プロバイダ | 種別 | 平均報酬 | 対象カテゴリ |")
        lines.append("|-----------|------|---------|-------------|")
        for pid, pinfo in asp_providers.items():
            name = pinfo.get("name", pid)
            ptype = pinfo.get("type", "?")
            commission = pinfo.get("avg_commission", pinfo.get("avg_commission_rate", "?"))
            cats = ", ".join(pinfo.get("categories", [])[:3])
            lines.append(f"| {name} | {ptype} | {commission} | {cats} |")
        lines.append("")

    cost_config = rev_config.get("cost_tracking", rev_config.get("api_costs", {}))
    if cost_config:
        lines.append("### コスト設定")
        lines.append("")
        for k, v in list(cost_config.items())[:5]:
            lines.append(f"- {k}: {v}")
        lines.append("")

    lines.extend([
        "## 3. 次週の施策",
        "",
        "1. 高PV低収益記事のCTA最適化",
        "2. 新規ASP案件の導入検討",
        "3. 記事あたりAPI費用の削減施策レビュー",
        "",
        "---",
        f"*自動生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
    ])
    return "\n".join(lines)


def main():
    report = generate_meeting()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    out_path = OUTPUT_DIR / f"revenue_{today}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[収益化部会議] 議事録保存: {out_path}")
    print(report)


if __name__ == "__main__":
    main()
