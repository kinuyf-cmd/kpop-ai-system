#!/usr/bin/env python3
"""gsc_indexing.py — Google Search Console Indexing API integration.
Sends URL_UPDATED notifications for newly published articles.

認証: google_metrics/service_account.json (indexing スコープ)

使い方:
  python3 lib/gsc_indexing.py --url "https://example.com/article"
  python3 lib/gsc_indexing.py --backfill --since "2026-04-23"
  python3 lib/gsc_indexing.py --status
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
DATA = BASE / "data"
SA_FILE = BASE / "google_metrics" / "service_account.json"
INDEX_LOG = DATA / "gsc_indexing_log.jsonl"
SITE_URL = "https://www.kpopjournal.tokyo/"
KPI_POSTS = LOGS / "kpi_posts.jsonl"
JST = timezone(timedelta(hours=9))

INDEXING_API_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
INDEXING_API_SCOPE = "https://www.googleapis.com/auth/indexing"
SITEMAP_PING_URL = "https://www.google.com/ping?sitemap="


# ── Auth helpers ──────────────────────────────────────────────


def _get_access_token_google_auth() -> str | None:
    """Try using google-auth library (preferred, available in venv)."""
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request

        creds = service_account.Credentials.from_service_account_file(
            str(SA_FILE), scopes=[INDEXING_API_SCOPE]
        )
        creds.refresh(Request())
        return creds.token
    except ImportError:
        return None
    except Exception as e:
        print(f"[gsc_indexing] google-auth token取得エラー: {e}", file=sys.stderr)
        return None


def _get_access_token_jwt() -> str | None:
    """Fallback: build JWT manually with cryptography lib."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        import base64
    except ImportError:
        return None

    try:
        sa = json.loads(SA_FILE.read_text())
    except Exception as e:
        print(f"[gsc_indexing] service_account.json読み込みエラー: {e}", file=sys.stderr)
        return None

    def b64url(data):
        if isinstance(data, str):
            data = data.encode()
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": sa["client_email"],
        "scope": INDEXING_API_SCOPE,
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }
    signing_input = f"{b64url(json.dumps(header))}.{b64url(json.dumps(claims))}".encode()
    pk = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = pk.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    jwt_token = f"{signing_input.decode()}.{b64url(sig)}"
    data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt_token,
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())["access_token"]
    except Exception as e:
        print(f"[gsc_indexing] JWT token交換エラー: {e}", file=sys.stderr)
        return None


def get_access_token() -> str | None:
    """Get access token, trying google-auth first, then manual JWT."""
    if not SA_FILE.exists():
        print(f"[gsc_indexing] service_account.json が見つかりません: {SA_FILE}", file=sys.stderr)
        return None
    token = _get_access_token_google_auth()
    if token:
        return token
    token = _get_access_token_jwt()
    if token:
        return token
    print("[gsc_indexing] 認証方法がありません。google-auth または cryptography をインストールしてください。",
          file=sys.stderr)
    return None


# ── Logging ───────────────────────────────────────────────────


def _log_entry(entry: dict) -> None:
    """Append one JSON line to data/gsc_indexing_log.jsonl."""
    DATA.mkdir(exist_ok=True)
    with INDEX_LOG.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── Core functions ────────────────────────────────────────────


def notify_url_updated(url: str, token: str | None = None) -> dict:
    """Send URL_UPDATED notification to Google Indexing API.

    Returns dict with keys: status, url, timestamp, response
    """
    ts = datetime.now(tz=JST).isoformat()

    if token is None:
        token = get_access_token()
    if token is None:
        # Fallback: sitemap ping
        result = _sitemap_ping_fallback(url)
        result["timestamp"] = ts
        _log_entry(result)
        return result

    payload = json.dumps({"url": url, "type": "URL_UPDATED"}).encode()
    req = urllib.request.Request(
        INDEXING_API_ENDPOINT,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )

    max_retries = 3
    last_error = ""
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read())
                result = {
                    "status": "ok",
                    "url": url,
                    "timestamp": ts,
                    "response": body,
                    "method": "indexing_api",
                }
                _log_entry(result)
                return result
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            last_error = f"HTTP {e.code}: {err_body}"
            # 403 often means indexing API scope not granted
            if e.code == 403:
                print(f"[gsc_indexing] 403 Forbidden — Indexing API スコープ未設定の可能性。"
                      f"sitemap ping にフォールバックします。", file=sys.stderr)
                result = _sitemap_ping_fallback(url)
                result["timestamp"] = ts
                result["original_error"] = last_error
                _log_entry(result)
                return result
            if e.code == 429:
                # Rate limit — wait and retry
                delay = 5 * (attempt + 1)
                print(f"  [warn] 429 Rate limit, {delay}秒後にリトライ...", file=sys.stderr)
                time.sleep(delay)
                continue
            # Other HTTP errors
            if attempt < max_retries - 1:
                time.sleep(3)
                continue
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                time.sleep(3)
                continue

    # All retries exhausted
    result = {
        "status": "error",
        "url": url,
        "timestamp": ts,
        "response": {"error": last_error},
        "method": "indexing_api",
    }
    _log_entry(result)
    return result


