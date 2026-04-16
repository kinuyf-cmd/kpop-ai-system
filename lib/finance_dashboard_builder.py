#!/usr/bin/env python3
"""
lib/finance_dashboard_builder.py
財務ダッシュボード (CJ セクション) 生成
収益寄与指標・KPI進捗・月末着地予測をオーナー向けに表示
"""

import json
import calendar
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
LOGS = BASE / "logs"

def _load_jsonl(path: Path, max_r: int = 500) -> list[dict]:
    if not path.exists():
        return []
    out = []
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return out[-max_r:]

def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def _month() -> str:
    return datetime.now().strftime("%Y-%m")

def _days_in_month() -> int:
    now = datetime.now()
    return calendar.monthrange(now.year, now.month)[1]

def _day_of_month() -> int:
    return datetime.now().day

def _project(actual: int) -> int:
    dom = _day_of_month()
    dim = _days_in_month()
    if dom <= 0:
        return 0
    return round(actual / dom * dim)

def _pct(actual, target) -> float:
    if not target:
        return 0.0
    return round(actual / target * 100, 1)

def _color(pct: float, is_error: bool = False) -> str:
    if is_error:
        return "#22c55e" if pct == 0 else ("#eab308" if pct <= 5 else "#ef4444")
    return "#22c55e" if pct >= 80 else ("#eab308" if pct >= 40 else "#ef4444")

def _bar(pct: float, color: str, width_px: int = 120) -> str:
    w = min(100, max(0, pct))
    return (f'<div style="background:#1e293b;border-radius:4px;height:6px;width:{width_px}px;display:inline-block;vertical-align:middle">'
            f'<div style="background:{color};height:6px;border-radius:4px;width:{w:.0f}%"></div></div>')

def collect_finance_actuals() -> dict:
    today = _today()
    month = _month()

    # 記事公開数
    posts = _load_jsonl(LOGS / "kpi_posts.jsonl")
    daily_posts = sum(1 for r in posts if r.get("date") == today and r.get("event") == "post_published")
    monthly_posts = sum(1 for r in posts if (r.get("date") or "").startswith(month) and r.get("event") == "post_published")

    # 収益寄与記事数 (has_cta=True かつ公開)
    daily_revenue_articles = sum(1 for r in posts if r.get("date") == today
                                  and r.get("event") == "post_published" and r.get("has_cta"))
    monthly_revenue_articles = sum(1 for r in posts if (r.get("date") or "").startswith(month)
                                    and r.get("event") == "post_published" and r.get("has_cta"))

    # CTA設置率
    total_pub = sum(1 for r in posts if (r.get("date") or "").startswith(month)
                    and r.get("event") == "post_published")
    cta_posts = sum(1 for r in posts if (r.get("date") or "").startswith(month)
                    and r.get("event") == "post_published" and r.get("has_cta"))
    cta_rate = round(cta_posts / max(total_pub, 1) * 100, 1)

    # X投稿
    admin = _load_jsonl(LOGS / "admin_actions.jsonl")
    daily_x = sum(1 for r in admin if r.get("timestamp", "").startswith(today)
                  and r.get("action") in ("x_backfill_posted", "x_posted", "x_post"))
    monthly_x = sum(1 for r in admin if r.get("timestamp", "").startswith(month)
                    and r.get("action") in ("x_backfill_posted", "x_posted", "x_post"))

    # CTR改善アクション
    monthly_ctr = sum(1 for r in admin if r.get("timestamp", "").startswith(month)
                      and any(k in str(r.get("action", "")).lower() for k in ("ctr", "rewrite", "title_fix")))

    # インデックス申請
    index_records = _load_jsonl(LOGS / "indexing_api_sends.jsonl")
    monthly_index = sum(1 for r in index_records if (r.get("sent_at", "") or "").startswith(month))

    # WIN記事数
    wp_records = _load_jsonl(LOGS / "winning_patterns.jsonl")
    monthly_wins = sum(1 for r in wp_records if r.get("rank") == "WIN")

    # エラー損失
    error_records = _load_jsonl(LOGS / "kpi_errors.jsonl")
    daily_errors = sum(1 for r in error_records if (r.get("date") or r.get("timestamp", ""))[:10] == today)
    monthly_errors = sum(1 for r in error_records if (r.get("date") or r.get("timestamp", ""))[:7] == month)

    # revenue_metrics.json から収益スコア
    rev = _load_json(BASE / "revenue_metrics.json")
    rev_summary = rev.get("summary", {})
    avg_rev_score = rev_summary.get("avg_revenue_score", 0)

    return {
        "daily_posts": daily_posts,
        "daily_revenue_articles": daily_revenue_articles,
        "daily_x": daily_x,
        "daily_errors": daily_errors,
        "monthly_posts": monthly_posts,
        "monthly_revenue_articles": monthly_revenue_articles,
        "monthly_x": monthly_x,
        "monthly_wins": monthly_wins,
        "monthly_ctr": monthly_ctr,
        "monthly_index": monthly_index,
        "monthly_errors": monthly_errors,
        "cta_rate": cta_rate,
        "avg_rev_score": avg_rev_score,
    }

