#!/usr/bin/env python3
"""
プロフィールクラスター（カテゴリ112）GSCインデックス状態確認スクリプト
Usage:
  python3 google_metrics/check_gsc_index_profile.py
  python3 google_metrics/check_gsc_index_profile.py --save   # ログ保存

確認項目: verdict / coverageState / lastCrawlTime / robotsTxtState / indexingState
"""

import json, urllib.request, urllib.parse, time, base64, os, argparse
from datetime import date
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

BASE = Path(__file__).parent.parent
SA_FILE = BASE / "google_metrics" / "service_account.json"
LOG_FILE = BASE / "logs" / "gsc_index_check_profile.jsonl"

SITE_URL = "https://www.kpopjournal.tokyo/"

# 確認対象URL一覧（112クラスター 11記事）
TARGETS = [
    {"post_id": 2475, "title": "BTSとは？7人のプロフィールと現在の活動状況【2026年最新】",
     "url": "https://www.kpopjournal.tokyo/bts-profile-2026/"},
    {"post_id": 2476, "title": "IVEとは？6人のメンバーと代表曲・人気の理由",
     "url": "https://www.kpopjournal.tokyo/ive-profile-2026/"},
    {"post_id": 2477, "title": "aespaとは？世界観・4人のメンバー・代表曲まとめ",
     "url": "https://www.kpopjournal.tokyo/aespa-profile-2026/"},
    {"post_id": 2478, "title": "NewJeansとは？5人のメンバー・活動状況・代表曲",
     "url": "https://www.kpopjournal.tokyo/newjeans-profile-2026/"},
    {"post_id": 2479, "title": "SEVENTEENとは？13人の構成・ユニット・人気の理由",
     "url": "https://www.kpopjournal.tokyo/seventeen-profile-2026/"},
    {"post_id": 2480, "title": "BLACKPINKとは？4人のメンバー・ソロ活動・代表曲",
     "url": "https://www.kpopjournal.tokyo/blackpink-profile-2026/"},
    {"post_id": 2481, "title": "Stray Kidsとは？メンバー・セルフプロデュース・代表曲",
     "url": "https://www.kpopjournal.tokyo/straykids-profile-2026/"},
    {"post_id": 2482, "title": "TWICEとは？9人のメンバー・日本での人気・代表曲",
     "url": "https://www.kpopjournal.tokyo/twice-profile-2026/"},
    {"post_id": 2483, "title": "NCTとは？拡張型グループの構造と派生ユニット・代表曲",
     "url": "https://www.kpopjournal.tokyo/nct-profile-2026/"},
    {"post_id": 2484, "title": "K-POP第4世代とは？代表グループと第3世代との違い",
     "url": "https://www.kpopjournal.tokyo/kpop-4th-gen-2026/"},
    {"post_id": 2485, "title": "K-POPアーティストプロフィール完全ガイド【2026年版】",
     "url": "https://www.kpopjournal.tokyo/kpop-profile-hub-2026/"},
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

    print(f"[check_gsc_index_profile] 実行日: {date.today()}")
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
