#!/usr/bin/env python3
"""
kpi_store.py — 統合KPIストア
GSC + GA4 + AdSense を統合した日次/記事別 JSONL を生成・管理。

出力ファイル:
  logs/kpi_daily.jsonl    — 日次サイト全体KPI (1行/日)
  logs/kpi_articles.jsonl — 記事別KPI (N行/日, 日付+URL がキー)

使い方:
  python3 lib/kpi_store.py collect          # 全ソース収集 → JSONL追記
  python3 lib/kpi_store.py query daily 7    # 直近7日の日次KPI
  python3 lib/kpi_store.py query articles 7 # 直近7日の記事別KPI (top50)
  python3 lib/kpi_store.py backfill         # 既存JSONから過去データ取り込み
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
GMETRICS = BASE / "google_metrics"

KPI_DAILY = LOGS / "kpi_daily.jsonl"
KPI_ARTICLES = LOGS / "kpi_articles.jsonl"

SA_FILE = GMETRICS / "service_account.json"
ADSENSE_TOKEN_FILE = GMETRICS / "oauth_token.json"
ADSENSE_CLIENT_SECRET = GMETRICS / "adsense_client_secret.json"
ARTICLE_INDEX = LOGS / "article_index.json"

GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "493983919")
GSC_SITE_URL = os.environ.get("GSC_SITE_URL", "https://www.kpopjournal.tokyo/")
ADSENSE_ACCOUNT = os.environ.get("ADSENSE_ACCOUNT_NAME", "accounts/pub-5968839599715792")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# JSONL ヘルパー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _append_jsonl(path: Path, record: dict):
    path.parent.mkdir(exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path, days: int | None = None) -> list[dict]:
    if not path.exists():
        return []
    cutoff = (date.today() - timedelta(days=days)).isoformat() if days else None
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if cutoff and rec.get("date", "") < cutoff:
                continue
            records.append(rec)
    return records


def _date_exists(path: Path, target_date: str) -> bool:
    """指定日のレコードが既に存在するか"""
    if not path.exists():
        return False
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line.strip())
                if rec.get("date") == target_date:
                    return True
            except (json.JSONDecodeError, KeyError):
                continue
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# データソース: GSC
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _collect_gsc(days: int = 7) -> dict:
    """GSC page別メトリクスを取得して site合計 + 記事別 を返す"""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        return {"error": "google-api not installed"}

    if not SA_FILE.exists():
        return {"error": f"service_account.json not found: {SA_FILE}"}

    creds = service_account.Credentials.from_service_account_file(
        str(SA_FILE), scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
    )
    service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)

    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days - 1)

    all_rows = []
    start_row = 0
    while True:
        body = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": ["page"],
            "rowLimit": 5000,
            "startRow": start_row,
        }
        try:
            res = service.searchanalytics().query(siteUrl=GSC_SITE_URL, body=body).execute()
        except Exception as e:
            return {"error": str(e)}
        rows = res.get("rows", [])
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < 5000:
            break
        start_row += 5000

    articles = []
    total_imp, total_clk = 0, 0
    for r in all_rows:
        url = r.get("keys", [""])[0]
        imp = int(r.get("impressions", 0))
        clk = int(r.get("clicks", 0))
        total_imp += imp
        total_clk += clk
        articles.append({
            "url": url,
            "gsc_impressions": imp,
            "gsc_clicks": clk,
            "gsc_ctr": round(float(r.get("ctr", 0)), 6),
            "gsc_position": round(float(r.get("position", 0)), 2),
        })

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "summary": {
            "gsc_impressions": total_imp,
            "gsc_clicks": total_clk,
            "gsc_ctr": round(total_clk / max(total_imp, 1), 6),
            "gsc_pages": len(articles),
        },
        "articles": articles,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# データソース: GA4
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _collect_ga4(days: int = 1) -> dict:
    """GA4 page別PV/セッションを取得"""
    try:
        from google.oauth2 import service_account as sa
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
    except ImportError:
        return {"error": "google-analytics-data not installed"}

    if not SA_FILE.exists():
        return {"error": f"service_account.json not found: {SA_FILE}"}

    creds = sa.Credentials.from_service_account_file(
        str(SA_FILE), scopes=["https://www.googleapis.com/auth/analytics.readonly"]
    )
    client = BetaAnalyticsDataClient(credentials=creds)

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)

    # サイト全体サマリー
    summary_req = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        metrics=[
            Metric(name="screenPageViews"),
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="engagedSessions"),
            Metric(name="averageSessionDuration"),
            Metric(name="bounceRate"),
        ],
        date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
    )
    try:
        sres = client.run_report(summary_req)
        srow = sres.rows[0] if sres.rows else None
    except Exception as e:
        return {"error": str(e)}

    summary = {}
    if srow:
        summary = {
            "ga4_pageviews": int(srow.metric_values[0].value),
            "ga4_sessions": int(srow.metric_values[1].value),
            "ga4_users": int(srow.metric_values[2].value),
            "ga4_engaged_sessions": int(srow.metric_values[3].value),
            "ga4_avg_duration": round(float(srow.metric_values[4].value), 1),
            "ga4_bounce_rate": round(float(srow.metric_values[5].value), 4),
        }

    # ページ別
    page_req = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        dimensions=[Dimension(name="pagePath")],
        metrics=[
            Metric(name="screenPageViews"),
            Metric(name="sessions"),
            Metric(name="averageSessionDuration"),
            Metric(name="bounceRate"),
        ],
        date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
        limit=500,
    )
    try:
        pres = client.run_report(page_req)
    except Exception as e:
        return {"summary": summary, "articles": [], "error_articles": str(e)}

    articles = []
    for row in pres.rows:
        path = row.dimension_values[0].value
        articles.append({
            "path": path,
            "url": GSC_SITE_URL.rstrip("/") + path,
            "ga4_pageviews": int(row.metric_values[0].value),
            "ga4_sessions": int(row.metric_values[1].value),
            "ga4_avg_duration": round(float(row.metric_values[2].value), 1),
            "ga4_bounce_rate": round(float(row.metric_values[3].value), 4),
        })

    # トラフィックソース（X流入計測用 + 全ソース記録）
    x_sessions = 0
    traffic_sources = {}
    try:
        src_req = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            dimensions=[Dimension(name="sessionSource")],
            metrics=[Metric(name="sessions"), Metric(name="engagedSessions")],
            date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
        )
        src_res = client.run_report(src_req)
        for row in src_res.rows:
            src = row.dimension_values[0].value
            sess = int(row.metric_values[0].value)
            engaged = int(row.metric_values[1].value)
            if src in ("t.co", "x.com", "twitter.com"):
                x_sessions += sess
            traffic_sources[src] = {"sessions": sess, "engaged": engaged}
    except Exception:
        pass
    summary["ga4_x_sessions"] = x_sessions
    summary["ga4_traffic_sources"] = traffic_sources

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "summary": summary,
        "articles": articles,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# データソース: AdSense
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _get_adsense_creds():
    """AdSense OAuth2 credential を取得 (token refresh 対応)"""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    scopes = ["https://www.googleapis.com/auth/adsense.readonly"]
    creds = None
    if ADSENSE_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(ADSENSE_TOKEN_FILE), scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                ADSENSE_TOKEN_FILE.write_text(creds.to_json())
            except Exception as e:
                err_msg = str(e)
                print(f"⚠️ AdSense token refresh失敗: {err_msg}")
                if 'invalid_grant' in err_msg:
                    print("❌ refresh_tokenが失効しています。Google Cloud Consoleで")
                    print("   OAuth同意画面を「Testing」→「本番」に変更し、再認証してください:")
                    print("   python3 tools/oauth_exchange.py --auth-url")
                return None
        else:
            return None  # 再認証が必要 — バッチでは不可
    return creds


def _collect_adsense_daily() -> dict:
    """AdSense 日次サイト全体の収益を取得"""
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return {"error": "googleapiclient not installed"}

    creds = _get_adsense_creds()
    if not creds:
        return {"error": "adsense token expired — manual re-auth required"}

    service = build("adsense", "v2", credentials=creds, cache_discovery=False)
    yesterday = date.today() - timedelta(days=1)

    try:
        report = service.accounts().reports().generate(
            account=ADSENSE_ACCOUNT,
            dateRange="CUSTOM",
            startDate_year=yesterday.year,
            startDate_month=yesterday.month,
            startDate_day=yesterday.day,
            endDate_year=yesterday.year,
            endDate_month=yesterday.month,
            endDate_day=yesterday.day,
            metrics=["ESTIMATED_EARNINGS", "PAGE_VIEWS", "IMPRESSIONS", "CLICKS", "PAGE_VIEWS_RPM"],
        ).execute()
    except Exception as e:
        return {"error": str(e)[:300]}

    headers = [h["name"] for h in report.get("headers", [])]
    rows = report.get("rows", [])
    cells = rows[0]["cells"] if rows else []
    mapped = {h: c.get("value") for h, c in zip(headers, cells)}

    earnings = float(mapped.get("ESTIMATED_EARNINGS", 0))
    pv = int(mapped.get("PAGE_VIEWS", 0))
    imp = int(mapped.get("IMPRESSIONS", 0))
    clk = int(mapped.get("CLICKS", 0))
    rpm = float(mapped.get("PAGE_VIEWS_RPM", 0))

    return {
        "date": yesterday.isoformat(),
        "summary": {
            "adsense_earnings_jpy": round(earnings, 2),
            "adsense_pageviews": pv,
            "adsense_impressions": imp,
            "adsense_clicks": clk,
            "adsense_rpm": round(rpm, 2),
        },
    }


def _collect_adsense_by_url() -> dict:
    """AdSense URL別収益を取得"""
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return {"error": "googleapiclient not installed"}

    creds = _get_adsense_creds()
    if not creds:
        return {"error": "adsense token expired"}

    service = build("adsense", "v2", credentials=creds, cache_discovery=False)
    yesterday = date.today() - timedelta(days=1)

    try:
        report = service.accounts().reports().generate(
            account=ADSENSE_ACCOUNT,
            dateRange="CUSTOM",
            startDate_year=yesterday.year,
            startDate_month=yesterday.month,
            startDate_day=yesterday.day,
            endDate_year=yesterday.year,
            endDate_month=yesterday.month,
            endDate_day=yesterday.day,
            dimensions=["PAGE_URL"],
            metrics=["ESTIMATED_EARNINGS", "PAGE_VIEWS", "IMPRESSIONS", "CLICKS"],
            orderBy=["+ESTIMATED_EARNINGS"],
            limit=200,
        ).execute()
    except Exception as e:
        return {"error": str(e)[:300]}

    headers = [h["name"] for h in report.get("headers", [])]
    articles = []
    for row in report.get("rows", []):
        cells = row.get("cells", [])
        mapped = {h: c.get("value") for h, c in zip(headers, cells)}
        url = mapped.get("PAGE_URL", "")
        earnings = float(mapped.get("ESTIMATED_EARNINGS", 0))
        if earnings <= 0 and not url:
            continue
        articles.append({
            "url": url,
            "adsense_earnings_jpy": round(earnings, 2),
            "adsense_pageviews": int(mapped.get("PAGE_VIEWS", 0)),
            "adsense_impressions": int(mapped.get("IMPRESSIONS", 0)),
            "adsense_clicks": int(mapped.get("CLICKS", 0)),
        })

    return {"date": yesterday.isoformat(), "articles": articles}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 統合収集
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _load_article_index() -> dict[str, dict]:
    if not ARTICLE_INDEX.exists():
        return {}
    data = json.loads(ARTICLE_INDEX.read_text(encoding="utf-8"))
    arts = data if isinstance(data, list) else data.get("articles", [])
    return {(a.get("url", "").rstrip("/") + "/"): a for a in arts}


def collect_all():
    """全ソースから収集し kpi_daily.jsonl / kpi_articles.jsonl に追記"""
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # 重複防止
    if _date_exists(KPI_DAILY, yesterday):
        print(f"[kpi_store] {yesterday} は既に記録済み — スキップ")
        return

    print("[kpi_store] データ収集開始...")
    errors: list[str] = []

    # GSC (7日間でサイト全体)
    print("  [1/3] GSC...")
    gsc = _collect_gsc(7)
    gsc_summary = gsc.get("summary", {}) if "error" not in gsc else {}
    if "error" in gsc:
        errors.append(f"GSC: {gsc['error']}")
        print(f"  ⚠ GSC: {gsc['error']}")

    # GA4 (昨日1日)
    print("  [2/3] GA4...")
    ga4 = _collect_ga4(1)
    ga4_summary = ga4.get("summary", {}) if "error" not in ga4 else {}
    if "error" in ga4:
        errors.append(f"GA4: {ga4['error']}")
        print(f"  ⚠ GA4: {ga4['error']}")

    # AdSense (昨日) — トークン失効しやすいので例外でも落とさない
    print("  [3/3] AdSense...")
    try:
        adsense_daily = _collect_adsense_daily()
    except Exception as e:
        adsense_daily = {"error": str(e)[:300]}
    adsense_summary = adsense_daily.get("summary", {}) if "error" not in adsense_daily else {}
    if "error" in adsense_daily:
        errors.append(f"AdSense: {adsense_daily['error']}")
        print(f"  ⚠ AdSense: {adsense_daily['error']}")

    # ── kpi_daily.jsonl ──
    daily_record = {
        "date": yesterday,
        "collected_at": today,
        # GSC (7d rolling)
        "gsc_impressions": gsc_summary.get("gsc_impressions", 0),
        "gsc_clicks": gsc_summary.get("gsc_clicks", 0),
        "gsc_ctr": gsc_summary.get("gsc_ctr", 0),
        "gsc_pages": gsc_summary.get("gsc_pages", 0),
        # GA4 (1d)
        "ga4_pageviews": ga4_summary.get("ga4_pageviews", 0),
        "ga4_sessions": ga4_summary.get("ga4_sessions", 0),
        "ga4_users": ga4_summary.get("ga4_users", 0),
        "ga4_engaged_sessions": ga4_summary.get("ga4_engaged_sessions", 0),
        "ga4_avg_duration": ga4_summary.get("ga4_avg_duration", 0),
        "ga4_bounce_rate": ga4_summary.get("ga4_bounce_rate", 0),
        "ga4_x_sessions": ga4_summary.get("ga4_x_sessions", 0),
        # AdSense (1d)
        "adsense_earnings_jpy": adsense_summary.get("adsense_earnings_jpy", 0),
        "adsense_pageviews": adsense_summary.get("adsense_pageviews", 0),
        "adsense_impressions": adsense_summary.get("adsense_impressions", 0),
        "adsense_clicks": adsense_summary.get("adsense_clicks", 0),
        "adsense_rpm": adsense_summary.get("adsense_rpm", 0),
        # メタ
        "errors": errors if errors else None,
    }
    _append_jsonl(KPI_DAILY, daily_record)
    print(f"  ✅ kpi_daily.jsonl 追記 ({yesterday})")

    # ── kpi_articles.jsonl ──
    # GSC記事 + GA4記事 + AdSense記事 を URL で結合
    article_index = _load_article_index()
    merged: dict[str, dict] = {}

    # GSC articles
    for a in gsc.get("articles", []):
        url = a["url"].rstrip("/") + "/"
        merged.setdefault(url, {"url": url})
        merged[url].update({
            "gsc_impressions": a["gsc_impressions"],
            "gsc_clicks": a["gsc_clicks"],
            "gsc_ctr": a["gsc_ctr"],
            "gsc_position": a["gsc_position"],
        })

    # GA4 articles (path → full URL)
    for a in ga4.get("articles", []):
        url = a["url"].rstrip("/") + "/"
        merged.setdefault(url, {"url": url})
        merged[url].update({
            "ga4_pageviews": a["ga4_pageviews"],
            "ga4_sessions": a["ga4_sessions"],
            "ga4_avg_duration": a["ga4_avg_duration"],
            "ga4_bounce_rate": a["ga4_bounce_rate"],
        })

    # AdSense by URL
    try:
        adsense_urls = _collect_adsense_by_url()
    except Exception as e:
        adsense_urls = {"error": str(e)[:300]}
    if "error" not in adsense_urls:
        for a in adsense_urls.get("articles", []):
            url = a["url"].rstrip("/") + "/"
            merged.setdefault(url, {"url": url})
            merged[url].update({
                "adsense_earnings_jpy": a["adsense_earnings_jpy"],
                "adsense_pageviews": a["adsense_pageviews"],
                "adsense_impressions": a["adsense_impressions"],
                "adsense_clicks": a["adsense_clicks"],
            })
    elif "error" in adsense_urls:
        errors.append(f"AdSense URL別: {adsense_urls['error']}")

    # article_index から post_id / title を補完
    article_count = 0
    for url, rec in merged.items():
        idx = article_index.get(url)
        rec["date"] = yesterday
        rec["post_id"] = idx.get("id") if idx else None
        rec["title"] = idx.get("title", "") if idx else None
        # デフォルト値埋め
        rec.setdefault("gsc_impressions", 0)
        rec.setdefault("gsc_clicks", 0)
        rec.setdefault("gsc_ctr", 0)
        rec.setdefault("gsc_position", 0)
        rec.setdefault("ga4_pageviews", 0)
        rec.setdefault("ga4_sessions", 0)
        rec.setdefault("ga4_avg_duration", 0)
        rec.setdefault("ga4_bounce_rate", 0)
        rec.setdefault("adsense_earnings_jpy", 0)
        rec.setdefault("adsense_pageviews", 0)
        rec.setdefault("adsense_impressions", 0)
        rec.setdefault("adsense_clicks", 0)
        _append_jsonl(KPI_ARTICLES, rec)
        article_count += 1

    print(f"  ✅ kpi_articles.jsonl 追記 ({yesterday}): {article_count}記事")
    if errors:
        print(f"  ⚠ エラー: {'; '.join(errors)}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# バックフィル: 既存 metrics_yesterday.json から取り込み
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def backfill():
    """既存の google_metrics/metrics_yesterday.json から kpi_daily.jsonl にバックフィル"""
    src = GMETRICS / "metrics_yesterday.json"
    if not src.exists():
        print("[kpi_store] metrics_yesterday.json が見つかりません")
        return

    data = json.loads(src.read_text(encoding="utf-8"))
    d = data.get("date")
    if not d:
        # date_range から推定
        dr = data.get("date_range", {})
        d = dr.get("end", date.today().isoformat())

    if _date_exists(KPI_DAILY, d):
        print(f"[kpi_store] {d} は既に記録済み — スキップ")
        return

    ga4 = data.get("ga4", {}).get("summary", {})
    gsc = data.get("gsc", {})
    adsense = data.get("adsense", {})
    cta = data.get("cta_events", {})

    # gsc top_pages から合計算出
    gsc_pages = gsc.get("top_pages", [])
    gsc_total_imp = sum(p.get("impressions", 0) for p in gsc_pages)
    gsc_total_clk = sum(p.get("clicks", 0) for p in gsc_pages)

    adsense_earnings = 0
    adsense_rpm = 0
    adsense_pv = 0
    adsense_imp = 0
    adsense_clk = 0
    if isinstance(adsense, dict) and "error" not in adsense:
        adsense_earnings = float(adsense.get("ESTIMATED_EARNINGS", 0))
        adsense_pv = int(adsense.get("PAGE_VIEWS", 0))
        adsense_imp = int(adsense.get("IMPRESSIONS", 0))
        adsense_clk = int(adsense.get("CLICKS", 0))
        adsense_rpm = float(adsense.get("PAGE_VIEWS_RPM", 0))

    record = {
        "date": d,
        "collected_at": date.today().isoformat(),
        "source": "backfill",
        "gsc_impressions": gsc_total_imp,
        "gsc_clicks": gsc_total_clk,
        "gsc_ctr": round(gsc_total_clk / max(gsc_total_imp, 1), 6),
        "gsc_pages": len(gsc_pages),
        "ga4_pageviews": int(ga4.get("pageviews", 0)),
        "ga4_sessions": int(ga4.get("sessions", 0)),
        "ga4_users": int(ga4.get("users", 0)),
        "ga4_engaged_sessions": int(ga4.get("engaged_sessions", 0)),
        "ga4_avg_duration": round(float(ga4.get("avg_session_duration", 0)), 1),
        "ga4_bounce_rate": 0,
        "ga4_x_sessions": data.get("ga4", {}).get("x_sessions", 0),
        "adsense_earnings_jpy": round(adsense_earnings, 2),
        "adsense_pageviews": adsense_pv,
        "adsense_impressions": adsense_imp,
        "adsense_clicks": adsense_clk,
        "adsense_rpm": round(adsense_rpm, 2),
        "cta_total_clicks": cta.get("total_cta_clicks", 0) if isinstance(cta, dict) else 0,
        "errors": None,
    }
    _append_jsonl(KPI_DAILY, record)
    print(f"[kpi_store] バックフィル完了: {d}")
    print(f"  GA4 PV={record['ga4_pageviews']} / GSC clk={record['gsc_clicks']} / AdSense ¥{record['adsense_earnings_jpy']}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# クエリ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def query_daily(days: int = 7) -> list[dict]:
    return _read_jsonl(KPI_DAILY, days)


def query_articles(days: int = 7, top_n: int = 50) -> list[dict]:
    recs = _read_jsonl(KPI_ARTICLES, days)
    # URL ごとに最新日を優先、ga4_pageviews 降順
    by_url: dict[str, dict] = {}
    for r in recs:
        url = r.get("url", "")
        existing = by_url.get(url)
        if not existing or r.get("date", "") >= existing.get("date", ""):
            by_url[url] = r
    sorted_arts = sorted(by_url.values(), key=lambda x: x.get("ga4_pageviews", 0), reverse=True)
    return sorted_arts[:top_n]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    ap = argparse.ArgumentParser(description="統合KPIストア")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("collect", help="全ソース収集→JSONL追記")
    sub.add_parser("backfill", help="既存JSONから取り込み")

    q = sub.add_parser("query", help="KPI照会")
    q.add_argument("target", choices=["daily", "articles"])
    q.add_argument("days", type=int, nargs="?", default=7)

    args = ap.parse_args()

    if args.cmd == "collect":
        collect_all()
    elif args.cmd == "backfill":
        backfill()
    elif args.cmd == "query":
        if args.target == "daily":
            data = query_daily(args.days)
        else:
            data = query_articles(args.days)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
