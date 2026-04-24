"""sec_08_errors — Error Audit section for dashboard v2."""

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


def load_jsonl(rel_path):
    p = BASE / rel_path
    if not p.exists():
        return []
    records = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def _week_start_iso():
    """ISO string for 7 days ago."""
    return (datetime.now(JST) - timedelta(days=7)).isoformat()


def _count_this_week(records):
    cutoff = _week_start_iso()
    return sum(1 for r in records if r.get("ts", "") >= cutoff)


def render() -> str:
    error_patterns = load_json("config/error_patterns.json")
    patterns = error_patterns.get("patterns", {})

    hook_records = load_jsonl("logs/gardevoir_hook.jsonl")
    quality_records = load_jsonl("logs/quality_issues.jsonl")

    # Classify patterns
    resolved = []
    unresolved = []
    for pid, info in patterns.items():
        entry = {"id": pid, **info}
        if info.get("resolved_at"):
            resolved.append(entry)
        else:
            unresolved.append(entry)

    # This week's new errors
    hook_week = _count_this_week(hook_records)
    quality_week = _count_this_week(quality_records)
    new_errors_week = hook_week + quality_week

    # Check for resolved patterns that re-occurred this week
    resolved_ids = {p["id"] for p in resolved}
    resolved_agents = {p.get("agent", "") for p in resolved}
    # Simple heuristic: hook errors from resolved agents
    reoccurrences = 0
    cutoff = _week_start_iso()
    for r in hook_records:
        if r.get("ts", "") >= cutoff and r.get("agent", "") in resolved_agents:
            reoccurrences += 1

    # Severity color helper
    def _sev_color(count):
        if count == 0:
            return "#22c55e"
        if count <= 3:
            return "#eab308"
        return "#ef4444"

    html = [
        '<div style="margin-bottom:24px;">',
        '<h2 style="color:#e2e8f0;font-size:1.4rem;margin-bottom:16px;">'
        f'⚠️ エラー監視 {get_score_badge(score_for_section("sec_08"))}</h2>',
    ]

    # E-2: Action guidance
    html.append('<div class="action-guidance">')
    html.append('<div class="action-title">&#x1F3AF; Yutaが判断すべきこと</div>')
    if len(unresolved) > 0:
        html.append(f'<div class="action-item" style="color:#ef4444;">未解決パターン {len(unresolved)}件 を確認してください</div>')
    if reoccurrences > 0:
        html.append(f'<div class="action-item" style="color:#f97316;">解決済パターンの再発 {reoccurrences}件 を確認してください</div>')
    if new_errors_week == 0 and len(unresolved) == 0:
        html.append('<div class="action-item" style="color:#22c55e;">エラーなし — 全システム正常</div>')
    html.append(f'<div class="metric-highlight" style="color:{_sev_color(new_errors_week)};">{new_errors_week} <span style="font-size:0.9rem;color:#94a3b8;">今週の新規エラー</span></div>')
    html.append('<div class="action-item" style="color:#94a3b8;">&#x1F4CA; 主要指標: 新規エラー / フックエラー / 品質問題 / 未解決パターン</div>')
    html.append('</div>')

    # Summary cards
    cards = [
        ("今週の新規", new_errors_week, _sev_color(new_errors_week)),
        ("フックエラー(7日)", hook_week, _sev_color(hook_week)),
        ("品質問題(7日)", quality_week, _sev_color(quality_week)),
        ("解決済の再発", reoccurrences, _sev_color(reoccurrences)),
        ("未解決パターン", len(unresolved), _sev_color(len(unresolved))),
    ]
    html.append(
        '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;">'
    )
    for label, val, color in cards:
        html.append(
            f'<div style="background:#1e293b;border-left:4px solid {color};'
            f'border-radius:8px;padding:12px 16px;min-width:110px;">'
            f'<div style="color:#94a3b8;font-size:0.78rem;">{label}</div>'
            f'<div style="color:{color};font-size:1.5rem;font-weight:700;">{val}</div>'
            f'</div>'
        )
    html.append("</div>")

    # Unresolved patterns table
    if unresolved:
        html.append(
            '<div style="background:#1e293b;border-radius:8px;padding:14px 18px;'
            'margin-bottom:14px;">'
            '<div style="color:#f87171;font-size:0.9rem;font-weight:600;'
            'margin-bottom:8px;">未解決パターン</div>'
            '<table style="width:100%;border-collapse:collapse;font-size:0.82rem;">'
            '<tr style="color:#94a3b8;text-align:left;">'
            '<th style="padding:4px 8px;">パターン</th>'
            '<th style="padding:4px 8px;">エージェント</th>'
            '<th style="padding:4px 8px;">件数</th>'
            '<th style="padding:4px 8px;">最終発生</th>'
            '<th style="padding:4px 8px;">例</th></tr>'
        )
        for p in sorted(unresolved, key=lambda x: x.get("count", 0), reverse=True):
            cnt = p.get("count", 0)
            cc = "#ef4444" if cnt >= 3 else "#eab308" if cnt >= 1 else "#94a3b8"
            example = p.get("example", "")
            if len(example) > 60:
                example = example[:57] + "..."
            html.append(
                f'<tr style="color:#e2e8f0;border-top:1px solid #334155;">'
                f'<td style="padding:4px 8px;color:#fb923c;">{p["id"]}</td>'
                f'<td style="padding:4px 8px;">{p.get("agent", "?")}</td>'
                f'<td style="padding:4px 8px;color:{cc};font-weight:600;">{cnt}</td>'
                f'<td style="padding:4px 8px;color:#94a3b8;">{p.get("last_seen", "?")}</td>'
                f'<td style="padding:4px 8px;color:#94a3b8;font-size:0.78rem;">'
                f'{example}</td></tr>'
            )
        html.append("</table></div>")

    # Resolved patterns (collapsed)
    if resolved:
        html.append(
            '<details style="background:#1e293b;border-radius:8px;padding:14px 18px;">'
            '<summary style="color:#22c55e;cursor:pointer;font-weight:600;'
            f'font-size:0.9rem;">解決済パターン ({len(resolved)}件)</summary>'
            '<table style="width:100%;border-collapse:collapse;font-size:0.8rem;'
            'margin-top:8px;">'
            '<tr style="color:#94a3b8;text-align:left;">'
            '<th style="padding:3px 8px;">パターン</th>'
            '<th style="padding:3px 8px;">エージェント</th>'
            '<th style="padding:3px 8px;">修正内容</th>'
            '<th style="padding:3px 8px;">解決日</th></tr>'
        )
        for p in resolved:
            fix_text = p.get("fix", "")
            if len(fix_text) > 70:
                fix_text = fix_text[:67] + "..."
            html.append(
                f'<tr style="color:#cbd5e1;border-top:1px solid #334155;">'
                f'<td style="padding:3px 8px;">{p["id"]}</td>'
                f'<td style="padding:3px 8px;">{p.get("agent", "?")}</td>'
                f'<td style="padding:3px 8px;color:#94a3b8;font-size:0.76rem;">'
                f'{fix_text}</td>'
                f'<td style="padding:3px 8px;color:#22c55e;">'
                f'{p.get("resolved_at", "?")}</td></tr>'
            )
        html.append("</table></details>")

    html.append("</div>")
    return "\n".join(html)
