"""sec_07_meetings — Meetings section for dashboard v2.

部門別スタンドアップ（5部門）+ 週次取締役会 + 未解決課題カウント を表示。
"""

import json, sys
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "lib"))
from health_score import get_score_badge, score_for_section

BASE = Path(__file__).resolve().parent.parent.parent.parent  # kpop-ai-system root
JST = timezone(timedelta(hours=9))

DEPT_STANDUP_BASE = BASE / "logs" / "standup" / "department"
BOARD_MEETING_DIR = BASE / "logs" / "board_meeting"
ERROR_PATTERNS_PATH = BASE / "config" / "error_patterns.json"
ORG_PATH = BASE / "config" / "organization.json"


def _today_jst():
    return datetime.now(JST).strftime("%Y-%m-%d")


def _yesterday_jst():
    return (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")


def _load_json_safe(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _read_standup(date_str):
    """Read a standup markdown and extract key metrics from the table."""
    p = BASE / "data" / "meetings" / "general" / f"standup_{date_str}.md"
    if not p.exists():
        return None
    text = p.read_text(errors="ignore")

    metrics = {}
    for m in re.finditer(r"\|\s*(.+?)\s*\|\s*(.+?)\s*\|", text):
        key = m.group(1).strip()
        val = m.group(2).strip()
        if key in ("指標", "---", "------"):
            continue
        metrics[key] = val

    errors = []
    for m in re.finditer(r"-\s+\*\*(.+?)\*\*.*?:\s*(\d+)\s*件", text):
        errors.append((m.group(1), int(m.group(2))))

    return {"date": date_str, "metrics": metrics, "errors": errors, "raw": text}


def _parse_num(val_str):
    """Extract a number from a string like '3 件' or '76.0%'."""
    m = re.search(r"[\d.]+", val_str.replace(",", ""))
    return float(m.group()) if m else None


def _delta_arrow(today_val, yest_val, higher_is_better=True):
    if today_val is None or yest_val is None:
        return ""
    if today_val > yest_val:
        arrow = "↑"
        color = "#22c55e" if higher_is_better else "#ef4444"
    elif today_val < yest_val:
        arrow = "↓"
        color = "#ef4444" if higher_is_better else "#22c55e"
    else:
        return '<span style="color:#94a3b8;">→</span>'
    diff = today_val - yest_val
    sign = "+" if diff > 0 else ""
    return f'<span style="color:{color};">{arrow} {sign}{diff:.1f}</span>'


def _list_weekly_meetings():
    d = BASE / "data" / "meetings" / "weekly"
    if not d.exists():
        return []
    files = sorted(d.glob("*.md"), reverse=True)
    return [f.name for f in files[:5]]


def _count_unresolved_issues():
    """error_patterns.json から未解決エラー件数を取得。"""
    data = _load_json_safe(ERROR_PATTERNS_PATH)
    count = 0
    for key, pat in data.get("patterns", {}).items():
        if not pat.get("resolved_at"):
            count += 1
    return count


def _read_dept_standups(date_str):
    """指定日の部門別スタンドアップを読み込む。"""
    org = _load_json_safe(ORG_PATH)
    departments = org.get("departments", {})
    results = []

    date_dir = DEPT_STANDUP_BASE / date_str
    if not date_dir.exists():
        return results

    for dept_key, dept_config in departments.items():
        dept_name = dept_config.get("name", dept_key)
        icon = dept_config.get("icon", "")
        path = date_dir / f"{dept_name}.md"
        if not path.exists():
            continue

        text = path.read_text(encoding="utf-8", errors="ignore")

        members = []
        for m in re.finditer(
            r"\|\s*(.+?)\s*\|\s*([\d.]+%)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|", text
        ):
            name = m.group(1).strip()
            if name in ("メンバー", "---"):
                continue
            members.append({
                "name": name,
                "rate": m.group(2).strip(),
                "rank": m.group(3).strip(),
            })

        pipeline_total = 0
        pipeline_errors = 0
        for m in re.finditer(r"パイプライン実行数\s*\|\s*(\d+)", text):
            pipeline_total = int(m.group(1))
        for m in re.finditer(r"エラー数\s*\|\s*(\d+)", text):
            pipeline_errors = int(m.group(1))

        results.append({
            "key": dept_key,
            "name": dept_name,
            "icon": icon,
            "members": members,
            "pipeline_total": pipeline_total,
            "pipeline_errors": pipeline_errors,
        })

    return results


def _read_latest_board_meeting():
    """最新の取締役会レポートのサマリを取得。"""
    if not BOARD_MEETING_DIR.exists():
        return None

    files = sorted(BOARD_MEETING_DIR.glob("*.md"), reverse=True)
    if not files:
        return None

    latest = files[0]
    text = latest.read_text(encoding="utf-8", errors="ignore")

    kpis = {}
    for m in re.finditer(r"\|\s*(.+?)\s*\|\s*(.+?)\s*\|", text):
        key = m.group(1).strip()
        val = m.group(2).strip()
        if key in ("指標", "---", "------", "値"):
            continue
        kpis[key] = val

    return {
        "filename": latest.name,
        "kpis": kpis,
    }


def render() -> str:
    today_str = _today_jst()
    yest_str = _yesterday_jst()
    today = _read_standup(today_str)
    yest = _read_standup(yest_str)

    unresolved_count = _count_unresolved_issues()

    html = [
        '<div style="margin-bottom:24px;">',
        '<h2 style="color:#e2e8f0;font-size:1.4rem;margin-bottom:16px;">'
        f'🏢 会議体 {get_score_badge(score_for_section("sec_07"))}</h2>',
    ]

    # E-2: Action guidance
    html.append('<div class="action-guidance">')
    html.append('<div class="action-title">&#x1F3AF; Yutaが判断すべきこと</div>')
    html.append(f'<div class="action-item">スタンドアップ結果を確認し、前日比の変動に注目してください</div>')
    if unresolved_count > 0:
        html.append(f'<div class="metric-highlight" style="color:#ef4444;">{unresolved_count} <span style="font-size:0.9rem;color:#94a3b8;">未解決課題</span></div>')
    else:
        html.append(f'<div class="metric-highlight" style="color:#22c55e;">0 <span style="font-size:0.9rem;color:#94a3b8;">未解決課題</span></div>')
    html.append('<div class="action-item" style="color:#94a3b8;">&#x1F4CA; 主要指標: 部門別スタンドアップ / 取締役会 / 未解決課題数</div>')
    html.append('</div>')

    # --- Unresolved issues badge ---
    badge_color = "#ef4444" if unresolved_count > 5 else "#fbbf24" if unresolved_count > 0 else "#22c55e"
    html.append(
        f'<div style="display:inline-block;background:{badge_color};color:#0f172a;'
        f'border-radius:12px;padding:2px 12px;font-size:0.8rem;font-weight:700;'
        f'margin-bottom:12px;">未解決課題: {unresolved_count} 件</div>'
    )

    # --- Department standups (5 departments) ---
    dept_standups = _read_dept_standups(today_str)
    dept_date_label = today_str
    if not dept_standups:
        dept_standups = _read_dept_standups(yest_str)
        dept_date_label = yest_str

    if dept_standups:
        html.append(
            f'<div style="margin-bottom:16px;">'
            f'<div style="color:#94a3b8;font-size:0.85rem;font-weight:600;'
            f'margin-bottom:8px;">部門別スタンドアップ ({dept_date_label})</div>'
            f'<div style="display:flex;gap:10px;flex-wrap:wrap;">'
        )

        for dept in dept_standups:
            err_badge = ""
            if dept["pipeline_errors"] > 0:
                err_badge = (
                    f'<span style="color:#f87171;font-size:0.75rem;">'
                    f' エラー: {dept["pipeline_errors"]}</span>'
                )

            member_html = ""
            for m in dept["members"][:5]:
                rank_color = (
                    "#22c55e" if "🟢" in m["rank"]
                    else "#fbbf24" if "🟡" in m["rank"]
                    else "#ef4444" if "🔴" in m["rank"]
                    else "#94a3b8"
                )
                member_html += (
                    f'<div style="display:flex;justify-content:space-between;'
                    f'border-top:1px solid #334155;padding:2px 0;">'
                    f'<span style="color:#cbd5e1;">{m["name"]}</span>'
                    f'<span style="color:{rank_color};font-weight:600;">{m["rate"]}</span>'
                    f'</div>'
                )

            html.append(
                f'<div style="background:#1e293b;border-radius:8px;padding:12px 14px;'
                f'flex:1;min-width:180px;max-width:220px;">'
                f'<div style="font-size:0.85rem;font-weight:600;color:#e2e8f0;'
                f'margin-bottom:6px;">{dept["icon"]} {dept["name"]}</div>'
                f'<div style="font-size:0.78rem;color:#94a3b8;margin-bottom:4px;">'
                f'実行: {dept["pipeline_total"]}件{err_badge}</div>'
                f'<div style="font-size:0.75rem;">{member_html}</div>'
                f'</div>'
            )

        html.append("</div></div>")

    # --- Legacy standup comparison ---
    if today or yest:
        html.append(
            '<div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:16px;">'
        )

        for label, data, is_today in [
            (f"全社朝会 ({today_str})", today, True),
            (f"全社朝会 ({yest_str})", yest, False),
        ]:
            bg = "#1e293b"
            html.append(
                f'<div style="background:{bg};border-radius:8px;padding:14px 18px;'
                f'flex:1;min-width:260px;">'
                f'<div style="color:#94a3b8;font-size:0.85rem;margin-bottom:8px;'
                f'font-weight:600;">{label}</div>'
            )
            if data and data["metrics"]:
                lower_better = {"エラー件数"}
                html.append(
                    '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;">'
                )
                for key, val in data["metrics"].items():
                    delta_html = ""
                    if is_today and yest and yest["metrics"].get(key):
                        t_num = _parse_num(val)
                        y_num = _parse_num(yest["metrics"][key])
                        hib = key not in lower_better
                        delta_html = _delta_arrow(t_num, y_num, higher_is_better=hib)
                    html.append(
                        f'<tr style="border-top:1px solid #334155;">'
                        f'<td style="padding:3px 6px;color:#94a3b8;">{key}</td>'
                        f'<td style="padding:3px 6px;color:#e2e8f0;font-weight:600;">'
                        f'{val}</td>'
                        f'<td style="padding:3px 6px;">{delta_html}</td></tr>'
                    )
                html.append("</table>")

                if data["errors"]:
                    html.append(
                        '<div style="margin-top:8px;font-size:0.78rem;color:#f87171;">'
                    )
                    for ename, ecount in data["errors"]:
                        html.append(f"<div>• {ename}: {ecount} 件</div>")
                    html.append("</div>")
            else:
                html.append(
                    '<div style="color:#64748b;font-size:0.82rem;">スタンドアップ未生成</div>'
                )
            html.append("</div>")

        html.append("</div>")
    else:
        html.append(
            '<div style="background:#1e293b;border-radius:8px;padding:14px 18px;'
            'color:#64748b;font-size:0.85rem;margin-bottom:16px;">'
            "本日・昨日のスタンドアップファイルが見つかりません。</div>"
        )

    # --- Board meeting summary ---
    board = _read_latest_board_meeting()
    if board:
        html.append(
            f'<div style="background:#1e293b;border-radius:8px;padding:14px 18px;'
            f'margin-bottom:12px;">'
            f'<div style="color:#94a3b8;font-size:0.85rem;font-weight:600;'
            f'margin-bottom:6px;">最新取締役会: {board["filename"]}</div>'
        )
        if board["kpis"]:
            html.append(
                '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;">'
            )
            for key, val in list(board["kpis"].items())[:8]:
                html.append(
                    f'<tr style="border-top:1px solid #334155;">'
                    f'<td style="padding:3px 6px;color:#94a3b8;">{key}</td>'
                    f'<td style="padding:3px 6px;color:#e2e8f0;font-weight:600;">'
                    f'{val}</td></tr>'
                )
            html.append("</table>")
        html.append("</div>")

    # --- Weekly meeting files ---
    weekly = _list_weekly_meetings()
    if weekly:
        html.append(
            '<div style="background:#1e293b;border-radius:8px;padding:14px 18px;">'
            '<div style="color:#94a3b8;font-size:0.85rem;font-weight:600;'
            'margin-bottom:6px;">週次会議（直近）</div>'
            '<div style="font-size:0.82rem;color:#cbd5e1;">'
        )
        for f in weekly:
            html.append(f"<div>📄 {f}</div>")
        html.append("</div></div>")

    html.append("</div>")
    return "\n".join(html)
