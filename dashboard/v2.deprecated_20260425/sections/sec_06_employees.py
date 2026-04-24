"""sec_06_employees — All Employees section for dashboard v2."""

import json, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "lib"))
from health_score import get_score_badge, score_for_section

BASE = Path(__file__).resolve().parent.parent.parent.parent  # kpop-ai-system root
JST = timezone(timedelta(hours=9))


def load_json(rel_path):
    p = BASE / rel_path
    return json.loads(p.read_text()) if p.exists() else {}


def _autonomy_recognition_count():
    """Count how many agents/*.md mention autonomy_matrix."""
    agents_dir = BASE / "agents"
    if not agents_dir.exists():
        return 0, 0
    md_files = list(agents_dir.glob("*.md"))
    total = len(md_files)
    recognised = sum(
        1 for f in md_files if "autonomy_matrix" in f.read_text(errors="ignore")
    )
    return recognised, total


def render() -> str:
    metrics = load_json("agent_metrics.json")
    agents_raw = metrics.get("agents", {})

    # Build sorted list
    agents = []
    for aid, info in agents_raw.items():
        agents.append({
            "id": aid,
            "name": info.get("name_ja", aid),
            "role": info.get("role", ""),
            "rank": info.get("rank", "?"),
            "success_rate": info.get("success_rate", 0),
            "total": info.get("total_count", 0),
            "success": info.get("success_count", 0),
            "fail": info.get("fail_count", 0),
            "error_flag": info.get("error_flag", False),
            "sabori_flag": info.get("sabori_flag", False),
        })

    # Sort worst first
    agents.sort(key=lambda a: a["success_rate"])

    # Group by rank
    groups = {"🟢": [], "🟡": [], "🔴": []}
    for a in agents:
        r = a["rank"]
        if r in groups:
            groups[r].append(a)
        else:
            groups.setdefault("?", []).append(a)

    count_green = len(groups.get("🟢", []))
    count_yellow = len(groups.get("🟡", []))
    count_red = len(groups.get("🔴", []))
    count_total = len(agents)

    # Autonomy matrix recognition
    recog, md_total = _autonomy_recognition_count()
    recog_pct = (recog / md_total * 100) if md_total > 0 else 0

    # ---- HTML ----
    html_parts = [
        '<div style="margin-bottom:24px;">',
        '  <h2 style="color:#e2e8f0;font-size:1.4rem;margin-bottom:16px;">'
        f'👥 社員状況 {get_score_badge(score_for_section("sec_06"))}</h2>',
    ]

    # E-2: Action guidance
    html_parts.append('<div class="action-guidance">')
    html_parts.append('<div class="action-title">&#x1F3AF; Yutaが判断すべきこと</div>')
    if count_red > 0:
        html_parts.append(f'<div class="action-item" style="color:#ef4444;">&#x1F534; 要注意エージェント {count_red}名 の対応を検討してください</div>')
    else:
        html_parts.append('<div class="action-item">全エージェントの稼働状況を確認してください</div>')
    html_parts.append(f'<div class="metric-highlight">{count_total} <span style="font-size:0.9rem;color:#94a3b8;">名稼働中</span></div>')
    html_parts.append(f'<div class="action-item" style="color:#94a3b8;">&#x1F4CA; 主要指標: 合計{count_total}名 / &#x1F7E2;{count_green} &#x1F7E1;{count_yellow} &#x1F534;{count_red}</div>')
    html_parts.append('</div>')

    # Summary cards row
    cards = [
        ("合計", count_total, "#94a3b8"),
        ("🟢 優秀", count_green, "#22c55e"),
        ("🟡 注意", count_yellow, "#eab308"),
        ("🔴 要対応", count_red, "#ef4444"),
    ]
    html_parts.append(
        '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">'
    )
    for label, val, color in cards:
        html_parts.append(
            f'<div style="background:#1e293b;border-left:4px solid {color};'
            f'border-radius:8px;padding:12px 18px;min-width:120px;">'
            f'<div style="color:#94a3b8;font-size:0.8rem;">{label}</div>'
            f'<div style="color:{color};font-size:1.6rem;font-weight:700;">{val}</div>'
            f'</div>'
        )
    html_parts.append("</div>")

    # Autonomy matrix recognition bar
    bar_color = "#22c55e" if recog_pct >= 80 else "#eab308" if recog_pct >= 50 else "#ef4444"
    html_parts.append(
        f'<div style="background:#1e293b;border-radius:8px;padding:14px 18px;margin-bottom:16px;">'
        f'<div style="color:#94a3b8;font-size:0.85rem;margin-bottom:6px;">'
        f'自律マトリクス認識率 — {recog}/{md_total} エージェント '
        f'({recog_pct:.0f}%)</div>'
        f'<div style="background:#334155;border-radius:6px;height:14px;overflow:hidden;">'
        f'<div style="background:{bar_color};height:100%;width:{recog_pct:.1f}%;'
        f'border-radius:6px;transition:width .3s;"></div>'
        f'</div></div>'
    )

    # Top 5 worst performers
    worst5 = agents[:5]
    if worst5:
        html_parts.append(
            '<div style="background:#1e293b;border-radius:8px;padding:14px 18px;margin-bottom:16px;">'
            '<div style="color:#f87171;font-size:0.9rem;font-weight:600;margin-bottom:8px;">'
            '⚠ 要注意エージェント Top5</div>'
            '<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">'
            '<tr style="color:#94a3b8;text-align:left;">'
            '<th style="padding:4px 8px;">エージェント</th>'
            '<th style="padding:4px 8px;">役割</th>'
            '<th style="padding:4px 8px;">成功率</th>'
            '<th style="padding:4px 8px;">成功/失敗</th>'
            '<th style="padding:4px 8px;">フラグ</th></tr>'
        )
        for a in worst5:
            rate_color = "#ef4444" if a["success_rate"] < 0.5 else "#eab308"
            flags = []
            if a["error_flag"]:
                flags.append('<span style="color:#f87171;">ERR</span>')
            if a["sabori_flag"]:
                flags.append('<span style="color:#fb923c;">IDLE</span>')
            html_parts.append(
                f'<tr style="color:#e2e8f0;border-top:1px solid #334155;">'
                f'<td style="padding:4px 8px;">{a["rank"]} {a["name"]}</td>'
                f'<td style="padding:4px 8px;color:#94a3b8;max-width:200px;'
                f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{a["role"]}</td>'
                f'<td style="padding:4px 8px;color:{rate_color};font-weight:600;">'
                f'{a["success_rate"]*100:.1f}%</td>'
                f'<td style="padding:4px 8px;">{a["success"]}/{a["fail"]}</td>'
                f'<td style="padding:4px 8px;">{" ".join(flags) if flags else "—"}</td>'
                f'</tr>'
            )
        html_parts.append("</table></div>")

    # Full roster table (collapsible)
    html_parts.append(
        '<details style="background:#1e293b;border-radius:8px;padding:14px 18px;">'
        '<summary style="color:#e2e8f0;cursor:pointer;font-weight:600;font-size:0.9rem;">'
        f'&#x1F50D; 全社員一覧 ({count_total}名) — 成功率順 ▲</summary>'
        '<table style="width:100%;border-collapse:collapse;font-size:0.8rem;margin-top:10px;">'
        '<tr style="color:#94a3b8;text-align:left;">'
        '<th style="padding:4px 6px;">ランク</th>'
        '<th style="padding:4px 6px;">エージェント</th>'
        '<th style="padding:4px 6px;">役割</th>'
        '<th style="padding:4px 6px;">成功率</th>'
        '<th style="padding:4px 6px;">合計</th></tr>'
    )
    for a in agents:
        rate = a["success_rate"] * 100
        rc = "#22c55e" if rate >= 80 else "#eab308" if rate >= 50 else "#ef4444"
        html_parts.append(
            f'<tr style="color:#cbd5e1;border-top:1px solid #1e293b;">'
            f'<td style="padding:3px 6px;">{a["rank"]}</td>'
            f'<td style="padding:3px 6px;">{a["name"]}</td>'
            f'<td style="padding:3px 6px;color:#64748b;max-width:180px;'
            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{a["role"]}</td>'
            f'<td style="padding:3px 6px;color:{rc};font-weight:600;">{rate:.1f}%</td>'
            f'<td style="padding:3px 6px;">{a["total"]}</td></tr>'
        )
    html_parts.append("</table></details>")
    html_parts.append("</div>")
    return "\n".join(html_parts)
