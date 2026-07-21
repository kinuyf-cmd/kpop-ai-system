import json
import os
import sys
from datetime import date, timedelta

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

BASE_DIR = os.path.expanduser("~/google_metrics")

GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "493983919")
GSC_SITE_URL = os.environ.get("GSC_SITE_URL", "https://www.kpopjournal.tokyo/")
ADSENSE_ACCOUNT_NAME = os.environ.get("ADSENSE_ACCOUNT_NAME", "accounts/pub-5968839599715792")

SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, "service_account.json")
ADSENSE_CLIENT_SECRET_FILE = os.path.join(BASE_DIR, "adsense_client_secret.json")
ADSENSE_TOKEN_FILE = os.path.join(BASE_DIR, "adsense_token.json")

# GA4 のデータ確定を待ってから取得する(2026-07-17 修正)。
# 旧実装は cron 8:30 に「昨日」を取りに行っていたが、GA4 のセッション系指標は確定に
# 24〜48時間かかるため、未確定の途中値を掴んで保存していた。実害:
#   engagedSessions が 25日分ほぼ全滅(rate 0〜2%)で保存されていた。同じ日付を後日
#   取り直すと 50〜64% と正常値。「エンゲージほぼ0=読まれていない」は計測の嘘で、
#   実際のサイトは健全だった(2026-07-17 実測で判明)。
# → LAG_DAYS 日前を取得する。_append_history は同じ date の行を置換するので、
#   遡って再実行すれば過去の誤った行も正しい値で上書きされる。
LAG_DAYS = int(os.environ.get("METRICS_LAG_DAYS", "3"))

# GA4 ランディングページの取得上限(2026-07-21 追加)。
#   実測で1日あたり約430ページに流入があるため既定 2000 で全件入る想定。
#   GA4 API の 1リクエスト上限は 250,000 行なので余裕がある。
GA4_LANDING_PAGE_LIMIT = int(os.environ.get("GA4_LANDING_PAGE_LIMIT", "2000"))

# GSC の行取得上限(2026-07-21 追加)。API 上限は 25,000 行/リクエスト。
GSC_ROW_LIMIT = int(os.environ.get("GSC_ROW_LIMIT", "2000"))

target_day = date.today() - timedelta(days=LAG_DAYS)
yesterday = target_day  # 後方互換(AdSense の startDate_* が参照)
start_date = target_day.isoformat()
end_date = target_day.isoformat()

def get_ga4_data():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"]
    )
    client = BetaAnalyticsDataClient(credentials=creds)

    # 2026-07-21: limit=10 固定だったため「上位10件が流入の何%か」を全体シェアと
    #   誤読する事故が起きた(実測では429ページが流入を持ち上位10件は34%でしかない)。
    #   全件取得に変更するが、top_landing_pages を増やすと daily_brief_v2 /
    #   kpi_dashboard の「top_pages 合算」が不連続に跳ねて時系列が壊れるため、
    #   既存キーは先頭10件のまま据え置き、全件は all_landing_pages に分けて持つ。
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
        limit=GA4_LANDING_PAGE_LIMIT,
    )

    res = client.run_report(req)

    all_pages = []
    for row in res.rows:
        all_pages.append({
            "page": row.dimension_values[0].value,
            "sessions": row.metric_values[0].value,
            "users": row.metric_values[1].value,
            "pageviews": row.metric_values[2].value,
            "engaged_sessions": row.metric_values[3].value,
            "avg_session_duration": row.metric_values[4].value,
        })

    # 既存消費側(kpop_master_scheduler.sh / score_articles.py / measure_initial_
    # performance.py)との後方互換のため top_landing_pages は従来どおり上位10件。
    top_pages = all_pages[:10]

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
        # 2026-07-21: 全ランディングページ。top_landing_pages(上位10件)を
        # 分母にした比率は全体シェアではないため、記事別分析にはこちらを使う。
        "all_landing_pages": all_pages,
        "landing_page_count": len(all_pages),
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
        # 2026-07-21: rowLimit=10 固定を撤廃(GA4 側と同じ「上位10件を全体と誤読」
        #   の罠を防ぐ)。ただし top_queries / top_pages は daily_brief_v2 と
        #   kpi_dashboard が合算して「サイト全体のGSC指標」として使っており、件数を
        #   増やすと値が不連続に跳ねて前日比が壊れる。既存キーは先頭10件で据え置き、
        #   全件は all_queries / all_pages に分けて持つ。
        body_queries = {
            "startDate": r["start"],
            "endDate": r["end"],
            "dimensions": ["query"],
            "rowLimit": GSC_ROW_LIMIT
        }

        body_pages = {
            "startDate": r["start"],
            "endDate": r["end"],
            "dimensions": ["page"],
            "rowLimit": GSC_ROW_LIMIT
        }

        q_res = run_gsc_query(service, body_queries)
        p_res = run_gsc_query(service, body_pages)

        q_rows = q_res.get("rows", []) if isinstance(q_res, dict) else []
        p_rows = p_res.get("rows", []) if isinstance(p_res, dict) else []

        if q_rows or p_rows:
            all_queries = []
            for row in q_rows:
                all_queries.append({
                    "query": row["keys"][0],
                    "clicks": row.get("clicks", 0),
                    "impressions": row.get("impressions", 0),
                    "ctr": row.get("ctr", 0),
                    "position": row.get("position", 0),
                })

            all_pages_gsc = []
            for row in p_rows:
                all_pages_gsc.append({
                    "page": row["keys"][0],
                    "clicks": row.get("clicks", 0),
                    "impressions": row.get("impressions", 0),
                    "ctr": row.get("ctr", 0),
                    "position": row.get("position", 0),
                })

            # 既存消費側との後方互換のため上位10件で据え置き(合算値の連続性を維持)
            top_queries = all_queries[:10]
            top_pages = all_pages_gsc[:10]

            return {
                "period_label": r["label"],
                "start_date": r["start"],
                "end_date": r["end"],
                "top_queries": top_queries,
                "top_pages": top_pages,
                # 2026-07-21: 全件。比率を出すときは必ずこちらを分母にする。
                "all_queries": all_queries,
                "all_pages": all_pages_gsc,
                "query_count": len(all_queries),
                "page_count": len(all_pages_gsc),
            }

    return {
        "period_label": "データなし",
        "start_date": None,
        "end_date": None,
        "top_queries": [],
        "top_pages": [],
        "all_queries": [],
        "all_pages": [],
        "query_count": 0,
        "page_count": 0,
    }

