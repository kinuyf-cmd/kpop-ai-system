#!/usr/bin/env python3
"""
lib/kpi_dashboard_builder.py
経営KPIボード ビルダー (CA/CB/CC/CD セクション)
デイリーKPI / マンスリーKPI / 進捗タイムライン / オーナー総合判断サマリー
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

BASE = Path(__file__).parent.parent
LOGS = BASE / "logs"

# ─── KPI目標値 ───────────────────────────────────────────
def load_kpi_targets() -> dict:
    cfg_path = BASE / "config" / "kpi_targets.json"
    if cfg_path.exists():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            return raw
        except Exception:
            pass
    return {}

DAILY_DEFAULTS = {
    "posts": 3,
    "x_posts": 3,
    "index_requests": 5,
    "rewrites": 2,
    "ctr_actions": 2,
    "thumbnail_fixes": 1,
    "errors": 0,
}

MONTHLY_DEFAULTS = {
    "posts": 90,
    "x_posts": 90,
    "index_requests": 120,
    "rewrites": 40,
    "win_articles": 20,
    "ctr_actions": 40,
}

def get_daily_targets() -> dict:
    raw = load_kpi_targets()
    daily = raw.get("daily", {})
    return {
        "posts":           daily.get("articles_posted", {}).get("target", DAILY_DEFAULTS["posts"]),
        "x_posts":         daily.get("x_posts", {}).get("target", DAILY_DEFAULTS["x_posts"]),
        "index_requests":  DAILY_DEFAULTS["index_requests"],
        "rewrites":        DAILY_DEFAULTS["rewrites"],
        "ctr_actions":     DAILY_DEFAULTS["ctr_actions"],
        "thumbnail_fixes": DAILY_DEFAULTS["thumbnail_fixes"],
        "errors":          0,
    }

def get_monthly_targets() -> dict:
    raw = load_kpi_targets()
    monthly = raw.get("monthly", {})
    return {
        "posts":           monthly.get("articles_total", {}).get("target", MONTHLY_DEFAULTS["posts"]),
        "x_posts":         monthly.get("x_posts", {}).get("target", MONTHLY_DEFAULTS["x_posts"]),
        "index_requests":  MONTHLY_DEFAULTS["index_requests"],
        "rewrites":        MONTHLY_DEFAULTS["rewrites"],
        "win_articles":    MONTHLY_DEFAULTS["win_articles"],
        "ctr_actions":     MONTHLY_DEFAULTS["ctr_actions"],
    }

# ─── ログ読み込みユーティリティ ───────────────────────────
def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return records

def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def this_month_str() -> str:
    return datetime.now().strftime("%Y-%m")

def jst_now() -> datetime:
    return datetime.now(tz=timezone(timedelta(hours=9)))

# ─── デイリー実績集計 ──────────────────────────────────────
def collect_daily_actuals() -> dict:
    today = today_str()
    month = this_month_str()

    # 1. 今日の公開記事数
    posts_records = load_jsonl(LOGS / "kpi_posts.jsonl")
    daily_posts = sum(1 for r in posts_records
                      if r.get("date") == today and r.get("event") == "post_published")

    # 2. 今日のX投稿数
    admin_records = load_jsonl(LOGS / "admin_actions.jsonl")
    daily_x = sum(1 for r in admin_records
                  if r.get("timestamp", "").startswith(today)
                  and r.get("action") in ("x_backfill_posted", "x_posted", "x_post"))
    # x_posted_urls.txt から今日投稿された数も参照
    x_url_path = LOGS / "x_posted_urls.txt"
    if x_url_path.exists():
        try:
            lines = x_url_path.read_text(encoding="utf-8").splitlines()
            # URLのみのファイルなのでそのまま日付フィルタできないが総数として使う
            # admin_actions.jsonl の方が信頼性高い
            pass
        except Exception:
            pass

    # 3. 今日のインデックス申請数
    index_records = load_jsonl(LOGS / "indexing_api_sends.jsonl")
    daily_index = sum(1 for r in index_records
                      if (r.get("sent_at", "") or "").startswith(today))

    # 4. 今日の改善処理数 (rewrite_losers.log 行数を月で割るか、kpi_posts から rewrite イベントを使う)
    rewrite_records = [r for r in posts_records
                       if r.get("date") == today and r.get("event") in ("rewrite_completed", "rewrite_done")]
    # admin_actions にもリライトイベントがある場合
    rewrite_from_admin = sum(1 for r in admin_records
                             if r.get("timestamp", "").startswith(today)
                             and "rewrite" in str(r.get("action", "")).lower())
    daily_rewrites = max(len(rewrite_records), rewrite_from_admin)

    # 5. 今日のエラー件数
    error_records = load_jsonl(LOGS / "kpi_errors.jsonl")
    daily_errors = sum(1 for r in error_records
                       if (r.get("date") == today or r.get("timestamp", "").startswith(today)))

    # 6. 今日のCTR改善アクション数
    ctr_from_admin = sum(1 for r in admin_records
                         if r.get("timestamp", "").startswith(today)
                         and any(k in str(r.get("action", "")).lower() for k in ("ctr", "rewrite", "title_fix")))
    daily_ctr = ctr_from_admin

    # 7. 今日のサムネ差し替え/修正数
    thumb_records = load_jsonl(LOGS / "thumbnail_performance.jsonl")
    daily_thumbnails = sum(1 for r in thumb_records
                           if (r.get("timestamp", "") or "").startswith(today)
                           and r.get("result") not in ("pending", None))
    thumb_from_admin = sum(1 for r in admin_records
                           if r.get("timestamp", "").startswith(today)
                           and any(k in str(r.get("action", "")).lower() for k in ("thumbnail", "thumb", "サムネ")))
    daily_thumbnails = max(daily_thumbnails, thumb_from_admin)

    return {
        "posts":           daily_posts,
        "x_posts":         daily_x,
        "index_requests":  daily_index,
        "rewrites":        daily_rewrites,
        "errors":          daily_errors,
        "ctr_actions":     daily_ctr,
        "thumbnail_fixes": daily_thumbnails,
    }

# ─── マンスリー実績集計 ─────────────────────────────────────
def collect_monthly_actuals() -> dict:
    month = this_month_str()
    today = today_str()

    posts_records = load_jsonl(LOGS / "kpi_posts.jsonl")
    monthly_posts = sum(1 for r in posts_records
                        if (r.get("date") or "").startswith(month)
                        and r.get("event") == "post_published")

    admin_records = load_jsonl(LOGS / "admin_actions.jsonl")
    monthly_x = sum(1 for r in admin_records
                    if r.get("timestamp", "").startswith(month)
                    and r.get("action") in ("x_backfill_posted", "x_posted", "x_post"))

    index_records = load_jsonl(LOGS / "indexing_api_sends.jsonl")
    monthly_index = sum(1 for r in index_records
                        if (r.get("sent_at", "") or "").startswith(month))

    rewrite_from_admin = sum(1 for r in admin_records
                             if r.get("timestamp", "").startswith(month)
                             and "rewrite" in str(r.get("action", "")).lower())
    monthly_rewrites = rewrite_from_admin

    # WIN判定数
    wp_records = load_jsonl(LOGS / "winning_patterns.jsonl")
    monthly_wins = sum(1 for r in wp_records
                       if r.get("rank") == "WIN" and
                       (r.get("timestamp", "") or r.get("date", "") or "").startswith(month))
    if monthly_wins == 0:
        # 月次全体でのWINを使う
        monthly_wins = sum(1 for r in wp_records if r.get("rank") == "WIN")

    # 月間エラー率
    error_records = load_jsonl(LOGS / "kpi_errors.jsonl")
    monthly_errors = sum(1 for r in error_records
                         if (r.get("date") or r.get("timestamp", ""))[:7] == month)
    # エラー率 = エラー数 / (記事数+1) で簡易算出
    monthly_error_rate = round(monthly_errors / max(monthly_posts, 1) * 100, 1)

    # CTRアクション数
    monthly_ctr = sum(1 for r in admin_records
                      if r.get("timestamp", "").startswith(month)
                      and any(k in str(r.get("action", "")).lower() for k in ("ctr", "rewrite", "title_fix")))

    return {
        "posts":        monthly_posts,
        "x_posts":      monthly_x,
        "index_requests": monthly_index,
        "rewrites":     monthly_rewrites,
        "win_articles": monthly_wins,
        "ctr_actions":  monthly_ctr,
        "error_rate":   monthly_error_rate,
    }

# ─── 月末着地予測 ───────────────────────────────────────────
def project_month_end(actual: int, today_date: datetime = None) -> dict:
    if today_date is None:
        today_date = datetime.now()
    day_of_month = today_date.day
    # 月の日数 (簡易: 次月1日 - 1日)
    year = today_date.year
    month = today_date.month
    if month == 12:
        days_in_month = 31
    else:
        import calendar
        days_in_month = calendar.monthrange(year, month)[1]
    daily_avg = actual / max(day_of_month, 1)
    projection = round(daily_avg * days_in_month)
    return {
        "projection": projection,
        "day_of_month": day_of_month,
        "days_in_month": days_in_month,
        "daily_avg": round(daily_avg, 1),
    }

# ─── intraday スナップショット追記 ────────────────────────────
def append_intraday_snapshot(daily_actuals: dict, daily_targets: dict):
    """run_dashboard_refresh.sh 実行時に呼ぶ。時刻スナップを追記する。"""
    snap_path = LOGS / "kpi_intraday_history.jsonl"
    now = jst_now()
    progress = {}
    for k in ["posts", "x_posts", "index_requests", "rewrites"]:
        tgt = daily_targets.get(k, 1)
        act = daily_actuals.get(k, 0)
        progress[k] = round(act / max(tgt, 1) * 100, 1)
    snapshot = {
        "ts": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "hour": now.hour,
        "posts": daily_actuals.get("posts", 0),
        "x_posts": daily_actuals.get("x_posts", 0),
        "errors": daily_actuals.get("errors", 0),
        "rewrites": daily_actuals.get("rewrites", 0),
        "index_requests": daily_actuals.get("index_requests", 0),
        "overall_progress": round(sum(progress.values()) / len(progress), 1),
    }
    try:
        with snap_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[kpi_dashboard_builder] intraday append error: {e}")

# ─── monthly snapshot 保存 ─────────────────────────────────
def save_monthly_snapshot(monthly_actuals: dict, monthly_targets: dict, projections: dict):
    snap_path = LOGS / "kpi_monthly_snapshot.json"
    now = datetime.now()
    data = {
        "generated_at": now.isoformat(),
        "month": now.strftime("%Y-%m"),
        "actuals": monthly_actuals,
        "targets": monthly_targets,
        "projections": projections,
    }
    try:
        snap_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[kpi_dashboard_builder] monthly snapshot save error: {e}")

# ─── 進捗率計算 ─────────────────────────────────────────────
def calc_progress(actual: int, target: int) -> float:
    if target <= 0:
        return 100.0
    return round(actual / target * 100, 1)

def progress_color(pct: float, is_error: bool = False) -> str:
    if is_error:
        return "#22c55e" if pct == 0 else ("#eab308" if pct <= 2 else "#ef4444")
    return "#22c55e" if pct >= 80 else ("#eab308" if pct >= 40 else "#ef4444")

def progress_class(pct: float, is_error: bool = False) -> str:
    if is_error:
        return "green" if pct == 0 else ("yellow" if pct <= 2 else "red")
    return "green" if pct >= 80 else ("yellow" if pct >= 40 else "red")

# ─── KPIプログレスバーHTML ───────────────────────────────────
def kpi_progress_bar(pct: float, is_error: bool = False) -> str:
    color = progress_color(pct, is_error)
    clamped = min(100, pct)
    return (
        f'<div style="background:#1e293b;border-radius:4px;height:8px;width:100%;margin-top:6px">'
        f'<div style="background:{color};height:8px;border-radius:4px;width:{clamped:.0f}%;'
        f'transition:width 0.3s ease"></div></div>'
    )

# ─── デイリーKPIカード1枚のHTML ─────────────────────────────
def daily_kpi_card(label: str, icon: str, actual: int, target: int,
                   unit: str = "件", is_error: bool = False) -> str:
    pct = calc_progress(actual, target)
    color = progress_color(pct, is_error)
    cls = progress_class(pct, is_error)
    bar_html = kpi_progress_bar(pct, is_error)
    if is_error:
        status_label = "✅ 正常" if actual == 0 else (f"⚠️ {actual}件" if actual <= 2 else f"🚨 {actual}件")
        return f"""<div class="kpi-card {cls}" style="min-width:140px">
  <div class="kpi-label">{icon} {label}</div>
  <div class="kpi-value" style="color:{color};font-size:1.6rem">{actual}</div>
  <div class="kpi-sub" style="color:{color}">{status_label}</div>
  {bar_html}
  <div style="font-size:0.65rem;color:#475569;margin-top:4px">目標: {target} {unit}</div>
