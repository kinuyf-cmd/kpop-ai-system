"""sec_10_revenue — 収益セクション for dashboard v2 (Phase 7 Track D-2 強化版)."""

import json, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "lib"))
from health_score import get_score_badge, score_for_section

BASE = Path(__file__).resolve().parent.parent.parent.parent  # kpop-ai-system root
JST = timezone(timedelta(hours=9))

# revenue_daily を動的にインポート
try:
    from revenue_daily import get_revenue_summary, get_top_articles_by_revenue
    HAS_REVENUE_DAILY = True
except ImportError:
    HAS_REVENUE_DAILY = False


def load_json(rel_path):
    p = BASE / rel_path
    return json.loads(p.read_text()) if p.exists() else {}


def _short_url(url):
    path = url.replace("https://www.kpopjournal.tokyo", "")
    path = unquote(path)
    if len(path) > 50:
        path = path[:47] + "..."
    return path


def _target_color(val, target):
    if target <= 0:
        return "#38bdf8"
    ratio = val / target
    if ratio >= 1.0:
        return "#22c55e"
    if ratio >= 0.5:
        return "#eab308"
    return "#ef4444"


def _trend_icon(trend: str) -> str:
    """トレンドに対応するアイコンを返す"""
    if trend == "上昇":
        return '<span style="color:#22c55e;">&#9650;</span>'
    elif trend == "下降":
        return '<span style="color:#ef4444;">&#9660;</span>'
    elif trend == "横ばい":
        return '<span style="color:#94a3b8;">&#9654;</span>'
    return '<span style="color:#64748b;">&#8212;</span>'


def _sparkline_svg(values: list, width: int = 180, height: int = 36,
                   color: str = "#22c55e") -> str:
    """値リストからインラインSVGスパークラインを生成（外部ライブラリ不要）"""
    if not values or len(values) < 2:
        return '<span style="color:#64748b;font-size:0.7rem;">データ不足</span>'

    max_val = max(values) if max(values) > 0 else 1
    min_val = min(values)
    val_range = max_val - min_val if max_val != min_val else 1
    pad = 2

    points = []
    for i, v in enumerate(values):
        x = pad + (i / (len(values) - 1)) * (width - 2 * pad)
        y = pad + (1 - (v - min_val) / val_range) * (height - 2 * pad)
        points.append(f"{x:.1f},{y:.1f}")

    polyline = " ".join(points)
    fill_points = (
        f"{pad:.1f},{height - pad:.1f} "
        + " ".join(points)
        + f" {width - pad:.1f},{height - pad:.1f}"
    )

    return (
        f'<svg width="{width}" height="{height}" style="vertical-align:middle;">'
        f'<polygon points="{fill_points}" fill="{color}22" />'
        f'<polyline points="{polyline}" fill="none" stroke="{color}" '
        f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />'
        f'</svg>'
    )


def _progress_bar(pct: float, label: str, color: str = None) -> str:
    """プログレスバーHTML生成"""
    clamped = min(max(pct, 0), 100)
    if color is None:
        color = "#22c55e" if clamped >= 100 else "#eab308" if clamped >= 50 else "#ef4444"
    return (
        f'<div style="margin-bottom:6px;">'
        f'<div style="display:flex;justify-content:space-between;font-size:0.72rem;'
        f'color:#94a3b8;margin-bottom:2px;">'
        f'<span>{label}</span><span style="color:{color};font-weight:700;">'
        f'{pct:.0f}%</span></div>'
        f'<div style="background:#334155;border-radius:6px;height:10px;'
        f'overflow:hidden;">'
        f'<div style="background:{color};height:100%;width:{clamped:.1f}%;'
        f'border-radius:6px;"></div></div></div>'
    )


def _load_cost_data() -> dict:
    """Load cost data from available sources with fallback chain."""
    # Source 1: cost_summary_daily.jsonl (from cost_daily_aggregator)
    summary_file = BASE / "data" / "cost_summary_daily.jsonl"
    if summary_file.exists():
        entries = []
        for line in summary_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        if entries:
            return {"source": "cost_summary_daily", "entries": entries}

    # Source 2: cost_daily.jsonl (from cost_optimizer)
    cost_daily = BASE / "logs" / "cost_daily.jsonl"
    if cost_daily.exists():
        entries = []
        for line in cost_daily.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        if entries:
            return {"source": "cost_daily", "entries": entries}

    # Source 3: estimate from pipeline.jsonl
    pipeline_log = BASE / "logs" / "pipeline.jsonl"
    if pipeline_log.exists():
        try:
            count = 0
            for line in pipeline_log.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip():
                    count += 1
            # Rough estimate: each pipeline entry ~ $0.02
            est_usd = count * 0.02
            return {
                "source": "pipeline_estimate",
                "entries": [{
                    "date": datetime.now(JST).strftime("%Y-%m-%d"),
                    "total_usd": round(est_usd, 2),
                    "total_jpy": round(est_usd * 150, 0),
                    "departments": {},
                    "top_agents": [],
                }]
            }
        except Exception:
            pass

    return {"source": "none", "entries": []}


