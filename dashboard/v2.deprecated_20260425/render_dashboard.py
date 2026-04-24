#!/usr/bin/env python3
"""
render_dashboard.py — AI会社 統合監視ダッシュボード v2
モジュラー構造: sections/ 内の各モジュールが render() を返す
Phase 7 Track E/F: UX overhaul + Japanese localization
"""

import json
import sys
import importlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent
SECTIONS_DIR = ROOT / "sections"
OUT = ROOT.parent.parent / "dashboard_v2.html"
JST = timezone(timedelta(hours=9))
BASE = ROOT.parent.parent  # kpop-ai-system root

SECTION_MODULES = [
    ("sec_01_emergency",  "🔴 緊急対応",     "emergency"),
    ("sec_02_important",  "🟡 重要課題",     "important"),
    ("sec_03_kpi_daily",  "📊 本日のKPI",    "kpi-daily"),
    ("sec_04_kpi_weekly", "📈 週次KPI",      "kpi-weekly"),
    ("sec_05_kpi_monthly","📅 月次KPI",      "kpi-monthly"),
    ("sec_06_employees",  "👥 社員状況",     "employees"),
    ("sec_07_meetings",   "🏢 会議体",       "meetings"),
    ("sec_08_errors",     "⚠️ エラー監視",   "errors"),
    ("sec_09_seo_health", "🔍 SEO健全性",    "seo"),
    ("sec_10_revenue",    "💰 収益・収益化", "revenue"),
]


# ── Agent display name mapping (F-3) ──
def load_agent_display_map():
    """Load Japanese agent display names from config/agent_display_map.json."""
    p = BASE / "config" / "agent_display_map.json"
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        # Build quick lookup: agent_key -> "ディスプレイ名（役割）"
        mapping = {}
        for key, info in raw.items():
            if info.get("archived"):
                continue
            dn = info.get("display_name", key)
            role = info.get("role", "")
            mapping[key] = f"{dn}（{role}）" if role else dn
        return mapping
    except Exception:
        return {}


AGENT_DISPLAY_MAP = None  # lazy-loaded


def get_agent_display_map():
    global AGENT_DISPLAY_MAP
    if AGENT_DISPLAY_MAP is None:
        AGENT_DISPLAY_MAP = load_agent_display_map()
    return AGENT_DISPLAY_MAP


def agent_ja(agent_key):
    """Return Japanese display name for an agent key, with fallback."""
    m = get_agent_display_map()
    return m.get(agent_key, m.get(agent_key.replace("_kpop", ""), agent_key))


def build_nav(sections_with_labels):
    items = ""
    for _, label, anchor in sections_with_labels:
        items += f'<a href="#{anchor}" class="nav-item">{label}</a>\n'
    return f'''<nav class="sidebar">
<div class="sidebar-logo">KpopJournal</div>
<div class="sidebar-subtitle">AI会社 オーナーダッシュボード</div>
{items}</nav>'''