</div>"""
    return f"""<div class="kpi-card {cls}" style="min-width:140px">
  <div class="kpi-label">{icon} {label}</div>
  <div class="kpi-value" style="color:{color};font-size:1.6rem">{actual}<span style="font-size:0.9rem;color:#64748b">/{target}</span></div>
  <div class="kpi-sub">{pct:.0f}% 達成</div>
  {bar_html}
  <div style="font-size:0.65rem;color:#475569;margin-top:4px">{unit}</div>
</div>"""

# ─── CA. デイリーKPIボード ──────────────────────────────────
def build_ca_section(daily_actuals: dict, daily_targets: dict) -> str:
    now_str = jst_now().strftime("%H:%M JST")
    today = today_str()

    overall_pcts = []
    for k in ["posts", "x_posts", "index_requests", "rewrites"]:
        overall_pcts.append(calc_progress(daily_actuals.get(k, 0), daily_targets.get(k, 1)))
    avg_progress = round(sum(overall_pcts) / len(overall_pcts), 1)
    avg_color = progress_color(avg_progress)

    cards = ""
    cards += daily_kpi_card("公開記事", "📝", daily_actuals["posts"], daily_targets["posts"], "本/日")
    cards += daily_kpi_card("X投稿", "🐦", daily_actuals["x_posts"], daily_targets["x_posts"], "件/日")
    cards += daily_kpi_card("インデックス申請", "🔍", daily_actuals["index_requests"], daily_targets["index_requests"], "件/日")
    cards += daily_kpi_card("改善処理", "✏️", daily_actuals["rewrites"], daily_targets["rewrites"], "件/日")
    cards += daily_kpi_card("エラー件数", "🚨", daily_actuals["errors"], 3, "件", is_error=True)
    cards += daily_kpi_card("CTR改善", "📈", daily_actuals["ctr_actions"], daily_targets["ctr_actions"], "件/日")
    cards += daily_kpi_card("サムネ修正", "🖼️", daily_actuals["thumbnail_fixes"], daily_targets["thumbnail_fixes"], "件/日")

    return f"""<div class="section" id="ca-daily-kpi" style="border:2px solid #22d3ee55;border-radius:14px;padding:20px;margin-bottom:20px;background:linear-gradient(135deg,#0a1628,#0d1b2a)">
  <div class="section-title" style="border-bottom-color:#22d3ee33;margin-bottom:16px">
    <span class="section-title-icon">📊</span>
    <span style="color:#22d3ee;font-size:0.9rem;font-weight:900">CA. デイリーKPIボード</span>
    <span style="margin-left:auto;font-size:0.72rem;color:#94a3b8">{today} {now_str} 時点</span>
    <span style="margin-left:12px;background:{avg_color}22;color:{avg_color};border:1px solid {avg_color}44;padding:3px 10px;border-radius:99px;font-size:0.72rem;font-weight:700">今日の平均達成率 {avg_progress:.0f}%</span>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px">
    {cards}
  </div>
