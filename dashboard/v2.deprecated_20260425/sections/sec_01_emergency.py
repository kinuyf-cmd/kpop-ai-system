"""sec_01_emergency.py - RED zone items needing owner approval."""
import json, sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "lib"))
from health_score import get_score_badge, score_for_section

BASE = Path(__file__).resolve().parent.parent.parent.parent  # kpop-ai-system root
JST = timezone(timedelta(hours=9))

STYLE = """
<style>
.sec-emergency { background: #1a0a0a; border: 1px solid #7f1d1d; border-radius: 12px; padding: 20px; margin-bottom: 24px; }
.sec-emergency h2 { color: #fca5a5; margin: 0 0 16px 0; font-size: 1.2rem; }
.sec-emergency .badge { display: inline-block; background: #991b1b; color: #fecaca; padding: 2px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; margin-left: 8px; }
.sec-emergency .item { background: #2a0f0f; border-left: 4px solid #dc2626; padding: 12px 16px; margin-bottom: 10px; border-radius: 0 8px 8px 0; }
.sec-emergency .item .agent { color: #f87171; font-weight: 700; font-size: 0.95rem; }
.sec-emergency .item .desc { color: #e2e8f0; font-size: 0.88rem; margin-top: 4px; }
.sec-emergency .item .ts { color: #94a3b8; font-size: 0.75rem; margin-top: 4px; }
.sec-emergency .empty { color: #6ee7b7; font-size: 0.95rem; padding: 8px 0; }
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


def load_json(rel_path):
    p = BASE / rel_path
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _is_red_zone(rec):
    """Determine if a record qualifies as RED zone / emergency."""
    # Explicit zone field
    zone = rec.get("zone", "")
    if "red" in zone.lower():
        return True
    # safety_class REVIEW + HIGH priority
    sc = rec.get("safety_class", "")
    if sc == "REVIEW" and rec.get("priority", "") == "HIGH":
        return True
    # BLOCKED action types
    action = rec.get("source_action_type", "")
    if "BLOCK" in action.upper():
        return True
    # Status explicitly blocked
    if rec.get("status", "").upper() == "BLOCKED":
        return True
    return False


def _check_system_critical():
    """Check for critical system events (pm2 down, SEO crash indicators)."""
    alerts = []
    # Check pm2 status via recent log
    pm2_err = BASE / "logs" / "pm2_error.log"
    if pm2_err.exists():
        try:
            lines = pm2_err.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
            for line in lines:
                if any(kw in line.lower() for kw in ("errored", "stopped", "crash", "oom")):
                    alerts.append({"agent": "SYSTEM", "desc": f"PM2異常: {line[:120]}", "ts": ""})
                    break
        except Exception:
            pass
    # Check for SEO crash (drastic drop in GSC clicks)
    metrics = load_json("google_metrics/metrics_yesterday.json")
    gsc = metrics.get("gsc", {}).get("summary", {})
    clicks = gsc.get("clicks")
    if clicks is not None:
        try:
            if float(clicks) == 0:
                alerts.append({"agent": "GSC", "desc": "GSCクリック数が0 - SEO異常の可能性", "ts": metrics.get("date", "")})
        except Exception:
            pass
    return alerts[:2]


def _agent_ja(key):
    """Japanese agent display name lookup."""
    try:
        _p = Path(__file__).resolve().parent.parent
        if str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
        from render_dashboard import agent_ja
        return agent_ja(key)
    except Exception:
        return key


def render():
    html_parts = [STYLE, '<div class="sec-emergency">']
    _badge = get_score_badge(score_for_section("sec_01"))
    html_parts.append(f'<h2>&#x1F534; 緊急対応 — RED zone（オーナー承認必要） {_badge}</h2>')

    items = []

    # 1. CEO improvement queue - red zone items
    queue = load_jsonl("logs/ceo_improvement_queue.jsonl")
    for rec in queue:
        if rec.get("status") == "archived":
            continue
        if _is_red_zone(rec):
            items.append({
                "agent": rec.get("target_agent", "不明"),
                "desc": rec.get("reason", rec.get("proposed_change", "")),
                "ts": rec.get("generated_at", ""),
            })

    # 2. Learning history red zone items
    learning = load_jsonl("logs/learning_history.jsonl")
    for rec in learning:
        zone = rec.get("zone", "")
        if "red" in zone.lower() and not rec.get("applied", False):
            items.append({
                "agent": rec.get("error_pattern", "学習エンジン"),
                "desc": rec.get("proposed_fix", ""),
                "ts": rec.get("timestamp", ""),
            })

    # 3. System-level critical alerts
    items.extend(_check_system_critical())

    # Deduplicate by description prefix and limit
    seen = set()
    unique = []
    for item in items:
        key = item["desc"][:60]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    items = unique[:5]

    # E-2: Action guidance
    html_parts.append('<div class="action-guidance">')
    html_parts.append('<div class="action-title">&#x1F3AF; Yutaが判断すべきこと</div>')
    if items:
        html_parts.append('<div class="action-item">RED zone項目の承認 or 差し戻し判断が必要です</div>')
        html_parts.append(f'<div class="metric-highlight" style="color:#ef4444;">{len(items)}件</div>')
        html_parts.append('<div class="action-item" style="color:#94a3b8;">&#x1F4CA; 主要指標: 緊急対応待ち件数</div>')
    else:
        html_parts.append('<div class="action-item" style="color:#22c55e;">緊急対応なし — 全システム正常稼働中</div>')
        html_parts.append('<div class="metric-highlight" style="color:#22c55e;">0件</div>')
    html_parts.append('</div>')

    if not items:
        html_parts.append('<div class="empty">&#x2705; なし &mdash; 緊急対応項目はありません</div>')
    else:
        html_parts.append(f'<span class="badge">{len(items)}件</span>')
        html_parts.append('<details><summary style="color:#fca5a5;cursor:pointer;font-size:0.88rem;margin:8px 0;">&#x1F50D; 詳細を表示</summary>')
        for item in items:
            ts_display = item["ts"][:16].replace("T", " ") if item["ts"] else ""
            agent_display = _agent_ja(item["agent"])
            html_parts.append(f'''<div class="item">
  <div class="agent">{_esc(agent_display)}</div>
  <div class="desc">{_esc(item["desc"][:200])}</div>
  <div class="ts">{_esc(ts_display)}</div>
</div>''')
        html_parts.append('</details>')

    html_parts.append("</div>")
    return "\n".join(html_parts)


def _esc(s):
    """Minimal HTML escape."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
