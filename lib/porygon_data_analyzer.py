#!/usr/bin/env python3
"""
porygon_data_analyzer.py — ポリゴン用データ分析パイプライン

kpop_weekly_review.sh および手動実行から呼び出され、
GSC/GA4/アーカイブ/winning_patterns の全データを統合して
ポリゴンが分析できる構造化レポートを生成する。

Usage:
  python3 lib/porygon_data_analyzer.py              # 週次分析（7日）
  python3 lib/porygon_data_analyzer.py --days 3      # 直近3日
  python3 lib/porygon_data_analyzer.py --daily        # 日次サマリ
  python3 lib/porygon_data_analyzer.py --output json  # JSON出力
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
ARCHIVES = Path.home() / "kpop_archives"
GMETRICS = BASE / "google_metrics"
JST = timezone(timedelta(hours=9))


def _load_jsonl(path: Path, max_lines: int = 0) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if max_lines:
        lines = lines[-max_lines:]
    out = []
    for line in lines:
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def collect_archive_stats(days: int = 7) -> dict:
    """直近N日のアーカイブから実行統計を収集"""
    cutoff = (datetime.now(JST) - timedelta(days=days)).strftime("%Y%m%d")
    total = 0
    success = 0
    stopped = 0
    error_agents: Counter = Counter()
    stop_reasons: Counter = Counter()
    articles: list[dict] = []
    pipeline_types: Counter = Counter()

    for d in sorted(glob.glob(str(ARCHIVES / "*" / ""))):
        dirname = os.path.basename(d.rstrip("/"))
        # dirname pattern: breaking_YYYYMMDD_HHMMSS or chart_YYYYMMDD_...
        parts = dirname.split("_", 1)
        if len(parts) < 2:
            continue
        date_part = parts[1][:8] if len(parts[1]) >= 8 else ""
        if not date_part.isdigit() or date_part < cutoff:
            continue

        total += 1
        pipe_type = parts[0] if parts[0] in ("breaking", "chart", "strategy") else "other"
        pipeline_types[pipe_type] += 1

        summary_file = os.path.join(d, "summary.txt")
        if not os.path.exists(summary_file):
            stopped += 1
            continue

        try:
            content = open(summary_file, encoding="utf-8", errors="replace").read()
        except Exception:
            stopped += 1
            continue

        if "投稿OK" in content or "SUCCESS" in content:
            success += 1
            title = ""
            for line in content.split("\n"):
                if line.startswith("タイトル"):
                    title = line.split(":", 1)[-1].strip()[:60]
                    break
            if title:
                articles.append({"title": title, "date": date_part, "type": pipe_type})
        else:
            stopped += 1
            # 停止原因を抽出
            for line in content.split("\n"):
                if "停止" in line or "BLOCK" in line or "ERROR" in line or "失敗" in line:
                    stop_reasons[line.strip()[:60]] += 1
                    break
            # 停止エージェントを抽出
            for line in content.split("\n"):
                if "エージェント" in line or "agent" in line.lower():
                    for word in line.split():
                        if word in ("butterfree", "deoxys_kpop", "metamon_kpop",
                                    "jirachi_kpop", "arceus", "gengar", "eevee"):
                            error_agents[word] += 1
                            break

    rate = round(success * 100 / total, 1) if total else 0.0
    return {
        "period_days": days,
        "total_runs": total,
        "success": success,
        "stopped": stopped,
        "success_rate": rate,
        "pipeline_types": dict(pipeline_types),
        "error_agents_top5": dict(error_agents.most_common(5)),
        "stop_reasons_top5": dict(stop_reasons.most_common(5)),
        "recent_articles": articles[-10:],
    }


def collect_content_metrics() -> dict:
    """GSC/GA4メトリクスの最新データを読み込み"""
    result = {}

    # article_metrics_latest.json（data_collector.py出力）
    metrics_file = LOGS / "article_metrics_latest.json"
    if metrics_file.exists():
        try:
            data = json.loads(metrics_file.read_text(encoding="utf-8"))
            gsc_summary = data.get("gsc", {}).get("summary", {})
            ga4_summary = data.get("ga4", {}).get("summary", {})
            merged = data.get("merged_articles", [])

            result["gsc_summary"] = gsc_summary
            result["ga4_summary"] = ga4_summary
            result["top_articles"] = [
                {
                    "url": a.get("url", ""),
                    "clicks": a.get("gsc_clicks", 0),
                    "impressions": a.get("gsc_impressions", 0),
                    "ctr": a.get("gsc_ctr", 0),
                    "position": a.get("gsc_position", 0),
                    "pageviews": a.get("ga4_pageviews", 0),
                }
                for a in merged[:10]
            ]
        except Exception as e:
            result["metrics_error"] = str(e)

    # metrics_yesterday.json
    yesterday = GMETRICS / "metrics_yesterday.json"
    if yesterday.exists():
        try:
            ym = json.loads(yesterday.read_text(encoding="utf-8"))
            result["yesterday_ga4"] = ym.get("ga4", {}).get("summary", {})
            result["yesterday_gsc_top_queries"] = ym.get("gsc", {}).get("top_queries", [])[:10]
        except Exception:
            pass

    return result


def collect_agent_performance() -> dict:
    """エージェント別パフォーマンス（pipeline.jsonlから）"""
    pipeline_log = LOGS / "pipeline.jsonl"
    if not pipeline_log.exists():
        return {}

    cutoff = (datetime.now(JST) - timedelta(days=7)).isoformat()
    agent_stats: dict[str, dict] = defaultdict(lambda: {"ok": 0, "fail": 0, "empty": 0})

    for rec in _load_jsonl(pipeline_log, max_lines=2000):
        ts = rec.get("timestamp", "")
        if ts < cutoff:
            continue
        agent = rec.get("agent", rec.get("step", ""))
        status = rec.get("status", "")
        if not agent:
            continue
        if status in ("ok", "success"):
            agent_stats[agent]["ok"] += 1
        elif status in ("error", "fail", "stopped"):
            agent_stats[agent]["fail"] += 1
        elif status in ("empty", "fallback"):
            agent_stats[agent]["empty"] += 1

    # 成功率計算
    result = {}
    for agent, stats in sorted(agent_stats.items()):
        total = stats["ok"] + stats["fail"] + stats["empty"]
        rate = round(stats["ok"] * 100 / total, 1) if total else 0.0
        result[agent] = {**stats, "total": total, "rate": rate}

    return result


def collect_winning_patterns(days: int = 7) -> dict:
    """winning_patterns.jsonlから記事品質・CTRトレンドを分析"""
    patterns = _load_jsonl(LOGS / "winning_patterns.jsonl", max_lines=500)
    cutoff = (datetime.now(JST) - timedelta(days=days)).isoformat()

    scores = []
    category_scores: dict[str, list] = defaultdict(list)
    high_performers = []
    low_performers = []

    for p in patterns:
        ts = p.get("recorded_at", "")
        if ts < cutoff:
            continue
        score = p.get("eval_72h") or p.get("eval_48h") or p.get("eval_24h")
        if not score or not isinstance(score, (int, float)):
            continue
        score = float(score)
        scores.append(score)
        cat = p.get("category", "other")
        category_scores[cat].append(score)

        entry = {
            "title": p.get("title", "")[:50],
            "score": score,
            "category": cat,
        }
        if score >= 50:
            high_performers.append(entry)
        elif score < 30:
            low_performers.append(entry)

    avg = round(sum(scores) / len(scores), 1) if scores else 0.0
    cat_avg = {
        cat: round(sum(s) / len(s), 1)
        for cat, s in category_scores.items() if s
    }

    return {
        "total_evaluated": len(scores),
        "avg_score": avg,
        "category_avg": cat_avg,
        "high_performers": high_performers[-5:],
        "low_performers": low_performers[-5:],
    }


def generate_report(days: int = 7, output_format: str = "text") -> str:
    """全データを統合してポリゴン用レポートを生成"""
    archive = collect_archive_stats(days)
    metrics = collect_content_metrics()
    agents = collect_agent_performance()
    patterns = collect_winning_patterns(days)

    report = {
        "generated_at": datetime.now(JST).isoformat(),
        "period_days": days,
        "pipeline": archive,
        "content_metrics": metrics,
        "agent_performance": agents,
        "quality_trends": patterns,
    }

    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)

    # テキストレポート生成
    lines = []
    lines.append(f"═══ ポリゴン データ分析レポート（直近{days}日間）═══")
    lines.append(f"生成日時: {datetime.now(JST).strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # パイプライン健全性
    lines.append("【1. パイプライン健全性】")
    lines.append(f"  総実行: {archive['total_runs']}回")
    lines.append(f"  成功: {archive['success']}回 / 停止: {archive['stopped']}回")
    lines.append(f"  成功率: {archive['success_rate']}%")
    if archive["pipeline_types"]:
        types_str = ", ".join(f"{k}={v}" for k, v in archive["pipeline_types"].items())
        lines.append(f"  パイプライン種別: {types_str}")
    if archive["error_agents_top5"]:
        lines.append(f"  停止頻出エージェント: {archive['error_agents_top5']}")
    if archive["stop_reasons_top5"]:
        lines.append("  停止理由TOP5:")
        for reason, cnt in archive["stop_reasons_top5"].items():
            lines.append(f"    - [{cnt}回] {reason}")
    lines.append("")

    # コンテンツメトリクス
    lines.append("【2. アクセス・検索メトリクス】")
    if "gsc_summary" in metrics:
        gs = metrics["gsc_summary"]
        lines.append(f"  GSC: クリック={gs.get('total_clicks', 0)} "
                     f"表示={gs.get('total_impressions', 0)} "
                     f"平均CTR={gs.get('avg_ctr', 0):.4f} "
                     f"平均順位={gs.get('avg_position', 0)}")
    if "ga4_summary" in metrics:
        ga = metrics["ga4_summary"]
        lines.append(f"  GA4: PV={ga.get('total_pageviews', 0)} "
                     f"セッション={ga.get('total_sessions', 0)} "
                     f"ユーザー={ga.get('total_users', 0)}")
    if "top_articles" in metrics and metrics["top_articles"]:
        lines.append("  PV上位5記事:")
        for a in metrics["top_articles"][:5]:
            url_short = a["url"].replace("https://www.kpopjournal.tokyo/", "/")
            lines.append(f"    {url_short[:45]} PV={a['pageviews']} clicks={a['clicks']}")
    if "yesterday_gsc_top_queries" in metrics:
        lines.append("  昨日の検索クエリTOP5:")
        for q in metrics["yesterday_gsc_top_queries"][:5]:
            lines.append(f"    「{q.get('query', '')}」clicks={q.get('clicks', 0)} "
                         f"impr={q.get('impressions', 0)} pos={q.get('position', 0)}")
    lines.append("")

    # エージェント別パフォーマンス
    lines.append("【3. エージェント別パフォーマンス（直近7日）】")
    if agents:
        # 成功率降順でソート
        sorted_agents = sorted(agents.items(), key=lambda x: x[1]["rate"])
        for agent, stats in sorted_agents:
            icon = "🟢" if stats["rate"] >= 90 else ("🟡" if stats["rate"] >= 70 else "🔴")
            lines.append(f"  {icon} {agent}: {stats['rate']}% "
                         f"(OK={stats['ok']} FAIL={stats['fail']} EMPTY={stats['empty']} "
                         f"計{stats['total']})")
    else:
        lines.append("  pipeline.jsonl データなし")
    lines.append("")

    # 記事品質トレンド
    lines.append("【4. 記事品質トレンド】")
    lines.append(f"  評価済み記事: {patterns['total_evaluated']}本")
    lines.append(f"  平均スコア: {patterns['avg_score']}")
    if patterns["category_avg"]:
        lines.append("  カテゴリ別平均:")
        for cat, avg in sorted(patterns["category_avg"].items(), key=lambda x: -x[1]):
            lines.append(f"    {cat}: {avg}")
    if patterns["high_performers"]:
        lines.append("  高評価記事:")
        for a in patterns["high_performers"]:
            lines.append(f"    ★ [{a['score']}] {a['title']}")
    if patterns["low_performers"]:
        lines.append("  低評価記事:")
        for a in patterns["low_performers"]:
            lines.append(f"    ▼ [{a['score']}] {a['title']}")
    lines.append("")

    # 投稿記事一覧
    lines.append("【5. 投稿記事一覧（直近10件）】")
    for a in archive["recent_articles"]:
        lines.append(f"  [{a['type']}] {a['date']} {a['title']}")
    lines.append("")

    lines.append("═══ レポート終了 ═══")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="ポリゴン用データ分析パイプライン")
    ap.add_argument("--days", type=int, default=7, help="分析対象日数")
    ap.add_argument("--daily", action="store_true", help="日次サマリモード（1日）")
    ap.add_argument("--output", choices=["text", "json"], default="text",
                    help="出力形式")
    ap.add_argument("--save", action="store_true",
                    help="logs/porygon_report_YYYYMMDD.json に保存")
    args = ap.parse_args()

    days = 1 if args.daily else args.days
    report = generate_report(days=days, output_format=args.output)
    print(report)

    if args.save:
        out_dir = LOGS
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"porygon_report_{date.today().isoformat()}.json"
        full = generate_report(days=days, output_format="json")
        out_file.write_text(full, encoding="utf-8")
        print(f"\n保存: {out_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
