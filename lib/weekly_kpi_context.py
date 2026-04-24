#!/usr/bin/env python3
"""
weekly_kpi_context.py — 週次KPIコンテキスト生成 v1.0

【責務】
  1. 前週7日間のKPIを集約し、週次トレンドサマリーを生成
  2. 各曜日の部署別会議に前週KPIを自動注入
  3. 週次レビューの戦略更新 → auto_directives.json に反映
  4. WoW (Week over Week) 比較で改善/悪化を自動検出

【パイプライン統合】
  各 meeting_*.sh から呼ばれる。
  kpop_weekly_review.sh の Lugia 戦略 → auto_directives反映も担う。

Usage:
  python3 lib/weekly_kpi_context.py                    # 前週KPIサマリー（JSON）
  python3 lib/weekly_kpi_context.py --brief            # 会議注入用テキスト
  python3 lib/weekly_kpi_context.py --brief --dept seo # SEO部向けブリーフ
  python3 lib/weekly_kpi_context.py --update-directives # auto_directives更新
"""
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"
GOOGLE_METRICS = BASE / "google_metrics"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

AUTO_DIRECTIVES_PATH = CONFIG / "auto_directives.json"
KPI_POSTS_PATH = LOGS / "kpi_posts.jsonl"
AGENT_METRICS_PATH = BASE / "agent_metrics.json"
METRICS_HISTORY_PATH = LOGS / "metrics_history.jsonl"


def _load_json(p: Path):
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    records = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def get_week_range(weeks_ago: int = 1) -> tuple[str, str]:
    """N週前の月〜日の日付範囲を返す。"""
    today = date.today()
    # 直近の月曜を起点
    days_since_monday = today.weekday()
    last_monday = today - timedelta(days=days_since_monday + 7 * weeks_ago)
    last_sunday = last_monday + timedelta(days=6)
    return last_monday.isoformat(), last_sunday.isoformat()


def build_weekly_summary(weeks_ago: int = 1) -> dict:
    """前週のKPIサマリーを構築する。"""
    start, end = get_week_range(weeks_ago)

    # 投稿データ
    posts = _load_jsonl(KPI_POSTS_PATH)
    week_posts = [p for p in posts if start <= p.get("date", "") <= end]
    prev_start, prev_end = get_week_range(weeks_ago + 1)
    prev_posts = [p for p in posts if prev_start <= p.get("date", "") <= prev_end]

    # カテゴリ別集計
    from collections import Counter
    cat_counts = Counter(p.get("article_type", "unknown") for p in week_posts)
    prev_cat_counts = Counter(p.get("article_type", "unknown") for p in prev_posts)

    # メトリクス履歴
    metrics_history = _load_jsonl(METRICS_HISTORY_PATH)
    week_metrics = [m for m in metrics_history if start <= m.get("date", "") <= end]
    prev_metrics = [m for m in metrics_history if prev_start <= m.get("date", "") <= prev_end]

    def avg_metric(records, path_fn):
        vals = [path_fn(r) for r in records if path_fn(r) is not None]
        return sum(vals) / len(vals) if vals else 0

    def extract_pv(r):
        try:
            return int(r.get("ga4", {}).get("summary", {}).get("pageviews", 0))
        except (ValueError, TypeError):
            return None

    def extract_ctr(r):
        try:
            pages = r.get("gsc", {}).get("top_pages", [])
            clicks = sum(p.get("clicks", 0) for p in pages)
            imps = sum(p.get("impressions", 0) for p in pages)
            return clicks / imps if imps > 0 else None
        except Exception:
            return None

    avg_pv = avg_metric(week_metrics, extract_pv)
    prev_avg_pv = avg_metric(prev_metrics, extract_pv)
    avg_ctr = avg_metric(week_metrics, extract_ctr)
    prev_avg_ctr = avg_metric(prev_metrics, extract_ctr)

    pv_change = (avg_pv - prev_avg_pv) / prev_avg_pv if prev_avg_pv > 0 else 0
    ctr_change = (avg_ctr - prev_avg_ctr) / prev_avg_ctr if prev_avg_ctr > 0 else 0

    # エージェント稼働
    agent_data = _load_json(AGENT_METRICS_PATH)
    agent_summary = agent_data.get("summary", {})

    return {
        "period": {"start": start, "end": end},
        "prev_period": {"start": prev_start, "end": prev_end},
        "posts": {
            "count": len(week_posts),
            "prev_count": len(prev_posts),
            "change": len(week_posts) - len(prev_posts),
            "categories": dict(cat_counts),
        },
        "traffic": {
            "avg_pv": round(avg_pv),
            "prev_avg_pv": round(prev_avg_pv),
            "pv_change_pct": round(pv_change * 100, 1),
            "avg_ctr": round(avg_ctr, 4),
            "prev_avg_ctr": round(prev_avg_ctr, 4),
            "ctr_change_pct": round(ctr_change * 100, 1),
        },
        "agents": {
            "overall_success_rate": agent_summary.get("overall_success_rate", 0),
            "active": agent_summary.get("active_agents", 0),
            "critical": agent_summary.get("critical_agents", 0),
            "warning": agent_summary.get("warning_agents", 0),
        },
    }


