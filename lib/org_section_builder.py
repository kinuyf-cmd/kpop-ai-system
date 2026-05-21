#!/usr/bin/env python3
"""
lib/org_section_builder.py
CE. 組織図 / CF. 部署一覧 セクション生成
agent_display_map.json + org_chart.json + agent_metrics.json を組み合わせて
オーナー向けの組織図・部署一覧HTMLを生成する
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
LOGS = BASE / "logs"

def _load(fname: str) -> dict:
    p = BASE / fname
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _status_color(status: str) -> str:
    return {
        "稼働中": "#22c55e",
        "注意":   "#eab308",
        "要改善": "#f97316",
        "待機中": "#3b82f6",
        "停止":   "#6b7280",
    }.get(status, "#64748b")

def _rank_color(rank: str) -> str:
    return {"🟢": "#22c55e", "🟡": "#eab308", "🔴": "#ef4444"}.get(rank, "#64748b")

def _fmt_time(ts: str) -> str:
    if not ts:
        return "未稼働"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        jst = dt.astimezone(timezone(timedelta(hours=9)))
        return jst.strftime("%m/%d %H:%M")
    except Exception:
        return ts[:10]

def _display_name(agent_id: str, adm: dict, fallback: str) -> str:
    return adm.get(agent_id, {}).get("display_name") or fallback

def _dept_label(agent_id: str, adm: dict) -> str:
    return adm.get(agent_id, {}).get("department", "—")

def build_org_parts() -> dict:
    """CE. 組織図 + CF. 部署一覧 のHTML を辞書で返す keys: ce_html, cf_html"""
    adm = _load("config/agent_display_map.json")
    org = _load("config/org_chart.json")
    am = _load("agent_metrics.json")
    agents_data = am.get("agents", {})

    departments = org.get("departments", {})
    ceo = org.get("ceo", {})

    # ──────────────────────────────────────────────
    # CE. 組織図セクション
    # ──────────────────────────────────────────────
    def _mini_agent_pill(aid: str) -> str:
        """エージェント1人をコンパクトなピルで表示"""
        v = agents_data.get(aid, {})
        name = _display_name(aid, adm, v.get("name_ja", aid))
        status = v.get("status", "待機中")
        sc = _status_color(status)
        rank = v.get("rank", "🟡")
        rc = _rank_color(rank)
        role = v.get("role", adm.get(aid, {}).get("role", "—"))
        last = _fmt_time(v.get("last_run_time", ""))
        rate = v.get("success_rate", 0)
        sabori = v.get("sabori_flag", False)
        error = v.get("error_flag", False)

        alert = ""
        if error:
            alert = '<span style="background:#ef4444;color:#fff;font-size:0.55rem;padding:1px 4px;border-radius:3px;margin-left:3px">要調査</span>'
        elif sabori:
            alert = '<span style="background:#d97706;color:#fff;font-size:0.55rem;padding:1px 4px;border-radius:3px;margin-left:3px">長期未稼働</span>'

        return f"""<div style="background:#0d1117;border:1px solid {rc}44;border-left:3px solid {rc};border-radius:6px;padding:7px 10px;margin-bottom:6px">
  <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
    <span style="font-weight:800;color:#e2e8f0;font-size:0.8rem">{name}</span>
    {alert}
    <span style="margin-left:auto;background:{sc}22;color:{sc};font-size:0.62rem;padding:1px 7px;border-radius:99px;border:1px solid {sc}44;white-space:nowrap">{status}</span>
  </div>
  <div style="font-size:0.65rem;color:#64748b;margin-top:3px">{role}</div>
  <div style="display:flex;gap:8px;margin-top:4px">
    <span style="font-size:0.6rem;color:#475569">成功率: <span style="color:{rc}">{rate:.0%}</span></span>
    <span style="font-size:0.6rem;color:#475569">最終稼働: {last}</span>
  </div>
