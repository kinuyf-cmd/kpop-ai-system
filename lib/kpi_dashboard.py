"""
KPI ダッシュボード生成モジュール
CEO Morning Brief / 日次会議で使用する KPI 集計・進捗レポートを生成する

出力:
  - generate_daily_kpi_block()  : 1日の目標 vs 実績 テーブル
  - generate_monthly_kpi_block(): 月間の目標 vs 実績 テーブル
  - generate_ultimate_progress(): 最終目標の進捗率
  - generate_full_dashboard()   : 全セクションまとめ（CEO Morning Brief 用）
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
BASE = Path("/home/aiuser/kpop-ai-system")
LOGS = BASE / "logs"
TARGETS_FILE = BASE / "config/kpi_targets.json"
METRICS_FILE = Path("/home/aiuser/google_metrics/metrics_yesterday.json")


# ──────────────────────────────────────────────
# 目標値ロード
# ──────────────────────────────────────────────
def load_targets() -> dict:
    if TARGETS_FILE.exists():
        return json.loads(TARGETS_FILE.read_text())
    return {}


# ──────────────────────────────────────────────
# 実績データ収集
# ──────────────────────────────────────────────
def collect_yesterday_actuals(yesterday_str: str) -> dict:
    """前日の実績値を各データソースから収集して返す"""
    actuals = {
        "sessions": None,
        "pageviews": None,
        "revenue_jpy": None,
        "rpm": None,
        "gsc_clicks": None,
        "avg_ctr": None,
        "avg_position": None,
        "articles_posted": 0,
        "x_posts": 0,
        "pipeline_uptime": None,
    }

    # ── GA4 / GSC / AdSense ──
    if METRICS_FILE.exists():
        try:
            m = json.loads(METRICS_FILE.read_text())
            ga4 = m.get("ga4", {}).get("summary", {})
            actuals["sessions"] = int(ga4.get("sessions", 0) or 0)
            actuals["pageviews"] = int(ga4.get("pageviews", 0) or 0)

            gsc = m.get("gsc", {})
            # top_pagesから合計クリック・CTR・掲載順位を計算
            top_pages = gsc.get("top_pages", [])
            top_queries = gsc.get("top_queries", [])
            all_pages = top_pages + top_queries
            if all_pages:
                total_clicks = sum(int(p.get("clicks", 0) or 0) for p in all_pages)
                total_imps = sum(int(p.get("impressions", 0) or 0) for p in all_pages)
                # top_pagesのみでクリック集計（queryとの重複を避ける）
                page_clicks = sum(int(p.get("clicks", 0) or 0) for p in top_pages)
                page_imps = sum(int(p.get("impressions", 0) or 0) for p in top_pages)
                actuals["gsc_clicks"] = page_clicks
                if page_imps > 0:
                    actuals["avg_ctr"] = round(page_clicks / page_imps * 100, 2)
                positions = [float(p.get("position", 0)) for p in top_pages if p.get("position")]
                if positions:
                    actuals["avg_position"] = round(sum(positions) / len(positions), 1)
            # フォールバック: 旧フォーマット
            if actuals["gsc_clicks"] is None:
                clicks_raw = gsc.get("clicks") or gsc.get("total_clicks")
                if clicks_raw is not None:
                    actuals["gsc_clicks"] = int(float(clicks_raw))

            ads = m.get("adsense", {})
            earn = ads.get("ESTIMATED_EARNINGS")
            if earn is not None:
                actuals["revenue_jpy"] = int(float(earn))
            rpm = ads.get("PAGE_VIEWS_RPM")
            if rpm is not None:
                actuals["rpm"] = int(float(rpm))
        except Exception:
            pass

    # ── 記事投稿数（kpi_posts.jsonl） ──
    # published_atがない場合はpost_idのWP作成日をAPIで確認する代わりに
    # ログファイルの更新日時から当日記録分をカウント
    kpi_path = LOGS / "kpi_posts.jsonl"
    if kpi_path.exists():
        count = 0
        # pipeline logの当日更新チェック
        for pl_log in [Path("/home/aiuser/ai_kpop.log"),
                       LOGS / "beauty_pipeline.log",
                       LOGS / "strategy_pipeline.log",
                       LOGS / "lifestyle_pipeline.log",
                       LOGS / "fashion_pipeline.log"]:
            if pl_log.exists():
                mtime = datetime.fromtimestamp(os.path.getmtime(pl_log), tz=JST)
                if mtime.strftime("%Y-%m-%d") == yesterday_str:
                    # ログに "投稿完了" or "POST_ID=" があればカウント
                    try:
                        txt = pl_log.read_text(errors="replace")
                        # 当日の投稿完了行を数える
                        import re as _re
                        count += len(_re.findall(r'POST_ID=\d+', txt))
                    except Exception:
                        pass
        actuals["articles_posted"] = min(count, 10)  # 上限10

    # ── X投稿数（x_post.log） ──
    x_log = LOGS / "x_post.log"
    if x_log.exists():
        ok_pattern = re.compile(r'\[(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2}\] RESULT: (?:投稿成功|フック投稿成功)')
        x_count = 0
        for line in x_log.read_text(errors="replace").splitlines():
            m2 = ok_pattern.search(line)
            if m2 and m2.group(1) == yesterday_str:
                x_count += 1
        actuals["x_posts"] = x_count

    # ── パイプライン稼働率（watchdog_repairs + pipeline logs） ──
    pipeline_logs = [
        (Path("/home/aiuser/ai_kpop.log"), "速報"),
        (LOGS / "beauty_pipeline.log", "美容"),
        (LOGS / "strategy_pipeline.log", "戦略"),
        (LOGS / "lifestyle_pipeline.log", "ライフスタイル"),
        (LOGS / "fashion_pipeline.log", "ファッション"),
    ]
    ok_pipes = 0
    total_pipes = len(pipeline_logs)
    yesterday_dt = datetime.strptime(yesterday_str, "%Y-%m-%d").replace(tzinfo=JST)
    for log_path, _ in pipeline_logs:
        if log_path.exists():
            mtime = datetime.fromtimestamp(os.path.getmtime(log_path), tz=JST)
            if (mtime - yesterday_dt).days == 0:
                ok_pipes += 1
    if total_pipes > 0:
        actuals["pipeline_uptime"] = round(ok_pipes / total_pipes * 100)

    return actuals


def collect_monthly_actuals(year: int, month: int) -> dict:
    """当月累計の実績値を集計して返す"""
    now = datetime.now(JST)
    month_str = f"{year:04d}-{month:02d}"
    days_elapsed = now.day

    actuals = {
        "sessions": None,
        "pageviews": None,
        "revenue_jpy": None,
        "articles_total": None,
        "x_posts": 0,
        "gsc_clicks": None,
        "pipeline_uptime": None,
        "avg_position": None,
        "_days_elapsed": days_elapsed,
    }

    # GA4/AdSense月間推計（前日実績×経過日数）
    if METRICS_FILE.exists():
        try:
            m = json.loads(METRICS_FILE.read_text())
            ga4 = m.get("ga4", {}).get("summary", {})
            sess_day = int(ga4.get("sessions", 0) or 0)
            pv_day = int(ga4.get("pageviews", 0) or 0)
            actuals["sessions"] = sess_day * days_elapsed
            actuals["pageviews"] = pv_day * days_elapsed

            ads = m.get("adsense", {})
            earn = ads.get("ESTIMATED_EARNINGS")
            if earn is not None:
                actuals["revenue_jpy"] = int(float(earn)) * days_elapsed

            gsc = m.get("gsc", {})
            clicks_day = int(float(gsc.get("clicks", 0) or 0))
            actuals["gsc_clicks"] = clicks_day * days_elapsed

            pos_raw = gsc.get("position")
            if pos_raw is not None:
                actuals["avg_position"] = round(float(pos_raw), 1)
        except Exception:
            pass

    # 記事総数（kpi_posts.jsonl 全件 — published_at有無に関係なく有効行を計上）
    kpi_path = LOGS / "kpi_posts.jsonl"
    if kpi_path.exists():
        total = 0
        seen_ids = set()
        for line in kpi_path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                pid = str(r.get("post_id", ""))
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    total += 1
            except Exception:
                pass
        actuals["articles_total"] = total

    # X投稿月間（x_post.log）
    x_log = LOGS / "x_post.log"
    if x_log.exists():
        ok_pattern = re.compile(r'\[(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2}\] RESULT: (?:投稿成功|フック投稿成功)')
        x_count = 0
        for line in x_log.read_text(errors="replace").splitlines():
            m2 = ok_pattern.search(line)
            if m2 and m2.group(1).startswith(month_str):
                x_count += 1
        actuals["x_posts"] = x_count

    return actuals


# ──────────────────────────────────────────────
# ビジュアル表示ヘルパー
# ──────────────────────────────────────────────
def _bar(pct: float, width: int = 12) -> str:
    """進捗バー。0-100%をビジュアル化"""
    pct = min(pct, 150)  # 150%でキャップ
    filled = round(pct / 100 * width)
    filled = min(filled, width)
    return "█" * filled + "░" * (width - filled)


def _status_icon(pct: float) -> str:
    if pct >= 100: return "✅"
    if pct >= 70:  return "🟡"
    if pct >= 40:  return "🟠"
    return "🔴"


def _fmt_val(val, unit: str) -> str:
    if val is None:
        return "---"
    if unit in ("%",):
        return f"{val:.1f}%"
    if "円" in unit:
        if val >= 10000:
            return f"¥{val:,}"
        return f"¥{val}"
    if "位" in unit:
        return f"{val:.1f}位"
    if isinstance(val, float):
        return f"{val:.1f}"
    return f"{val:,}"


def _progress_row(label: str, actual, target: float, unit: str, width: int = 55) -> str:
    if actual is None:
        pct = 0.0
        actual_str = "未取得"
        bar = "░" * 12
        icon = "⬜"
    else:
        pct = actual / target * 100 if target else 0
        actual_str = _fmt_val(actual, unit)
        bar = _bar(pct)
        icon = _status_icon(pct)

    target_str = _fmt_val(target, unit)
    pct_str = f"{pct:.0f}%" if actual is not None else "---"

    return (
        f"  {icon} {label:<16} {actual_str:>8} / {target_str:<8} "
        f"[{bar}] {pct_str:>5}"
    )


# ──────────────────────────────────────────────
# セクション生成
# ──────────────────────────────────────────────
def generate_daily_kpi_block(actuals: dict, targets: dict, date_label: str) -> str:
    dt = targets.get("daily", {})
    lines = [
        f"┌─────────────────────────────────────────────────────────────────┐",
        f"│  📊 デイリーKPI — {date_label}                                       │",
        f"├──────────────┬──────────┬──────────┬──────────────┬─────────────┤",
        f"│  指標         │  実績     │  目標     │  達成率       │  進捗       │",
        f"├──────────────┼──────────┼──────────┼──────────────┼─────────────┤",
    ]

    metrics = [
        ("セッション",      actuals.get("sessions"),        dt.get("sessions",{}).get("target",500),    "セッション"),
        ("PV",              actuals.get("pageviews"),        dt.get("pageviews",{}).get("target",700),   "PV"),
        ("収益",            actuals.get("revenue_jpy"),      dt.get("revenue_jpy",{}).get("target",200), "円"),
        ("GSCクリック",     actuals.get("gsc_clicks"),       dt.get("gsc_clicks",{}).get("target",50),   "クリック"),
        ("平均CTR",         actuals.get("avg_ctr"),          dt.get("avg_ctr",{}).get("target",3.0),     "%"),
        ("RPM",             actuals.get("rpm"),              dt.get("rpm",{}).get("target",400),         "円"),
        ("記事投稿",         actuals.get("articles_posted"), dt.get("articles_posted",{}).get("target",5),"本"),
        ("X投稿",           actuals.get("x_posts"),          dt.get("x_posts",{}).get("target",4),       "件"),
        ("PL稼働率",         actuals.get("pipeline_uptime"), dt.get("pipeline_uptime",{}).get("target",95),"%"),
    ]

    for label, actual, target, unit in metrics:
        if actual is None:
            pct_str = "---"
            bar = "░" * 10
            icon = "⬜"
            actual_str = "未取得"
        else:
            pct = actual / target * 100 if target else 0
            pct_str = f"{min(pct,999):.0f}%"
            bar = _bar(pct, 10)
            icon = _status_icon(pct)
            actual_str = _fmt_val(actual, unit)
        target_str = _fmt_val(target, unit)
        lines.append(
            f"│  {icon} {label:<11}│ {actual_str:>8} │ {target_str:>8} │ {pct_str:>10}   │ {bar}  │"
        )

    lines.append(f"└──────────────┴──────────┴──────────┴──────────────┴─────────────┘")
    return "\n".join(lines)


def generate_monthly_kpi_block(actuals: dict, targets: dict, year: int, month: int) -> str:
    mt = targets.get("monthly", {})
    days_elapsed = actuals.get("_days_elapsed", 1)
    days_in_month = 30
    month_progress_pct = days_elapsed / days_in_month * 100

    lines = [
        f"┌─────────────────────────────────────────────────────────────────┐",
        f"│  📅 月次KPI — {year}年{month}月 ({days_elapsed}日経過/{days_in_month}日, {month_progress_pct:.0f}%)    │",
        f"├──────────────┬──────────┬──────────┬──────────────┬─────────────┤",
        f"│  指標         │  実績     │  月目標   │  達成率       │  進捗       │",
        f"├──────────────┼──────────┼──────────┼──────────────┼─────────────┤",
    ]

    metrics = [
        ("セッション",   actuals.get("sessions"),       mt.get("sessions",{}).get("target",15000),     "セッション"),
        ("PV",           actuals.get("pageviews"),       mt.get("pageviews",{}).get("target",21000),    "PV"),
        ("収益",         actuals.get("revenue_jpy"),     mt.get("revenue_jpy",{}).get("target",6000),   "円"),
        ("GSCクリック",  actuals.get("gsc_clicks"),      mt.get("gsc_clicks",{}).get("target",1500),    "クリック"),
        ("累計記事数",   actuals.get("articles_total"),  mt.get("articles_total",{}).get("target",150), "本"),
        ("X投稿",        actuals.get("x_posts"),         mt.get("x_posts",{}).get("target",120),        "件"),
        ("平均掲載順位", actuals.get("avg_position"),    mt.get("avg_position",{}).get("target",15),    "位"),
    ]

    for label, actual, target, unit in metrics:
        if actual is None:
            pct_str = "---"
            bar = "░" * 10
            icon = "⬜"
            actual_str = "未取得"
        else:
            # 掲載順位は低いほど良い（逆転）
            if unit == "位":
                pct = (target / actual * 100) if actual else 0
            else:
                pct = actual / target * 100 if target else 0
            pct_str = f"{min(pct,999):.0f}%"
            bar = _bar(pct, 10)
            icon = _status_icon(pct)
            actual_str = _fmt_val(actual, unit)
        target_str = _fmt_val(target, unit)
        lines.append(
            f"│  {icon} {label:<11}│ {actual_str:>8} │ {target_str:>8} │ {pct_str:>10}   │ {bar}  │"
        )

    lines.append(f"└──────────────┴──────────┴──────────┴──────────────┴─────────────┘")
    return "\n".join(lines)


def generate_ultimate_progress(monthly_actuals: dict, targets: dict) -> str:
    ut = targets.get("ultimate", {})
    lines = [
        f"┌─────────────────────────────────────────────────────────────────┐",
        f"│  🎯 最終目標進捗 — Q2末(2026年6月末)ロードマップ                  │",
        f"├──────────────┬──────────┬──────────┬──────────────┬─────────────┤",
        f"│  指標         │  現在値   │  最終目標  │  進捗率       │  残り        │",
        f"├──────────────┼──────────┼──────────┼──────────────┼─────────────┤",
    ]

    # 最終目標 vs 月次推計（月次ペースから換算）
    metrics = [
        ("セッション/日",  monthly_actuals.get("sessions", 0) / max(monthly_actuals.get("_days_elapsed",1),1),
                           ut.get("sessions",{}).get("target",3000), "セッション"),
        ("月間収益",       monthly_actuals.get("revenue_jpy"),
                           ut.get("revenue_jpy",{}).get("target",30000), "円"),
        ("累計記事数",     monthly_actuals.get("articles_total"),
                           ut.get("articles_total",{}).get("target",500), "本"),
        ("RPM",            None, ut.get("rpm",{}).get("target",500), "円"),  # 別途取得
        ("平均掲載順位",   monthly_actuals.get("avg_position"),
                           ut.get("avg_position",{}).get("target",10), "位"),
    ]

    for label, actual, target, unit in metrics:
        if actual is None:
            pct_str = "---"
            bar = "░" * 10
            icon = "⬜"
            actual_str = "未取得"
            remain_str = "---"
        else:
            if unit == "位":
                pct = (target / actual * 100) if actual else 0
                remain_str = f"あと{actual - target:.1f}位改善"
            else:
                pct = actual / target * 100 if target else 0
                remain = target - actual
                remain_str = f"あと{_fmt_val(remain, unit)}"
            pct_str = f"{min(pct,999):.0f}%"
            bar = _bar(pct, 10)
            icon = _status_icon(pct)
            actual_str = _fmt_val(actual, unit)

        target_str = _fmt_val(target, unit)
        lines.append(
            f"│  {icon} {label:<11}│ {actual_str:>8} │ {target_str:>8} │ {pct_str:>10}   │ {remain_str:<11} │"
        )

    lines.append(f"└──────────────┴──────────┴──────────┴──────────────┴─────────────┘")
    return "\n".join(lines)


def generate_alert_block(daily_actuals: dict, targets: dict) -> str:
    """KPI達成率70%未満の項目をアラートとして列挙"""
    dt = targets.get("daily", {})
    alerts = []
    checks = [
        ("セッション",  daily_actuals.get("sessions"),       dt.get("sessions",{}).get("target",500)),
        ("収益",         daily_actuals.get("revenue_jpy"),     dt.get("revenue_jpy",{}).get("target",200)),
        ("GSCクリック",  daily_actuals.get("gsc_clicks"),      dt.get("gsc_clicks",{}).get("target",50)),
        ("記事投稿",     daily_actuals.get("articles_posted"), dt.get("articles_posted",{}).get("target",5)),
        ("X投稿",        daily_actuals.get("x_posts"),         dt.get("x_posts",{}).get("target",4)),
        ("PL稼働率",     daily_actuals.get("pipeline_uptime"), dt.get("pipeline_uptime",{}).get("target",95)),
    ]
    for label, val, target in checks:
        if val is None:
            continue
        pct = val / target * 100 if target else 0
        if pct < 70:
            alerts.append(f"  ⚠ {label}: 目標比 {pct:.0f}% ({_fmt_val(val, '')} / {_fmt_val(target, '')})")

    if not alerts:
        return "  ✅ 全指標が目標の70%以上を達成しています"
    return "\n".join(alerts)


# ──────────────────────────────────────────────
# メイン: フルダッシュボード生成
# ──────────────────────────────────────────────
def generate_full_dashboard() -> str:
    now = datetime.now(JST)
    yesterday = now - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    yesterday_label = yesterday.strftime("%Y年%m月%d日")

    targets = load_targets()
    daily_actuals = collect_yesterday_actuals(yesterday_str)
    monthly_actuals = collect_monthly_actuals(now.year, now.month)

    sections = []

    # ヘッダー
    sections.append(
        f"╔═══════════════════════════════════════════════════════════════════╗\n"
        f"║       📋  CEO MORNING BRIEF  —  {now.strftime('%Y年%m月%d日')} ({_weekday_jp(now.weekday())})  ║\n"
        f"║              KPOP JOURNAL  経営ダッシュボード                      ║\n"
        f"╚═══════════════════════════════════════════════════════════════════╝"
    )

    # デイリーKPI
    sections.append(generate_daily_kpi_block(daily_actuals, targets, yesterday_label))

    # 月次KPI
    sections.append(generate_monthly_kpi_block(monthly_actuals, targets, now.year, now.month))

    # 最終目標進捗
    sections.append(generate_ultimate_progress(monthly_actuals, targets))

    # アラート
    alert_body = generate_alert_block(daily_actuals, targets)
    sections.append(
        f"┌─────────────────────────────────────────────────────────────────┐\n"
        f"│  🚨 要対応アラート（目標比70%未満）                               │\n"
        f"├─────────────────────────────────────────────────────────────────┤\n"
        + "\n".join(f"│{line:<67}│" for line in alert_body.splitlines()) + "\n"
        f"└─────────────────────────────────────────────────────────────────┘"
    )

    return "\n\n".join(sections)


def _weekday_jp(wd: int) -> str:
    return ["月", "火", "水", "木", "金", "土", "日"][wd]


if __name__ == "__main__":
    print(generate_full_dashboard())