</div>"""

# ─── CB. マンスリーKPIボード ────────────────────────────────
def build_cb_section(monthly_actuals: dict, monthly_targets: dict) -> str:
    today_date = datetime.now()
    import calendar
    days_in_month = calendar.monthrange(today_date.year, today_date.month)[1]
    day_of_month = today_date.day
    month_progress_pct = round(day_of_month / days_in_month * 100, 1)

    rows = ""
    kpi_items = [
        ("posts",          "📝 月間公開記事数",   "本"),
        ("x_posts",        "🐦 月間X投稿数",      "件"),
        ("index_requests", "🔍 月間インデックス申請数", "件"),
        ("rewrites",       "✏️ 月間リライト改善数", "件"),
        ("win_articles",   "🏆 月間WIN記事数",    "本"),
        ("ctr_actions",    "📈 月間CTR改善アクション数", "件"),
    ]
    on_track_count = 0
    total_kpis = len(kpi_items)

    for key, label, unit in kpi_items:
        tgt = monthly_targets.get(key, 1)
        act = monthly_actuals.get(key, 0)
        pct_done = calc_progress(act, tgt)
        proj_info = project_month_end(act, today_date)
        proj_val = proj_info["projection"]
        on_track = proj_val >= tgt
        if on_track:
            on_track_count += 1
        track_label = "🟢 ON TRACK" if on_track else ("🟡 AT RISK" if pct_done >= month_progress_pct * 0.7 else "🔴 BEHIND")
        track_color = "#22c55e" if on_track else ("#eab308" if pct_done >= month_progress_pct * 0.7 else "#ef4444")
        bar_w = min(100, pct_done)
        rows += f"""<tr style="border-bottom:1px solid #1e293b">
  <td style="padding:8px 10px;color:#94a3b8;font-size:0.8rem">{label}</td>
  <td style="padding:8px 10px;text-align:right;color:#e2e8f0;font-weight:700">{act}</td>
  <td style="padding:8px 10px;text-align:right;color:#64748b">{tgt} {unit}</td>
  <td style="padding:8px 10px;width:100px">
    <div style="background:#1e293b;border-radius:3px;height:6px">
      <div style="background:{progress_color(pct_done)};height:6px;border-radius:3px;width:{bar_w:.0f}%"></div>
    </div>
    <div style="font-size:0.65rem;color:#64748b;margin-top:2px">{pct_done:.0f}%</div>
  </td>
  <td style="padding:8px 10px;text-align:right;color:#818cf8">{proj_val} {unit}</td>
  <td style="padding:8px 10px;font-size:0.72rem">
    <span style="background:{track_color}22;color:{track_color};border:1px solid {track_color}44;padding:2px 8px;border-radius:99px">{track_label}</span>
  </td>
