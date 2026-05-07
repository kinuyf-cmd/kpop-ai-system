"""
KPI ダッシュボード生成モジュール
CEO Morning Brief / 日次会議で使用する KPI 集計・進捗レポートを生成する

出力:
  - generate_daily_kpi_block()  : 1日の目標 vs 実績 テーブル
  - generate_monthly_kpi_block(): 月間の目標 vs 実績 テーブル
  - generate_ultimate_progress(): 最終目標の進捗率
  - generate_full_dashboard()   : 全セクションまとめ（CEO Morning Brief 用）

データソース (2026-05-07 監査・根治):
  - 記事投稿: logs/unified_publish.jsonl の success:true 件数 (旧: pipeline log POST_ID + min(count,10) cap)
  - X投稿  : logs/x_posts.jsonl の status='ok' 件数 (旧: x_post.log RESULT行)
  - PL稼働 : 下記 PIPELINES_REGISTRY のみが母数。lifestyle/fashion/ai_meeting/chart/weekly_review は廃止のため除外
  - GSC     : metrics_yesterday.json gsc.sitewide.clicks 優先、無ければ gsc.clicks フォールバック
  - 古データ: metrics_yesterday.json の date が yesterday と一致しない場合は警告 (generate_full_dashboard)
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

# 現役パイプライン母数 (crontab確認済 / 過去7日以内mtime更新あり)。
# 廃止: lifestyle_pipeline.log, fashion_pipeline.log, ai_meeting.log,
#       chart_pipeline.log, weekly_review.log は2026-05時点でcron無し。
PIPELINES_REGISTRY = [
    (Path("/home/aiuser/ai_kpop.log"),                "07:00 速報パイプライン"),
    (LOGS / "beauty_pipeline.log",                    "11:00 美容・コスメ"),
    (LOGS / "strategy_pipeline.log",                  "12:00 戦略・資産記事"),
    (LOGS / "morning_brief.log",                      "09:00 CEOブリーフ"),
    (LOGS / "post_publish_enricher.log",              "記事公開エンリッチャー"),
    (LOGS / "post_audit_feedback_loop.log",           "記事監査フィードバックループ"),
    (LOGS / "breaking_news.log",                      "速報ニュース検知"),
    (LOGS / "x_scheduled.log",                        "X投稿スケジューラー"),
]


def _count_unified_publish_success(date_prefix: str) -> int:
    """unified_publish.jsonl の success:true 件数を ts プレフィックス一致で返す"""
    p = LOGS / "unified_publish.jsonl"
    if not p.exists():
        return 0
    n = 0
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("success") is True and str(r.get("ts", "")).startswith(date_prefix):
            n += 1
    return n


def _count_x_posts_ok(date_prefix: str) -> int:
    """x_posts.jsonl の status='ok' 件数を ts プレフィックス一致で返す"""
    p = LOGS / "x_posts.jsonl"
    if not p.exists():
        return 0
    n = 0
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("status") == "ok" and str(r.get("ts", "")).startswith(date_prefix):
            n += 1
    return n


def metrics_data_freshness(yesterday_str: str) -> dict:
    """metrics_yesterday.json と AdSense の鮮度を返す。古ければ警告に使う"""
    info = {"metrics_date": None, "is_stale": True, "adsense_status": "unknown"}
    if not METRICS_FILE.exists():
        return info
    try:
        m = json.loads(METRICS_FILE.read_text())
        info["metrics_date"] = m.get("date")
        info["is_stale"] = (m.get("date") != yesterday_str)
        ads = m.get("adsense", {})
        if isinstance(ads, dict):
            if ads.get("error"):
                info["adsense_status"] = "error"
                info["adsense_error"] = str(ads.get("error", ""))[:120]
            elif ads.get("ESTIMATED_EARNINGS") is not None:
                info["adsense_status"] = "ok"
    except Exception as e:
        info["error"] = str(e)
    return info


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
            # 新フォーマット (sitewide) 優先、旧フォーマットへフォールバック
            sw = gsc.get("sitewide") or {}
            if sw.get("clicks") is not None:
                actuals["gsc_clicks"] = int(float(sw.get("clicks") or 0))
                if sw.get("ctr") is not None:
                    actuals["avg_ctr"] = round(float(sw.get("ctr")) * 100, 2)
                if sw.get("position") is not None:
                    actuals["avg_position"] = round(float(sw.get("position")), 1)
            else:
                # 旧フォーマット: top_pages集計 (sitewide欠落時のみ)
                top_pages = gsc.get("top_pages", [])
                if top_pages:
                    page_clicks = sum(int(p.get("clicks", 0) or 0) for p in top_pages)
                    page_imps = sum(int(p.get("impressions", 0) or 0) for p in top_pages)
                    actuals["gsc_clicks"] = page_clicks
                    if page_imps > 0:
                        actuals["avg_ctr"] = round(page_clicks / page_imps * 100, 2)
                    positions = [float(p.get("position", 0)) for p in top_pages if p.get("position")]
                    if positions:
                        actuals["avg_position"] = round(sum(positions) / len(positions), 1)
                clicks_raw = gsc.get("clicks") or gsc.get("total_clicks")
                if actuals["gsc_clicks"] is None and clicks_raw is not None:
                    actuals["gsc_clicks"] = int(float(clicks_raw))

            ads = m.get("adsense", {})
            # AdSense は token 失効等で error フィールドが入る場合がある
            earn = ads.get("ESTIMATED_EARNINGS") if isinstance(ads, dict) else None
            if earn is not None:
                actuals["revenue_jpy"] = int(float(earn))
            rpm = ads.get("PAGE_VIEWS_RPM") if isinstance(ads, dict) else None
            if rpm is not None:
                actuals["rpm"] = int(float(rpm))
        except Exception:
            pass

    # ── 記事投稿数: unified_publish.jsonl の success:true (cap撤廃、真値) ──
    actuals["articles_posted"] = _count_unified_publish_success(yesterday_str)

    # ── X投稿数: x_posts.jsonl の status='ok' (旧 x_post.log 廃止) ──
    actuals["x_posts"] = _count_x_posts_ok(yesterday_str)

    # ── パイプライン稼働率: 現役 PIPELINES_REGISTRY のみ母数 ──
    # 判定: yesterday 0:00 ~ now の26時間以内にmtime更新があれば稼働扱い。
    # これは「常時稼働ログ (post_publish_enricher等) は今日にmtimeが付くため
    # yesterday完全一致だと落ちる」問題への対応。日次バッチログも前日中の更新が拾える。
    now = datetime.now(JST)
    yesterday_start = datetime.strptime(yesterday_str, "%Y-%m-%d").replace(tzinfo=JST)
    ok_pipes = 0
    total_pipes = len(PIPELINES_REGISTRY)
    for log_path, _ in PIPELINES_REGISTRY:
        if log_path.exists():
            mtime = datetime.fromtimestamp(os.path.getmtime(log_path), tz=JST)
            if mtime >= yesterday_start and mtime <= now:
                ok_pipes += 1
    if total_pipes > 0:
        actuals["pipeline_uptime"] = round(ok_pipes / total_pipes * 100)

    return actuals


def collect_monthly_actuals(year: int, month: int) -> dict:
    """当月累計の実績値を集計して返す。
    数字は実累計のみ。GA4/AdSense は1日値しか metrics_yesterday.json に無いため
    現状は当月実累計が取れない指標 (sessions/pageviews/revenue) は推計表記とせず
    Noneのまま返す (=表示は '未取得')。実累計が必要なら別途日次積み上げログが要る。
    """
    now = datetime.now(JST)
    month_str = f"{year:04d}-{month:02d}"
    days_elapsed = now.day

    actuals = {
        "sessions": None,         # 当月実累計の集計ソース未整備のためNone
        "pageviews": None,
        "revenue_jpy": None,
        "articles_total": None,
        "x_posts": 0,
        "gsc_clicks": None,
        "pipeline_uptime": None,
        "avg_position": None,
        "_days_elapsed": days_elapsed,
    }

    # 平均掲載順位は最新値を表示 (新フォーマット sitewide.position)
    if METRICS_FILE.exists():
        try:
            m = json.loads(METRICS_FILE.read_text())
            gsc = m.get("gsc", {})
            sw = gsc.get("sitewide") or {}
            pos_raw = sw.get("position", gsc.get("position"))
            if pos_raw is not None:
                actuals["avg_position"] = round(float(pos_raw), 1)
        except Exception:
            pass

    # 記事総数: 当月の unified_publish.jsonl success:true 件数 (旧: kpi_posts.jsonl 全期間累計はバグ)
    actuals["articles_total"] = _count_unified_publish_success(month_str)

    # X投稿月間: x_posts.jsonl の status='ok' 当月分
    actuals["x_posts"] = _count_x_posts_ok(month_str)

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
def generate_daily_kpi_block(actuals: dict, targets: dict, date_label: str, stale: bool = False) -> str:
    dt = targets.get("daily", {})
    header_inner = f"📊 デイリーKPI — {date_label}" + (" ⚠️ 古データ" if stale else "")
    lines = [
        f"┌─────────────────────────────────────────────────────────────────┐",
        f"│  {header_inner:<63}│",
        f"├──────────────┬──────────┬──────────┬──────────────┬─────────────┤",
        f"│  指標         │  実績     │  目標     │  達成率       │  進捗       │",
        f"├──────────────┼──────────┼──────────┼──────────────┼─────────────┤",
    ]

    # GA4/AdSense/GSC指標は metrics_yesterday.json 由来のため stale 影響を受ける
    stale_flagged = {"セッション", "PV", "収益", "GSCクリック", "平均CTR", "RPM"}

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
        label_disp = f"{label}*" if (stale and label in stale_flagged and actual is not None) else label
        lines.append(
            f"│  {icon} {label_disp:<11}│ {actual_str:>8} │ {target_str:>8} │ {pct_str:>10}   │ {bar}  │"
        )

    if stale:
        lines.append(f"│  * 印は古データソース由来 (metrics_yesterday.json date不一致)")

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

    # セッション/日: 月次累計を集計していないため、最新日次値 (collect_yesterday_actuals) を参照したいが
    # ここでは monthly_actuals から取り出す経路がないため None で表示
    sess_per_day = None
    if monthly_actuals.get("sessions") is not None:
        days = max(monthly_actuals.get("_days_elapsed", 1), 1)
        sess_per_day = monthly_actuals["sessions"] / days

    metrics = [
        ("セッション/日",  sess_per_day,
                           ut.get("sessions",{}).get("target",3000), "セッション"),
        ("月間収益",       monthly_actuals.get("revenue_jpy"),
                           ut.get("revenue_jpy",{}).get("target",30000), "円"),
        ("累計記事数",     monthly_actuals.get("articles_total"),
                           ut.get("articles_total",{}).get("target",500), "本"),
        ("RPM",            None, ut.get("rpm",{}).get("target",500), "円"),
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
    freshness = metrics_data_freshness(yesterday_str)

    sections = []

    # ヘッダー
    sections.append(
        f"╔═══════════════════════════════════════════════════════════════════╗\n"
        f"║       📋  CEO MORNING BRIEF  —  {now.strftime('%Y年%m月%d日')} ({_weekday_jp(now.weekday())})  ║\n"
        f"║              KPOP JOURNAL  経営ダッシュボード                      ║\n"
        f"╚═══════════════════════════════════════════════════════════════════╝"
    )

    # データ鮮度警告
    warn_lines = []
    if freshness.get("is_stale"):
        md = freshness.get("metrics_date") or "未取得"
        warn_lines.append(
            f"⚠️ GA4/GSC/AdSense データが古いか欠落: metrics_yesterday.json date={md} "
            f"(期待: {yesterday_str})。下記KPIのうち sessions/PV/収益/RPM/GSC は (古データ) 表示"
        )
    if freshness.get("adsense_status") == "error":
        warn_lines.append(
            f"⚠️ AdSense API エラー (token失効の可能性): {freshness.get('adsense_error','')}"
        )
    if warn_lines:
        sections.append("\n".join(warn_lines))

    # デイリーKPI
    sections.append(generate_daily_kpi_block(daily_actuals, targets, yesterday_label, stale=freshness.get("is_stale")))

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