def _render_cost_section() -> str:
    """Render the revenue-vs-cost and per-department cost subsections."""
    cost_data = _load_cost_data()
    entries = cost_data.get("entries", [])

    if not entries:
        return (
            '<div style="background:#1e293b;border-radius:8px;padding:14px 18px;'
            'margin-bottom:14px;margin-top:14px;">'
            '<div style="color:#94a3b8;font-size:0.82rem;">コストデータなし</div>'
            '</div>'
        )

    today_str = datetime.now(JST).strftime("%Y-%m-%d")

    # Find today's entry
    today_entry = None
    for e in entries:
        if e.get("date") == today_str:
            today_entry = e
            break
    if today_entry is None and entries:
        today_entry = entries[-1]  # latest available

    today_cost_usd = today_entry.get("total_usd", today_entry.get("cost_usd", 0))
    today_cost_jpy = today_entry.get("total_jpy", round(today_cost_usd * 150, 0))

    # Revenue estimate (from parent render scope is not accessible, re-load)
    rev_metrics = load_json("google_metrics/metrics_yesterday.json")
    adsense = rev_metrics.get("adsense", {})
    try:
        today_revenue_jpy = float(adsense.get("ESTIMATED_EARNINGS", "0"))
    except (TypeError, ValueError):
        today_revenue_jpy = 0

    today_profit_jpy = today_revenue_jpy - today_cost_jpy

    # 7-day and 30-day averages
    sorted_entries = sorted(entries, key=lambda x: x.get("date", ""))
    recent_7 = [e for e in sorted_entries if e.get("date", "") >= (
        datetime.now(JST) - timedelta(days=7)).strftime("%Y-%m-%d")]
    recent_30 = [e for e in sorted_entries if e.get("date", "") >= (
        datetime.now(JST) - timedelta(days=30)).strftime("%Y-%m-%d")]

    def _avg_cost(entries_list):
        if not entries_list:
            return 0, 0
        usd = sum(e.get("total_usd", e.get("cost_usd", 0)) for e in entries_list)
        jpy = sum(e.get("total_jpy", round(
            e.get("total_usd", e.get("cost_usd", 0)) * 150, 0)) for e in entries_list)
        n = len(entries_list)
        return round(usd / n, 4), round(jpy / n, 0)

    avg_7d_usd, avg_7d_jpy = _avg_cost(recent_7)
    avg_30d_usd, avg_30d_jpy = _avg_cost(recent_30)

    parts = []

    # ── 収益 vs コスト ──
    profit_color = "#22c55e" if today_profit_jpy >= 0 else "#ef4444"
    parts.append(
        '<div style="background:#1e293b;border-radius:8px;padding:14px 18px;'
        'margin-bottom:14px;margin-top:18px;">'
        '<div style="color:#f59e0b;font-size:0.95rem;font-weight:700;'
        'margin-bottom:12px;">収益 vs コスト</div>'
    )

    # Today's cards
    cards = [
        ("本日収益", f"&yen;{today_revenue_jpy:,.0f}", "#22c55e"),
        ("本日コスト", f"&yen;{today_cost_jpy:,.0f}", "#ef4444"),
        ("本日利益", f"&yen;{today_profit_jpy:,.0f}", profit_color),
    ]
    parts.append('<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;">')
    for label, val, color in cards:
        parts.append(
            f'<div style="background:#0f172a;border-left:3px solid {color};'
            f'border-radius:6px;padding:8px 14px;flex:1;min-width:90px;">'
            f'<div style="color:#94a3b8;font-size:0.7rem;">{label}</div>'
            f'<div style="color:{color};font-size:1.15rem;font-weight:700;">{val}</div>'
            f'</div>'
        )
    parts.append('</div>')

    # Averages table
    parts.append(
        '<table style="width:100%;border-collapse:collapse;font-size:0.78rem;">'
        '<tr style="color:#94a3b8;text-align:left;">'
        '<th style="padding:3px 8px;">期間</th>'
        '<th style="padding:3px 8px;">平均コスト/日</th>'
        '<th style="padding:3px 8px;">USD</th></tr>'
    )
    for period, jpy, usd in [
        ("7日平均", avg_7d_jpy, avg_7d_usd),
        ("30日平均", avg_30d_jpy, avg_30d_usd),
    ]:
        parts.append(
            f'<tr style="color:#e2e8f0;border-top:1px solid #334155;">'
            f'<td style="padding:3px 8px;">{period}</td>'
            f'<td style="padding:3px 8px;">&yen;{jpy:,.0f}</td>'
            f'<td style="padding:3px 8px;color:#64748b;">${usd:.4f}</td></tr>'
        )
    parts.append('</table>')
    parts.append('</div>')

    # ── 部署別コスト ──
    departments = today_entry.get("departments", {})
    if departments:
        parts.append(
            '<div style="background:#1e293b;border-radius:8px;padding:14px 18px;'
            'margin-bottom:14px;">'
            '<div style="color:#a78bfa;font-size:0.95rem;font-weight:700;'
            'margin-bottom:10px;">部署別コスト</div>'
            '<table style="width:100%;border-collapse:collapse;font-size:0.78rem;">'
            '<tr style="color:#94a3b8;text-align:left;">'
            '<th style="padding:4px 8px;">部署</th>'
            '<th style="padding:4px 8px;">コスト (JPY)</th>'
            '<th style="padding:4px 8px;">コスト (USD)</th>'
            '<th style="padding:4px 8px;">API呼出</th></tr>'
        )

        # Sort departments by cost descending
        dept_items = sorted(departments.items(),
                            key=lambda x: x[1].get("cost_usd",
                                                    x[1].get("usd", 0)),
                            reverse=True)

        dept_colors = {
            "editorial": "#818cf8", "publishing": "#fb923c",
            "marketing": "#34d399", "seo": "#22d3ee",
            "revenue": "#facc15", "finance": "#ec4899",
            "audit": "#fbbf24", "management": "#a78bfa",
            "competitive": "#f87171", "design": "#c084fc",
            "hr": "#f472b6", "general_affairs": "#94a3b8",
            "executive": "#38bdf8",
        }

        for dept_key, dept_data in dept_items:
            label = dept_data.get("label", dept_key)
            cost_jpy = dept_data.get("cost_jpy", dept_data.get("jpy", 0))
            cost_usd = dept_data.get("cost_usd", dept_data.get("usd", 0))
            calls = dept_data.get("api_calls", dept_data.get("calls", 0))
            color = dept_colors.get(dept_key, "#94a3b8")

            parts.append(
                f'<tr style="color:#e2e8f0;border-top:1px solid #334155;">'
                f'<td style="padding:4px 8px;">'
                f'<span style="display:inline-block;width:8px;height:8px;'
                f'border-radius:50%;background:{color};margin-right:6px;"></span>'
                f'{label}</td>'
                f'<td style="padding:4px 8px;">&yen;{cost_jpy:,.1f}</td>'
                f'<td style="padding:4px 8px;color:#64748b;">${cost_usd:.4f}</td>'
                f'<td style="padding:4px 8px;color:#64748b;">{calls}</td></tr>'
            )

        # Total row
        total_jpy = sum(d.get("cost_jpy", d.get("jpy", 0))
                        for d in departments.values())
        total_usd = sum(d.get("cost_usd", d.get("usd", 0))
                        for d in departments.values())
        total_calls = sum(d.get("api_calls", d.get("calls", 0))
                          for d in departments.values())
        parts.append(
            f'<tr style="color:#e2e8f0;border-top:2px solid #475569;font-weight:700;">'
            f'<td style="padding:4px 8px;">合計</td>'
            f'<td style="padding:4px 8px;">&yen;{total_jpy:,.1f}</td>'
            f'<td style="padding:4px 8px;color:#64748b;">${total_usd:.4f}</td>'
            f'<td style="padding:4px 8px;color:#64748b;">{total_calls}</td></tr>'
        )
        parts.append('</table></div>')

    # ── Top agents ──
    top_agents = today_entry.get("top_agents", [])
    if top_agents:
        parts.append(
            '<details style="background:#1e293b;border-radius:8px;padding:14px 18px;'
            'margin-bottom:14px;">'
            '<summary style="color:#38bdf8;cursor:pointer;font-weight:600;'
            'font-size:0.85rem;">コスト上位エージェント</summary>'
            '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;">'
        )
        for a in top_agents[:5]:
            agent = a.get("agent", "?")
            cost = a.get("cost_usd", 0)
            parts.append(
                f'<div style="background:#0f172a;border-radius:6px;padding:6px 12px;">'
                f'<span style="color:#e2e8f0;font-size:0.78rem;">{agent}</span> '
                f'<span style="color:#f59e0b;font-size:0.78rem;font-weight:600;">'
                f'${cost:.4f}</span></div>'
            )
        parts.append('</div></details>')

    return "\n".join(parts)