</tr>"""

    # エラー率行
    err_rate = monthly_actuals.get("error_rate", 0)
    err_color = "#22c55e" if err_rate < 5 else ("#eab308" if err_rate < 15 else "#ef4444")
    rows += f"""<tr>
  <td style="padding:8px 10px;color:#94a3b8;font-size:0.8rem">⚠️ 月間エラー率</td>
  <td style="padding:8px 10px;text-align:right;color:{err_color};font-weight:700">{err_rate:.1f}%</td>
  <td style="padding:8px 10px;text-align:right;color:#64748b">目標 &lt;5%</td>
  <td colspan="3" style="padding:8px 10px;font-size:0.72rem;color:{err_color}">
    {"✅ 正常範囲" if err_rate < 5 else ("⚠️ 要注意" if err_rate < 15 else "🚨 要対応")}
  </td>
</tr>"""

    month_on_track = on_track_count >= (total_kpis // 2 + 1)
    overall_risk = "ON_TRACK" if on_track_count >= total_kpis * 0.7 else ("AT_RISK" if on_track_count >= total_kpis * 0.4 else "BEHIND")
    risk_color = "#22c55e" if overall_risk == "ON_TRACK" else ("#eab308" if overall_risk == "AT_RISK" else "#ef4444")
    month_str = today_date.strftime("%Y年%m月")

    return f"""<div class="section" id="cb-monthly-kpi" style="border:2px solid #818cf855;border-radius:14px;padding:20px;margin-bottom:20px;background:linear-gradient(135deg,#0a1628,#0f0c29)">
  <div class="section-title" style="border-bottom-color:#818cf833;margin-bottom:16px">
    <span class="section-title-icon">📅</span>
    <span style="color:#818cf8;font-size:0.9rem;font-weight:900">CB. マンスリーKPIボード</span>
    <span style="margin-left:auto;font-size:0.72rem;color:#94a3b8">{month_str} — {day_of_month}/{days_in_month}日経過 ({month_progress_pct:.0f}%)</span>
    <span style="margin-left:12px;background:{risk_color}22;color:{risk_color};border:1px solid {risk_color}44;padding:3px 10px;border-radius:99px;font-size:0.72rem;font-weight:700">{overall_risk}</span>
  </div>
  <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:0.8rem">
      <thead>
        <tr style="border-bottom:2px solid #1e293b;color:#64748b;font-size:0.72rem">
          <th style="text-align:left;padding:6px 10px">KPI項目</th>
          <th style="text-align:right;padding:6px 10px">実績</th>
          <th style="text-align:right;padding:6px 10px">目標</th>
          <th style="text-align:left;padding:6px 10px;width:100px">進捗</th>
          <th style="text-align:right;padding:6px 10px">月末予測</th>
          <th style="text-align:left;padding:6px 10px">判定</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <div style="margin-top:12px;font-size:0.72rem;color:#64748b;padding:8px;background:#0d1117;border-radius:6px">
    ※ 月末予測 = 日次平均 × 月日数で算出。単純推計。
  </div>