def format_brief(summary: dict, dept: str = "general") -> str:
    """会議注入用のテキストブリーフを生成する。"""
    p = summary["posts"]
    t = summary["traffic"]
    a = summary["agents"]
    period = summary["period"]

    lines = [
        f"【前週KPIサマリー（{period['start']}〜{period['end']}）】",
        f"  投稿数: {p['count']}本（前週{p['prev_count']}本、{p['change']:+d}）",
        f"  日平均PV: {t['avg_pv']}（前週{t['prev_avg_pv']}、{t['pv_change_pct']:+.1f}%）",
        f"  平均CTR: {t['avg_ctr']:.2%}（前週{t['prev_avg_ctr']:.2%}、{t['ctr_change_pct']:+.1f}%）",
        f"  エージェント成功率: {a['overall_success_rate']:.0%}  CRITICAL: {a['critical']}件",
    ]

    # カテゴリ内訳
    if p["categories"]:
        lines.append("  カテゴリ別: " + " / ".join(
            f"{cat}:{cnt}" for cat, cnt in sorted(p["categories"].items(), key=lambda x: -x[1])
        ))

    # WoW分析
    lines.append("")
    lines.append("【WoW分析】")
    if t["pv_change_pct"] > 10:
        lines.append(f"  📈 PV{t['pv_change_pct']:+.1f}% — 成長トレンド維持。")
    elif t["pv_change_pct"] < -10:
        lines.append(f"  📉 PV{t['pv_change_pct']:+.1f}% — 原因調査と対策が必要。")
    if t["ctr_change_pct"] > 5:
        lines.append(f"  📈 CTR{t['ctr_change_pct']:+.1f}% — タイトル戦略が奏功。")
    elif t["ctr_change_pct"] < -5:
        lines.append(f"  📉 CTR{t['ctr_change_pct']:+.1f}% — タイトル/メタ改善が急務。")

    # 部署別追加コンテキスト
    if dept == "seo":
        lines.append("")
        lines.append("【SEO部向け重点】")
        lines.append(f"  CTR改善が{'不要（好調）' if t['ctr_change_pct'] > 0 else '最優先課題'}。")
        lines.append("  低CTRページのリライト、内部リンク最適化を検討すること。")
    elif dept == "finance":
        lines.append("")
        lines.append("【経理部向け重点】")
        lines.append(f"  投稿数{p['count']}本 → 収益インパクトを試算すること。")
    elif dept == "sns":
        lines.append("")
        lines.append("【SNS部向け重点】")
        lines.append("  X流入セッションの前週比を確認し、投稿戦略を調整すること。")
    elif dept == "audit":
        lines.append("")
        lines.append("【監査部向け重点】")
        lines.append(f"  CRITICAL{a['critical']}件の根本原因を特定し、再発防止策を報告すること。")

    return "\n".join(lines)


def update_directives_with_weekly(summary: dict, dry_run: bool = False) -> bool:
    """auto_directives.jsonにweekly_kpiセクションを更新する。"""
    directives = _load_json(AUTO_DIRECTIVES_PATH)
    if not directives:
        directives = {}

    t = summary["traffic"]
    p = summary["posts"]

    directives["weekly_kpi"] = {
        "updated_at": NOW.isoformat(),
        "period": summary["period"],
        "posts_count": p["count"],
        "avg_pv": t["avg_pv"],
        "avg_ctr": t["avg_ctr"],
        "pv_trend": "up" if t["pv_change_pct"] > 5 else ("down" if t["pv_change_pct"] < -5 else "flat"),
        "ctr_trend": "up" if t["ctr_change_pct"] > 5 else ("down" if t["ctr_change_pct"] < -5 else "flat"),
        "priority_action": (
            "CTR改善" if t["ctr_change_pct"] < -5
            else "PV回復" if t["pv_change_pct"] < -10
            else "投稿量増" if p["count"] < 20
            else "品質維持"
        ),
    }
    directives["updated_at"] = NOW.isoformat()

    if dry_run:
        print("[DRY-RUN] auto_directives.json にweekly_kpiを更新")
        return True

    AUTO_DIRECTIVES_PATH.write_text(
        json.dumps(directives, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return True


def main():
    parser = argparse.ArgumentParser(description="週次KPIコンテキスト v1.0")
    parser.add_argument("--brief", action="store_true", help="会議注入用ブリーフ")
    parser.add_argument("--dept", default="general",
                        choices=["general", "seo", "finance", "sns", "audit", "hr", "analytics"],
                        help="部署別ブリーフ")
    parser.add_argument("--update-directives", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    summary = build_weekly_summary()

    if args.brief:
        print(format_brief(summary, dept=args.dept))
    elif args.update_directives:
        updated = update_directives_with_weekly(summary, dry_run=args.dry_run)
        print(json.dumps({"updated": updated}, ensure_ascii=False))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