def build_html(section_htmls):
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")

    nav = build_nav(SECTION_MODULES)
    body_sections = ""
    for (_, label, anchor), html in zip(SECTION_MODULES, section_htmls):
        body_sections += f'''
<section id="{anchor}" class="section">
  <h2 class="section-title">{label}</h2>
  <div class="section-body">{html}</div>
</section>
'''

    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KpopJournal AI会社 — オーナーダッシュボード</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Hiragino Sans", "Noto Sans JP", sans-serif;
  background: #0f172a; color: #e2e8f0; display: flex; min-height: 100vh;
}}
/* ── K-POP Pink Gradient Accents ── */
.kpop-accent {{ background: linear-gradient(135deg, #ec4899, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
/* ── Sidebar ── */
.sidebar {{
  width: 240px; position: fixed; top: 0; left: 0; bottom: 0;
  background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
  padding: 0; overflow-y: auto;
  border-right: 1px solid #334155; z-index: 100;
}}
.sidebar-logo {{
  font-size: 1.3rem; font-weight: 800; padding: 20px 20px 4px;
  background: linear-gradient(135deg, #ec4899, #a855f7);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}}
.sidebar-subtitle {{
  font-size: 0.72rem; color: #64748b; padding: 0 20px 16px;
  border-bottom: 1px solid #334155;
}}
.sidebar .nav-item {{
  display: block; padding: 11px 20px; color: #94a3b8; text-decoration: none;
  font-size: 0.84rem; border-left: 3px solid transparent; transition: all 0.2s;
}}
.sidebar .nav-item:hover {{ color: #e2e8f0; background: rgba(255,255,255,0.05); border-left-color: rgba(236,72,153,0.4); }}
.sidebar .nav-item.active {{ color: #f472b6; border-left-color: #ec4899; background: rgba(236,72,153,0.08); }}
/* ── Main ── */
.main {{ margin-left: 240px; flex: 1; padding: 28px; max-width: 1200px; }}
.header {{
  display: flex; justify-content: space-between; align-items: center;
  padding-bottom: 16px; border-bottom: 1px solid #334155; margin-bottom: 28px;
}}
.header h1 {{ font-size: 1.5rem; font-weight: 700; }}
.header .ts {{ font-size: 0.8rem; color: #64748b; }}
/* ── Section cards ── */
.section {{ margin-bottom: 24px; }}
.section-title {{
  font-size: 1.2rem; font-weight: 700; padding: 14px 0; margin-bottom: 14px;
  border-bottom: 2px solid #334155;
  background: linear-gradient(90deg, #e2e8f0, #cbd5e1);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}}
.section-body {{ }}
/* ── Cards ── */
.card {{
  background: #1e293b; border-radius: 12px; padding: 18px; margin-bottom: 14px;
  border: 1px solid #334155; box-shadow: 0 2px 8px rgba(0,0,0,0.2);
  transition: box-shadow 0.2s;
}}
.card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,0.3); }}
.card-red {{ border-left: 4px solid #ef4444; background: rgba(239,68,68,0.06); }}
.card-yellow {{ border-left: 4px solid #eab308; background: rgba(234,179,8,0.06); }}
.card-green {{ border-left: 4px solid #22c55e; background: rgba(34,197,94,0.06); }}
.card-blue {{ border-left: 4px solid #3b82f6; background: rgba(59,130,246,0.06); }}
/* ── KPI Grid ── */
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }}
.kpi-card {{
  background: #1e293b; border-radius: 12px; padding: 18px; text-align: center;
  border: 1px solid #334155; box-shadow: 0 2px 8px rgba(0,0,0,0.2);
}}
.kpi-value {{ font-size: 2rem; font-weight: 800; color: #f8fafc; }}
.kpi-label {{ font-size: 0.78rem; color: #94a3b8; margin-top: 4px; }}
.kpi-target {{ font-size: 0.72rem; color: #64748b; }}
.progress-bar {{
  background: #334155; border-radius: 4px; height: 6px; margin-top: 8px; overflow: hidden;
}}
.progress-fill {{ height: 6px; border-radius: 4px; transition: width 0.3s; }}
/* ── Action guidance box (E-2) ── */
.action-guidance {{
  background: linear-gradient(135deg, rgba(236,72,153,0.08), rgba(168,85,247,0.08));
  border: 1px solid rgba(236,72,153,0.2); border-radius: 12px;
  padding: 16px 18px; margin-bottom: 16px;
}}
.action-guidance .action-title {{
  font-size: 0.92rem; font-weight: 700; color: #f472b6; margin-bottom: 8px;
}}
.action-guidance .action-item {{
  font-size: 0.84rem; color: #e2e8f0; padding: 3px 0;
}}
.action-guidance .metric-highlight {{
  font-size: 2.2rem; font-weight: 800; color: #f8fafc; margin: 4px 0;
}}
/* ── Tables ── */
table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
th {{ text-align: left; padding: 8px 12px; border-bottom: 2px solid #334155; color: #94a3b8; font-weight: 600; }}
td {{ padding: 8px 12px; border-bottom: 1px solid #1e293b; }}
tr:hover {{ background: rgba(255,255,255,0.02); }}
/* ── Badges ── */
.badge {{
  display: inline-block; padding: 2px 8px; border-radius: 99px;
  font-size: 0.72rem; font-weight: 700;
}}
.badge-red {{ background: rgba(239,68,68,0.15); color: #ef4444; }}
.badge-yellow {{ background: rgba(234,179,8,0.15); color: #eab308; }}
.badge-green {{ background: rgba(34,197,94,0.15); color: #22c55e; }}
.badge-blue {{ background: rgba(59,130,246,0.15); color: #3b82f6; }}
.empty {{ color: #475569; font-style: italic; padding: 20px; text-align: center; }}
/* ── Collapsible details ── */
details {{ border-radius: 12px; }}
details summary {{ cursor: pointer; user-select: none; }}
details summary:hover {{ opacity: 0.85; }}
/* ── Chart containers ── */
.chart-container {{ position: relative; height: 200px; margin: 12px 0; }}
/* ── Mobile responsive ── */
@media (max-width: 768px) {{
  .sidebar {{ display: none; }}
  .main {{ margin-left: 0; padding: 14px; }}
  .kpi-grid {{ grid-template-columns: repeat(2, 1fr); gap: 10px; }}
  .kpi-value {{ font-size: 1.5rem; }}
  .action-guidance .metric-highlight {{ font-size: 1.6rem; }}
  .chart-container {{ height: 160px; }}
}}
@media (max-width: 480px) {{
  .kpi-grid {{ grid-template-columns: 1fr; }}
  .header h1 {{ font-size: 1.1rem; }}
}}
</style>
</head>
<body>
{nav}
<div class="main">
<div class="header">
  <h1>KpopJournal AI会社 — オーナーダッシュボード</h1>
  <div class="ts">更新: {now}</div>
</div>
{body_sections}
<footer style="text-align:center;color:#475569;font-size:0.7rem;padding:32px 0 16px">
  Dashboard v2 Phase 7 — 「実装完了 ≠ 完了」原則に基づき、全データはリアルソースから取得<br>
  生成: {now}
</footer>
</div>
<script>
// Active nav highlighting on scroll
const sections = document.querySelectorAll('.section');
const navItems = document.querySelectorAll('.nav-item');
const observer = new IntersectionObserver(entries => {{
  entries.forEach(entry => {{
    if (entry.isIntersecting) {{
      navItems.forEach(n => n.classList.remove('active'));
      const id = entry.target.id;
      const active = document.querySelector(`.nav-item[href="#${{id}}"]`);
      if (active) active.classList.add('active');
    }}
  }});
}}, {{ threshold: 0.3 }});
sections.forEach(s => observer.observe(s));
</script>
</body>
</html>'''


def main():
    # Add sections dir to path
    sys.path.insert(0, str(SECTIONS_DIR))

    # Pre-load agent display map so sections can import it
    get_agent_display_map()

    section_htmls = []
    for mod_name, label, _ in SECTION_MODULES:
        try:
            mod = importlib.import_module(mod_name)
            html = mod.render()
            section_htmls.append(html)
            print(f"  ✅ {label}")
        except Exception as e:
            err_html = f'<div class="card card-red"><b>セクション読み込みエラー:</b> {e}</div>'
            section_htmls.append(err_html)
            print(f"  ❌ {label}: {e}")

    html = build_html(section_htmls)
    OUT.write_text(html)
    size = OUT.stat().st_size
    print(f"\n[dashboard v2] ✅ {OUT.name} 生成完了: {size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