</div>"""

# ─── CC. KPI進捗タイムライン ────────────────────────────────
def build_cc_section() -> str:
    today = today_str()
    snap_path = LOGS / "kpi_intraday_history.jsonl"
    records = load_jsonl(snap_path)
    today_records = [r for r in records if r.get("date") == today]

    # 時刻ごとに最新スナップを取る
    hourly = {}
    for r in today_records:
        h = r.get("hour", 0)
        hourly[h] = r

    time_slots = [9, 11, 13, 15, 17, 19, 21]
    now_hour = jst_now().hour

    rows = ""
    for slot in time_slots:
        # その時刻以前で最新のスナップを探す
        snap = None
        for h in sorted(hourly.keys(), reverse=True):
            if h <= slot:
                snap = hourly[h]
                break
        is_future = slot > now_hour
        is_current = abs(slot - now_hour) <= 1 and not is_future
        row_style = "background:#1e293b22" if is_current else ""
        future_style = "opacity:0.4" if is_future else ""

        if snap:
            posts = snap.get("posts", "—")
            x_posts = snap.get("x_posts", "—")
            errors = snap.get("errors", "—")
            rewrites = snap.get("rewrites", "—")
            progress = snap.get("overall_progress", "—")
            prog_color = progress_color(float(progress)) if isinstance(progress, (int, float)) else "#64748b"
            prog_str = f'<span style="color:{prog_color};font-weight:700">{progress}%</span>' if isinstance(progress, (int, float)) else "—"
        else:
            posts = x_posts = errors = rewrites = "—"
            prog_str = "—" if is_future else "取得待ち"

        slot_label = f"{slot:02d}:00"
        current_mark = " 🔴LIVE" if is_current else ""
        rows += f"""<tr style="border-bottom:1px solid #1e293b;{row_style};{future_style}">
  <td style="padding:7px 12px;font-size:0.8rem;font-weight:700;color:{'#22d3ee' if is_current else '#94a3b8'}">{slot_label}{current_mark}</td>
  <td style="padding:7px 12px;text-align:center;color:#86efac">{posts}</td>
  <td style="padding:7px 12px;text-align:center;color:#a5f3fc">{x_posts}</td>
  <td style="padding:7px 12px;text-align:center;color:#fca5a5">{errors}</td>
  <td style="padding:7px 12px;text-align:center;color:#c4b5fd">{rewrites}</td>
  <td style="padding:7px 12px;text-align:center">{prog_str}</td>
