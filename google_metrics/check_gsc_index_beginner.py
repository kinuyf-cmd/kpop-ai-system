#!/usr/bin/env python3
"""
初心者ガイドクラスター（カテゴリ113）GSCインデックス状態確認スクリプト
Usage:
  python3 google_metrics/check_gsc_index_beginner.py
  python3 google_metrics/check_gsc_index_beginner.py --save   # ログ保存

確認項目: verdict / coverageState / lastCrawlTime / robotsTxtState / indexingState
"""

import json, urllib.request, urllib.parse, time, base64, os, argparse
from datetime import date
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

BASE = Path(__file__).parent.parent
SA_FILE = BASE / "google_metrics" / "service_account.json"
LOG_FILE = BASE / "logs" / "gsc_index_check_beginner.jsonl"

SITE_URL = "https://www.kpopjournal.tokyo/"

# 確認対象URL一覧（113クラスター 11記事）
TARGETS = [
    {"post_id": 2432, "title": "K-POPとは何か？初めての方向け基本ガイド",
     "url": "https://www.kpopjournal.tokyo/kpop-beginner-guide-2026/"},
    {"post_id": 2433, "title": "カムバックとは？K-POPの活動サイクル解説",
     "url": "https://www.kpopjournal.tokyo/kpop-comeback-meaning-guide/"},
    {"post_id": 2434, "title": "K-POP音楽番組の仕組み｜Music Bank等の違い",
     "url": "https://www.kpopjournal.tokyo/kpop-music-show-howto-guide/"},
    {"post_id": 2435, "title": "WeVerseとは？K-POPファンクラブアプリ入門",
     "url": "https://www.kpopjournal.tokyo/weverse-guide-beginner/"},
    {"post_id": 2436, "title": "K-POPライブ・コンサート初参戦ガイド",
     "url": "https://www.kpopjournal.tokyo/kpop-live-concert-beginner/"},
    {"post_id": 2437, "title": "K-POPグループの「世代」とは？1〜5世代解説",
     "url": "https://www.kpopjournal.tokyo/kpop-generation-guide/"},
    {"post_id": 2438, "title": "K-POPの推し活入門｜ファンダム文化の基本",
     "url": "https://www.kpopjournal.tokyo/kpop-fanculture-beginner/"},
    {"post_id": 2439, "title": "韓国語がわからなくてもK-POPを楽しむ5つの方法",
     "url": "https://www.kpopjournal.tokyo/kpop-enjoy-without-korean/"},
    {"post_id": 2440, "title": "K-POPアイドルの「所属事務所」入門",
     "url": "https://www.kpopjournal.tokyo/kpop-agency-beginner-guide/"},
    {"post_id": 2441, "title": "ABEMAとLeminoでK-POPを見る方法",
     "url": "https://www.kpopjournal.tokyo/kpop-abema-lemino-beginner/"},
    {"post_id": 2442, "title": "K-POP初心者ガイドまとめ【113ハブ】",
     "url": "https://www.kpopjournal.tokyo/kpop-beginner-hub-2026/"},
]


def get_access_token() -> str:
    with open(SA_FILE) as f:
        sa = json.load(f)

    def b64url(data):
        if isinstance(data, str): data = data.encode()
        return base64.urlsafe_b64encode(data).rstrip(b'=').decode()

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/webmasters.readonly",
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now, "exp": now + 3600,
    }
    signing_input = f"{b64url(json.dumps(header))}.{b64url(json.dumps(claims))}".encode()
    private_key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    jwt = f"{signing_input.decode()}.{b64url(sig)}"

    data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt,
    }).encode()
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["access_token"]


def inspect_url(url: str, access_token: str) -> dict:
    payload = json.dumps({
        "inspectionUrl": url,
        "siteUrl": SITE_URL,
    }).encode()
    req = urllib.request.Request(
        "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
        data=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true", help="ログをJSONLに保存")
    args = parser.parse_args()

    print(f"[check_gsc_index_beginner] 実行日: {date.today()}")
    print(f"対象: {len(TARGETS)}記事\n")

    token = get_access_token()
    results = []

    for t in TARGETS:
        result = inspect_url(t["url"], token)
        if "error" in result:
            verdict = "ERROR"
            coverage = result["error"]
            last_crawl = "-"
            robots = "-"
            indexing = "-"
        else:
            idx_result = result.get("inspectionResult", {}).get("indexStatusResult", {})
            verdict = idx_result.get("verdict", "UNKNOWN")
            coverage = idx_result.get("coverageState", "UNKNOWN")
            last_crawl = idx_result.get("lastCrawlTime", "-")[:10] if idx_result.get("lastCrawlTime") else "-"
            robots = idx_result.get("robotsTxtState", "-")
            indexing = idx_result.get("indexingState", "-")

        icon = "✅" if verdict == "PASS" else ("🔄" if last_crawl != "-" else "⏳")
        print(f"{icon} [{t['post_id']}] {t['title'][:35]:<35}")
        print(f"   verdict={verdict} | coverage={coverage}")
        print(f"   lastCrawl={last_crawl} | robots={robots} | indexing={indexing}")

        entry = {
            "checked_at": date.today().isoformat(),
            "post_id": t["post_id"],
            "title": t["title"],
            "url": t["url"],
            "verdict": verdict,
            "coverageState": coverage,
            "lastCrawlTime": last_crawl,
            "robotsTxtState": robots,
            "indexingState": indexing,
        }
        results.append(entry)

    # サマリー
    indexed = sum(1 for r in results if r["verdict"] == "PASS")
    crawled = sum(1 for r in results if r["lastCrawlTime"] != "-")
    unknown = sum(1 for r in results if "unknown" in r.get("coverageState", "").lower())
    print(f"\n=== サマリー ===")
    print(f"インデックス済み: {indexed}/{len(results)}")
    print(f"クロール済み:     {crawled}/{len(results)}")
    print(f"未登録(unknown): {unknown}/{len(results)}")

    if args.save:
        with open(LOG_FILE, "a") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n✅ ログ保存: {LOG_FILE}")


if __name__ == "__main__":
    main()
