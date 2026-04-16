#!/usr/bin/env python3
"""gsc_index_tracker.py — URL Inspection API で全記事（またはgsc_resubmit_logの対象）の
インデックス状態 (submitted / indexed / not_indexed) を取得してログ保存。

ソース:
  - logs/gsc_resubmit_log.jsonl (直近で送信した URL)
  - または --all で WP API の全公開記事

出力:
  - logs/gsc_index_status.jsonl (追記)
  - logs/gsc_index_summary.json (最新サマリ — ダッシュボード連携用)

使い方:
  python3 lib/gsc_index_tracker.py            # 直近gsc_resubmit対象を確認
  python3 lib/gsc_index_tracker.py --all      # 全公開記事（時間がかかる）
  python3 lib/gsc_index_tracker.py --limit 30 # 最大件数指定
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
SA_FILE = BASE / "google_metrics" / "service_account.json"
STATUS_JSONL = LOGS / "gsc_index_status.jsonl"
SUMMARY = LOGS / "gsc_index_summary.json"
SITE_URL = "https://www.kpopjournal.tokyo/"
JST = timezone(timedelta(hours=9))


def get_access_token() -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    import base64, urllib.request, urllib.parse
    sa = json.loads(SA_FILE.read_text())

    def b64url(data):
        if isinstance(data, str):
            data = data.encode()
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/webmasters.readonly",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now, "exp": now + 3600,
    }
    signing_input = f"{b64url(json.dumps(header))}.{b64url(json.dumps(claims))}".encode()
    pk = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = pk.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{signing_input.decode()}.{b64url(sig)}"
    data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt,
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["access_token"]


def inspect_url(url: str, token: str) -> dict:
    import urllib.request
    payload = json.dumps({"inspectionUrl": url, "siteUrl": SITE_URL}).encode()
    req = urllib.request.Request(
        "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def categorize(r: dict) -> str:
    """verdict/coverageState から indexed/submitted/not_indexed/error に分類"""
    if "error" in r:
        return "error"
    idx = r.get("inspectionResult", {}).get("indexStatusResult", {})
    v = idx.get("verdict", "UNKNOWN")
    cov = idx.get("coverageState", "").lower()
    if v == "PASS":
        return "indexed"
    if "submitted" in cov or "discovered" in cov or v == "PARTIAL":
        return "submitted"
    if "excluded" in cov or "noindex" in cov or v == "FAIL":
        return "not_indexed"
    if idx.get("lastCrawlTime"):
        return "submitted"
    return "not_indexed"


def get_urls_from_resubmit_log(limit: int) -> list[str]:
    p = LOGS / "gsc_resubmit_log.jsonl"
    if not p.exists():
        return []
    urls = []
    seen = set()
    # 最新順
    for line in reversed(p.read_text(errors="replace").splitlines()):
        try:
            d = json.loads(line)
            u = d.get("url", "")
            if u and u not in seen:
                seen.add(u)
                urls.append(u)
                if len(urls) >= limit:
                    break
        except Exception:
            continue
    return urls


def get_all_urls(limit: int) -> list[str]:
    import subprocess
    WP = "https://www.kpopjournal.tokyo"
    AUTH = str(Path.home() / ".wp_auth")
    urls = []
    page = 1
    while len(urls) < limit:
        cmd = ["curl", "-s", f"{WP}/wp-json/wp/v2/posts?per_page=50&page={page}"
               "&status=publish&_fields=link", "-K", AUTH]
        try:
            batch = json.loads(subprocess.check_output(cmd, timeout=30).decode())
        except Exception:
            break
        if not batch or not isinstance(batch, list):
            break
        urls.extend(p["link"] for p in batch if p.get("link"))
        if len(batch) < 50:
            break
        page += 1
    return urls[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args()

    urls = get_all_urls(args.limit) if args.all else get_urls_from_resubmit_log(args.limit)
    print(f"[gsc_index_tracker] 対象 {len(urls)} URL")
    if not urls:
        print("  URL がありません。--all または gsc_resubmit_log.jsonl が必要")
        return

    try:
        token = get_access_token()
    except Exception as e:
        print(f"[gsc_index_tracker] 認証エラー: {e}", file=sys.stderr)
        return

    now = datetime.now(tz=JST).isoformat()
    counts = {"indexed": 0, "submitted": 0, "not_indexed": 0, "error": 0}
    details = []
    with STATUS_JSONL.open("a") as fp:
        for i, u in enumerate(urls, 1):
            r = inspect_url(u, token)
            status = categorize(r)
            counts[status] += 1
            idx = r.get("inspectionResult", {}).get("indexStatusResult", {}) if "error" not in r else {}
            entry = {
                "checked_at": now, "url": u, "status": status,
                "verdict": idx.get("verdict", ""),
                "coverage": idx.get("coverageState", ""),
                "last_crawl": (idx.get("lastCrawlTime", "") or "")[:10],
                "indexing": idx.get("indexingState", ""),
                "error": r.get("error", "")[:200],
            }
            fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
            details.append(entry)
            mark = {"indexed": "✅", "submitted": "🔄", "not_indexed": "⏳", "error": "❌"}[status]
            print(f"  {mark} [{i:3d}/{len(urls)}] {status:12s} {u}")
            # Rate limiting: GSC Inspection API は 1分600req だが余裕で0.2秒
            time.sleep(0.3)

    total = sum(counts.values())
    indexed_rate = (counts["indexed"] / total * 100) if total else 0
    summary = {
        "generated_at": now,
        "total_checked": total,
        "counts": counts,
        "indexed_rate_pct": round(indexed_rate, 1),
        "recent_details": details[-20:],
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print()
    print(f"[gsc_index_tracker] 完了: indexed={counts['indexed']} "
          f"submitted={counts['submitted']} not_indexed={counts['not_indexed']} "
          f"error={counts['error']} / インデックス率={indexed_rate:.1f}%")
    print(f"  サマリ: {SUMMARY}")


if __name__ == "__main__":
    main()
