#!/usr/bin/env python3
"""
daily_kpi_injector.py — 日次KPI自動注入エンジン v1.0

【責務】
  1. 前日のGSC/GA4/AdSenseメトリクスを構造化サマリーに変換
  2. auto_directives.json に kpi_context セクションを自動更新
  3. 編集部朝会・全社夜会で参照可能な「数字根拠」テキストを生成
  4. 前日と7日平均の比較で異常/好調を自動フラグ付け

【パイプライン統合】
  improvement_engine.sh STEP 0.5 (06:00直後) から呼ばれる。
  daily_data_collect.sh → fetch_yesterday_metrics.py の後に走る前提。

Usage:
  python3 lib/daily_kpi_injector.py                  # auto_directives更新 + サマリー出力
  python3 lib/daily_kpi_injector.py --morning-brief  # 編集部朝会用ブリーフ
  python3 lib/daily_kpi_injector.py --evening-brief  # 全社夜会用ブリーフ
  python3 lib/daily_kpi_injector.py --dry-run        # 判定のみ
"""
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
GOOGLE_METRICS = BASE / "google_metrics"
LOGS = BASE / "logs"
CONFIG = BASE / "config"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

METRICS_PATH = GOOGLE_METRICS / "metrics_yesterday.json"
LOW_CTR_PATH = GOOGLE_METRICS / "low_ctr_pages.json"
AUTO_DIRECTIVES_PATH = CONFIG / "auto_directives.json"
KPI_POSTS_PATH = LOGS / "kpi_posts.jsonl"
PIPELINE_LOG_PATH = LOGS / "pipeline.jsonl"
AGENT_METRICS_PATH = BASE / "agent_metrics.json"


def _load_json(p: Path):
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_jsonl_tail(p: Path, n: int = 50) -> list[dict]:
    if not p.exists():
        return []
    records = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]:
        if line.strip():
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


# ═══════════════════════════════════════════════════════════════
# KPIサマリー生成
# ═══════════════════════════════════════════════════════════════

def build_kpi_summary() -> dict:
    """前日メトリクスから構造化KPIサマリーを生成する。"""
    metrics = _load_json(METRICS_PATH)
    if not metrics:
        return {"available": False, "reason": "metrics_yesterday.json not found"}

    ga4 = metrics.get("ga4", {})
    gsc = metrics.get("gsc", {})
    adsense = metrics.get("adsense", {})
    cta = metrics.get("cta_events", {})

    summary_ga4 = ga4.get("summary", {})
    sessions = int(summary_ga4.get("sessions", 0))
    users = int(summary_ga4.get("users", 0))
    pageviews = int(summary_ga4.get("pageviews", 0))
    avg_duration = float(summary_ga4.get("avg_session_duration", 0))
    x_sessions = ga4.get("x_sessions", 0)

    # GSC
    gsc_queries = gsc.get("top_queries", [])
    gsc_pages = gsc.get("top_pages", [])
    total_clicks = sum(q.get("clicks", 0) for q in gsc_queries)
    total_impressions = sum(q.get("impressions", 0) for q in gsc_queries)
    avg_ctr = total_clicks / total_impressions if total_impressions > 0 else 0

    # AdSense
    earnings = adsense.get("ESTIMATED_EARNINGS", "0")
    ad_pageviews = adsense.get("PAGE_VIEWS", "0")
    rpm = adsense.get("PAGE_VIEWS_RPM", "0")

    # CTA
    cta_total = cta.get("total_cta_clicks", 0)
    cta_ctr = cta.get("cta_ctr_real", 0)

    # 今日の投稿数
    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    posts = _load_jsonl_tail(KPI_POSTS_PATH, 30)
    yesterday_posts = [p for p in posts if p.get("date", "") == yesterday_str]
    today_posts = [p for p in posts if p.get("date", "") == today_str]

    # 低CTR
    low_ctr = _load_json(LOW_CTR_PATH)
    if isinstance(low_ctr, list):
        low_ctr_count = len([p for p in low_ctr if p.get("ctr", 1) < 0.02])
    else:
        low_ctr_count = 0

    # エージェント稼働
    agent_metrics = _load_json(AGENT_METRICS_PATH)
    agent_summary = agent_metrics.get("summary", {})

    return {
        "available": True,
        "date": metrics.get("date", yesterday_str),
        "ga4": {
            "sessions": sessions,
            "users": users,
            "pageviews": pageviews,
            "avg_duration": round(avg_duration, 1),
            "x_sessions": x_sessions,
        },
        "gsc": {
            "total_clicks": total_clicks,
            "total_impressions": total_impressions,
            "avg_ctr": round(avg_ctr, 4),
            "top_query": gsc_queries[0].get("query", "") if gsc_queries else "",
            "top_page_clicks": gsc_pages[0].get("clicks", 0) if gsc_pages else 0,
        },
        "adsense": {
            "earnings": earnings,
            "rpm": rpm,
        },
        "cta": {
            "total_clicks": cta_total,
            "ctr": round(cta_ctr, 4) if cta_ctr else 0,
        },
        "posts": {
            "yesterday_count": len(yesterday_posts),
            "today_count": len(today_posts),
        },
        "low_ctr_pages": low_ctr_count,
        "agents": {
            "overall_success_rate": agent_summary.get("overall_success_rate", 0),
            "active": agent_summary.get("active_agents", 0),
            "critical": agent_summary.get("critical_agents", 0),
        },
    }