</div>"""

    dept_cards_html = ""
    dept_summary = {}

    for dept_key, dept_info in departments.items():
        color = dept_info.get("color", "#818cf8")
        label = dept_info.get("label", dept_key)
        icon = dept_info.get("icon", "")
        manager = dept_info.get("manager", "—")
        mission = dept_info.get("mission", "")
        member_ids = dept_info.get("agents", [])

        active_count = 0
        error_count = 0
        total_active = 0
        agent_pills = ""
        for aid in member_ids:
            v = agents_data.get(aid, {})
            st = v.get("status", "待機中")
            if st in ("稼働中", "注意", "要改善"):
                total_active += 1
            if st == "稼働中":
                active_count += 1
            if v.get("error_flag") or v.get("sabori_flag"):
                error_count += 1
            agent_pills += _mini_agent_pill(aid)

        dept_summary[dept_key] = {
            "label": label, "icon": icon, "color": color,
            "manager": manager, "member_count": len(member_ids),
            "active_count": active_count, "error_count": error_count,
        }

        status_badge = "green" if error_count == 0 and active_count >= len(member_ids) * 0.7 else (
            "yellow" if error_count <= 1 else "red")
        badge_c = {"green": "#22c55e", "yellow": "#eab308", "red": "#ef4444"}[status_badge]
        badge_text = {"green": "良好", "yellow": "要注意", "red": "問題あり"}[status_badge]

        dept_cards_html += f"""<div style="background:#111827;border:1px solid {color}44;border-top:4px solid {color};border-radius:12px;padding:16px;break-inside:avoid">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
    <span style="font-size:1.2rem">{icon}</span>
    <span style="font-weight:900;color:{color};font-size:0.88rem">{label}</span>
    <span style="margin-left:auto;background:{badge_c}22;color:{badge_c};border:1px solid {badge_c}44;font-size:0.65rem;padding:2px 8px;border-radius:99px;font-weight:700">{badge_text}</span>
  </div>
  <div style="font-size:0.68rem;color:#475569;margin-bottom:8px">部署長: {manager} ／ {mission}</div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
    <span style="background:#1e293b;color:#94a3b8;font-size:0.65rem;padding:2px 8px;border-radius:99px">社員数: {len(member_ids)}人</span>
    <span style="background:#22c55e22;color:#22c55e;font-size:0.65rem;padding:2px 8px;border-radius:99px">稼働中: {active_count}人</span>
    {f'<span style="background:#ef444422;color:#ef4444;font-size:0.65rem;padding:2px 8px;border-radius:99px">問題: {error_count}件</span>' if error_count > 0 else ''}
  </div>
  <details style="cursor:pointer">
    <summary style="font-size:0.7rem;color:#64748b;list-style:none;display:flex;align-items:center;gap:4px;padding:4px 0">
      <span>▶ 社員一覧を見る</span>
    </summary>
    <div style="margin-top:8px">{agent_pills}</div>
  </details>
</div>"""

    # CEO 位置
    ceo_name = ceo.get("display_name", "ミュウツー")
    ceo_id = ceo.get("id", "mewtwo")
    ceo_v = agents_data.get(ceo_id, {})
    ceo_rate = ceo_v.get("success_rate", 0)
    ceo_last = _fmt_time(ceo_v.get("last_run_time", ""))

    ce_section = f"""<div class="section" id="ce-org-chart" style="margin-bottom:24px">
  <div class="section-title" style="border-bottom-color:#818cf833;margin-bottom:16px">
    <span class="section-title-icon">🏢</span>
    <span style="color:#818cf8;font-size:0.9rem;font-weight:900">CE. 組織図</span>
    <span style="margin-left:auto;font-size:0.72rem;color:#64748b">K-POP Journal AI Company — {len(departments)}部署 {sum(len(d.get('agents',[])) for d in departments.values())}名</span>
  </div>

  <!-- CEO -->
  <div style="text-align:center;margin-bottom:20px">
    <div style="display:inline-block;background:linear-gradient(135deg,#7c3aed,#2563eb);border-radius:12px;padding:14px 28px">
      <div style="font-size:0.7rem;color:#a78bfa;margin-bottom:4px">CEO・編集長</div>
      <div style="font-size:1.1rem;font-weight:900;color:#fff">👑 {ceo_name}</div>
      <div style="font-size:0.65rem;color:#c4b5fd;margin-top:4px">成功率 {ceo_rate:.0%} ／ 最終稼働 {ceo_last}</div>
    </div>
    <div style="height:20px;border-left:2px dashed #334155;margin:0 auto;width:1px"></div>
    <div style="font-size:0.65rem;color:#334155;margin-bottom:8px">↓ 7つの部署</div>
  </div>

  <!-- 部署グリッド -->
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px">
    {dept_cards_html}
  </div>
