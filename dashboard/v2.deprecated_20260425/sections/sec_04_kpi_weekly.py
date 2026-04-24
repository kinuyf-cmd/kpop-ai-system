"""sec_04_kpi_weekly.py - Weekly KPI aggregation with sparklines."""
import json, sys
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "lib"))
from health_score import get_score_badge, score_for_section

BASE = Path(__file__).resolve().parent.parent.parent.parent
JST = timezone(timedelta(hours=9))

STYLE = """
<style>
.sec-kpi-weekly { background: #0f172a; border: 1px solid #334155; border-radius: 12px; padding: 20px; margin-bottom: 24px; }
.sec-kpi-weekly h2 { color: #a78bfa; margin: 0 0 16px 0; font-size: 1.2rem; }
.sec-kpi-weekly .summary-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; margin-bottom: 16px; }
.sec-kpi-weekly .stat-card { background: #1e293b; border-radius: 8px; padding: 14px; text-align: center; }
.sec-kpi-weekly .stat-value { color: #e2e8f0; font-size: 1.6rem; font-weight: 700; }
.sec-kpi-weekly .stat-label { color: #94a3b8; font-size: 0.8rem; margin-top: 4px; }
.sec-kpi-weekly .sparkline-row { display: flex; align-items: center; gap: 12px; background: #1e293b; border-radius: 8px; padding: 10px 14px; margin-bottom: 8px; }
.sec-kpi-weekly .spark-label { color: #94a3b8; font-size: 0.82rem; min-width: 100px; }
.sec-kpi-weekly .spark-bars { display: flex; align-items: end; gap: 3px; height: 32px; flex: 1; }
.sec-kpi-weekly .spark-bar { background: #6366f1; border-radius: 2px 2px 0 0; min-width: 8px; flex: 1; transition: height 0.3s; }
.sec-kpi-weekly .spark-total { color: #c4b5fd; font-size: 0.85rem; font-weight: 600; min-width: 60px; text-align: right; }
.sec-kpi-weekly .no-data { color: #64748b; font-style: italic; padding: 8px 0; }
</style>
"""


def load_json(rel_path):
    p = BASE / rel_path
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_standup(date_str):
    """Parse standup markdown for key values."""
    p = BASE / "data" / "meetings" / "general" / f"standup_{date_str}.md"
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")
    result = {"date": date_str}

    for m in re.finditer(r'\|\s*(.+?)\s*\|\s*(.+?)\s*\|', text):
        key, val = m.group(1).strip(), m.group(2).strip()
        num = re.search(r'[\d,]+\.?\d*', val.replace(",", ""))
        if not num:
            continue
        num_val = float(num.group().replace(",", ""))
        key_lower = key.lower()
        if "投稿数" in key or "記事" in key:
            result["articles"] = num_val
        elif "pv" in key_lower or "pageview" in key_lower:
            result["pv"] = num_val
        elif "セッション" in key or "session" in key_lower:
            result["sessions"] = num_val
        elif "エラー" in key:
            result["errors"] = num_val

    return result if len(result) > 1 else None


def _sparkline_html(label, values, total):
    if not values or max(values) == 0:
        return f'''<div class="sparkline-row">
  <span class="spark-label">{label}</span>
  <span class="no-data">データなし</span>
</div>'''
    max_val = max(values) if max(values) > 0 else 1
    bars = []
    for v in values:
        h = max(2, int(v / max_val * 30))
        bars.append(f'<div class="spark-bar" style="height:{h}px" title="{v:.0f}"></div>')
    total_display = f"{total:,.0f}"
    return f'''<div class="sparkline-row">
  <span class="spark-label">{label}</span>
  <div class="spark-bars">{"".join(bars)}</div>
  <span class="spark-total">{total_display}</span>
</div>'''


def render():
    now = datetime.now(JST)
    days = []
    for i in range(7, 0, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        days.append(d)

    # Collect daily standups
    standups = []
    for d in days:
        s = _parse_standup(d)
        standups.append(s)

    articles_list = [s.get("articles", 0) if s else 0 for s in standups]
    pv_list = [s.get("pv", 0) if s else 0 for s in standups]
    sessions_list = [s.get("sessions", 0) if s else 0 for s in standups]
    errors_list = [s.get("errors", 0) if s else 0 for s in standups]

    total_articles = sum(articles_list)
    total_pv = sum(pv_list)
    total_sessions = sum(sessions_list)
    total_errors = sum(errors_list)

    # GSC weekly data
    gsc = load_json("google_metrics/metrics_yesterday.json")
    gsc_summary = gsc.get("gsc", {}).get("summary", {})
    gsc_clicks = _safe_float(gsc_summary.get("clicks"))
    gsc_impressions = _safe_float(gsc_summary.get("impressions"))

    html_parts = [STYLE, '<div class="sec-kpi-weekly">']
    _badge = get_score_badge(score_for_section("sec_04"))
    html_parts.append(f'<h2>&#x1F4C8; 週次KPI（過去7日） {_badge}</h2>')

    # E-2: Action guidance
    html_parts.append('<div class="action-guidance">')
    html_parts.append('<div class="action-title">&#x1F3AF; Yutaが判断すべきこと</div>')
    html_parts.append('<div class="action-item">週次トレンドの方向性を確認し、施策の効果を判断してください</div>')
    html_parts.append(f'<div class="metric-highlight">{total_articles:.0f} <span style="font-size:0.9rem;color:#94a3b8;">週間記事</span></div>')
    html_parts.append('<div class="action-item" style="color:#94a3b8;">&#x1F4CA; 主要指標: 記事数 / PV / セッション / エラー数</div>')
    html_parts.append('</div>')

    # Summary cards
    html_parts.append('<div class="summary-grid">')
    cards = [
        (f"{total_articles:.0f}", "週間記事数"),
        (f"{total_pv:,.0f}", "週間PV"),
        (f"{total_sessions:,.0f}", "週間セッション"),
        (f"{gsc_clicks:,.0f}" if gsc_clicks is not None else "---", "GSCクリック(直近)"),
        (f"{gsc_impressions:,.0f}" if gsc_impressions is not None else "---", "GSC表示回数(直近)"),
        (f"{total_errors:.0f}", "週間エラー"),
    ]
    for val, label in cards:
        html_parts.append(f'''<div class="stat-card">
  <div class="stat-value">{val}</div>
  <div class="stat-label">{label}</div>
</div>''')
    html_parts.append("</div>")

    # Sparklines in collapsible details
    html_parts.append('<details open><summary style="color:#a78bfa;cursor:pointer;font-size:0.88rem;margin:12px 0 8px;">&#x1F50D; 詳細を表示</summary>')
    day_labels = [(now - timedelta(days=i)).strftime("%m/%d") for i in range(7, 0, -1)]
    html_parts.append(_sparkline_html("記事数", articles_list, total_articles))
    html_parts.append(_sparkline_html("PV", pv_list, total_pv))
    html_parts.append(_sparkline_html("セッション", sessions_list, total_sessions))
    html_parts.append(_sparkline_html("エラー", errors_list, total_errors))
    html_parts.append('</details>')

    html_parts.append("</div>")
    return "\n".join(html_parts)


def _safe_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None
