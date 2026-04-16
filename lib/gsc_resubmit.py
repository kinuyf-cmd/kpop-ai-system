#!/usr/bin/env python3
"""gsc_resubmit.py — GSC (Google Indexing API) 優先URL一括再送信

優先順:
  1. BTS 関連
  2. BLACKPINK 関連
  3. トラフィック上位 (metrics_yesterday.json / GSC logs があれば)
  4. 直近の投稿

使い方:
  python3 lib/gsc_resubmit.py [--top 30] [--dry-run]
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
LOGS.mkdir(exist_ok=True)
OUT_LOG = LOGS / "gsc_resubmit_log.jsonl"
SITEMAP_INDEX = "https://www.kpopjournal.tokyo/sitemap.xml"
REQUEST_INDEX_SH = BASE / "google_metrics" / "request_index.sh"
JST = timezone(timedelta(hours=9))

PRIORITY_KEYWORDS = [
    ("bts", 100),       # rank weight
    ("blackpink", 95),
    ("bigbang", 80),
    ("twice", 80),
    ("newjeans", 80),
    ("aespa", 75),
    ("ive", 75),
    ("illit", 70),
    ("le-sserafim", 70),
    ("seventeen", 65),
    ("enhypen", 65),
    ("babymonster", 60),
    ("shinee", 60),
    ("taemin", 55),
    ("nct", 55),
    ("txt", 50),
    ("stray", 50),
]


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "gsc-resubmit/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


def collect_urls_from_sitemap() -> list[dict]:
    """sitemap_indexから全URLとlastmodを取得"""
    index_xml = fetch(SITEMAP_INDEX)
    sub_sitemaps = re.findall(r"<loc>([^<]+)</loc>", index_xml)
    urls = []
    for sm in sub_sitemaps:
        if "posts-post" not in sm:
            continue
        try:
            sub = fetch(sm)
            for m in re.finditer(r"<url>\s*<loc>([^<]+)</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?", sub):
                urls.append({"url": m.group(1), "lastmod": m.group(2) or ""})
        except Exception as e:
            print(f"  [warn] sub sitemap fetch failed: {sm} {e}", file=sys.stderr)
    return urls


def score_url(u: dict) -> int:
    url = u["url"].lower()
    score = 0
    for kw, weight in PRIORITY_KEYWORDS:
        if kw in url:
            score = max(score, weight)
    # recent posts bonus (lastmod within 14 days)
    try:
        if u.get("lastmod"):
            ts = datetime.fromisoformat(u["lastmod"].replace("Z", "+00:00"))
            days = (datetime.now(tz=JST) - ts.astimezone(JST)).days
            if days <= 3:
                score += 40
            elif days <= 7:
                score += 25
            elif days <= 14:
                score += 10
    except Exception:
        pass
    return score


def submit_url(url: str, dry_run: bool) -> tuple[bool, str]:
    if dry_run:
        return True, "dry-run"
    try:
        r = subprocess.run(
            ["bash", str(REQUEST_INDEX_SH), url],
            timeout=30, capture_output=True, text=True,
        )
        out = (r.stdout + r.stderr).strip()
        ok = "インデックス登録リクエスト成功" in out or "urlNotificationMetadata" in out
        return ok, out[-300:]
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, f"error:{e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"[gsc_resubmit] sitemap から URL を収集中...")
    urls = collect_urls_from_sitemap()
    print(f"[gsc_resubmit] {len(urls)}件取得")

    scored = [(u, score_url(u)) for u in urls]
    scored.sort(key=lambda x: -x[1])
    top = scored[: args.top]

    ts = datetime.now(tz=JST).isoformat()
    success = 0
    fail = 0
    with OUT_LOG.open("a") as fp:
        for u, sc in top:
            ok, msg = submit_url(u["url"], args.dry_run)
            result = "ok" if ok else "fail"
            line = json.dumps({
                "ts": ts, "url": u["url"], "score": sc,
                "lastmod": u.get("lastmod", ""), "result": result,
                "detail": msg[:120],
            }, ensure_ascii=False)
            fp.write(line + "\n")
            mark = "✅" if ok else "❌"
            print(f"  {mark} score={sc:3d} {u['url']}")
            if ok:
                success += 1
            else:
                fail += 1

    print()
    print(f"[gsc_resubmit] 完了: 成功={success} / 失敗={fail} / 対象={len(top)}")
    print(f"  ログ: {OUT_LOG}")


if __name__ == "__main__":
    main()
