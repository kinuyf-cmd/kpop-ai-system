"""sec_02_important.py - YELLOW zone items not yet reviewed in 24h."""
import json, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "lib"))
from health_score import get_score_badge, score_for_section

BASE = Path(__file__).resolve().parent.parent.parent.parent
JST = timezone(timedelta(hours=9))

STYLE = """
<style>
.sec-important { background: #1a1708; border: 1px solid #854d0e; border-radius: 12px; padding: 20px; margin-bottom: 24px; }
.sec-important h2 { color: #fde68a; margin: 0 0 16px 0; font-size: 1.2rem; }
.sec-important .badge { display: inline-block; background: #854d0e; color: #fef3c7; padding: 2px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; margin-left: 8px; }
.sec-important .overdue { background: #422006; border-color: #f59e0b; }
.sec-important .item { background: #1e1a0a; border-left: 4px solid #eab308; padding: 12px 16px; margin-bottom: 10px; border-radius: 0 8px 8px 0; }
.sec-important .item.overdue { border-left-color: #f97316; background: #271a0a; }
.sec-important .item .agent { color: #facc15; font-weight: 700; font-size: 0.95rem; }
.sec-important .item .desc { color: #e2e8f0; font-size: 0.88rem; margin-top: 4px; }
.sec-important .item .meta { color: #94a3b8; font-size: 0.75rem; margin-top: 4px; }
.sec-important .item .overdue-tag { display: inline-block; background: #9a3412; color: #fed7aa; padding: 1px 6px; border-radius: 4px; font-size: 0.7rem; margin-left: 6px; }
.sec-important .empty { color: #6ee7b7; font-size: 0.95rem; padding: 8px 0; }
</style>
"""


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


def _is_yellow_zone(rec):
    """Determine if a record qualifies as YELLOW zone."""
    if rec.get("status") == "archived":
        return False
    zone = rec.get("zone", "")
    if "yellow" in zone.lower():
        return True
    # Pending SAFE items or REVIEW with non-HIGH priority
    sc = rec.get("safety_class", "")
    status = rec.get("status", "")
    priority = rec.get("priority", "")
    if status == "pending":
        if sc == "SAFE" and priority in ("HIGH", "MEDIUM"):
            return True
        if sc == "REVIEW" and priority != "HIGH":
            return True
    return False


def _parse_ts(ts_str):
    """Parse ISO timestamp string."""
    if not ts_str:
        return None
    try:
        ts_str = ts_str.replace("+09:00", "+0900").replace("+00:00", "+0000")
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(ts_str, fmt)
            except ValueError:
                continue
        from dateutil.parser import parse as du_parse
        return du_parse(ts_str)
    except Exception:
        return None


def _agent_ja(key):
    try:
        _p = Path(__file__).resolve().parent.parent
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
        from render_dashboard import agent_ja
        return agent_ja(key)
    except Exception:
        return key


def render():
    now = datetime.now(JST)
    cutoff_24h = now - timedelta(hours=24)
    html_parts = [STYLE, '<div class="sec-important">']
    _badge = get_score_badge(score_for_section("sec_02"))
    html_parts.append(f'<h2>&#x1F7E1; 重要課題 — YELLOW zone（24h以内確認） {_badge}</h2>')

    items = []
    queue = load_jsonl("logs/ceo_improvement_queue.jsonl")
    for rec in queue:
        if not _is_yellow_zone(rec):
            continue
        ts = _parse_ts(rec.get("generated_at", ""))
        is_overdue = ts is not None and ts < cutoff_24h
        items.append({
            "agent": rec.get("target_agent", "不明"),
            "desc": rec.get("reason", rec.get("proposed_change", "")),
            "ts": rec.get("generated_at", ""),
            "priority": rec.get("priority", ""),
            "type": rec.get("improvement_type", ""),
            "overdue": is_overdue,
        })

    # Sort: overdue first, then by priority
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    items.sort(key=lambda x: (not x["overdue"], priority_order.get(x["priority"], 3)))
    items = items[:10]

    overdue_count = sum(1 for i in items if i["overdue"])

    # E-2: Action guidance
    html_parts.append('<div class="action-guidance">')
    html_parts.append('<div class="action-title">&#x1F3AF; Yutaが判断すべきこと</div>')
    if items:
        html_parts.append(f'<div class="action-item">改善提案 {len(items)}件 の確認・承認が必要です</div>')
        if overdue_count:
            html_parts.append(f'<div class="action-item" style="color:#f97316;">うち {overdue_count}件 が24時間超過</div>')
        html_parts.append(f'<div class="metric-highlight" style="color:#eab308;">{len(items)}件</div>')
        html_parts.append('<div class="action-item" style="color:#94a3b8;">&#x1F4CA; 主要指標: 確認待ち件数 / 24h超過数</div>')
    else:
        html_parts.append('<div class="action-item" style="color:#22c55e;">確認待ち項目はありません</div>')
        html_parts.append('<div class="metric-highlight" style="color:#22c55e;">0件</div>')
    html_parts.append('</div>')

    if not items:
        html_parts.append('<div class="empty">&#x2705; なし &mdash; 確認待ち項目はありません</div>')
    else:
        html_parts.append(f'<span class="badge">{len(items)}件</span>')
        if overdue_count:
            html_parts.append(f'<span class="badge overdue">{overdue_count}件 24h超過</span>')

        html_parts.append('<details><summary style="color:#fde68a;cursor:pointer;font-size:0.88rem;margin:8px 0;">&#x1F50D; 詳細を表示</summary>')
        for item in items:
            cls = "item overdue" if item["overdue"] else "item"
            ts_display = item["ts"][:16].replace("T", " ") if item["ts"] else ""
            overdue_tag = '<span class="overdue-tag">24h超過</span>' if item["overdue"] else ""
            agent_display = _agent_ja(item["agent"])
            html_parts.append(f'''<div class="{cls}">
  <div class="agent">{_esc(agent_display)} <span style="color:#94a3b8;font-size:0.8rem">[{_esc(item["priority"])}] {_esc(item["type"])}</span>{overdue_tag}</div>
  <div class="desc">{_esc(item["desc"][:200])}</div>
  <div class="meta">{_esc(ts_display)}</div>
</div>''')
        html_parts.append('</details>')

    html_parts.append("</div>")
    return "\n".join(html_parts)


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
