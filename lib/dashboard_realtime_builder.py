#!/usr/bin/env python3
"""
dashboard_realtime_builder.py — リアルタイムAIダッシュボード強化 (Phase5)

generate_dashboard.py から呼び出され、以下の新セクションHTMLを返す:
  CL. エグゼクティブサマリー（PV/CTR/品質/収益を4カード表示）
  CM. エージェント30体リアルタイム稼働マップ（緑/黄/赤/灰）
  CN. PDCA追跡ボード（Plan/Do/Check/Actの進捗可視化）
  CO. 記事パフォーマンス分析（CTR分布・スコア推移・勝率）
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
GMETRICS = BASE / "google_metrics"
JST = timezone(timedelta(hours=9))


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_jsonl(path: Path, max_lines: int = 0) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if max_lines:
        lines = lines[-max_lines:]
    out = []
    for line in lines:
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _now_jst() -> str:
    return datetime.now(JST).strftime("%m/%d %H:%M")


# ─── CL: エグゼクティブサマリー ────────────────────────────────

def build_cl_section() -> str:
    """PV/CTR/品質スコア/収益の4カードサマリー"""
    metrics = _load_json(GMETRICS / "metrics_yesterday.json")
    ga4 = metrics.get("ga4", {}).get("summary", {})
    gsc = metrics.get("gsc", {})

    pv = ga4.get("pageviews", ga4.get("sessions", 0))
    users = ga4.get("users", 0)
    top_queries = gsc.get("top_queries", [])
    avg_ctr = 0
    if top_queries:
        ctrs = [q.get("ctr", 0) for q in top_queries if isinstance(q.get("ctr"), (int, float))]
        avg_ctr = sum(ctrs) / len(ctrs) if ctrs else 0

    # 品質スコア（winning_patterns平均）
    patterns = _load_jsonl(LOGS / "winning_patterns.jsonl", max_lines=100)
    cutoff = (datetime.now(JST) - timedelta(days=7)).isoformat()
    scores = []
    for p in patterns:
        ts = p.get("recorded_at", "")
        if ts < cutoff:
            continue
        s = p.get("eval_72h") or p.get("eval_48h") or p.get("eval_24h")
        if s and isinstance(s, (int, float)) and s > 0:
            scores.append(float(s))
    avg_quality = round(sum(scores) / len(scores), 1) if scores else 0

    wins = sum(1 for p in patterns if p.get("recorded_at", "") >= cutoff
               and (p.get("eval_72h") or 0) >= 50)
    total_eval = len(scores)
    win_rate = round(wins * 100 / total_eval, 0) if total_eval else 0

    # 収益推定（AdSense RPM × PV / 1000）
    finance = _load_json(BASE / "config" / "finance_targets.json")
    rpm = finance.get("estimated_rpm", 150)  # 円
    daily_revenue = round(int(pv) * rpm / 1000) if pv else 0

    def _card(title, value, unit, sub, color, icon):
        return f'''
        <div style="background:linear-gradient(135deg,{color}15,{color}08);
                    border:1px solid {color}30;border-radius:16px;padding:20px;
                    min-width:200px;flex:1">
          <div style="font-size:13px;color:#94a3b8;margin-bottom:4px">{icon} {title}</div>
          <div style="font-size:32px;font-weight:900;color:{color};line-height:1.2">
            {value}<span style="font-size:14px;font-weight:600;color:#64748b"> {unit}</span>
          </div>
          <div style="font-size:12px;color:#64748b;margin-top:4px">{sub}</div>
        </div>'''

    pv_color = "#22c55e" if int(pv or 0) >= 500 else ("#eab308" if int(pv or 0) >= 200 else "#ef4444")
    ctr_color = "#22c55e" if avg_ctr >= 3.0 else ("#eab308" if avg_ctr >= 1.5 else "#ef4444")
    qual_color = "#22c55e" if avg_quality >= 50 else ("#eab308" if avg_quality >= 35 else "#ef4444")
    rev_color = "#22c55e" if daily_revenue >= 200 else ("#eab308" if daily_revenue >= 50 else "#ef4444")

    cards = _card("デイリーPV", f"{int(pv or 0):,}", "PV",
                  f"ユニークユーザー {int(users or 0):,}", pv_color, "📊")
    cards += _card("平均CTR", f"{avg_ctr:.1f}", "%",
                   f"検索クエリ上位 {len(top_queries)}件", ctr_color, "🎯")
    cards += _card("品質スコア", f"{avg_quality:.0f}", "/100",
                   f"勝率 {win_rate:.0f}% ({wins}/{total_eval})", qual_color, "⭐")
    cards += _card("推定収益", f"¥{daily_revenue:,}", "/日",
                   f"RPM ¥{rpm}", rev_color, "💰")

    return f'''
    <div id="sec-cl" style="margin-bottom:28px">
      <h2 style="font-size:18px;font-weight:800;color:#e2e8f0;margin:0 0 16px;
                 display:flex;align-items:center;gap:8px">
        <span style="background:linear-gradient(135deg,#FF2D55,#7B61FF);-webkit-background-clip:text;
              -webkit-text-fill-color:transparent;font-size:20px">CL</span>
        エグゼクティブサマリー
        <span style="font-size:11px;color:#64748b;font-weight:400;margin-left:auto">
          更新 {_now_jst()}</span>
      </h2>
      <div style="display:flex;gap:14px;flex-wrap:wrap">{cards}</div>
    </div>'''


# ─── CM: エージェント稼働マップ ────────────────────────────────

def build_cm_section() -> str:
    """30体のエージェントをリアルタイム色分け表示"""
    org_map = _load_json(BASE / "org_map.json")
    agents_data = org_map.get("agents", {})
    display_map = _load_json(BASE / "config" / "agent_display_map.json")

    # ステータス色マッピング
    def _status_to_color(status, rank):
        if status in ("稼働中",):
            return "#22c55e"
        if status in ("注意", "要改善"):
            return "#eab308" if rank != "🔴" else "#ef4444"
        if status in ("停止",):
            return "#ef4444"
        return "#64748b"  # 待機/不明 → グレー

    tiles = []
    # エージェントをステータス順にソート
    agent_list = []
    for key, info in agents_data.items():
        dm = display_map.get(key, {})
        if dm.get("archived"):
            continue
        display_name = dm.get("display_name", info.get("display_name", key))
        role = dm.get("role", info.get("role", ""))
        status = info.get("status", "待機中")
        rank = info.get("rank", "")
        success_rate = info.get("success_rate", 0)
        last_run = info.get("last_run_relative", "")
        dept = dm.get("department", "")
        color = _status_to_color(status, rank)
        agent_list.append({
            "key": key, "name": display_name, "role": role, "status": status,
            "rate": success_rate, "last": last_run, "color": color, "dept": dept,
        })

    # fallback: org_mapが空ならdisplay_mapから構築
    if not agent_list:
        for key, dm in display_map.items():
            if not isinstance(dm, dict):
                continue
            if dm.get("archived"):
                continue
            agent_list.append({
                "key": key, "name": dm.get("display_name", key),
                "role": dm.get("role", ""), "status": "待機",
                "rate": 0, "last": "", "color": "#64748b", "dept": dm.get("department", ""),
            })

    # タイル生成
    for a in agent_list:
        rate_str = f'{a["rate"]:.0f}%' if a["rate"] else "—"
        tiles.append(f'''
        <div style="background:{a['color']}12;border:1px solid {a['color']}35;
                    border-radius:12px;padding:10px 12px;min-width:140px;flex:1 1 140px;
                    position:relative;overflow:hidden" title="{a['key']}: {a['role']}">
          <div style="position:absolute;top:8px;right:10px;width:8px;height:8px;
                      border-radius:50%;background:{a['color']};
                      box-shadow:0 0 6px {a['color']}88"></div>
          <div style="font-size:13px;font-weight:700;color:#e2e8f0;margin-bottom:2px">
            {a['name']}</div>
          <div style="font-size:10px;color:#64748b;margin-bottom:4px">{a['dept']}</div>
          <div style="font-size:11px;color:{a['color']};font-weight:600">{rate_str}</div>
        </div>''')

    tile_html = "".join(tiles)

    # 凡例
    legend = '''
    <div style="display:flex;gap:16px;margin-bottom:14px;flex-wrap:wrap">
      <span style="font-size:11px;color:#94a3b8">
        <span style="display:inline-block;width:8px;height:8px;background:#22c55e;border-radius:50%;margin-right:4px"></span>稼働中
      </span>
      <span style="font-size:11px;color:#94a3b8">
        <span style="display:inline-block;width:8px;height:8px;background:#eab308;border-radius:50%;margin-right:4px"></span>注意
      </span>
      <span style="font-size:11px;color:#94a3b8">
        <span style="display:inline-block;width:8px;height:8px;background:#ef4444;border-radius:50%;margin-right:4px"></span>要改善
      </span>
      <span style="font-size:11px;color:#94a3b8">
        <span style="display:inline-block;width:8px;height:8px;background:#64748b;border-radius:50%;margin-right:4px"></span>待機/停止
      </span>
    </div>'''

    return f'''
    <div id="sec-cm" style="margin-bottom:28px">
      <h2 style="font-size:18px;font-weight:800;color:#e2e8f0;margin:0 0 16px;
                 display:flex;align-items:center;gap:8px">
        <span style="background:linear-gradient(135deg,#FF2D55,#7B61FF);-webkit-background-clip:text;
              -webkit-text-fill-color:transparent;font-size:20px">CM</span>
        エージェント稼働マップ ({len(agent_list)}体)
      </h2>
      {legend}
      <div style="display:flex;gap:10px;flex-wrap:wrap">{tile_html}</div>
    </div>'''


# ─── CN: PDCA追跡ボード ────────────────────────────────────────

def build_cn_section() -> str:
    """Plan/Do/Check/Actの進捗を可視化"""
    # CEO改善キューからPDCAデータを取得
    improvements = _load_jsonl(LOGS / "ceo_improvements.jsonl", max_lines=50)
    admin_actions = _load_jsonl(LOGS / "admin_actions.jsonl", max_lines=100)
    cutoff = (datetime.now(JST) - timedelta(days=7)).isoformat()

    # PDCAフェーズ分類
    plan_items = []
    do_items = []
    check_items = []
    act_items = []

    for imp in improvements:
        ts = imp.get("timestamp", "")
        if ts < cutoff:
            continue
        status = imp.get("status", "")
        title = imp.get("title", imp.get("action", ""))[:40]
        agent = imp.get("agent", "")

        if status in ("proposed", "planned", "pending"):
            plan_items.append({"title": title, "agent": agent, "ts": ts})
        elif status in ("in_progress", "executing"):
            do_items.append({"title": title, "agent": agent, "ts": ts})
        elif status in ("evaluating", "measuring"):
            check_items.append({"title": title, "agent": agent, "ts": ts})
        elif status in ("completed", "applied", "deployed"):
            act_items.append({"title": title, "agent": agent, "ts": ts})

    # アクション数からも推定
    for aa in admin_actions:
        ts = aa.get("timestamp", "")
        if ts < cutoff:
            continue
        action = aa.get("action", "")[:40]
        if "plan" in action.lower() or "提案" in action:
            plan_items.append({"title": action, "agent": "", "ts": ts})
        elif "deploy" in action.lower() or "適用" in action:
            act_items.append({"title": action, "agent": "", "ts": ts})

    def _pdca_column(label, icon, color, items, max_show=5):
        count = len(items)
        item_html = ""
        for it in items[-max_show:]:
            item_html += f'''
            <div style="background:{color}10;border-left:3px solid {color};
                        padding:6px 10px;border-radius:0 6px 6px 0;margin-bottom:6px;
                        font-size:11px;color:#cbd5e1">
              {it['title']}
              <span style="color:#475569;font-size:10px">{it.get('agent','')}</span>
            </div>'''
        if not item_html:
            item_html = '<div style="color:#374151;font-size:11px;padding:8px">アイテムなし</div>'

        return f'''
        <div style="flex:1;min-width:180px;background:#0f172a;border-radius:12px;
                    padding:14px;border:1px solid {color}25">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:10px">
            <span style="font-size:18px">{icon}</span>
            <span style="font-size:14px;font-weight:700;color:{color}">{label}</span>
            <span style="background:{color}22;color:{color};font-size:11px;font-weight:700;
                         padding:2px 8px;border-radius:8px;margin-left:auto">{count}</span>
          </div>
          {item_html}
        </div>'''

    cols = _pdca_column("Plan", "📋", "#3b82f6", plan_items)
    cols += _pdca_column("Do", "⚡", "#8b5cf6", do_items)
    cols += _pdca_column("Check", "🔍", "#f59e0b", check_items)
    cols += _pdca_column("Act", "✅", "#22c55e", act_items)

    return f'''
    <div id="sec-cn" style="margin-bottom:28px">
      <h2 style="font-size:18px;font-weight:800;color:#e2e8f0;margin:0 0 16px;
                 display:flex;align-items:center;gap:8px">
        <span style="background:linear-gradient(135deg,#FF2D55,#7B61FF);-webkit-background-clip:text;
              -webkit-text-fill-color:transparent;font-size:20px">CN</span>
        PDCA追跡ボード（直近7日）
      </h2>
      <div style="display:flex;gap:12px;flex-wrap:wrap">{cols}</div>
    </div>'''


# ─── CO: 記事パフォーマンス分析 ────────────────────────────────

def build_co_section() -> str:
    """CTR分布・スコア推移・勝率の可視化"""
    patterns = _load_jsonl(LOGS / "winning_patterns.jsonl", max_lines=200)
    cutoff = (datetime.now(JST) - timedelta(days=14)).isoformat()

    recent = [p for p in patterns if p.get("recorded_at", "") >= cutoff]

    # スコア分布
    score_bins = {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
    category_stats: dict[str, list] = defaultdict(list)
    wins = 0
    total = 0

    for p in recent:
        score = p.get("eval_72h") or p.get("eval_48h") or p.get("eval_24h")
        if not score or not isinstance(score, (int, float)):
            continue
        score = float(score)
        total += 1
        if score >= 50:
            wins += 1

        if score < 20:
            score_bins["0-20"] += 1
        elif score < 40:
            score_bins["20-40"] += 1
        elif score < 60:
            score_bins["40-60"] += 1
        elif score < 80:
            score_bins["60-80"] += 1
        else:
            score_bins["80-100"] += 1

        cat = p.get("category", "other")
        category_stats[cat].append(score)

    win_rate = round(wins * 100 / total, 1) if total else 0

    # スコア分布バー
    max_bin = max(score_bins.values()) or 1
    dist_html = ""
    bin_colors = {"0-20": "#ef4444", "20-40": "#f97316", "40-60": "#eab308",
                  "60-80": "#22c55e", "80-100": "#10b981"}
    for label, count in score_bins.items():
        w = int(count / max_bin * 120)
        color = bin_colors[label]
        dist_html += f'''
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
          <span style="width:50px;font-size:11px;color:#94a3b8;text-align:right">{label}</span>
          <div style="background:{color}22;border-radius:4px;height:18px;width:120px">
            <div style="background:{color};height:18px;border-radius:4px;width:{w}px;
                        transition:width 0.3s"></div>
          </div>
          <span style="font-size:11px;color:#cbd5e1;font-weight:600">{count}</span>
        </div>'''

    # カテゴリ別平均
    cat_html = ""
    for cat, scores_list in sorted(category_stats.items(), key=lambda x: -sum(x[1]) / len(x[1]) if x[1] else 0):
        avg = sum(scores_list) / len(scores_list)
        color = "#22c55e" if avg >= 50 else ("#eab308" if avg >= 35 else "#ef4444")
        cat_html += f'''
        <div style="display:flex;align-items:center;justify-content:space-between;
                    padding:6px 0;border-bottom:1px solid #1e293b">
          <span style="font-size:12px;color:#94a3b8">{cat}</span>
          <span style="font-size:13px;font-weight:700;color:{color}">{avg:.1f}</span>
        </div>'''

    # 直近TOP5記事
    top5_html = ""
    scored_recent = sorted(
        [p for p in recent if p.get("eval_72h") and isinstance(p.get("eval_72h"), (int, float))],
        key=lambda x: -x["eval_72h"]
    )[:5]
    for i, p in enumerate(scored_recent, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, "")
        title = p.get("title", "")[:35]
        score = p.get("eval_72h", 0)
        top5_html += f'''
        <div style="display:flex;align-items:center;gap:8px;padding:6px 0;
                    border-bottom:1px solid #1e293b;font-size:12px">
          <span style="width:20px;text-align:center">{medal or i}</span>
          <span style="flex:1;color:#cbd5e1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{title}</span>
          <span style="color:#22c55e;font-weight:700">{score:.0f}</span>
        </div>'''

    return f'''
    <div id="sec-co" style="margin-bottom:28px">
      <h2 style="font-size:18px;font-weight:800;color:#e2e8f0;margin:0 0 16px;
                 display:flex;align-items:center;gap:8px">
        <span style="background:linear-gradient(135deg,#FF2D55,#7B61FF);-webkit-background-clip:text;
              -webkit-text-fill-color:transparent;font-size:20px">CO</span>
        記事パフォーマンス分析（14日間）
      </h2>
      <div style="display:flex;gap:14px;flex-wrap:wrap">
        <!-- 勝率カード -->
        <div style="background:#0f172a;border:1px solid #1e293b;border-radius:14px;
                    padding:18px;flex:1;min-width:200px;text-align:center">
          <div style="font-size:12px;color:#64748b;margin-bottom:6px">勝率（スコア50+）</div>
          <div style="font-size:42px;font-weight:900;
                      color:{'#22c55e' if win_rate >= 50 else '#eab308'}">{win_rate:.0f}%</div>
          <div style="font-size:11px;color:#475569">{wins}勝 / {total}評価</div>
        </div>
        <!-- スコア分布 -->
        <div style="background:#0f172a;border:1px solid #1e293b;border-radius:14px;
                    padding:18px;flex:1.5;min-width:240px">
          <div style="font-size:13px;font-weight:700;color:#94a3b8;margin-bottom:10px">スコア分布</div>
          {dist_html}
        </div>
        <!-- カテゴリ別 -->
        <div style="background:#0f172a;border:1px solid #1e293b;border-radius:14px;
                    padding:18px;flex:1;min-width:180px">
          <div style="font-size:13px;font-weight:700;color:#94a3b8;margin-bottom:10px">カテゴリ別平均</div>
          {cat_html or '<div style="color:#374151;font-size:11px">データなし</div>'}
        </div>
      </div>
      <!-- TOP5記事 -->
      <div style="background:#0f172a;border:1px solid #1e293b;border-radius:14px;
                  padding:18px;margin-top:14px">
        <div style="font-size:13px;font-weight:700;color:#94a3b8;margin-bottom:10px">
          🏆 高評価TOP5</div>
        {top5_html or '<div style="color:#374151;font-size:11px">データなし</div>'}
      </div>
    </div>'''


# ─── 統合ビルダー ─────────────────────────────────────────────

def build_realtime_sections() -> dict:
    """全セクションをまとめて返す"""
    return {
        "cl_html": build_cl_section(),
        "cm_html": build_cm_section(),
        "cn_html": build_cn_section(),
        "co_html": build_co_section(),
    }


if __name__ == "__main__":
    parts = build_realtime_sections()
    for key, html in parts.items():
        print(f"=== {key} ({len(html):,} bytes) ===")
        print(html[:500])
        print("...")