def render() -> str:
    rev_config = load_json("config/revenue_config.json")
    finance_targets = load_json("config/finance_targets.json")
    metrics = load_json("google_metrics/metrics_yesterday.json")

    adsense = metrics.get("adsense", {})

    # === dashboard.json正確値オーバーライド ===
    _fp = Path("/home/aiuser/kpopjournal-frontend/public/data/dashboard.json")
    if _fp.exists():
        try:
            _dd = json.loads(_fp.read_text(encoding="utf-8"))
            _ads = _dd.get("adsense", {})
            if _ads.get("available"):
                adsense["ESTIMATED_EARNINGS"] = str(_ads.get("yesterday_jpy", 0))
        except Exception:
            pass

    # ── revenue_daily からサマリー取得 ──
    summary = {}
    top_articles = []
    if HAS_REVENUE_DAILY:
        try:
            summary = get_revenue_summary(days=30)
            top_articles = get_top_articles_by_revenue(n=10)
        except Exception:
            summary = {}

    # ── 目標値 ──
    daily_target = finance_targets.get("daily", {}).get(
        "revenue_jpy", {}).get("target", 200)
    monthly_target = finance_targets.get("monthly", {}).get(
        "revenue_jpy", {}).get("target", 6000)
    rpm_target = rev_config.get("adsense_optimization", {}).get("rpm_target", 300)

    # ── サマリーデータ展開 ──
    yesterday = summary.get("yesterday", {})
    yesterday_rev = yesterday.get("revenue_jpy", 0)
    if not yesterday_rev and adsense:
        try:
            yesterday_rev = float(adsense.get("ESTIMATED_EARNINGS", "0"))
        except (TypeError, ValueError):
            yesterday_rev = 0

    avg_7d = summary.get("avg_7d_jpy", yesterday_rev)
    avg_30d = summary.get("avg_30d_jpy", yesterday_rev)
    mtd_revenue = summary.get("mtd_revenue_jpy", yesterday_rev)
    mtd_days = summary.get("mtd_days", 1)
    projected = summary.get("projected_monthly_jpy", yesterday_rev * 30)
    weekly_trend = summary.get("weekly_trend", "データ不足")
    monthly_trend = summary.get("monthly_trend", "データ不足")
    rpm_trend = summary.get("rpm_trend", "データ不足")
    avg_rpm = summary.get("avg_rpm", 0)
    avg_cpm = summary.get("avg_cpm", 0)

    if not avg_rpm and adsense:
        try:
            avg_rpm = float(adsense.get("PAGE_VIEWS_RPM", "0"))
        except (TypeError, ValueError):
            avg_rpm = 0

    sparkline_values = [d.get("revenue", 0)
                        for d in summary.get("daily_revenues", [])]

    targets_info = summary.get("targets", {})
    monthly_ach = targets_info.get("monthly_achievement_pct", 0)

    now_jst = datetime.now(JST).strftime("%m/%d %H:%M")

    # ── HTML構築 ──
    html = [
        '<div style="margin-bottom:24px;">',
        '<h2 style="color:#e2e8f0;font-size:1.4rem;margin-bottom:16px;">'
        f'💰 収益・収益化 {get_score_badge(score_for_section("sec_10"))}</h2>',
    ]

    # E-2: Action guidance
    html.append('<div class="action-guidance">')
    html.append('<div class="action-title">&#x1F3AF; Yutaが判断すべきこと</div>')
    if monthly_target > 0 and projected < monthly_target * 0.5:
        html.append(f'<div class="action-item" style="color:#ef4444;">月末予測が目標の50%未満です。収益施策の強化を検討してください</div>')
    else:
        html.append('<div class="action-item">収益トレンドを確認し、ASP・AdSense最適化の方向性を判断してください</div>')
    html.append(f'<div class="metric-highlight">¥{projected:,.0f} <span style="font-size:0.9rem;color:#94a3b8;">月末予測</span></div>')
    html.append('<div class="action-item" style="color:#94a3b8;">&#x1F4CA; 主要指標: 昨日収益 / 7日平均 / 月累計 / 月末予測 / RPM</div>')
    html.append('</div>')

    # ── KPIカード群 ──
    kpis = [
        ("昨日の収益",
         f"¥{yesterday_rev:,.0f}",
         _target_color(yesterday_rev, daily_target),
         f"目標 ¥{daily_target:,}/日"),
        ("7日平均",
         f"¥{avg_7d:,.0f}",
         _target_color(avg_7d, daily_target),
         f"{weekly_trend} {_trend_icon(weekly_trend)}"),
        ("30日平均",
         f"¥{avg_30d:,.0f}",
         _target_color(avg_30d, daily_target),
         f"{monthly_trend} {_trend_icon(monthly_trend)}"),
        ("月累計",
         f"¥{mtd_revenue:,.0f}",
         _target_color(mtd_revenue, monthly_target),
         f"{mtd_days}日経過"),
        ("月末予測",
         f"¥{projected:,.0f}",
         _target_color(projected, monthly_target),
         f"目標 ¥{monthly_target:,}"),
    ]

    html.append(
        '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px;">'
    )
    for label, val, color, sub in kpis:
        html.append(
            f'<div style="background:#1e293b;border-left:4px solid {color};'
            f'border-radius:8px;padding:10px 14px;min-width:110px;flex:1;">'
            f'<div style="color:#94a3b8;font-size:0.72rem;">{label}</div>'
            f'<div style="color:{color};font-size:1.3rem;font-weight:700;">{val}</div>'
            f'<div style="color:#64748b;font-size:0.68rem;">{sub}</div>'
            f'</div>'
        )
    html.append("</div>")

    # ── 月次目標プログレスバー ──
    html.append(
        '<div style="background:#1e293b;border-radius:8px;padding:14px 18px;'
        'margin-bottom:14px;">'
        '<div style="color:#94a3b8;font-size:0.82rem;font-weight:600;'
        'margin-bottom:10px;">月次目標進捗</div>'
    )
    html.append(_progress_bar(
        monthly_ach,
        f"収益: ¥{mtd_revenue:,.0f} / ¥{monthly_target:,}"
    ))
    rpm_ach = (avg_rpm / rpm_target * 100) if rpm_target > 0 else 0
    html.append(_progress_bar(
        rpm_ach,
        f"RPM: ¥{avg_rpm:,.0f} / ¥{rpm_target:,}"
    ))
    html.append("</div>")

    # ── CPM/RPMトレンド ──
    html.append(
        '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px;">'
    )
    for label, val, color, sub in [
        ("RPM (1000PVあたり収益)",
         f"¥{avg_rpm:,.0f}", _target_color(avg_rpm, rpm_target),
         f"{rpm_trend} {_trend_icon(rpm_trend)}"),
        ("CPM (1000インプレッションあたり)",
         f"¥{avg_cpm:,.0f}", "#a78bfa", ""),
    ]:
        html.append(
            f'<div style="background:#1e293b;border-radius:8px;padding:10px 14px;'
            f'flex:1;min-width:160px;">'
            f'<div style="color:#94a3b8;font-size:0.72rem;">{label}</div>'
            f'<div style="color:{color};font-size:1.2rem;font-weight:700;">{val}</div>'
            f'<div style="color:#64748b;font-size:0.68rem;">{sub}</div>'
            f'</div>'
        )
    html.append("</div>")

    # ── 収益スパークライン ──
    if sparkline_values and len(sparkline_values) >= 2:
        sparkline_color = (
            "#22c55e" if weekly_trend == "上昇"
            else "#ef4444" if weekly_trend == "下降"
            else "#eab308"
        )
        spark_svg = _sparkline_svg(sparkline_values, width=280, height=40,
                                    color=sparkline_color)
        daily_revenues = summary.get("daily_revenues", [])
        dates = [d.get("date", "")[-5:] for d in daily_revenues]
        first_date = dates[0] if dates else ""
        last_date = dates[-1] if dates else ""

        html.append(
            f'<div style="background:#1e293b;border-radius:8px;padding:14px 18px;'
            f'margin-bottom:14px;">'
            f'<div style="color:#94a3b8;font-size:0.82rem;font-weight:600;'
            f'margin-bottom:8px;">収益推移（直近{len(sparkline_values)}日）</div>'
            f'<div style="display:flex;align-items:center;gap:14px;">'
            f'{spark_svg}'
            f'<div style="font-size:0.68rem;color:#64748b;">'
            f'{first_date} → {last_date}</div>'
            f'</div></div>'
        )

    # ── 推定収益上位記事 ──
    display_articles = top_articles if top_articles else []
    if not display_articles:
        # フォールバック: metrics_yesterday から GA4ページ
        ga4_pages = metrics.get("ga4", {}).get("top_landing_pages", [])
        for p in ga4_pages:
            path = p.get("page", "")
            if path and path != "(not set)":
                pv = int(p.get("pageviews", p.get("sessions", 0)))
                display_articles.append({
                    "url": path,
                    "pageviews": pv,
                    "est_revenue_jpy": pv * avg_rpm / 1000 if avg_rpm > 0 else pv * 2,
                })
        display_articles.sort(
            key=lambda x: x.get("est_revenue_jpy", 0), reverse=True
        )

    top10 = display_articles[:10]
    if top10:
        html.append(
            '<div style="background:#1e293b;border-radius:8px;padding:14px 18px;'
            'margin-bottom:14px;">'
            '<div style="color:#22c55e;font-size:0.9rem;font-weight:600;'
            'margin-bottom:8px;">推定収益上位記事 Top 10</div>'
            '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;">'
            '<tr style="color:#94a3b8;text-align:left;">'
            '<th style="padding:4px 8px;">#</th>'
            '<th style="padding:4px 8px;">記事</th>'
            '<th style="padding:4px 8px;">PV</th>'
            '<th style="padding:4px 8px;">推定収益</th></tr>'
        )
        for i, a in enumerate(top10, 1):
            est = a.get("est_revenue_jpy", a.get("est_revenue", 0))
            pv = a.get("pageviews", a.get("pv", 0))
            url = a.get("url", "")
            rev_c = (
                "#22c55e" if est >= 50
                else "#eab308" if est >= 10
                else "#94a3b8"
            )
            html.append(
                f'<tr style="color:#e2e8f0;border-top:1px solid #334155;">'
                f'<td style="padding:4px 8px;color:#64748b;">{i}</td>'
                f'<td style="padding:4px 8px;max-width:300px;overflow:hidden;'
                f'text-overflow:ellipsis;white-space:nowrap;" title="{url}">'
                f'{_short_url(url)}</td>'
                f'<td style="padding:4px 8px;">{pv:,}</td>'
                f'<td style="padding:4px 8px;color:{rev_c};font-weight:600;">'
                f'¥{est:,.0f}</td></tr>'
            )
        html.append("</table></div>")

    # ── 収益チャネル ──
    asp_providers = rev_config.get("asp_providers", {})
    if asp_providers:
        html.append(
            '<details style="background:#1e293b;border-radius:8px;padding:14px 18px;">'
            f'<summary style="color:#a78bfa;cursor:pointer;font-weight:600;'
            f'font-size:0.9rem;">収益チャネル ({len(asp_providers)})</summary>'
            '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:10px;">'
        )
        for pid, info in asp_providers.items():
            name = info.get("name", pid)
            cats = ", ".join(info.get("categories", [])[:3])
            avg_c = info.get(
                "avg_commission", info.get("avg_commission_rate", "—")
            )
            if isinstance(avg_c, float) and avg_c < 1:
                avg_label = f"{avg_c*100:.0f}%"
            else:
                avg_label = (
                    f"¥{avg_c:,}"
                    if isinstance(avg_c, (int, float))
                    else str(avg_c)
                )
            html.append(
                f'<div style="background:#0f172a;border-radius:6px;padding:8px 14px;'
                f'min-width:160px;">'
                f'<div style="color:#e2e8f0;font-size:0.82rem;font-weight:600;">'
                f'{name}</div>'
                f'<div style="color:#94a3b8;font-size:0.72rem;">{cats}</div>'
                f'<div style="color:#38bdf8;font-size:0.78rem;">平均: {avg_label}</div>'
                f'</div>'
            )
        html.append("</div></details>")

    # ── 収益 vs コスト セクション ──
    html.append(_render_cost_section())

    # ── フッター ──
    html.append(
        f'<div style="color:#334155;font-size:0.6rem;margin-top:8px;">'
        f'※ 推定収益はRPMベースの概算値です。更新: {now_jst} JST</div>'
    )

    html.append("</div>")
    return "\n".join(html)
