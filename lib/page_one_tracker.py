#!/usr/bin/env python3
"""page_one_tracker.py — 「Google検索1ページ目進出」を週次で計測する(読み取りのみ)。

2ヶ月計画の主KPI:
  - primary: position < 10(1ページ目)への進入記事数
  - stretch: position < 3(上位)への進入記事数

着手前に --baseline で対象 query/page の現在 position を固定し、毎週の差分を記録。
判定窓: enrich/Indexing から最低14日後に効果判定(GSC は2-3日遅延+再評価に時間)。

使い方:
  venv_kpi/bin/python3 lib/page_one_tracker.py --baseline   # Week0 ベースライン固定
  venv_kpi/bin/python3 lib/page_one_tracker.py              # 週次計測(差分を progress に追記)
依存: service_account.json(venv_kpi)。書き込みは baseline/progress JSON のみ。
"""
import os
import sys
import json
import argparse
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SA_FILE = os.path.join(BASE_DIR, "google_metrics", "service_account.json")
SITE = os.environ.get("GSC_SITE_URL", "https://www.kpopjournal.tokyo/")

QUEUE_IN = os.path.join(BASE_DIR, "data", "seo_opportunity_queue.json")
ENRICH_QUEUE = os.path.join(BASE_DIR, "data", "enrich_queue.json")
BASELINE = os.path.join(BASE_DIR, "data", "page_one_baseline.json")
PROGRESS = os.path.join(BASE_DIR, "data", "page_one_progress.jsonl")


def _service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        SA_FILE, scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    return build("searchconsole", "v1", credentials=creds)


def _query_position(svc, query, days=28):
    """直近 days のそのクエリの position/clicks(query 次元)。無ければ None。"""
    end = date.today().isoformat()
    start = (date.today() - timedelta(days=days)).isoformat()
    body = {
        "startDate": start, "endDate": end,
        "dimensions": ["query"],
        "dimensionFilterGroups": [{
            "filters": [{"dimension": "query", "operator": "equals", "expression": query}]
        }],
        "rowLimit": 1,
    }
    try:
        res = svc.searchanalytics().query(siteUrl=SITE, body=body).execute()
    except Exception as e:
        print(f"  GSC error query={query!r}: {e}", file=sys.stderr)
        return None
    rows = res.get("rows", [])
    if not rows:
        return None
    r = rows[0]
    return {"position": float(r.get("position", 0.0)),
            "clicks": int(r.get("clicks", 0)),
            "impressions": int(r.get("impressions", 0))}


def _target_queries():
    """追跡対象クエリ = enrich_queue + Lane C/B 上位(着手対象)。"""
    qs = {}
    if os.path.exists(ENRICH_QUEUE):
        try:
            for r in json.load(open(ENRICH_QUEUE, encoding="utf-8")):
                if r.get("query"):
                    qs[r["query"]] = {"slug": r.get("slug", ""), "potential": r.get("potential", 0)}
        except Exception:
            pass
    if os.path.exists(QUEUE_IN):
        try:
            q = json.load(open(QUEUE_IN, encoding="utf-8"))
            for r in (q.get("lane_C_rewrite", [])[:30] + q.get("lane_B_new", [])[:20]):
                qs.setdefault(r["query"], {"slug": "", "potential": r.get("potential", 0)})
        except Exception:
            pass
    return qs


def do_baseline():
    svc = _service()
    targets = _target_queries()
    base = {"created": date.today().isoformat(), "queries": {}}
    for query, meta in targets.items():
        pos = _query_position(svc, query)
        if pos:
            base["queries"][query] = {
                "baseline_pos": round(pos["position"], 2),
                "baseline_clicks": pos["clicks"],
                "slug": meta["slug"], "potential": meta["potential"],
            }
    json.dump(base, open(BASELINE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[tracker] baseline 固定: {len(base['queries'])} queries → {BASELINE}")
    return 0


def do_weekly():
    if not os.path.exists(BASELINE):
        print("[tracker] baseline が無い。先に --baseline を実行してください。", file=sys.stderr)
        return 1
    base = json.load(open(BASELINE, encoding="utf-8"))
    svc = _service()
    week = date.today().isoformat()
    crossed_10 = crossed_3 = 0
    rows = []
    for query, b in base["queries"].items():
        cur = _query_position(svc, query)
        if not cur:
            continue
        bp, cp = b["baseline_pos"], round(cur["position"], 2)
        c10 = (bp >= 10) and (cp < 10)   # 新たに1ページ目進入
        c3 = (bp >= 3) and (cp < 3)      # 新たに上位進入
        if c10:
            crossed_10 += 1
        if c3:
            crossed_3 += 1
        rec = {
            "week": week, "query": query, "slug": b.get("slug", ""),
            "baseline_pos": bp, "current_pos": cp,
            "crossed_10": c10, "crossed_3": c3,
            "clicks_delta": cur["clicks"] - b.get("baseline_clicks", 0),
            "potential": b.get("potential", 0),
        }
        rows.append(rec)
        with open(PROGRESS, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    in_page1 = sum(1 for r in rows if r["current_pos"] < 10)
    in_top3 = sum(1 for r in rows if r["current_pos"] < 3)
    total_clicks_delta = sum(r["clicks_delta"] for r in rows)
    print(f"[tracker] 週次計測 {week}")
    print(f"  追跡クエリ: {len(rows)}")
    print(f"  今週 新規 pos<10 進入: {crossed_10} / 新規 pos<3 進入: {crossed_3}")
    print(f"  現在 pos<10: {in_page1} / pos<3: {in_top3}")
    print(f"  clicks増分(baseline比): {total_clicks_delta:+d}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true", help="Week0 ベースライン固定")
    args = ap.parse_args()
    sys.exit(do_baseline() if args.baseline else do_weekly())


if __name__ == "__main__":
    main()
