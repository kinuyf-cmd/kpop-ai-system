#!/usr/bin/env python3
"""X→サイト流入の実測レポート(導線施策の効果測定)。

背景 (2026-08-17):
  X からサイトへの流入導線(本文フック+自己リプURL)を新設した(commit eec9324)が、
  効果を測る手段が無かった。導線を入れても測れなければ、続けるべきか判断できない。

  導入時点のベースライン実測(2026-07-18〜08-14・確定分):
    総セッション 10,872 のうち t.co(X) は **37 (0.3%)** = ほぼゼロ
    (direct)46.7% / google 22.8% / bing 13.4% / yahoo 10.6%
    X流入の質: 1.54 PV/セッション・**滞在12.9秒**(ほぼ即離脱)

  ベースラインを日次分解して分かった構造(移動合計で語ってはいけない):
    37件のうち **31件が 8/14 の1日に集中**、うち22件は
    /summer-sonic-2026-day-guide への流入だった。当日開催イベントのガイド記事。
    そして自社は **サマソニ記事を一度もX投稿していない**(logs/x_posts.jsonl 実測0件)。
    → つまり **自動投稿由来の流入はゼロ**で、実際に流入が起きたのは
      「その日に需要があるイベント記事を第三者がシェアした」ケースだけ。
    導線を評価するときは、この「他者シェア由来のスパイク」と自社投稿由来を
    landingPage と投稿ログで切り分けること。合計値だけ見ると施策の効果を誤認する。

判定の考え方:
  - X 流入は t.co(リンククリック)と、プロフィール経由の direct に分かれる。
    direct は他要因と混ざるため、**t.co を主指標**にする。
  - GA4 は確定に24〜48h かかる(memory: ga4-must-wait-for-data-finalization)。
    既定で3日前までを対象にする。「昨日」を見ると途中値を掴む。

usage:
  venv_kpi/bin/python3 tools/x_traffic_report.py              # 直近28d
  venv_kpi/bin/python3 tools/x_traffic_report.py --days 7
  venv_kpi/bin/python3 tools/x_traffic_report.py --daily      # 日次の推移も出す
  venv_kpi/bin/python3 tools/x_traffic_report.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path("/home/aiuser/kpop-ai-system")
sys.path.insert(0, str(BASE))

try:
    from dotenv import load_dotenv
    load_dotenv(str(BASE / ".env"))
except Exception:
    pass

# GA4 は確定に24〜48h。既定で3日前までを対象にする(memory の LAG_DAYS=3 と同方針)。
LAG_DAYS = 3
# X 由来と見なす sessionSource。t.co は X のリンク短縮ドメイン。
X_SOURCES = {"t.co", "x.com", "twitter.com", "twitter", "x"}
REPORT_LOG = BASE / "logs" / "x_traffic_report.jsonl"


def _client():
    from lib.data_collector import GA4_PROPERTY_ID, SERVICE_ACCOUNT_FILE
    from google.oauth2 import service_account
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/analytics.readonly"])
    return BetaAnalyticsDataClient(credentials=creds), GA4_PROPERTY_ID


def _run(dims: list[str], metrics: list[str], days: int) -> list[dict]:
    from google.analytics.data_v1beta.types import (
        RunReportRequest, DateRange, Dimension, Metric)
    client, prop = _client()
    end = date.today() - timedelta(days=LAG_DAYS)
    start = end - timedelta(days=days - 1)
    req = RunReportRequest(
        property=f"properties/{prop}",
        date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
        dimensions=[Dimension(name=d) for d in dims],
        metrics=[Metric(name=m) for m in metrics],
        limit=100000,
    )
    resp = client.run_report(req)
    out = []
    for row in resp.rows:
        d = {dims[i]: row.dimension_values[i].value for i in range(len(dims))}
        for i, m in enumerate(metrics):
            v = row.metric_values[i].value
            try:
                d[m] = float(v) if "." in v else int(v)
            except ValueError:
                d[m] = 0
        out.append(d)
    return out


def collect(days: int) -> dict:
    """流入元別のセッションと、X 由来の内訳を集計する。"""
    rows = _run(["sessionSource"], ["sessions", "totalUsers", "screenPageViews",
                                    "userEngagementDuration"], days)
    total = sum(r["sessions"] for r in rows)
    x_rows = [r for r in rows if r["sessionSource"].lower() in X_SOURCES]
    x_sessions = sum(r["sessions"] for r in x_rows)
    x_pv = sum(r["screenPageViews"] for r in x_rows)
    x_dur = sum(r["userEngagementDuration"] for r in x_rows)
    direct = sum(r["sessions"] for r in rows
                 if r["sessionSource"] in ("(direct)", "(not set)"))
    end = date.today() - timedelta(days=LAG_DAYS)
    return {
        "period": {"days": days,
                   "start": (end - timedelta(days=days - 1)).isoformat(),
                   "end": end.isoformat()},
        "total_sessions": total,
        "x_sessions": x_sessions,
        "x_share_pct": round(x_sessions / total * 100, 2) if total else 0.0,
        # 流入の質: 1セッションあたりPVと滞在秒。導線が「話題と無関係な記事」へ
        # 飛ばしていると、ここが落ちる(直帰)。
        "x_pv_per_session": round(x_pv / x_sessions, 2) if x_sessions else 0.0,
        "x_sec_per_session": round(x_dur / x_sessions, 1) if x_sessions else 0.0,
        "direct_sessions": direct,
        "top_sources": sorted(
            [{"source": r["sessionSource"], "sessions": r["sessions"]} for r in rows],
            key=lambda x: -x["sessions"])[:10],
    }


def daily_x(days: int) -> list[dict]:
    """X 由来セッションの日次推移(移動合計で語らないため日次に分解する)。"""
    rows = _run(["date", "sessionSource"], ["sessions"], days)
    acc: dict[str, int] = {}
    for r in rows:
        if r["sessionSource"].lower() in X_SOURCES:
            acc[r["date"]] = acc.get(r["date"], 0) + r["sessions"]
    return [{"date": d, "x_sessions": acc[d]} for d in sorted(acc)]


def x_landing_pages(days: int) -> list[dict]:
    """X 由来セッションの着地ページ別内訳。

    合計値だけでは「自社投稿の成果」と「他者シェアのスパイク」を区別できない。
    ベースライン期間では22件が1本のイベントガイド記事に集中しており、
    その記事は自社で一度もX投稿していなかった。
    """
    rows = _run(["landingPage", "sessionSource"], ["sessions"], days)
    acc: dict[str, int] = {}
    for r in rows:
        if r["sessionSource"].lower() in X_SOURCES:
            acc[r["landingPage"]] = acc.get(r["landingPage"], 0) + r["sessions"]
    return sorted(({"page": k, "sessions": v} for k, v in acc.items()),
                  key=lambda x: -x["sessions"])


def posted_urls() -> set:
    """自社が X に投稿した記事 URL(のパス)。他者シェアと切り分けるために使う。"""
    import re
    log = BASE / "logs" / "x_posts.jsonl"
    out = set()
    if not log.exists():
        return out
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        for u in re.findall(r"https?://[^\s]+", d.get("text", "") + " "
                            + str(d.get("reply_text", ""))):
            m = re.sub(r"^https?://[^/]+", "", u).rstrip("/")
            if m:
                out.add(m)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--daily", action="store_true", help="日次推移も表示")
    ap.add_argument("--pages", action="store_true",
                    help="X由来の着地ページ内訳(自社投稿/他者シェアの切り分け)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true", help="logs/x_traffic_report.jsonl に追記")
    args = ap.parse_args()

    try:
        rep = collect(args.days)
    except Exception as e:
        print(f"[x_traffic_report] GA4取得失敗: {e}")
        print("  venv_kpi/bin/python3 で実行しているか確認してください")
        return 1
    if args.daily:
        rep["daily"] = daily_x(args.days)
    if args.pages:
        pages = x_landing_pages(args.days)
        posted = posted_urls()
        for p in pages:
            p["self_posted"] = p["page"].rstrip("/") in posted
        rep["pages"] = pages
        rep["x_self_posted_sessions"] = sum(p["sessions"] for p in pages
                                            if p["self_posted"])

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        p = rep["period"]
        print(f"=== X→サイト流入 ({p['start']}〜{p['end']}, {p['days']}日) ===")
        print(f"  総セッション   : {rep['total_sessions']:,}")
        print(f"  X由来(t.co等)  : {rep['x_sessions']:,} ({rep['x_share_pct']}%)")
        print(f"  X流入の質      : {rep['x_pv_per_session']} PV/セッション, "
              f"{rep['x_sec_per_session']}秒/セッション")
        print(f"  direct         : {rep['direct_sessions']:,} "
              "(プロフィール経由もここに混ざる)")
        print("  参考: 導線新設時(2026-08-17)のベースラインは 30dで37セッション(0.3%)")
        if rep.get("daily"):
            print("\n  日次推移:")
            for d in rep["daily"]:
                print(f"    {d['date']} {d['x_sessions']:4d}")
        if rep.get("pages") is not None:
            print(f"\n  X由来のうち自社投稿の記事: {rep['x_self_posted_sessions']} "
                  f"/ {rep['x_sessions']} セッション")
            print("  着地ページ内訳(自社=自社でX投稿した記事):")
            for p in rep["pages"][:10]:
                mark = "自社" if p["self_posted"] else "他者"
                print(f"    [{mark}] {p['sessions']:4d} {p['page'][:60]}")
        print("\n  流入元TOP:")
        for s in rep["top_sources"]:
            print(f"    {s['source']:26s} {s['sessions']:6d}")

    if args.save:
        from datetime import datetime
        rep["fetched_at"] = datetime.now().isoformat()
        with REPORT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rep, ensure_ascii=False) + "\n")
        print(f"\n  → {REPORT_LOG} に追記")
    return 0


if __name__ == "__main__":
    sys.exit(main())
