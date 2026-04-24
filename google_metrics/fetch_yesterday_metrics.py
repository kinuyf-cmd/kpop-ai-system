import json
import os
from datetime import date, timedelta

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "493983919")
GSC_SITE_URL = os.environ.get("GSC_SITE_URL", "https://www.kpopjournal.tokyo/")
ADSENSE_ACCOUNT_NAME = os.environ.get("ADSENSE_ACCOUNT_NAME", "accounts/pub-5968839599715792")

SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "service_account.json")
ADSENSE_CLIENT_SECRET_FILE = os.path.join(BASE_DIR, "adsense_client_secret.json")
ADSENSE_TOKEN_FILE = os.path.join(BASE_DIR, "adsense_token.json")

yesterday = date.today() - timedelta(days=1)
start_date = yesterday.isoformat()
end_date = yesterday.isoformat()

def get_ga4_data():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"]
    )
    client = BetaAnalyticsDataClient(credentials=creds)

    req = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        dimensions=[Dimension(name="landingPagePlusQueryString")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="screenPageViews"),
            Metric(name="engagedSessions"),
            Metric(name="averageSessionDuration"),
        ],
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        limit=10,
    )

    res = client.run_report(req)

    top_pages = []
    for row in res.rows:
        top_pages.append({
            "page": row.dimension_values[0].value,
            "sessions": row.metric_values[0].value,
            "users": row.metric_values[1].value,
            "pageviews": row.metric_values[2].value,
            "engaged_sessions": row.metric_values[3].value,
            "avg_session_duration": row.metric_values[4].value,
        })

    summary_req = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="screenPageViews"),
            Metric(name="engagedSessions"),
            Metric(name="averageSessionDuration"),
        ],
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
    )
    summary_res = client.run_report(summary_req)
    summary_row = summary_res.rows[0]

    # トラフィックソース別セッション数（X流入計測用）
    source_req = RunReportRequest(
        property=f"properties/{GA4_PROPERTY_ID}",
        dimensions=[Dimension(name="sessionSource")],
        metrics=[Metric(name="sessions")],
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
    )
    try:
        source_res = client.run_report(source_req)
        traffic_sources = {}
        x_sessions = 0
        for row in source_res.rows:
            src = row.dimension_values[0].value
            sess = int(row.metric_values[0].value)
            traffic_sources[src] = sess
            if src in ("t.co", "x.com", "twitter.com"):
                x_sessions += sess
    except Exception:
        traffic_sources = {}
        x_sessions = 0

    return {
        "summary": {
            "sessions": summary_row.metric_values[0].value,
            "users": summary_row.metric_values[1].value,
            "pageviews": summary_row.metric_values[2].value,
            "engaged_sessions": summary_row.metric_values[3].value,
            "avg_session_duration": summary_row.metric_values[4].value,
        },
        "top_landing_pages": top_pages,
        "traffic_sources": traffic_sources,
        "x_sessions": x_sessions,
    }

def run_gsc_query(service, body):
    try:
        return service.searchanalytics().query(siteUrl=GSC_SITE_URL, body=body).execute()
    except Exception as e:
        return {"error": str(e)}

def get_gsc_data():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
    )
    service = build("searchconsole", "v1", credentials=creds)

    # 取得優先順位：前日 → 3日前 → 直近7日
    ranges = [
        {
            "label": "前日",
            "start": (date.today() - timedelta(days=1)).isoformat(),
            "end": (date.today() - timedelta(days=1)).isoformat(),
        },
        {
            "label": "3日前",
            "start": (date.today() - timedelta(days=3)).isoformat(),
            "end": (date.today() - timedelta(days=3)).isoformat(),
        },
        {
            "label": "直近7日",
            "start": (date.today() - timedelta(days=7)).isoformat(),
            "end": (date.today() - timedelta(days=1)).isoformat(),
        },
    ]

    for r in ranges:
        body_queries = {
            "startDate": r["start"],
            "endDate": r["end"],
            "dimensions": ["query"],
            "rowLimit": 10
        }

        body_pages = {
            "startDate": r["start"],
            "endDate": r["end"],
            "dimensions": ["page"],
            "rowLimit": 10
        }

        q_res = run_gsc_query(service, body_queries)
        p_res = run_gsc_query(service, body_pages)

        q_rows = q_res.get("rows", []) if isinstance(q_res, dict) else []
        p_rows = p_res.get("rows", []) if isinstance(p_res, dict) else []

        if q_rows or p_rows:
            top_queries = []
            for row in q_rows:
                top_queries.append({
                    "query": row["keys"][0],
                    "clicks": row.get("clicks", 0),
                    "impressions": row.get("impressions", 0),
                    "ctr": row.get("ctr", 0),
                    "position": row.get("position", 0),
                })

            top_pages = []
            for row in p_rows:
                top_pages.append({
                    "page": row["keys"][0],
                    "clicks": row.get("clicks", 0),
                    "impressions": row.get("impressions", 0),
                    "ctr": row.get("ctr", 0),
                    "position": row.get("position", 0),
                })

            return {
                "period_label": r["label"],
                "start_date": r["start"],
                "end_date": r["end"],
                "top_queries": top_queries,
                "top_pages": top_pages
            }

    return {
        "period_label": "データなし",
        "start_date": None,
        "end_date": None,
        "top_queries": [],
        "top_pages": []
    }