</tr>"""

    return f"""<div class="section" id="cc-intraday-timeline" style="border:2px solid #34d39955;border-radius:14px;padding:20px;margin-bottom:20px">
  <div class="section-title" style="border-bottom-color:#34d39933;margin-bottom:16px">
    <span class="section-title-icon">⏱️</span>
    <span style="color:#34d399;font-size:0.9rem;font-weight:900">CC. KPI進捗タイムライン</span>
    <span style="margin-left:auto;font-size:0.72rem;color:#94a3b8">今日の時間帯別進捗 ({today})</span>
  </div>
  <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:0.8rem">
      <thead>
        <tr style="border-bottom:2px solid #1e293b;color:#64748b;font-size:0.72rem">
          <th style="text-align:left;padding:6px 12px">時刻</th>
          <th style="text-align:center;padding:6px 12px">📝公開記事</th>
          <th style="text-align:center;padding:6px 12px">🐦X投稿</th>
          <th style="text-align:center;padding:6px 12px">🚨エラー</th>
          <th style="text-align:center;padding:6px 12px">✏️改善</th>
          <th style="text-align:center;padding:6px 12px">📊進捗率</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <div style="margin-top:10px;font-size:0.7rem;color:#475569">
    ※ 各ダッシュボード更新時 (09:00〜21:00 2時間毎) に自動記録
  </div>