def get_adsense_credentials():
    scopes = ["https://www.googleapis.com/auth/adsense.readonly"]

    creds = None
    if os.path.exists(ADSENSE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(ADSENSE_TOKEN_FILE, scopes)

    if not creds or not creds.valid:
        refreshed = False
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                refreshed = True
            except RefreshError:
                # refresh_token が Google 側で失効(invalid_grant)。
                # 黙ってスキップせず、同意フローで再取得できるよう死トークンを捨てる。
                creds = None
        if not refreshed and not (creds and creds.valid):
            # 対話フロー(ブラウザ承認)は人がいる時だけ。cron から入ると
            # run_local_server がポートを掴んだまま承認を永久に待ち、プロセスが死なない。
            # 実害(2026-07-17 発見): 7/10 8:30 のcron起動プロセスが **7日10時間** 生き続け、
            # ポート8765を占有 → 以降の毎日のcronが「Address already in use」で失敗し続け、
            # AdSense収益データが25日分ゼロになっていた(cronログに失敗90行)。
            # → 非対話(cron/TTYなし)では即座に諦めてスキップさせる。人が手で実行したときだけ承認へ進む。
            interactive = sys.stdin.isatty() or os.environ.get("ADSENSE_OAUTH_INTERACTIVE") == "1"
            if not interactive:
                raise RuntimeError(
                    "AdSense の refresh_token が失効しており再認証(ブラウザ承認)が必要ですが、"
                    "非対話実行のためスキップします。owner が手動で次を実行してください:\n"
                    "  cd /home/aiuser/kpop-ai-system && "
                    "venv_kpi/bin/python3 google_metrics/fetch_yesterday_metrics.py"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                ADSENSE_CLIENT_SECRET_FILE, scopes
            )
            # ヘッドレスVM(DISPLAY無し)では自動でブラウザを開けない。
            # run_console は google-auth-oauthlib 1.0 で廃止されたため、
            # 固定ポートの run_local_server + 手元PCからのSSHポート転送で承認する。
            #   手元PC: ssh -L 8765:localhost:8765 <vm>
            #   表示されたURLを手元ブラウザで開く → localhost:8765 へリダイレクトされ完了
            if os.environ.get("DISPLAY"):
                creds = flow.run_local_server(port=0)
            else:
                oob_port = int(os.environ.get("ADSENSE_OAUTH_PORT", "8765"))
                creds = flow.run_local_server(
                    host="localhost", port=oob_port,
                    open_browser=False,
                    authorization_prompt_message=(
                        "\n手元PCで別ターミナルを開き次を実行(ポート転送):\n"
                        # sshd は Port 2222(22は閉じている)。-p を書かないと Connection refused に
                        # なり owner が詰まる(2026-07-17 実際に発生)。
                        f"    ssh -L {oob_port}:localhost:{oob_port} -p 2222 aiuser@160.251.254.62\n"
                        "そのうえで以下のURLを手元ブラウザで開いて承認してください:\n\n    {url}\n"
                        "\n※ 承認中に 'channel N: open failed: Connection refused' が出ても無害です"
                        "(VM側は受信済み)。\n"
                    ),
                )
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

def _safe(label, fn):
    """1ブロックの失敗が全体(=書込)を止めないよう分離。失敗は error を残し継続。

    背景(2026-05-23): AdSense OAuth が invalid_grant で失効していたため、
    get_adsense_data() の例外が main() の dict 生成ごと巻き込み、GA4/GSC の値も
    metrics_yesterday.json に書かれず、トラフィック計測が約6週間止まっていた。
    GA4 / GSC / AdSense を独立ブロックにし、1つ失敗しても他は書く。"""
    try:
        return fn(), None
    except Exception as e:  # 認証失効・API エラー等。値は出さずクラス名+短文のみ
        msg = f"{type(e).__name__}: {str(e)[:160]}"
        print(f"  WARN: {label} 取得失敗 → スキップ継続 ({msg})")
        return None, msg


def _append_history(result):
    """metrics_history.jsonl に1日1行で追記。同じ date の既存行は置換(re-run対応)。

    全体の書込を止めないよう、履歴追記の失敗は警告のみで握りつぶす
    (metrics_yesterday.json の上書きは既に成功している前提)。
    """
    hist_path = os.path.join(BASE_DIR, "metrics_history.jsonl")
    try:
        d = result.get("date")
        rows = []
        if os.path.exists(hist_path):
            with open(hist_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # 壊れた行はスキップ
                    if rec.get("date") == d:
                        continue  # 同日は新しい result で置換するため除外
                    rows.append(rec)
        rows.append(result)
        rows.sort(key=lambda r: r.get("date", ""))
        with open(hist_path, "w", encoding="utf-8") as f:
            for rec in rows:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"  history: {hist_path} ({len(rows)} days)")
    except Exception as e:
        print(f"  WARN: history 追記失敗 → スキップ ({type(e).__name__}: {str(e)[:80]})")


def main():
    ga4, ga4_err = _safe("GA4", get_ga4_data)
    gsc, gsc_err = _safe("GSC", get_gsc_data)
    adsense, ads_err = _safe("AdSense", get_adsense_data)

    result = {
        "date": start_date,
        "fetched_at": date.today().isoformat(),  # 鮮度判定用(brief 側で古さを検知)
        "ga4": ga4,
        "gsc": gsc,
        "adsense": adsense,
        "errors": {k: v for k, v in
                   {"ga4": ga4_err, "gsc": gsc_err, "adsense": ads_err}.items() if v},
    }

    out_path = os.path.join(BASE_DIR, "metrics_yesterday.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 2026-07-21: all_* (全ランディングページ/全クエリ) はスナップショットにのみ持たせ、
    #   履歴には入れない。_append_history は全行をメモリに読んで書き直す実装のため、
    #   1日67KB(429ページ)を積むと年24MBに肥大し日次 cron が重くなる。履歴の用途は
    #   時系列トレンドで、全件明細は当日分があれば足りる。件数だけは残して
    #   「上位10件が全体の何%か」を後から検算できるようにする。
    _hist = json.loads(json.dumps(result, ensure_ascii=False))
    for _sec, _keys in (("ga4", ("all_landing_pages",)),
                        ("gsc", ("all_queries", "all_pages"))):
        _d = _hist.get(_sec)
        if isinstance(_d, dict):
            for _k in _keys:
                _d.pop(_k, None)

    # 2026-06-22: metrics_yesterday.json は毎回上書きで日次履歴が残らず、
    #   PV/検索のトレンドが追えない盲点だった(GSCは別途API直叩きで追えるが
    #   GA4 PV は履歴ゼロ)。同じ result を date キーで dedup しつつ
    #   metrics_history.jsonl に追記し、トレンド追跡を可能にする。
    _append_history(_hist)

    # 1つでも取れていれば 0、全滅なら 1(cron ログで気づける)
    ok = any(x is not None for x in (ga4, gsc, adsense))
    print(out_path, "(GA4=%s GSC=%s AdSense=%s)" % (
        "OK" if ga4 else "NG", "OK" if gsc else "NG", "OK" if adsense else "NG"))
    return 0 if ok else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