def get_adsense_credentials():
    scopes = ["https://www.googleapis.com/auth/adsense.readonly"]

    creds = None
    if os.path.exists(ADSENSE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(ADSENSE_TOKEN_FILE, scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                ADSENSE_CLIENT_SECRET_FILE, scopes
            )
            creds = flow.run_local_server(port=0)
        with open(ADSENSE_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds

def get_adsense_data():
    creds = get_adsense_credentials()
    service = build("adsense", "v2", credentials=creds)

    report = service.accounts().reports().generate(
        account=ADSENSE_ACCOUNT_NAME,
        dateRange="CUSTOM",
        startDate_year=yesterday.year,
        startDate_month=yesterday.month,
        startDate_day=yesterday.day,
        endDate_year=yesterday.year,
        endDate_month=yesterday.month,
        endDate_day=yesterday.day,
        metrics=["ESTIMATED_EARNINGS", "PAGE_VIEWS", "IMPRESSIONS", "CLICKS", "PAGE_VIEWS_RPM"]
    ).execute()

    headers = [h["name"] for h in report.get("headers", [])]
    rows = report.get("rows", [])
    values = rows[0]["cells"] if rows else []

    mapped = {}
    for h, v in zip(headers, values):
        mapped[h] = v.get("value")

    return mapped

def get_cta_events():
    """
    GA4からCTAクリックイベントを集計する。
    イベント名: cta_click_top / cta_click_middle / cta_click_bottom /
               cta_click_fixed_bar / fixed_cta_impression / fixed_cta_close
    """
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"]
    )
    client = BetaAnalyticsDataClient(credentials=creds)

    CTA_EVENTS = [
        "cta_click_top", "cta_click_middle", "cta_click_bottom",
        "cta_click_fixed_bar", "fixed_cta_impression", "fixed_cta_close",
    ]

    try:
        # イベント名別の合計
        req = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            dimensions=[Dimension(name="eventName")],
            metrics=[Metric(name="eventCount")],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        )
        res = client.run_report(req)
        event_counts = {}
        for row in res.rows:
            ev  = row.dimension_values[0].value
            cnt = int(row.metric_values[0].value)
            if ev in CTA_EVENTS:
                event_counts[ev] = cnt

        # 記事タイプ別内訳
        type_req = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            dimensions=[
                Dimension(name="eventName"),
                Dimension(name="customEvent:article_type"),
            ],
            metrics=[Metric(name="eventCount")],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        )
        type_res = client.run_report(type_req)
        type_breakdown = {}
        for row in type_res.rows:
            ev       = row.dimension_values[0].value
            art_type = row.dimension_values[1].value or "不明"
            cnt      = int(row.metric_values[0].value)
            if ev in CTA_EVENTS and "cta_click" in ev:
                pos = ev.replace("cta_click_", "")
                if art_type not in type_breakdown:
                    type_breakdown[art_type] = {}
                type_breakdown[art_type][pos] = type_breakdown[art_type].get(pos, 0) + cnt

        clicks_top   = event_counts.get("cta_click_top", 0)
        clicks_mid   = event_counts.get("cta_click_middle", 0)
        clicks_bot   = event_counts.get("cta_click_bottom", 0)
        clicks_fixed = event_counts.get("cta_click_fixed_bar", 0)
        impressions  = event_counts.get("fixed_cta_impression", 0)
        closes       = event_counts.get("fixed_cta_close", 0)
        total        = clicks_top + clicks_mid + clicks_bot + clicks_fixed

        return {
            "cta_click_top":        clicks_top,
            "cta_click_middle":     clicks_mid,
            "cta_click_bottom":     clicks_bot,
            "cta_click_fixed_bar":  clicks_fixed,
            "fixed_cta_impression": impressions,
            "fixed_cta_close":      closes,
            "total_cta_clicks":     total,
            "fixed_cta_click_rate": round(clicks_fixed / impressions, 4) if impressions > 0 else 0.0,
            "fixed_cta_close_rate": round(closes / impressions, 4) if impressions > 0 else 0.0,
            "type_breakdown":       type_breakdown,
            "source": "ga4_real",
        }

    except Exception as e:
        return {"error": str(e), "source": "ga4_error"}

def main():
    ga4_data = get_ga4_data()

    # CTA実イベント取得（エラーでも全体を止めない）
    try:
        cta_data = get_cta_events()
        # CTA CTR = 総クリック ÷ PV
        pv = int(ga4_data.get("summary", {}).get("pageviews", 0))
        total_clicks = cta_data.get("total_cta_clicks", 0)
        cta_data["cta_ctr_real"] = round(total_clicks / pv, 4) if pv > 0 else None
        cta_data["pageviews"] = pv
    except Exception as e:
        cta_data = {"error": str(e), "source": "ga4_error"}

    # AdSense はトークン失効で落ちやすい。失敗しても GA4/GSC の値は必ず書き出す。
    try:
        adsense_data = get_adsense_data()
    except Exception as e:
        adsense_data = {"error": str(e)[:200], "source": "adsense_token_expired_or_failed"}
        print(f"[WARN] AdSense取得失敗（GA4/GSCは書き出し継続）: {e}", flush=True)

    result = {
        "date": start_date,
        "ga4": ga4_data,
        "gsc": get_gsc_data(),
        "adsense": adsense_data,
        "cta_events": cta_data,
    }

    out_path = os.path.join(BASE_DIR, "metrics_yesterday.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ui_cta_events.jsonlにも追記
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(BASE_DIR), "kpop-ai-system", "lib"))
        cta_log = os.path.join(os.path.dirname(BASE_DIR), "kpop-ai-system", "logs", "ui_cta_events.jsonl")
        cta_record = dict(cta_data)
        cta_record["date"] = start_date
        cta_record["fetched_at"] = date.today().isoformat() + "T00:00:00+09:00"
        with open(cta_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(cta_record, ensure_ascii=False) + "\n")
    except Exception:
        pass

    print(out_path)

if __name__ == "__main__":
    main()