</div>"""

# ─── CD. オーナー総合判断サマリー ─────────────────────────────
def build_cd_section(daily_actuals: dict, daily_targets: dict,
                     monthly_actuals: dict, monthly_targets: dict) -> str:
    today_date = datetime.now()
    import calendar
    days_in_month = calendar.monthrange(today_date.year, today_date.month)[1]
    day_of_month = today_date.day
    month_progress_pct = day_of_month / days_in_month * 100

    # 今日の状態判定
    daily_posts_pct = calc_progress(daily_actuals["posts"], daily_targets["posts"])
    daily_x_pct = calc_progress(daily_actuals["x_posts"], daily_targets["x_posts"])
    daily_rewrite_pct = calc_progress(daily_actuals["rewrites"], daily_targets["rewrites"])
    daily_index_pct = calc_progress(daily_actuals["index_requests"], daily_targets["index_requests"])
    daily_errors = daily_actuals["errors"]
    avg_daily = round((daily_posts_pct + daily_x_pct + daily_rewrite_pct + daily_index_pct) / 4, 1)

    if daily_errors >= 3 and avg_daily < 40:
        today_status = "DANGER"
        today_status_color = "#ef4444"
        today_status_label = "🚨 DANGER"
    elif daily_errors <= 1 and avg_daily >= 60:
        today_status = "GOOD"
        today_status_color = "#22c55e"
        today_status_label = "✅ GOOD"
    else:
        today_status = "WATCH"
        today_status_color = "#eab308"
        today_status_label = "👀 WATCH"

    # 今日の状態の理由文
    reasons = []
    if daily_posts_pct < 40:
        reasons.append(f"記事数が目標の{daily_posts_pct:.0f}%にとどまる")
    elif daily_posts_pct >= 80:
        reasons.append(f"記事数は目標の{daily_posts_pct:.0f}%達成")
    if daily_x_pct >= 80:
        reasons.append("X投稿は順調")
    elif daily_x_pct < 40:
        reasons.append(f"X投稿が{daily_x_pct:.0f}%と遅れ")
    if daily_errors >= 3:
        reasons.append(f"エラー{daily_errors}件が発生中")
    if daily_rewrite_pct < 40:
        reasons.append("改善処理が遅れ")
    if daily_index_pct < 40:
        reasons.append("インデックス申請が不足")
    today_reason = "、".join(reasons) if reasons else "全KPI順調"

    # 今月の状態判定
    monthly_on_track_count = 0
    monthly_kpi_keys = ["posts", "x_posts", "index_requests", "rewrites", "win_articles", "ctr_actions"]
    bottlenecks = []
    successes = []
    for key in monthly_kpi_keys:
        tgt = monthly_targets.get(key, 1)
        act = monthly_actuals.get(key, 0)
        proj = project_month_end(act, today_date)["projection"]
        pct_done = calc_progress(act, tgt)
        if proj >= tgt:
            monthly_on_track_count += 1
        pace_vs_month = pct_done / month_progress_pct * 100 if month_progress_pct > 0 else 0
        if pace_vs_month < 70:
            bottlenecks.append(key)
        elif pace_vs_month >= 100:
            successes.append(key)

    monthly_ratio = monthly_on_track_count / len(monthly_kpi_keys)
    if monthly_ratio >= 0.7:
        monthly_status = "ON_TRACK"
        monthly_color = "#22c55e"
    elif monthly_ratio >= 0.4:
        monthly_status = "AT_RISK"
        monthly_color = "#eab308"
    else:
        monthly_status = "BEHIND"
        monthly_color = "#ef4444"

    # ボトルネック・成果のラベル
    label_map = {
        "posts": "公開記事数",
        "x_posts": "X投稿数",
        "index_requests": "インデックス申請",
        "rewrites": "リライト改善",
        "win_articles": "WIN記事",
        "ctr_actions": "CTR改善アクション",
    }
    top_bottleneck = "、".join(label_map.get(k, k) for k in bottlenecks[:2]) if bottlenecks else "なし（順調）"
    top_success = "、".join(label_map.get(k, k) for k in successes[:2]) if successes else "—"

    # 次に見るべきセクション
    next_sections = ["CA"]
    if daily_errors >= 1:
        next_sections.append("BG")
    if daily_posts_pct < 60:
        next_sections.append("BW")
    if daily_index_pct < 60:
        next_sections.append("BS")
    next_sections_str = " / ".join(next_sections)

    # 今打つべき1アクション
    if daily_errors >= 3:
        next_action = "🚨 kpi_errors.jsonlを確認し、エラー原因を即解消してください"
    elif daily_posts_pct < 40:
        next_action = "📝 記事パイプラインの遅れを確認し、run_daily_optimization.sh を実行確認してください"
    elif daily_index_pct < 40:
        next_action = "🔍 indexing_api_sends.jsonlを確認し、インデックス申請を追加実行してください"
    elif daily_x_pct < 40:
        next_action = "🐦 X投稿が遅れています。X投稿エージェントの状態を確認してください"
    elif monthly_status == "BEHIND":
        next_action = f"📅 月間KPIが遅延中。特に「{top_bottleneck}」の強化を検討してください"
    else:
        next_action = "✅ 現在の運用ペースを維持してください"

    return f"""<div class="section" id="cd-owner-summary" style="border:3px solid {today_status_color}66;border-radius:14px;padding:20px;margin-bottom:20px;background:linear-gradient(135deg,#0a1628,{'#1a0a0a' if today_status=='DANGER' else '#0a140a' if today_status=='GOOD' else '#141008'})">
  <div class="section-title" style="border-bottom-color:{today_status_color}33;margin-bottom:16px">
    <span class="section-title-icon">👑</span>
    <span style="color:{today_status_color};font-size:0.95rem;font-weight:900">CD. オーナー総合判断サマリー</span>
    <span style="margin-left:auto;background:{today_status_color}22;color:{today_status_color};border:2px solid {today_status_color}66;padding:4px 14px;border-radius:99px;font-size:0.8rem;font-weight:900">{today_status_label}</span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
    <div style="background:#0d1117;border:1px solid {today_status_color}33;border-radius:10px;padding:14px">
      <div style="font-size:0.72rem;color:#64748b;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.08em">今日の経営状態</div>
      <div style="font-size:1.4rem;font-weight:900;color:{today_status_color}">{today_status_label}</div>
      <div style="font-size:0.78rem;color:#94a3b8;margin-top:8px;line-height:1.6">{today_reason}</div>
    </div>
    <div style="background:#0d1117;border:1px solid {monthly_color}33;border-radius:10px;padding:14px">
      <div style="font-size:0.72rem;color:#64748b;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.08em">今月の進捗状態</div>
      <div style="font-size:1.4rem;font-weight:900;color:{monthly_color}">{monthly_status}</div>
      <div style="font-size:0.78rem;color:#94a3b8;margin-top:8px">
        {monthly_on_track_count}/{len(monthly_kpi_keys)} KPIが月末目標ペース以上
      </div>
    </div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px">
    <div style="background:#0d1117;border:1px solid #ef444433;border-radius:8px;padding:12px">
      <div style="font-size:0.7rem;color:#64748b;margin-bottom:4px">🔴 最大ボトルネック</div>
      <div style="font-size:0.85rem;color:#fca5a5;font-weight:700">{top_bottleneck}</div>
    </div>
    <div style="background:#0d1117;border:1px solid #22c55e33;border-radius:8px;padding:12px">
      <div style="font-size:0.7rem;color:#64748b;margin-bottom:4px">🏆 今日のトップ成果</div>
      <div style="font-size:0.85rem;color:#86efac;font-weight:700">{top_success if top_success != "—" else "まだ集計中"}</div>
    </div>
  </div>
  <div style="background:#0d1117;border:1px solid #818cf833;border-radius:8px;padding:12px;margin-bottom:12px">
    <div style="font-size:0.7rem;color:#64748b;margin-bottom:6px">🧭 次に見るべきセクション: <span style="color:#818cf8;font-weight:700">{next_sections_str}</span></div>
    <div style="font-size:0.85rem;color:#e2e8f0;font-weight:700;line-height:1.6">📌 今打つべき1アクション: {next_action}</div>
  </div>
  <div style="font-size:0.7rem;color:#475569;text-align:right">
    デイリー達成率: 📝{daily_posts_pct:.0f}% / 🐦{daily_x_pct:.0f}% / 🔍{daily_index_pct:.0f}% / ✏️{daily_rewrite_pct:.0f}%
  </div>
