#!/usr/bin/env python3
"""
daily_standup.py — 朝会（COO ルギア主催）
毎朝の全社スタンドアップミーティングを自動生成。

Usage:
  python3 lib/daily_standup.py
  python3 lib/daily_standup.py --date 2026-04-17
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
METRICS_PATH = BASE_DIR / "agent_metrics.json"
POSTS_LOG = LOGS_DIR / "kpi_posts.jsonl"
ERRORS_LOG = LOGS_DIR / "kpi_errors.jsonl"
OUTPUT_DIR = DATA_DIR / "meetings" / "general"


def _load_jsonl(path: Path, date_filter: str | None = None) -> list[dict]:
    """Load JSONL file, optionally filtering by date field."""
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


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_post_stats(date_str: str) -> dict:
    """Get post statistics for a given date."""
    posts = _load_jsonl(POSTS_LOG, date_filter=date_str)
    if not posts:
        return {"count": 0, "avg_score": 0, "avg_chars": 0, "with_thumbnail": 0, "with_cta": 0}

    scores = [p.get("score", 0) for p in posts]
    chars = [p.get("char_count", 0) for p in posts]
    return {
        "count": len(posts),
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "avg_chars": round(sum(chars) / len(chars)) if chars else 0,
        "with_thumbnail": sum(1 for p in posts if p.get("has_thumbnail")),
        "with_cta": sum(1 for p in posts if p.get("has_cta")),
    }


def _get_error_stats(date_str: str) -> dict:
    """Get error statistics for a given date."""
    errors = _load_jsonl(ERRORS_LOG, date_filter=date_str)
    by_type: dict[str, int] = {}
    for e in errors:
        etype = e.get("error_type", "unknown")
        by_type[etype] = by_type.get(etype, 0) + 1
    return {"count": len(errors), "by_type": by_type}


def _get_agent_summary() -> dict:
    """Summarize agent status from agent_metrics.json."""
    metrics = _load_json(METRICS_PATH)
    summary = metrics.get("summary", {})
    agents = metrics.get("agents", {})

    error_flagged = []
    sabori_list = []
    for aid, info in agents.items():
        if info.get("danger", "").startswith("🔴") or info.get("rank") == "🔴":
            error_flagged.append({"id": aid, "name": info.get("name_ja", aid),
                                  "rate": info.get("success_rate", 0)})
        if info.get("sabori_flag"):
            sabori_list.append({"id": aid, "name": info.get("name_ja", aid)})

    return {
        "overall_success_rate": summary.get("overall_success_rate", 0),
        "total_agents": summary.get("total_agents_defined", 0),
        "active_agents": summary.get("active_agents", 0),
        "excellent": summary.get("excellent_agents", 0),
        "warning": summary.get("warning_agents", 0),
        "critical": summary.get("critical_agents", 0),
        "error_flagged": error_flagged,
        "sabori_list": sabori_list,
    }


def generate_standup(target_date: str) -> str:
    """Generate standup report markdown."""
    yesterday = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    post_stats = _get_post_stats(yesterday)
    error_stats = _get_error_stats(yesterday)
    agent_summary = _get_agent_summary()

    lines = [
        f"# 朝会レポート — {target_date}",
        f"**主催**: ルギア（COO）  ",
        f"**対象日**: {yesterday} の実績",
        "",
        "---",
        "",
        "## 1. 前日の実績",
        "",
        f"| 指標 | 値 |",
        f"|------|-----|",
        f"| 投稿数 | {post_stats['count']} 件 |",
        f"| 平均品質スコア | {post_stats['avg_score']} |",
        f"| 平均文字数 | {post_stats['avg_chars']:,} 字 |",
        f"| サムネイル設定率 | {post_stats['with_thumbnail']}/{post_stats['count']} |",
        f"| CTA設定率 | {post_stats['with_cta']}/{post_stats['count']} |",
        f"| エラー件数 | {error_stats['count']} 件 |",
        "",
    ]

    if error_stats["by_type"]:
        lines.append("### エラー内訳")
        lines.append("")
        for etype, cnt in sorted(error_stats["by_type"].items(), key=lambda x: -x[1]):
            lines.append(f"- **{etype}**: {cnt} 件")
        lines.append("")

    lines.extend([
        "## 2. 社員ステータス概要",
        "",
        f"| 指標 | 値 |",
        f"|------|-----|",
        f"| 全社成功率 | {agent_summary['overall_success_rate']:.1%} |",
        f"| 定義済社員数 | {agent_summary['total_agents']} |",
        f"| アクティブ社員 | {agent_summary['active_agents']} |",
        f"| 優秀(🟢) | {agent_summary['excellent']} |",
        f"| 要注意(🟡) | {agent_summary['warning']} |",
        f"| 危険(🔴) | {agent_summary['critical']} |",
        "",
    ])

    lines.extend([
        "## 3. 注意事項（エラーフラグのある社員）",
        "",
    ])
    if agent_summary["error_flagged"]:
        for a in agent_summary["error_flagged"]:
            lines.append(f"- **{a['name']}** ({a['id']}): 成功率 {a['rate']:.1%}")
    else:
        lines.append("- エラーフラグのある社員はいません。")
    lines.append("")

    if agent_summary["sabori_list"]:
        lines.append("### サボり疑惑社員")
        lines.append("")
        for a in agent_summary["sabori_list"]:
            lines.append(f"- {a['name']} ({a['id']})")
        lines.append("")

    lines.extend([
        "## 4. 本日の計画",
        "",
        "- パイプライン定時実行（通常スケジュール）",
        "- CTR改善タイトル書き換え（低CTRページ対象）",
        "- GSC インデックス状況確認",
        f"- エラーフラグ社員 {len(agent_summary['error_flagged'])} 名の改善フォロー",
        "",
        "---",
        f"*自動生成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
    ])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="朝会レポート生成")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                        help="対象日 (default: today)")
    args = parser.parse_args()

    report = generate_standup(args.date)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"standup_{args.date}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"[朝会] レポート保存: {out_path}")

    # Discord notification
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from discord_notifier import send_discord
        send_discord(
            channel="general",
            title=f"朝会レポート {args.date}",
            body=f"投稿数: {_get_post_stats((datetime.strptime(args.date, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d'))['count']}件 / "
                 f"エラー: {_get_error_stats((datetime.strptime(args.date, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d'))['count']}件",
            color=0x3498db,
            event_key=f"standup__{args.date}",
            severity="INFO"
        )
        print("[朝会] Discord通知送信完了")
    except Exception as e:
        print(f"[朝会] Discord通知スキップ: {e}")

    print(report)


if __name__ == "__main__":
    main()
