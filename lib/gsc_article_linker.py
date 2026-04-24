#!/usr/bin/env python3
"""
gsc_article_linker.py — GSC メトリクスを article_index.json に自動紐付け
3 期間 (48h / 7d / 30d) の page 別 impressions/clicks/ctr/position を取得し
記事ごとに集約して logs/gsc_article_map.json に保存。

使い方:
  python3 lib/gsc_article_linker.py              # 全期間取得
  python3 lib/gsc_article_linker.py --periods 7  # 7d のみ
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
SA_FILE = BASE / "google_metrics" / "service_account.json"
ARTICLE_INDEX = LOGS / "article_index.json"
OUT = LOGS / "gsc_article_map.json"
SITE_URL = "https://www.kpopjournal.tokyo/"

# 期間定義 (名前, 日数)
PERIODS = [
    ("48h", 2),
    ("7d", 7),
    ("30d", 30),
]


def _load_article_index() -> dict[str, dict]:
    """article_index.json を URL→記事メタ の dict に変換"""
    if not ARTICLE_INDEX.exists():
        return {}
    data = json.loads(ARTICLE_INDEX.read_text(encoding="utf-8"))
    articles = data if isinstance(data, list) else data.get("articles", [])
    url_map: dict[str, dict] = {}
    for a in articles:
        url = a.get("url", "").rstrip("/") + "/"
        url_map[url] = {
            "post_id": a.get("id"),
            "title": a.get("title", ""),
            "url": url,
        }
    return url_map


def _fetch_gsc_pages(days: int) -> list[dict]:
    """GSC Search Analytics API で page 別データを取得"""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        print("[gsc_article_linker] google-auth / googleapiclient 未インストール", file=sys.stderr)
        return []
    if not SA_FILE.exists():
        print(f"[gsc_article_linker] service_account.json が見つかりません: {SA_FILE}", file=sys.stderr)
        return []

    creds = service_account.Credentials.from_service_account_file(
        str(SA_FILE), scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
    )
    service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)

    end = date.today() - timedelta(days=2)  # GSC 2日ラグ
    start = end - timedelta(days=days - 1)

    all_rows: list[dict] = []
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
            res = service.searchanalytics().query(siteUrl=SITE_URL, body=body).execute()
        except Exception as e:
            print(f"[gsc_article_linker] API error ({days}d): {e}", file=sys.stderr)
            break
        rows = res.get("rows", [])
        if not rows:
            break
        all_rows.extend(rows)
        if len(rows) < 5000:
            break
        start_row += 5000

    # normalize
    pages = []
    for r in all_rows:
        url = r.get("keys", [""])[0]
        pages.append({
            "url": url,
            "impressions": int(r.get("impressions", 0)),
            "clicks": int(r.get("clicks", 0)),
            "ctr": round(float(r.get("ctr", 0)), 6),
            "position": round(float(r.get("position", 0)), 2),
        })
    pages.sort(key=lambda x: -x["impressions"])
    return pages


def _normalize_url(url: str) -> str:
    """末尾スラッシュを統一"""
    return url.rstrip("/") + "/"


def link_articles(period_filter: list[int] | None = None) -> dict:
    """
    GSC ページデータと article_index を紐付け。
    返り値: {period_name: {url: {post_id, title, metrics...}}}
    """
    article_map = _load_article_index()
    result: dict = {
        "generated_at": date.today().isoformat(),
        "site": SITE_URL,
        "periods": {},
        "summary": {},
    }

    target_periods = PERIODS
    if period_filter:
        target_periods = [(n, d) for n, d in PERIODS if d in period_filter]

    for period_name, days in target_periods:
        end = date.today() - timedelta(days=2)
        start = end - timedelta(days=days - 1)

        pages = _fetch_gsc_pages(days)

        linked: list[dict] = []
        unlinked: list[dict] = []

        for p in pages:
            norm_url = _normalize_url(p["url"])
            article = article_map.get(norm_url)
            entry = {**p}
            if article:
                entry["post_id"] = article["post_id"]
                entry["title"] = article["title"]
                entry["linked"] = True
                linked.append(entry)
            else:
                entry["post_id"] = None
                entry["title"] = None
                entry["linked"] = False
                unlinked.append(entry)

        all_entries = linked + unlinked

        result["periods"][period_name] = {
            "date_range": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
            "total_pages": len(all_entries),
            "linked_count": len(linked),
            "unlinked_count": len(unlinked),
            "articles": all_entries,
        }

        total_imp = sum(p["impressions"] for p in all_entries)
        total_clk = sum(p["clicks"] for p in all_entries)
        result["summary"][period_name] = {
            "pages": len(all_entries),
            "linked": len(linked),
            "total_impressions": total_imp,
            "total_clicks": total_clk,
            "avg_ctr": round(total_clk / max(total_imp, 1), 6),
        }

    return result


def main():
    ap = argparse.ArgumentParser(description="GSC→記事URL自動紐付けバッチ")
    ap.add_argument("--periods", type=int, nargs="*", help="対象日数 (2,7,30)")
    args = ap.parse_args()

    data = link_articles(args.periods)
    LOGS.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[gsc_article_linker] 保存: {OUT}")
    for pname, s in data["summary"].items():
        print(f"  {pname}: {s['pages']}ページ (紐付済={s['linked']}) / imp={s['total_impressions']} / clk={s['total_clicks']}")


if __name__ == "__main__":
    main()