</div>"""

# ─── メイン: 全セクションを返す ─────────────────────────────
def build_kpi_sections(do_snapshot: bool = False) -> dict:
    """
    CA + CB + CC + CD の HTML を辞書で返す。
    keys: "cd_html", "ca_cb_cc_html"
    do_snapshot=True の場合は intraday スナップを追記し、monthly も保存する。
    """
    daily_targets = get_daily_targets()
    monthly_targets = get_monthly_targets()
    daily_actuals = collect_daily_actuals()
    monthly_actuals = collect_monthly_actuals()

    if do_snapshot:
        append_intraday_snapshot(daily_actuals, daily_targets)

    # Monthly projections
    today_date = datetime.now()
    projections = {}
    for key in ["posts", "x_posts", "index_requests", "rewrites", "win_articles", "ctr_actions"]:
        projections[key] = project_month_end(monthly_actuals.get(key, 0), today_date)

    if do_snapshot:
        save_monthly_snapshot(monthly_actuals, monthly_targets, projections)

    ca = build_ca_section(daily_actuals, daily_targets)
    cb = build_cb_section(monthly_actuals, monthly_targets)
    cc = build_cc_section()
    cd = build_cd_section(daily_actuals, daily_targets, monthly_actuals, monthly_targets)

    # dashboard_summary.json にKPIフィールドを追加
    _update_dashboard_summary(daily_actuals, daily_targets, monthly_actuals, monthly_targets)

    return {
        "cd_html": cd,
        "ca_cb_cc_html": f"{ca}\n{cb}\n{cc}",
    }

def _update_dashboard_summary(daily_actuals: dict, daily_targets: dict,
                               monthly_actuals: dict, monthly_targets: dict):
    """dashboard_summary.json にKPIフィールドを追加・更新する"""
    summary_path = BASE / "dashboard_summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    except Exception:
        summary = {}

    def _pct(act, tgt): return round(act / max(tgt, 1) * 100, 1)

    # Daily KPI
    summary["daily_kpi_status"] = "updated"
    for k in ["posts", "x_posts", "index_requests", "rewrites", "ctr_actions", "thumbnail_fixes"]:
        act = daily_actuals.get(k, 0)
        tgt = daily_targets.get(k, 1)
        summary[f"daily_{k}_target"] = tgt
        summary[f"daily_{k}_actual"] = act
        summary[f"daily_{k}_progress"] = _pct(act, tgt)
    summary["daily_error_actual"] = daily_actuals.get("errors", 0)

    # Monthly KPI
    today_date = datetime.now()
    summary["monthly_kpi_status"] = "updated"
    for k in ["posts", "x_posts", "index_requests", "rewrites", "win_articles", "ctr_actions"]:
        act = monthly_actuals.get(k, 0)
        tgt = monthly_targets.get(k, 1)
        proj = project_month_end(act, today_date)["projection"]
        summary[f"monthly_{k}_target"] = tgt
        summary[f"monthly_{k}_actual"] = act
        summary[f"monthly_{k}_progress"] = _pct(act, tgt)
        summary[f"monthly_{k}_projection"] = proj
    summary["monthly_error_rate"] = monthly_actuals.get("error_rate", 0)

    # Owner summary
    avg_daily = round((_pct(daily_actuals.get("posts",0), daily_targets.get("posts",1)) +
                       _pct(daily_actuals.get("x_posts",0), daily_targets.get("x_posts",1)) +
                       _pct(daily_actuals.get("rewrites",0), daily_targets.get("rewrites",1)) +
                       _pct(daily_actuals.get("index_requests",0), daily_targets.get("index_requests",1))) / 4, 1)
    daily_errors = daily_actuals.get("errors", 0)
    if daily_errors >= 3 and avg_daily < 40:
        status = "DANGER"
    elif daily_errors <= 1 and avg_daily >= 60:
        status = "GOOD"
    else:
        status = "WATCH"
    summary["owner_business_status"] = status
    summary["kpi_generated_at"] = datetime.now().isoformat()

    try:
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[kpi_dashboard_builder] dashboard_summary update error: {e}")


if __name__ == "__main__":
    # 単体テスト
    html = build_kpi_sections(do_snapshot=True)
    print(f"Generated KPI HTML: {len(html)} chars")
    print("Daily targets:", get_daily_targets())
    print("Daily actuals:", collect_daily_actuals())
    print("Monthly actuals:", collect_monthly_actuals())