def format_morning_brief(kpi: dict) -> str:
    """編集部朝会用の数字ブリーフを生成する。"""
    if not kpi.get("available"):
        return "【KPIデータ】取得できませんでした。"

    ga4 = kpi["ga4"]
    gsc = kpi["gsc"]
    ads = kpi["adsense"]
    posts = kpi["posts"]

    lines = [
        f"【前日KPIサマリー（{kpi['date']}）】",
        f"  PV: {ga4['pageviews']}  セッション: {ga4['sessions']}  ユーザー: {ga4['users']}",
        f"  平均滞在: {ga4['avg_duration']}秒  X流入: {ga4['x_sessions']}セッション",
        f"  GSC: クリック{gsc['total_clicks']}  表示{gsc['total_impressions']}  CTR={gsc['avg_ctr']:.2%}",
        f"  AdSense: ¥{ads['earnings']}  RPM: ¥{ads['rpm']}",
        f"  CTA: {kpi['cta']['total_clicks']}クリック (CTR={kpi['cta']['ctr']:.2%})",
        f"  投稿数: 前日{posts['yesterday_count']}本 / 本日{posts['today_count']}本",
        f"  低CTRページ: {kpi['low_ctr_pages']}件（要リライト候補）",
        "",
        "【数字から読む編集方針】",
    ]

    # 自動分析コメント
    if gsc["avg_ctr"] < 0.02:
        lines.append("  ⚠ CTR低下傾向 → タイトル訴求力を強化。感情語+数字+対比を意識。")
    if ga4["pageviews"] < 500:
        lines.append("  ⚠ PV低調 → SEO記事（検索流入重視）を優先。")
    if ga4["x_sessions"] > ga4["sessions"] * 0.3:
        lines.append("  📈 X流入好調 → SNS向け速報記事が有効。")
    if kpi["low_ctr_pages"] >= 5:
        lines.append(f"  ⚠ 低CTRページ{kpi['low_ctr_pages']}件 → リライト優先度を上げること。")
    if posts["yesterday_count"] == 0:
        lines.append("  🚨 前日投稿0件 → パイプライン状態を確認。")

    if gsc["top_query"]:
        lines.append(f"  🔍 最多検索キーワード: 「{gsc['top_query']}」")

    return "\n".join(lines)


