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

BASE_DIR = os.path.expanduser("~/google_metrics")

GA4_PROPERTY_ID = "493983919"
GSC_SITE_URL = "https://www.kpopjournal.tokyo/"
ADSENSE_ACCOUNT_NAME = "accounts/pub-5968839599715792"

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

    return {
        "summary": {
            "sessions": summary_row.metric_values[0].value,
            "users": summary_row.metric_values[1].value,
            "pageviews": summary_row.metric_values[2].value,
            "engaged_sessions": summary_row.metric_values[3].value,
            "avg_session_duration": summary_row.metric_values[4].value,
        },
        "top_landing_pages": top_pages
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

def main():
    result = {
        "date": start_date,
        "ga4": get_ga4_data(),
        "gsc": get_gsc_data(),
        "adsense": get_adsense_data(),
    }

    out_path = os.path.join(BASE_DIR, "metrics_yesterday.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(out_path)

if __name__ == "__main__":
    main()
