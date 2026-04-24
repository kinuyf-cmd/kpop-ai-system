"""sec_09_seo_health — SEO Health section for dashboard v2."""

import json, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "lib"))
from health_score import get_score_badge, score_for_section

BASE = Path(__file__).resolve().parent.parent.parent.parent  # kpop-ai-system root
JST = timezone(timedelta(hours=9))


def load_json(rel_path):
    p = BASE / rel_path
    return json.loads(p.read_text()) if p.exists() else {}


def _short_url(url):
    """Strip domain, decode, and truncate for display."""
    path = url.replace("https://www.kpopjournal.tokyo", "")
    path = unquote(path)
    if len(path) > 55:
        path = path[:52] + "..."
    return path


def render() -> str:
    gsc_data = load_json("google_metrics/metrics_yesterday.json")
    low_ctr = load_json("google_metrics/low_ctr_pages.json")
    # low_ctr can be a list or dict with list inside
    if isinstance(low_ctr, dict):
        low_ctr_pages = low_ctr.get("pages", low_ctr.get("data", []))
        if not isinstance(low_ctr_pages, list):
            low_ctr_pages = []
    elif isinstance(low_ctr, list):
        low_ctr_pages = low_ctr
    else:
        low_ctr_pages = []

    # GSC overview
    gsc = gsc_data.get("gsc", {})
    ga4 = gsc_data.get("ga4", {})
    top_pages = gsc.get("top_pages", [])
    top_queries = gsc.get("top_queries", [])
    gsc_date = gsc_data.get("date", "?")
    period_label = gsc.get("period_label", "")

    # Totals from top_pages
    total_clicks = sum(p.get("clicks", 0) for p in top_pages)
    total_impressions = sum(p.get("impressions", 0) for p in top_pages)
    avg_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
    avg_position = (
        sum(p.get("position", 0) * p.get("impressions", 1) for p in top_pages)
        / max(total_impressions, 1)
    )

    # GA4 summary
    ga4_summary = ga4.get("summary", {})
    sessions = ga4_summary.get("sessions", "—")
    users = ga4_summary.get("users", "—")
    pageviews = ga4_summary.get("pageviews", "—")

    html = [
        '<div style="margin-bottom:24px;">',
        '<h2 style="color:#e2e8f0;font-size:1.4rem;margin-bottom:16px;">'
        f'🔍 SEO健全性 {get_score_badge(score_for_section("sec_09"))}</h2>',
    ]

    # E-2: Action guidance
    html.append('<div class="action-guidance">')
    html.append('<div class="action-title">&#x1F3AF; Yutaが判断すべきこと</div>')
    if avg_ctr < 2.0 and total_impressions > 0:
        html.append(f'<div class="action-item" style="color:#ef4444;">平均CTRが {avg_ctr:.2f}% と低いため、タイトル・メタ改善を検討してください</div>')
    elif len(low_ctr_pages) > 5:
        html.append(f'<div class="action-item" style="color:#eab308;">低CTRページが {len(low_ctr_pages)}件 あります。リライト優先順位を決めてください</div>')
    else:
        html.append('<div class="action-item">SEO指標を確認し、改善施策の効果を判定してください</div>')
    html.append(f'<div class="metric-highlight">{total_clicks:,} <span style="font-size:0.9rem;color:#94a3b8;">クリック</span></div>')
    html.append('<div class="action-item" style="color:#94a3b8;">&#x1F4CA; 主要指標: クリック / 表示回数 / CTR / 平均順位</div>')
    html.append('</div>')

    # Date label
    html.append(
        f'<div style="color:#64748b;font-size:0.78rem;margin-bottom:10px;">'
        f'GSC date: {gsc_date} {period_label}</div>'
    )

    # KPI cards
    kpis = [
        ("クリック", f"{total_clicks:,}", "#38bdf8"),
        ("表示回数", f"{total_impressions:,}", "#a78bfa"),
        ("平均CTR", f"{avg_ctr:.2f}%", "#22c55e" if avg_ctr >= 3 else "#eab308"),
        ("平均順位", f"{avg_position:.1f}", "#fb923c"),
        ("セッション", str(sessions), "#818cf8"),
        ("ユーザー", str(users), "#f472b6"),
    ]
    html.append(
        '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">'
    )
    for label, val, color in kpis:
        html.append(
            f'<div style="background:#1e293b;border-left:4px solid {color};'
            f'border-radius:8px;padding:10px 16px;min-width:100px;">'
            f'<div style="color:#94a3b8;font-size:0.75rem;">{label}</div>'
            f'<div style="color:{color};font-size:1.3rem;font-weight:700;">{val}</div>'
            f'</div>'
        )
    html.append("</div>")

    # Top 5 pages by clicks
    top5 = sorted(top_pages, key=lambda p: p.get("clicks", 0), reverse=True)[:5]
    if top5:
        html.append(
            '<div style="background:#1e293b;border-radius:8px;padding:14px 18px;'
            'margin-bottom:14px;">'
            '<div style="color:#38bdf8;font-size:0.9rem;font-weight:600;'
            'margin-bottom:8px;">クリック数 Top5 ページ</div>'
            '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;">'
            '<tr style="color:#94a3b8;text-align:left;">'
            '<th style="padding:4px 8px;">ページ</th>'
            '<th style="padding:4px 8px;">クリック</th>'
            '<th style="padding:4px 8px;">表示</th>'
            '<th style="padding:4px 8px;">CTR</th>'
            '<th style="padding:4px 8px;">順位</th></tr>'
        )
        for p in top5:
            ctr = p.get("ctr", 0) * 100
            ctr_c = "#22c55e" if ctr >= 5 else "#eab308" if ctr >= 2 else "#ef4444"
            html.append(
                f'<tr style="color:#e2e8f0;border-top:1px solid #334155;">'
                f'<td style="padding:4px 8px;max-width:280px;overflow:hidden;'
                f'text-overflow:ellipsis;white-space:nowrap;" title="{p.get("page","")}">'
                f'{_short_url(p.get("page", ""))}</td>'
                f'<td style="padding:4px 8px;font-weight:600;">{p.get("clicks",0)}</td>'
                f'<td style="padding:4px 8px;">{p.get("impressions",0):,}</td>'
                f'<td style="padding:4px 8px;color:{ctr_c};">{ctr:.1f}%</td>'
                f'<td style="padding:4px 8px;">{p.get("position",0):.1f}</td></tr>'
            )
        html.append("</table></div>")

    # Top queries
    top_q5 = sorted(top_queries, key=lambda q: q.get("clicks", 0), reverse=True)[:5]
    if top_q5:
        html.append(
            '<div style="background:#1e293b;border-radius:8px;padding:14px 18px;'
            'margin-bottom:14px;">'
            '<div style="color:#a78bfa;font-size:0.9rem;font-weight:600;'
            'margin-bottom:8px;">検索クエリ Top5</div>'
            '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;">'
            '<tr style="color:#94a3b8;text-align:left;">'
            '<th style="padding:4px 8px;">クエリ</th>'
            '<th style="padding:4px 8px;">クリック</th>'
            '<th style="padding:4px 8px;">表示</th>'
            '<th style="padding:4px 8px;">CTR</th>'
            '<th style="padding:4px 8px;">順位</th></tr>'
        )
        for q in top_q5:
            ctr = q.get("ctr", 0) * 100
            html.append(
                f'<tr style="color:#e2e8f0;border-top:1px solid #334155;">'
                f'<td style="padding:4px 8px;">{q.get("query","")}</td>'
                f'<td style="padding:4px 8px;font-weight:600;">{q.get("clicks",0)}</td>'
                f'<td style="padding:4px 8px;">{q.get("impressions",0):,}</td>'
                f'<td style="padding:4px 8px;">{ctr:.1f}%</td>'
                f'<td style="padding:4px 8px;">{q.get("position",0):.1f}</td></tr>'
            )
        html.append("</table></div>")

    # Low CTR pages
    if low_ctr_pages:
        shown = sorted(low_ctr_pages, key=lambda p: p.get("impressions", 0), reverse=True)[:8]
        html.append(
            '<details style="background:#1e293b;border-radius:8px;padding:14px 18px;">'
            f'<summary style="color:#eab308;cursor:pointer;font-weight:600;'
            f'font-size:0.9rem;">低CTRページ（{len(low_ctr_pages)}件）</summary>'
            '<table style="width:100%;border-collapse:collapse;font-size:0.8rem;'
            'margin-top:8px;">'
            '<tr style="color:#94a3b8;text-align:left;">'
            '<th style="padding:3px 8px;">Page</th>'
            '<th style="padding:3px 8px;">Clicks</th>'
            '<th style="padding:3px 8px;">Impr</th>'
            '<th style="padding:3px 8px;">CTR</th>'
            '<th style="padding:3px 8px;">Pos</th></tr>'
        )
        for p in shown:
            ctr = p.get("ctr", 0) * 100
            page_url = p.get("page", p.get("url", ""))
            html.append(
                f'<tr style="color:#cbd5e1;border-top:1px solid #334155;">'
                f'<td style="padding:3px 8px;">{_short_url(page_url)}</td>'
                f'<td style="padding:3px 8px;">{p.get("clicks",0)}</td>'
                f'<td style="padding:3px 8px;">{p.get("impressions",0):,}</td>'
                f'<td style="padding:3px 8px;color:#ef4444;">{ctr:.2f}%</td>'
                f'<td style="padding:3px 8px;">{p.get("position",0):.1f}</td></tr>'
            )
        html.append("</table></details>")

    # Index submission status (legacy plain-text log)
    idx_log = BASE / "logs" / "gsc_index_submit.log"
    if idx_log.exists():
        lines = idx_log.read_text().splitlines()
        recent = lines[-5:] if len(lines) >= 5 else lines
        html.append(
            '<div style="background:#1e293b;border-radius:8px;padding:14px 18px;'
            'margin-top:14px;">'
            '<div style="color:#94a3b8;font-size:0.85rem;font-weight:600;'
            'margin-bottom:4px;">インデックス申請（直近）</div>'
            '<div style="font-size:0.78rem;color:#cbd5e1;font-family:monospace;">'
        )
        for line in recent:
            html.append(f"<div>{line}</div>")
        html.append("</div></div>")

    # GSC Indexing API stats (from data/gsc_indexing_log.jsonl)
    gsc_idx_log = BASE / "data" / "gsc_indexing_log.jsonl"
    if gsc_idx_log.exists():
        today_str = datetime.now(tz=JST).strftime("%Y-%m-%d")
        total_today = 0
        ok_today = 0
        fallback_today = 0
        error_today = 0
        total_all = 0
        ok_all = 0
        recent_submissions = []
        try:
            for line in gsc_idx_log.read_text(errors="replace").splitlines():
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if entry.get("action") == "status_check":
                    continue
                total_all += 1
                st = entry.get("status", "")
                if st == "ok":
                    ok_all += 1
                ts = entry.get("timestamp", "")
                if ts[:10] == today_str:
                    total_today += 1
                    if st == "ok":
                        ok_today += 1
                    elif "fallback" in st:
                        fallback_today += 1
                    elif st == "error":
                        error_today += 1
                if entry.get("url"):
                    recent_submissions.append(entry)
        except Exception:
            pass

        success_rate = round(ok_all / max(total_all, 1) * 100, 1)
        recent_5 = recent_submissions[-5:]

        html.append(
            '<div style="background:#1e293b;border-radius:8px;padding:14px 18px;'
            'margin-top:14px;">'
            '<div style="color:#22d3ee;font-size:0.9rem;font-weight:600;'
            'margin-bottom:10px;">GSC Indexing API</div>'
        )
        # KPI row
        idx_kpis = [
            ("本日送信", str(total_today), "#38bdf8"),
            ("本日成功", str(ok_today), "#22c55e"),
            ("本日FB", str(fallback_today), "#eab308"),
            ("本日エラー", str(error_today), "#ef4444" if error_today > 0 else "#94a3b8"),
            ("累計成功率", f"{success_rate}%", "#22c55e" if success_rate >= 80 else "#eab308"),
        ]
        html.append('<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px;">')
        for label, val, color in idx_kpis:
            html.append(
                f'<div style="background:#0f172a;border-radius:6px;padding:6px 12px;'
                f'text-align:center;">'
                f'<div style="color:#64748b;font-size:0.7rem;">{label}</div>'
                f'<div style="color:{color};font-size:1.1rem;font-weight:700;">{val}</div>'
                f'</div>'
            )
        html.append('</div>')

        # Recent submissions
        if recent_5:
            html.append(
                '<div style="font-size:0.78rem;color:#94a3b8;margin-bottom:4px;">'
                '直近の送信:</div>'
                '<div style="font-size:0.75rem;font-family:monospace;">'
            )
            for entry in reversed(recent_5):
                st = entry.get("status", "?")
                url_short = _short_url(entry.get("url", ""))
                st_color = {"ok": "#22c55e", "fallback_ok": "#eab308",
                            "error": "#ef4444", "fallback_error": "#ef4444"
                            }.get(st, "#94a3b8")
                ts_short = entry.get("timestamp", "")[:16]
                method = entry.get("method", "")
                html.append(
                    f'<div style="color:#cbd5e1;margin-bottom:2px;">'
                    f'<span style="color:{st_color};">[{st}]</span> '
                    f'{url_short} '
                    f'<span style="color:#475569;">{ts_short} {method}</span></div>'
                )
            html.append('</div>')

        html.append('</div>')

    html.append("</div>")
    return "\n".join(html)