def _load_targets() -> dict:
    p = BASE / "config" / "finance_targets.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def build_cj_section() -> str:
    actuals = collect_finance_actuals()
    targets_cfg = _load_targets()
    daily_t = targets_cfg.get("daily", {})
    monthly_t = targets_cfg.get("monthly", {})
    today = _today()
    month = _month()
    dom = _day_of_month()
    dim = _days_in_month()
    month_pct = round(dom / dim * 100, 1)
    now_jst = datetime.now(tz=timezone(timedelta(hours=9))).strftime("%m/%d %H:%M")

    # ── デイリー指標カード ──
    def d_card(label, icon, actual, target, unit="件", is_error=False):
        p = _pct(actual, target) if not is_error else (100 if actual > 0 else 0)
        c = _color(p, is_error)
        bar_html = _bar(min(100, _pct(actual, target)), c)
        if is_error:
            val_str = f'<span style="color:{c};font-size:1.4rem;font-weight:900">{actual}</span>'
            sub = "✅ 正常" if actual == 0 else f"⚠️ {actual}件発生"
        else:
            val_str = f'<span style="color:{c};font-size:1.4rem;font-weight:900">{actual}</span><span style="color:#475569;font-size:0.8rem">/{target}</span>'
            sub = f"{_pct(actual, target):.0f}% 達成"
        return f"""<div style="background:#111827;border:1px solid #1e293b;border-top:3px solid {c};border-radius:10px;padding:12px;text-align:center">
  <div style="font-size:0.68rem;color:#64748b;margin-bottom:6px">{icon} {label}</div>
  <div>{val_str}</div>
  <div style="font-size:0.68rem;color:#64748b;margin-top:4px">{sub}</div>
  <div style="margin-top:6px">{bar_html}</div>
  <div style="font-size:0.6rem;color:#374151;margin-top:3px">目標: {target} {unit}</div>
</div>"""

    daily_cards = (
        d_card("今日の公開記事",       "📝", actuals["daily_posts"],            daily_t.get("revenue_articles",{}).get("target",3), "本") +
        d_card("今日の収益記事",       "💰", actuals["daily_revenue_articles"],  daily_t.get("revenue_articles",{}).get("target",3), "本") +
        d_card("今日のX投稿",          "🐦", actuals["daily_x"],                 daily_t.get("cta_actions",{}).get("target",2), "件") +
        d_card("今日のエラー損失",     "🚨", actuals["daily_errors"],            daily_t.get("error_loss",{}).get("target",0), "件", is_error=True)
    )

    # ── マンスリー指標テーブル ──
    m_items = [
        ("月間公開記事数",   "📝", actuals["monthly_posts"],            monthly_t.get("revenue_articles",{}).get("target",60),  "本"),
        ("月間収益記事数",   "💰", actuals["monthly_revenue_articles"], monthly_t.get("revenue_articles",{}).get("target",60),  "本"),
        ("月間X投稿数",      "🐦", actuals["monthly_x"],                monthly_t.get("win_articles",{}).get("target",90),      "件"),
        ("月間WIN記事数",    "🏆", actuals["monthly_wins"],             monthly_t.get("win_articles",{}).get("target",20),      "本"),
        ("月間CTR改善数",    "📈", actuals["monthly_ctr"],              monthly_t.get("ctr_improvements",{}).get("target",40),  "件"),
        ("月間索引申請数",   "🔍", actuals["monthly_index"],            monthly_t.get("index_sends",{}).get("target",120),      "件"),
    ]

    m_rows = ""
    on_track_count = 0
    for label, icon, actual, target, unit in m_items:
        done_pct = _pct(actual, target)
        proj = _project(actual)
        on_track = proj >= target
        if on_track:
            on_track_count += 1
        c = _color(done_pct)
        track_c = "#22c55e" if on_track else ("#eab308" if done_pct >= month_pct * 0.7 else "#ef4444")
        track_label = "順調" if on_track else ("注意" if done_pct >= month_pct * 0.7 else "遅れ")
        bar_html = _bar(done_pct, c, 80)
        m_rows += f"""<tr style="border-bottom:1px solid #1e293b">
  <td style="padding:6px 8px;font-size:0.78rem;color:#94a3b8">{icon} {label}</td>
  <td style="padding:6px 8px;text-align:right;font-weight:700;color:#e2e8f0">{actual}</td>
  <td style="padding:6px 8px;text-align:right;color:#475569">{target}</td>
  <td style="padding:6px 8px">{bar_html} <span style="font-size:0.65rem;color:{c}">{done_pct:.0f}%</span></td>
  <td style="padding:6px 8px;text-align:right;color:#818cf8">{proj}</td>
  <td style="padding:6px 8px"><span style="background:{track_c}22;color:{track_c};border:1px solid {track_c}44;padding:2px 7px;border-radius:99px;font-size:0.65rem;font-weight:700">{track_label}</span></td>
</tr>"""

    # エラー損失行
    err_c = _color(0, is_error=True) if actuals["monthly_errors"] == 0 else _color(50, is_error=True)
    m_rows += f"""<tr>
  <td style="padding:6px 8px;font-size:0.78rem;color:#94a3b8">🚨 月間エラー損失</td>
  <td style="padding:6px 8px;text-align:right;font-weight:700;color:{err_c}">{actuals['monthly_errors']}</td>
  <td style="padding:6px 8px;text-align:right;color:#475569">0 件</td>
  <td colspan="3" style="padding:6px 8px;font-size:0.72rem;color:{err_c}">
    {"✅ エラーなし" if actuals['monthly_errors']==0 else f"⚠️ {actuals['monthly_errors']}件のエラー損失が発生"}
  </td>
</tr>"""

    # ── ボトルネック判定 ──
    bottlenecks = []
    for label, icon, actual, target, unit in m_items:
        done_pct = _pct(actual, target)
        if done_pct < month_pct * 0.6:
            bottlenecks.append(f"{icon} {label}（{done_pct:.0f}%）")

    if actuals["monthly_errors"] > 0:
        bottlenecks.append(f"🚨 エラー損失{actuals['monthly_errors']}件")

    btn_html = ""
    for b in bottlenecks[:3]:
        btn_html += f'<div style="background:#1a0a0a;border:1px solid #ef444433;border-radius:6px;padding:8px 12px;font-size:0.78rem;color:#fca5a5;margin-bottom:6px">🔴 {b}</div>'
    if not btn_html:
        btn_html = '<div style="color:#22c55e;font-size:0.78rem;padding:8px">✅ 財務ボトルネックなし — 全指標順調</div>'

    # ── サマリーバー ──
    cta_c = "#22c55e" if actuals["cta_rate"] >= 70 else ("#eab308" if actuals["cta_rate"] >= 40 else "#ef4444")
    rev_c = "#22c55e" if actuals["avg_rev_score"] >= 0.75 else ("#eab308" if actuals["avg_rev_score"] >= 0.5 else "#ef4444")
    overall_track = on_track_count >= len(m_items) * 0.6
    track_banner_c = "#22c55e" if overall_track else "#eab308"
    track_banner = "月間目標ペース順調" if overall_track else f"一部指標が遅れ中 ({on_track_count}/{len(m_items)}達成ペース)"

    return f"""<div class="section" id="cj-finance" style="border:2px solid #a3e63555;border-radius:14px;padding:20px;margin-bottom:20px;background:linear-gradient(135deg,#0a1410,#0d1b0a)">
  <div class="section-title" style="border-bottom-color:#a3e63533;margin-bottom:16px">
    <span class="section-title-icon">💹</span>
    <span style="color:#a3e635;font-size:0.9rem;font-weight:900">CJ. 財務・収益状況</span>
    <span style="margin-left:auto;font-size:0.72rem;color:#64748b">{today} {now_jst}</span>
    <span style="margin-left:10px;background:{track_banner_c}22;color:{track_banner_c};border:1px solid {track_banner_c}44;padding:3px 10px;border-radius:99px;font-size:0.7rem;font-weight:700">{track_banner}</span>
  </div>

  <!-- 収益スコアバー -->
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px">
    <div style="background:#111827;border:1px solid #1e293b;border-radius:8px;padding:10px 16px;flex:1;min-width:140px;text-align:center">
      <div style="font-size:0.65rem;color:#64748b;margin-bottom:4px">CTA設置率</div>
      <div style="font-size:1.4rem;font-weight:900;color:{cta_c}">{actuals['cta_rate']:.0f}%</div>
      <div style="font-size:0.65rem;color:#475569">目標 80%以上</div>
    </div>
    <div style="background:#111827;border:1px solid #1e293b;border-radius:8px;padding:10px 16px;flex:1;min-width:140px;text-align:center">
      <div style="font-size:0.65rem;color:#64748b;margin-bottom:4px">収益スコア（平均）</div>
      <div style="font-size:1.4rem;font-weight:900;color:{rev_c}">{actuals['avg_rev_score']:.2f}</div>
      <div style="font-size:0.65rem;color:#475569">目標 0.75以上</div>
    </div>
    <div style="background:#111827;border:1px solid #1e293b;border-radius:8px;padding:10px 16px;flex:1;min-width:140px;text-align:center">
      <div style="font-size:0.65rem;color:#64748b;margin-bottom:4px">WIN記事累計</div>
      <div style="font-size:1.4rem;font-weight:900;color:#fbbf24">{actuals['monthly_wins']}</div>
      <div style="font-size:0.65rem;color:#475569">目標 20本/月</div>
    </div>
  </div>

  <!-- 今日の指標 -->
  <div style="font-size:0.72rem;color:#a3e635;font-weight:800;margin-bottom:8px">今日の指標</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px;margin-bottom:16px">
    {daily_cards}
  </div>

  <!-- 今月の指標 -->
  <div style="font-size:0.72rem;color:#a3e635;font-weight:800;margin-bottom:8px">今月の指標（{dom}/{dim}日経過・月の{month_pct:.0f}%）</div>
  <div style="overflow-x:auto;margin-bottom:16px">
    <table style="width:100%;border-collapse:collapse;font-size:0.78rem">
      <thead>
        <tr style="border-bottom:2px solid #1e293b;color:#64748b;font-size:0.65rem">
          <th style="text-align:left;padding:5px 8px">指標</th>
          <th style="text-align:right;padding:5px 8px">実績</th>
          <th style="text-align:right;padding:5px 8px">目標</th>
          <th style="text-align:left;padding:5px 8px;width:110px">進み具合</th>
          <th style="text-align:right;padding:5px 8px">月末予測</th>
          <th style="text-align:left;padding:5px 8px">判定</th>
        </tr>
      </thead>
      <tbody>{m_rows}</tbody>
    </table>
  </div>

  <!-- ボトルネック -->
  <div style="font-size:0.72rem;color:#fca5a5;font-weight:800;margin-bottom:8px">収益ボトルネック</div>
  {btn_html}
  <div style="font-size:0.65rem;color:#334155;margin-top:8px">※ 月末予測 = 日次平均×月日数。収益数値は直接取得できないため代替指標（記事数・CTA率・WIN記事数）で算出。</div>
</div>"""


if __name__ == "__main__":
    html = build_cj_section()
    print(f"CJ section: {len(html)} chars")
    a = collect_finance_actuals()
    print("Finance actuals:", a)
