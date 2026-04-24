"""sec_03_kpi_daily.py - Daily KPI section with actuals vs targets."""
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
.sec-kpi-daily { background: #0f172a; border: 1px solid #334155; border-radius: 12px; padding: 20px; margin-bottom: 24px; }
.sec-kpi-daily h2 { color: #93c5fd; margin: 0 0 16px 0; font-size: 1.2rem; }
.sec-kpi-daily .date-label { color: #64748b; font-size: 0.8rem; margin-bottom: 12px; }
.sec-kpi-daily .kpi-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.sec-kpi-daily .kpi-card { background: #1e293b; border-radius: 8px; padding: 14px; }
.sec-kpi-daily .kpi-label { color: #94a3b8; font-size: 0.8rem; margin-bottom: 6px; }
.sec-kpi-daily .kpi-values { display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px; }
.sec-kpi-daily .kpi-actual { color: #e2e8f0; font-size: 1.4rem; font-weight: 700; }
.sec-kpi-daily .kpi-target { color: #64748b; font-size: 0.85rem; }
.sec-kpi-daily .bar-bg { background: #334155; border-radius: 4px; height: 8px; width: 100%; overflow: hidden; }
.sec-kpi-daily .bar-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
.sec-kpi-daily .bar-green { background: linear-gradient(90deg, #22c55e, #4ade80); }
.sec-kpi-daily .bar-yellow { background: linear-gradient(90deg, #eab308, #facc15); }
.sec-kpi-daily .bar-red { background: linear-gradient(90deg, #ef4444, #f87171); }
.sec-kpi-daily .bar-over { background: linear-gradient(90deg, #3b82f6, #60a5fa); }
.sec-kpi-daily .pct { color: #94a3b8; font-size: 0.75rem; text-align: right; margin-top: 2px; }
.sec-kpi-daily .no-data { color: #64748b; font-style: italic; padding: 8px 0; }
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
    """Parse standup markdown for KPI values."""
    p = BASE / "data" / "meetings" / "general" / f"standup_{date_str}.md"
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    result = {}

    # Parse table rows: | 指標 | 値 |
    for m in re.finditer(r'\|\s*(.+?)\s*\|\s*(.+?)\s*\|', text):
        key, val = m.group(1).strip(), m.group(2).strip()
        num = re.search(r'[\d,]+\.?\d*', val.replace(",", ""))
        if num:
            num_val = float(num.group().replace(",", ""))
        else:
            continue

        key_lower = key.lower()
        if "投稿数" in key or "記事" in key:
            result["articles_posted"] = num_val
        elif "pv" in key_lower or "pageview" in key_lower:
            result["pageviews"] = num_val
        elif "セッション" in key or "session" in key_lower:
            result["sessions"] = num_val
        elif "エラー" in key:
            result["errors"] = num_val
        elif "品質スコア" in key:
            result["quality_score"] = num_val
        elif "文字数" in key:
            result["avg_chars"] = num_val

    return result


def _bar_color(pct):
    if pct >= 100:
        return "bar-over"
    if pct >= 70:
        return "bar-green"
    if pct >= 40:
        return "bar-yellow"
    return "bar-red"


def _kpi_card(label, actual, target, unit=""):
    if actual is None:
        return f'''<div class="kpi-card">
  <div class="kpi-label">{label}</div>
  <div class="no-data">データなし</div>
</div>'''
    pct = (actual / target * 100) if target > 0 else 0
    pct_capped = min(pct, 100)
    color = _bar_color(pct)
    actual_display = f"{actual:,.0f}" if actual == int(actual) else f"{actual:,.1f}"
    target_display = f"{target:,.0f}" if target == int(target) else f"{target:,.1f}"
    return f'''<div class="kpi-card">
  <div class="kpi-label">{label}</div>
  <div class="kpi-values">
    <span class="kpi-actual">{actual_display}</span>
    <span class="kpi-target">/ {target_display} {_esc(unit)}</span>
  </div>
  <div class="bar-bg"><div class="bar-fill {color}" style="width:{pct_capped:.0f}%"></div></div>
  <div class="pct">{pct:.0f}%</div>
</div>'''


def _calc_quality_score():
    """Calculate quality score from quality_score_history.jsonl (latest entry average)."""
    records = load_jsonl("logs/quality_score_history.jsonl")
    if not records:
        return None
    latest = records[-1]
    scores = latest.get("scores", {})
    if not scores:
        return None
    vals = [v for v in scores.values() if isinstance(v, (int, float))]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 1)


def render():
    now = datetime.now(JST)
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    # Try today's standup first, then yesterday's
    standup = _parse_standup(today_str)
    used_date = today_str
    if not standup:
        standup = _parse_standup(yesterday_str)
        used_date = yesterday_str

    # Override quality_score with actual data from quality_score_history.jsonl
    actual_quality = _calc_quality_score()
    if actual_quality is not None:
        standup["quality_score"] = actual_quality

    targets = load_json("config/kpi_targets.json").get("daily", {})

    # GSC metrics
    gsc = load_json("google_metrics/metrics_yesterday.json")
    ga4_summary = gsc.get("ga4", {}).get("summary", {})
    gsc_summary = gsc.get("gsc", {}).get("summary", {})

    # Merge GA4 data if standup is sparse
    if "sessions" not in standup and ga4_summary.get("sessions"):
        try:
            standup["sessions"] = float(ga4_summary["sessions"])
        except Exception:
            pass
    if "pageviews" not in standup and ga4_summary.get("pageviews"):
        try:
            standup["pageviews"] = float(ga4_summary["pageviews"])
        except Exception:
            pass

    # Count today's X posts from kpi_posts.jsonl
    x_posts_today = 0
    kpi_posts = load_jsonl("logs/kpi_posts.jsonl")
    for rec in kpi_posts:
        ts = rec.get("timestamp", rec.get("date", ""))
        if today_str in ts or yesterday_str in ts:
            x_posts_today += 1

    html_parts = [STYLE, '<div class="sec-kpi-daily">']
    _badge = get_score_badge(score_for_section("sec_03"))
    html_parts.append(f'<h2>&#x1F4CA; 本日のKPI {_badge}</h2>')
    html_parts.append(f'<div class="date-label">{_esc(used_date)} のデータ</div>')

    # E-2: Action guidance
    articles_val = standup.get("articles_posted")
    sessions_val = standup.get("sessions")
    clicks_val = _safe_float(gsc_summary.get("clicks"))
    html_parts.append('<div class="action-guidance">')
    html_parts.append('<div class="action-title">&#x1F3AF; Yutaが判断すべきこと</div>')
    html_parts.append('<div class="action-item">目標未達のKPIがあれば対策を検討してください</div>')
    # Show top metric large
    if clicks_val is not None:
        html_parts.append(f'<div class="metric-highlight">{clicks_val:,.0f} <span style="font-size:0.9rem;color:#94a3b8;">GSCクリック</span></div>')
    elif sessions_val is not None:
        html_parts.append(f'<div class="metric-highlight">{sessions_val:,.0f} <span style="font-size:0.9rem;color:#94a3b8;">セッション</span></div>')
    html_parts.append('<div class="action-item" style="color:#94a3b8;">&#x1F4CA; 主要指標: 記事数 / PV / CTR / エラー数</div>')
    html_parts.append('</div>')

    html_parts.append('<div class="kpi-grid">')

    # Build KPI cards
    kpis = [
        ("記事公開数", articles_val, targets.get("articles_posted", {}).get("target", 5), "本"),
        ("セッション", sessions_val, targets.get("sessions", {}).get("target", 500), ""),
        ("PV", standup.get("pageviews"), targets.get("pageviews", {}).get("target", 700), ""),
        ("X投稿数", x_posts_today if x_posts_today > 0 else standup.get("x_posts"), targets.get("x_posts", {}).get("target", 4), "件"),
        ("GSCクリック", clicks_val, targets.get("gsc_clicks", {}).get("target", 50), ""),
        ("平均CTR", _safe_float(gsc_summary.get("ctr")), targets.get("avg_ctr", {}).get("target", 3.0), "%"),
        ("品質スコア", standup.get("quality_score"), 100.0, "点"),
        ("エラー件数", standup.get("errors"), targets.get("daily_errors", 0) if isinstance(targets.get("daily_errors"), (int, float)) else 0, "件"),
    ]

    for label, actual, target, unit in kpis:
        html_parts.append(_kpi_card(label, actual, target, unit))

    html_parts.append("</div>")

    # E-3: Chart.js 7-day trend chart
    # Collect 7 days of data for trend
    trend_labels = []
    trend_articles = []
    trend_sessions = []
    for i in range(7, 0, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        trend_labels.append((now - timedelta(days=i)).strftime("%m/%d"))
        s = _parse_standup(d)
        trend_articles.append(s.get("articles_posted", 0) if s else 0)
        trend_sessions.append(s.get("sessions", 0) if s else 0)

    import hashlib
    chart_id = "dailyTrend_" + hashlib.md5(today_str.encode()).hexdigest()[:6]
    labels_js = json.dumps(trend_labels)
    articles_js = json.dumps(trend_articles)
    sessions_js = json.dumps(trend_sessions)

    html_parts.append(f'''
<div style="background:#1e293b;border-radius:12px;padding:16px;margin-top:16px;">
  <div style="color:#94a3b8;font-size:0.85rem;font-weight:600;margin-bottom:8px;">7日間トレンド</div>
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
        labels: {labels_js},
        datasets: [
          {{
            label: '記事数',
            data: {articles_js},
            borderColor: '#ec4899',
            backgroundColor: 'rgba(236,72,153,0.1)',
            tension: 0.3,
            fill: true,
            yAxisID: 'y',
          }},
          {{
            label: 'セッション',
            data: {sessions_js},
            borderColor: '#38bdf8',
            backgroundColor: 'rgba(56,189,248,0.1)',
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
          y1: {{ position: 'right', ticks: {{ color: '#38bdf8', font: {{ size: 10 }} }}, grid: {{ drawOnChartArea: false }}, title: {{ display: true, text: 'セッション', color: '#38bdf8' }} }}
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
