#!/usr/bin/env python3
"""gsc_metrics_fetcher.py — Google Search Console Search Analytics API で
page別の impressions / clicks / ctr / position を取得し logs/gsc_metrics_latest.json に保存。

認証: google_metrics/service_account.json (webmasters.readonly スコープ)

使い方:
  python3 lib/gsc_metrics_fetcher.py              # 直近28日 全ページ
  python3 lib/gsc_metrics_fetcher.py --days 7     # 直近7日
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
SA_FILE = BASE / "google_metrics" / "service_account.json"
OUT = LOGS / "gsc_metrics_latest.json"
SITE_URL = "https://www.kpopjournal.tokyo/"


def fetch_gsc(days: int) -> dict:
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        print("[gsc_metrics_fetcher] google-auth/googleapiclient 未インストール — venv有効化が必要", file=sys.stderr)
        return {}
    if not SA_FILE.exists():
        print(f"[gsc_metrics_fetcher] service_account.json が見つかりません: {SA_FILE}", file=sys.stderr)
        return {}
    creds = service_account.Credentials.from_service_account_file(
        str(SA_FILE), scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
    )
    service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    end = date.today() - timedelta(days=2)  # GSCは2日ラグ
    start = end - timedelta(days=days - 1)

    all_rows = []
    start_row = 0
    while True:
        body = {
            "startDate": start.isoformat(),
            "endDate":   end.isoformat(),
            "dimensions": ["page"],
            "rowLimit":   5000,
            "startRow":   start_row,
        }
        try:
            res = service.searchanalytics().query(siteUrl=SITE_URL, body=body).execute()
        except Exception as e:
            print(f"[gsc_metrics_fetcher] API error: {e}", file=sys.stderr)
            break
        rows = res.get("rows", [])
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < 5000:
            break
        start_row += 5000

    return {
        "site":       SITE_URL,
        "date_range": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "row_count":  len(all_rows),
        "rows":       all_rows,
    }


def normalize(raw: dict) -> dict:
    rows = raw.get("rows", [])
    # dimensions[0] = page
    norm = []
    for r in rows:
        page = r.get("keys", [""])[0]
        norm.append({
            "url":         page,
            "impressions": int(r.get("impressions", 0)),
            "clicks":      int(r.get("clicks", 0)),
            "ctr":         float(r.get("ctr", 0)),  # 0.0〜1.0
            "position":    float(r.get("position", 0)),
        })
    norm.sort(key=lambda x: -x["impressions"])
    return {
        "site":       raw.get("site"),
        "date_range": raw.get("date_range"),
        "row_count":  len(norm),
        "pages":      norm,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    args = ap.parse_args()

    raw = fetch_gsc(args.days)
    if not raw:
        # 空のファイル出力で後続スクリプトが落ちないように
        OUT.write_text(json.dumps({"site": SITE_URL, "row_count": 0, "pages": [], "note": "auth or API failure"}, ensure_ascii=False))
        print(f"[gsc_metrics_fetcher] 空データ保存: {OUT}")
        return
    norm = normalize(raw)
    OUT.write_text(json.dumps(norm, ensure_ascii=False, indent=2))
    imp = sum(p["impressions"] for p in norm["pages"])
    clk = sum(p["clicks"] for p in norm["pages"])
    print(f"[gsc_metrics_fetcher] 保存: {OUT}")
    print(f"  期間: {norm['date_range']['start']}〜{norm['date_range']['end']}")
    print(f"  ページ数: {norm['row_count']} / 総impr: {imp} / 総clicks: {clk}")


if __name__ == "__main__":
    main()
