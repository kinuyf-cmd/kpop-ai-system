"""sec_05_kpi_monthly.py - Monthly KPI aggregation with revenue and autonomy stats."""
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
.sec-kpi-monthly { background: #0f172a; border: 1px solid #334155; border-radius: 12px; padding: 20px; margin-bottom: 24px; }
.sec-kpi-monthly h2 { color: #67e8f9; margin: 0 0 16px 0; font-size: 1.2rem; }
.sec-kpi-monthly .month-label { color: #64748b; font-size: 0.8rem; margin-bottom: 12px; }
.sec-kpi-monthly .metric-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin-bottom: 16px; }
.sec-kpi-monthly .metric-card { background: #1e293b; border-radius: 8px; padding: 16px; }
.sec-kpi-monthly .metric-value { color: #e2e8f0; font-size: 1.5rem; font-weight: 700; }
.sec-kpi-monthly .metric-sub { color: #94a3b8; font-size: 0.78rem; margin-top: 2px; }
.sec-kpi-monthly .metric-label { color: #94a3b8; font-size: 0.82rem; margin-top: 6px; }
.sec-kpi-monthly .target-bar { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
.sec-kpi-monthly .bar-bg { background: #334155; border-radius: 4px; height: 6px; flex: 1; overflow: hidden; }
.sec-kpi-monthly .bar-fill { height: 100%; border-radius: 4px; }
.sec-kpi-monthly .bar-cyan { background: linear-gradient(90deg, #06b6d4, #22d3ee); }
.sec-kpi-monthly .bar-green { background: linear-gradient(90deg, #22c55e, #4ade80); }
.sec-kpi-monthly .pct-text { color: #67e8f9; font-size: 0.75rem; min-width: 40px; text-align: right; }
.sec-kpi-monthly .autonomy-section { background: #1e293b; border-radius: 8px; padding: 14px; margin-top: 12px; }
.sec-kpi-monthly .autonomy-title { color: #a78bfa; font-size: 0.9rem; font-weight: 600; margin-bottom: 8px; }
.sec-kpi-monthly .autonomy-row { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #334155; }
.sec-kpi-monthly .autonomy-label { color: #94a3b8; font-size: 0.82rem; }
.sec-kpi-monthly .autonomy-value { color: #e2e8f0; font-size: 0.85rem; font-weight: 600; }
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


def load_jsonl(rel_path):
    p = BASE / rel_path
    if not p.exists():
        return []
    records = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def _parse_standup(date_str):
    p = BASE / "data" / "meetings" / "general" / f"standup_{date_str}.md"
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")
    result = {}
    for m in re.finditer(r'\|\s*(.+?)\s*\|\s*(.+?)\s*\|', text):
        key, val = m.group(1).strip(), m.group(2).strip()
        num = re.search(r'[\d,]+\.?\d*', val.replace(",", ""))
        if not num:
            continue
        num_val = float(num.group().replace(",", ""))
        if "投稿数" in key or "記事" in key:
            result["articles"] = num_val
        elif "pv" in key.lower() or "pageview" in key.lower():
            result["pv"] = num_val
        elif "セッション" in key:
            result["sessions"] = num_val
    return result if result else None


def _monthly_bar(label, actual, target, unit=""):
    pct = (actual / target * 100) if target > 0 else 0
    pct_capped = min(pct, 100)
    color = "bar-green" if pct >= 80 else "bar-cyan"
    actual_disp = f"{actual:,.0f}" if actual == int(actual) else f"{actual:,.1f}"
    target_disp = f"{target:,.0f}" if target == int(target) else f"{target:,.1f}"
    return f'''<div class="metric-card">
  <div class="metric-value">{actual_disp}</div>
  <div class="metric-sub">目標: {target_disp} {_esc(unit)}</div>
  <div class="metric-label">{label}</div>
  <div class="target-bar">
    <div class="bar-bg"><div class="bar-fill {color}" style="width:{pct_capped:.0f}%"></div></div>
    <span class="pct-text">{pct:.0f}%</span>
  </div>
</div>'''


def render():
    now = datetime.now(JST)
    year_month = now.strftime("%Y-%m")
    month_display = now.strftime("%Y年%m月")

    # Aggregate all standups for current month
    total_articles = 0
    total_pv = 0
    total_sessions = 0
    days_with_data = 0

    for day in range(1, now.day + 1):
        date_str = f"{year_month}-{day:02d}"
        s = _parse_standup(date_str)
        if s:
            days_with_data += 1
            total_articles += s.get("articles", 0)
            total_pv += s.get("pv", 0)
            total_sessions += s.get("sessions", 0)

    # Targets
    targets = load_json("config/kpi_targets.json")
    monthly_targets = targets.get("monthly", {})

    # Revenue estimation from revenue_config.json
    rev_config = load_json("config/revenue_config.json")
    daily_rev_targets = rev_config.get("daily_revenue_targets", {})
    # Use month_1 target as current monthly target
    monthly_rev_target = daily_rev_targets.get("month_1", 3000)
    # Estimate revenue: PV * avg RPM / 1000
    adsense_rpm = rev_config.get("adsense_optimization", {}).get("rpm_target", 300)
    estimated_revenue = total_pv * adsense_rpm / 1000 if total_pv > 0 else 0

    # GSC average position
    gsc = load_json("google_metrics/metrics_yesterday.json")
    gsc_summary = gsc.get("gsc", {}).get("summary", {})
    avg_position = _safe_float(gsc_summary.get("position", gsc_summary.get("avg_position")))
    position_target = monthly_targets.get("avg_position", {}).get("target", 15)

    # Autonomy improvement rate from learning_history
    learning = load_jsonl("logs/learning_history.jsonl")
    month_learning = [r for r in learning if r.get("timestamp", "").startswith(year_month)]
    total_proposals = len(month_learning)
    applied_count = sum(1 for r in month_learning if r.get("applied", False))
    improvement_rate = (applied_count / total_proposals * 100) if total_proposals > 0 else 0

    # Zone breakdown
    zone_counts = {"green": 0, "yellow": 0, "red": 0}
    for r in month_learning:
        z = r.get("zone", "").lower()
        if "green" in z:
            zone_counts["green"] += 1
        elif "yellow" in z:
            zone_counts["yellow"] += 1
        elif "red" in z:
            zone_counts["red"] += 1

    html_parts = [STYLE, '<div class="sec-kpi-monthly">']
    _badge = get_score_badge(score_for_section("sec_05"))
    html_parts.append(f'<h2>&#x1F4C5; 月次KPI {_badge}</h2>')
    html_parts.append(f'<div class="month-label">{_esc(month_display)} ({days_with_data}日分のデータ)</div>')

    # E-2: Action guidance
    html_parts.append('<div class="action-guidance">')
    html_parts.append('<div class="action-title">&#x1F3AF; Yutaが判断すべきこと</div>')
    html_parts.append('<div class="action-item">月次目標の進捗を確認し、目標未達のKPIに対策を打ってください</div>')
    html_parts.append(f'<div class="metric-highlight">¥{estimated_revenue:,.0f} <span style="font-size:0.9rem;color:#94a3b8;">推定月間収益</span></div>')
    html_parts.append('<div class="action-item" style="color:#94a3b8;">&#x1F4CA; 主要指標: 記事数 / PV / セッション / 推定収益 / 自律改善率</div>')
    html_parts.append('</div>')

    html_parts.append('<div class="metric-grid">')

    # Article total
    art_target = monthly_targets.get("articles_total", {}).get("target", 150)
    html_parts.append(_monthly_bar("月間記事総数", total_articles, art_target, "本"))

    # PV
    pv_target = monthly_targets.get("pageviews", {}).get("target", 21000)
    html_parts.append(_monthly_bar("月間PV", total_pv, pv_target, ""))

    # Sessions
    sess_target = monthly_targets.get("sessions", {}).get("target", 15000)
    html_parts.append(_monthly_bar("月間セッション", total_sessions, sess_target, ""))

    # Estimated revenue
    html_parts.append(_monthly_bar("推定収益", estimated_revenue, monthly_rev_target, "円"))

    # GSC average position (lower is better, invert display)
    if avg_position is not None:
        # For position, closer to target (lower) is better
        pos_pct = (position_target / avg_position * 100) if avg_position > 0 else 0
        pos_pct = min(pos_pct, 100)
        color = "bar-green" if avg_position <= position_target else "bar-cyan"
        html_parts.append(f'''<div class="metric-card">
  <div class="metric-value">{avg_position:.1f}</div>
  <div class="metric-sub">目標: {position_target}位以内</div>
  <div class="metric-label">GSC平均掲載順位</div>
  <div class="target-bar">
    <div class="bar-bg"><div class="bar-fill {color}" style="width:{pos_pct:.0f}%"></div></div>
    <span class="pct-text">{pos_pct:.0f}%</span>
  </div>
</div>''')
    else:
        html_parts.append(f'''<div class="metric-card">
  <div class="metric-value">---</div>
  <div class="metric-label">GSC平均掲載順位</div>
</div>''')

    # Autonomy improvement rate
    html_parts.append(f'''<div class="metric-card">
  <div class="metric-value">{improvement_rate:.0f}%</div>
  <div class="metric-sub">{applied_count}/{total_proposals} 件適用</div>
  <div class="metric-label">自律改善適用率</div>
</div>''')

    html_parts.append("</div>")

    # Autonomy zone breakdown (collapsible)
    if total_proposals > 0:
        html_parts.append('<details><summary style="color:#a78bfa;cursor:pointer;font-size:0.88rem;margin:12px 0 8px;">&#x1F50D; 自律改善ゾーン内訳を表示</summary>')
        html_parts.append('<div class="autonomy-section">')
        html_parts.append('<div class="autonomy-title">自律改善ゾーン内訳</div>')
        for zone_name, zone_label, zone_color in [
            ("green", "GREEN（自動実行）", "#22c55e"),
            ("yellow", "YELLOW（事後確認）", "#eab308"),
            ("red", "RED（承認必須）", "#ef4444"),
        ]:
            count = zone_counts[zone_name]
            html_parts.append(f'''<div class="autonomy-row">
  <span class="autonomy-label" style="color:{zone_color}">{zone_label}</span>
  <span class="autonomy-value">{count}件</span>
</div>''')
        html_parts.append("</div>")
        html_parts.append("</details>")

    # E-3: Chart.js monthly cumulative trend
    import json as _json
    daily_articles_cumul = []
    daily_pv_cumul = []
    day_labels = []
    cum_art = 0
    cum_pv = 0
    for day in range(1, now.day + 1):
        date_str = f"{year_month}-{day:02d}"
        s = _parse_standup(date_str)
        cum_art += s.get("articles", 0) if s else 0
        cum_pv += s.get("pv", 0) if s else 0
        daily_articles_cumul.append(cum_art)
        daily_pv_cumul.append(cum_pv)
        day_labels.append(f"{day}日")

    if days_with_data > 1:
        chart_id = f"monthlyTrend_{year_month.replace('-', '')}"
        html_parts.append(f'''
<div style="background:#1e293b;border-radius:12px;padding:16px;margin-top:16px;">
  <div style="color:#94a3b8;font-size:0.85rem;font-weight:600;margin-bottom:8px;">月次累積トレンド</div>
  <div class="chart-container">
    <canvas id="{chart_id}"></canvas>
  </div>
</div>
<script>
(function() {{
  const ctx = document.getElementById('{chart_id}');
  if (ctx && typeof Chart !== 'undefined') {{
    new Chart(ctx, {{
      type: 'line',
      data: {{
        labels: {_json.dumps(day_labels)},
        datasets: [
          {{
            label: '累積記事数',
            data: {_json.dumps(daily_articles_cumul)},
            borderColor: '#ec4899',
            backgroundColor: 'rgba(236,72,153,0.1)',
            tension: 0.3,
            fill: true,
            yAxisID: 'y',
          }},
          {{
            label: '累積PV',
            data: {_json.dumps(daily_pv_cumul)},
            borderColor: '#22d3ee',
            backgroundColor: 'rgba(34,211,238,0.1)',
            tension: 0.3,
            fill: true,
            yAxisID: 'y1',
          }}
        ]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 11 }} }} }}
        }},
        scales: {{
          x: {{ ticks: {{ color: '#64748b', font: {{ size: 10 }} }}, grid: {{ color: 'rgba(51,65,85,0.5)' }} }},
          y: {{ position: 'left', ticks: {{ color: '#ec4899', font: {{ size: 10 }} }}, grid: {{ color: 'rgba(51,65,85,0.3)' }}, title: {{ display: true, text: '記事数', color: '#ec4899' }} }},
          y1: {{ position: 'right', ticks: {{ color: '#22d3ee', font: {{ size: 10 }} }}, grid: {{ drawOnChartArea: false }}, title: {{ display: true, text: 'PV', color: '#22d3ee' }} }}
        }}
      }}
    }});
  }}
}})();
</script>
''')

    html_parts.append("</div>")
    return "\n".join(html_parts)


def _safe_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