</div>"""

    # ──────────────────────────────────────────────
    # CF. 部署一覧（進捗テーブル形式）
    # ──────────────────────────────────────────────
    cf_rows = ""
    for dept_key, info in dept_summary.items():
        color = info["color"]
        label = info["label"]
        icon = info["icon"]
        manager = info["manager"]
        total = info["member_count"]
        active = info["active_count"]
        errors = info["error_count"]
        pct = round(active / max(total, 1) * 100)
        bar_c = "#22c55e" if errors == 0 and pct >= 70 else ("#eab308" if pct >= 40 else "#ef4444")

        cf_rows += f"""<tr style="border-bottom:1px solid #1e293b">
  <td style="padding:8px 10px">
    <span style="font-size:0.9rem">{icon}</span>
    <span style="font-size:0.8rem;font-weight:700;color:{color};margin-left:6px">{label}</span>
  </td>
  <td style="padding:8px 10px;font-size:0.75rem;color:#94a3b8">{manager}</td>
  <td style="padding:8px 10px;text-align:center;font-size:0.75rem;color:#e2e8f0">{total}人</td>
  <td style="padding:8px 10px">
    <div style="background:#1e293b;border-radius:3px;height:6px;width:80px;display:inline-block;vertical-align:middle">
      <div style="background:{bar_c};height:6px;border-radius:3px;width:{pct}%"></div>
    </div>
    <span style="font-size:0.65rem;color:{bar_c};margin-left:4px">{active}/{total}稼働</span>
  </td>
  <td style="padding:8px 10px;text-align:center">
    {f'<span style="color:#ef4444;font-size:0.72rem;font-weight:700">⚠️ {errors}件</span>' if errors > 0 else '<span style="color:#22c55e;font-size:0.72rem">✅</span>'}
  </td>
</tr>"""

    cf_section = f"""<div class="section" id="cf-departments" style="margin-bottom:24px">
  <div class="section-title" style="border-bottom-color:#22d3ee33;margin-bottom:16px">
    <span class="section-title-icon">🏗️</span>
    <span style="color:#22d3ee;font-size:0.9rem;font-weight:900">CF. 部署一覧</span>
  </div>
  <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="border-bottom:2px solid #1e293b;color:#64748b;font-size:0.65rem">
          <th style="text-align:left;padding:6px 10px">部署名</th>
          <th style="text-align:left;padding:6px 10px">部署長</th>
          <th style="text-align:center;padding:6px 10px">社員数</th>
          <th style="text-align:left;padding:6px 10px">稼働状況</th>
          <th style="text-align:center;padding:6px 10px">問題</th>
        </tr>
      </thead>
      <tbody>{cf_rows}</tbody>
    </table>
  </div>
</div>"""

    return {"ce_html": ce_section, "cf_html": cf_section}


def build_ce_cf_sections() -> str:
    """後方互換: CE+CF を結合して返す"""
    parts = build_org_parts()
    return parts["ce_html"] + parts["cf_html"]


if __name__ == "__main__":
    html = build_ce_cf_sections()
    print(f"CE+CF sections: {len(html)} chars")