def _sitemap_ping_fallback(url: str) -> dict:
    """Fallback: ping Google with sitemap URL when Indexing API is unavailable."""
    sitemap_url = SITE_URL.rstrip("/") + "/sitemap.xml"
    ping_url = SITEMAP_PING_URL + urllib.parse.quote(sitemap_url, safe="")
    try:
        req = urllib.request.Request(ping_url, headers={"User-Agent": "gsc-indexing/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            status_code = resp.getcode()
            return {
                "status": "fallback_ok" if status_code == 200 else "fallback_error",
                "url": url,
                "response": {"ping_url": ping_url, "http_status": status_code},
                "method": "sitemap_ping",
            }
    except Exception as e:
        return {
            "status": "fallback_error",
            "url": url,
            "response": {"error": str(e)},
            "method": "sitemap_ping",
        }


def backfill_recent(since_date: str, dry_run: bool = False) -> list[dict]:
    """Submit all articles published since the given date.

    Reads from logs/kpi_posts.jsonl to find recently published URLs.
    Falls back to WP REST API if kpi_posts.jsonl unavailable.
    """
    urls = _get_recent_urls(since_date)
    if not urls:
        print(f"[gsc_indexing] {since_date} 以降の記事が見つかりません。")
        return []

    print(f"[gsc_indexing] {since_date} 以降の記事: {len(urls)}件")

    if dry_run:
        for u in urls:
            print(f"  [dry-run] {u}")
        return [{"status": "dry-run", "url": u} for u in urls]

    token = get_access_token()
    results = []
    for i, url in enumerate(urls, 1):
        result = notify_url_updated(url, token=token)
        mark = "OK" if result["status"] == "ok" else result["status"].upper()
        print(f"  [{i}/{len(urls)}] {mark} {url}")
        results.append(result)
        # Rate limiting
        time.sleep(0.5)

    ok = sum(1 for r in results if r["status"] == "ok")
    fallback = sum(1 for r in results if "fallback" in r.get("status", ""))
    err = sum(1 for r in results if r["status"] == "error")
    print(f"\n[gsc_indexing] backfill完了: ok={ok} fallback={fallback} error={err}")
    return results


def _get_recent_urls(since_date: str) -> list[str]:
    """Get URLs of articles published since the given date."""
    urls: list[str] = []
    seen: set[str] = set()

    # Source 1: kpi_posts.jsonl
    if KPI_POSTS.exists():
        for line in KPI_POSTS.read_text(errors="replace").splitlines():
            try:
                d = json.loads(line)
                post_date = d.get("date", d.get("timestamp", ""))[:10]
                if post_date >= since_date:
                    url = d.get("url", "")
                    if url and url not in seen:
                        seen.add(url)
                        urls.append(url)
            except Exception:
                continue

    # Source 2: WP REST API fallback (if kpi_posts.jsonl yielded nothing)
    if not urls:
        urls = _get_urls_from_wp_api(since_date)

    return urls


def _get_urls_from_wp_api(since_date: str) -> list[str]:
    """Fetch recent article URLs from WordPress REST API."""
    import subprocess
    WP = "https://www.kpopjournal.tokyo"
    AUTH = str(Path.home() / ".wp_auth")
    urls: list[str] = []
    page = 1
    while True:
        cmd = [
            "curl", "-s",
            f"{WP}/wp-json/wp/v2/posts?per_page=50&page={page}"
            f"&status=publish&after={since_date}T00:00:00&_fields=link",
            "-K", AUTH,
        ]
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
    return urls


def check_index_status(urls: list[str] | None = None) -> list[dict]:
    """Check index status of recently submitted URLs.

    If urls is None, reads from data/gsc_indexing_log.jsonl to get recent submissions.
    Uses URL Inspection API to verify indexation.
    """
    if urls is None:
        urls = _get_recent_submitted_urls()

    if not urls:
        print("[gsc_indexing] チェック対象のURLがありません。")
        return []

    token = get_access_token()
    if not token:
        print("[gsc_indexing] 認証失敗。ステータス確認をスキップします。", file=sys.stderr)
        return []

    print(f"[gsc_indexing] {len(urls)}件のURLをチェック中...")
    results = []
    for i, url in enumerate(urls, 1):
        result = _inspect_url(url, token)
        status = _categorize_inspection(result)
        entry = {
            "url": url,
            "index_status": status,
            "checked_at": datetime.now(tz=JST).isoformat(),
            "verdict": result.get("inspectionResult", {}).get("indexStatusResult", {}).get("verdict", ""),
            "coverage": result.get("inspectionResult", {}).get("indexStatusResult", {}).get("coverageState", ""),
        }
        results.append(entry)
        mark = {"indexed": "OK", "submitted": "PENDING", "not_indexed": "NOT_INDEXED", "error": "ERROR"}.get(status, "?")
        print(f"  [{i}/{len(urls)}] {mark:12s} {url}")
        # Rate limit for URL Inspection API
        time.sleep(0.3)

    # Log results
    ts = datetime.now(tz=JST).isoformat()
    for r in results:
        _log_entry({"action": "status_check", **r})

    counts = {}
    for r in results:
        s = r["index_status"]
        counts[s] = counts.get(s, 0) + 1
    print(f"\n[gsc_indexing] ステータス確認完了: {counts}")
    return results


def _get_recent_submitted_urls(limit: int = 30) -> list[str]:
    """Read recently submitted URLs from the indexing log."""
    if not INDEX_LOG.exists():
        return []
    urls = []
    seen = set()
    lines = INDEX_LOG.read_text(errors="replace").splitlines()
    for line in reversed(lines):
        try:
            d = json.loads(line)
            if d.get("action") == "status_check":
                continue
            url = d.get("url", "")
            if url and url not in seen and d.get("status") in ("ok", "fallback_ok"):
                seen.add(url)
                urls.append(url)
                if len(urls) >= limit:
                    break
        except Exception:
            continue
    return urls


def _inspect_url(url: str, token: str) -> dict:
    """Call URL Inspection API."""
    payload = json.dumps({"inspectionUrl": url, "siteUrl": SITE_URL}).encode()
    req = urllib.request.Request(
        "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def _categorize_inspection(r: dict) -> str:
    """Categorize URL Inspection result into indexed/submitted/not_indexed/error."""
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


# ── CLI ───────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(
        description="GSC Indexing API — URL_UPDATED通知・バックフィル・ステータス確認"
    )
    ap.add_argument("--url", type=str, help="単一URLを送信")
    ap.add_argument("--backfill", action="store_true", help="期間内の全記事を送信")
    ap.add_argument("--since", type=str, default="", help="バックフィル開始日 (YYYY-MM-DD)")
    ap.add_argument("--status", action="store_true", help="最近送信したURLのインデックス状況を確認")
    ap.add_argument("--dry-run", action="store_true", help="実際には送信しない")
    args = ap.parse_args()

    if args.url:
        # Single URL submission
        if args.dry_run:
            print(f"[dry-run] {args.url}")
            return
        result = notify_url_updated(args.url)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] == "ok":
            print(f"\nURL_UPDATED 送信成功: {args.url}")
        elif "fallback" in result["status"]:
            print(f"\nIndexing API 不可のため sitemap ping で代替: {args.url}")
        else:
            print(f"\n送信失敗: {args.url}", file=sys.stderr)
            sys.exit(1)

    elif args.backfill:
        since = args.since
        if not since:
            # Default: 7 days ago
            since = (datetime.now(tz=JST) - timedelta(days=7)).strftime("%Y-%m-%d")
            print(f"[gsc_indexing] --since 未指定のため直近7日 ({since}〜) を対象にします")
        backfill_recent(since, dry_run=args.dry_run)

    elif args.status:
        check_index_status()

    else:
        ap.print_help()


if __name__ == "__main__":
    main()