def format_evening_brief(kpi: dict) -> str:
    """全社夜会用の本日実績ブリーフを生成する。"""
    if not kpi.get("available"):
        return "【本日KPIデータ】取得できませんでした。"

    ga4 = kpi["ga4"]
    gsc = kpi["gsc"]
    agents = kpi["agents"]
    posts = kpi["posts"]

    lines = [
        f"【本日の実績レビュー（{NOW.strftime('%Y-%m-%d')}）】",
        f"  前日PV: {ga4['pageviews']}  GSC CTR: {gsc['avg_ctr']:.2%}",
        f"  本日投稿: {posts['today_count']}本  前日投稿: {posts['yesterday_count']}本",
        f"  エージェント全体成功率: {agents['overall_success_rate']:.0%}",
        f"  アクティブ: {agents['active']}  CRITICAL: {agents['critical']}",
        "",
        "【明日への示唆】",
    ]

    if agents["critical"] > 0:
        lines.append(f"  ⚠ CRITICAL状態のエージェント{agents['critical']}件 → 修復を優先。")
    if gsc["avg_ctr"] >= 0.03:
        lines.append("  📈 CTR好調 → 現在のタイトル戦略を継続。")
    elif gsc["avg_ctr"] < 0.015:
        lines.append("  ⚠ CTR低迷 → タイトルリライト戦略を強化。")
    if posts["today_count"] >= 5:
        lines.append("  📈 投稿ペース良好。品質維持に注力。")
    elif posts["today_count"] <= 1:
        lines.append("  ⚠ 投稿数不足 → パイプライン稼働率を確認。")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# auto_directives.json への注入
# ═══════════════════════════════════════════════════════════════

def update_auto_directives(kpi: dict, dry_run: bool = False) -> bool:
    """auto_directives.jsonにkpi_contextセクションを更新する。"""
    if not kpi.get("available"):
        return False

    directives = _load_json(AUTO_DIRECTIVES_PATH)
    if not directives:
        directives = {}

    directives["kpi_context"] = {
        "updated_at": NOW.isoformat(),
        "date": kpi["date"],
        "pageviews": kpi["ga4"]["pageviews"],
        "sessions": kpi["ga4"]["sessions"],
        "gsc_ctr": kpi["gsc"]["avg_ctr"],
        "gsc_clicks": kpi["gsc"]["total_clicks"],
        "gsc_impressions": kpi["gsc"]["total_impressions"],
        "top_query": kpi["gsc"]["top_query"],
        "adsense_earnings": kpi["adsense"]["earnings"],
        "x_sessions": kpi["ga4"]["x_sessions"],
        "cta_clicks": kpi["cta"]["total_clicks"],
        "low_ctr_pages": kpi["low_ctr_pages"],
        "yesterday_posts": kpi["posts"]["yesterday_count"],
        "agent_success_rate": kpi["agents"]["overall_success_rate"],
        "morning_brief": format_morning_brief(kpi),
        "evening_brief": format_evening_brief(kpi),
    }
    directives["updated_at"] = NOW.isoformat()

    if dry_run:
        print(f"[DRY-RUN] auto_directives.json にkpi_contextを更新")
        return True

    AUTO_DIRECTIVES_PATH.write_text(
        json.dumps(directives, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return True


def main():
    parser = argparse.ArgumentParser(description="日次KPI自動注入エンジン v1.0")
    parser.add_argument("--morning-brief", action="store_true", help="朝会用ブリーフ出力")
    parser.add_argument("--evening-brief", action="store_true", help="夜会用ブリーフ出力")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    kpi = build_kpi_summary()

    if args.morning_brief:
        print(format_morning_brief(kpi))
        return

    if args.evening_brief:
        print(format_evening_brief(kpi))
        return

    # auto_directives更新
    updated = update_auto_directives(kpi, dry_run=args.dry_run)
    result = {"kpi_available": kpi.get("available", False), "directives_updated": updated}
    if kpi.get("available"):
        result["pageviews"] = kpi["ga4"]["pageviews"]
        result["gsc_ctr"] = kpi["gsc"]["avg_ctr"]
        result["posts_yesterday"] = kpi["posts"]["yesterday_count"]
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
