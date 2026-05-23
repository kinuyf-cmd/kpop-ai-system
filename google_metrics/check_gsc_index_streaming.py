#!/usr/bin/env python3
"""
視聴導線クラスター GSCインデックス状態確認スクリプト
Usage:
  python3 google_metrics/check_gsc_index_streaming.py
  python3 google_metrics/check_gsc_index_streaming.py --save   # ログ保存

確認項目: verdict / coverageState / lastCrawlTime / robotsTxtState / indexingState
"""

import json, urllib.request, urllib.parse, time, base64, os, argparse, sys
from datetime import date
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

BASE = Path(__file__).parent.parent
SA_FILE = BASE / "google_metrics" / "service_account.json"
LOG_FILE = BASE / "logs" / "gsc_index_check.jsonl"

SITE_URL = "https://www.kpopjournal.tokyo/"


def get_targets_from_db(limit: int = 20, category_slug: str = ""):
    """現存する publish 記事の実 URL を DB から取得して対象にする(2026-05-23)。

    旧 TARGETS は post_id 2333-2401 のハードコード11件だったが、rebuild で
    全て消滅(現存しない URL)。GSC が「URL is unknown to Google」を返すのは
    当然で、インデックス状況の指標として無意味だった。現存 publish 記事の
    パーマリンクを動的取得して、実態を測れるようにする。

    URL は wp_posts.guid ではなく post_name(slug)からパーマリンク組み立て
    (このサイトは /<slug>/ 形式)。新しい順に limit 件。
    """
    try:
        sys.path.insert(0, str(BASE))
        import lib.popup_event_to_post as P
    except Exception as e:
        print(f"  WARN: DB モジュール読込失敗 → 対象0件 ({type(e).__name__})")
        return []
    cat = ""
    if category_slug:
        cat = (
            "JOIN wp_term_relationships tr ON tr.object_id=p.ID "
            "JOIN wp_term_taxonomy tt ON tt.term_taxonomy_id=tr.term_taxonomy_id "
            "JOIN wp_terms t ON t.term_id=tt.term_id "
            f"AND tt.taxonomy='category' AND t.slug='{P.esc_sql(category_slug)}' "
        )
    sql = (
        "SELECT p.ID, p.post_title, p.post_name FROM wp_posts p "
        + cat +
        "WHERE p.post_type='post' AND p.post_status='publish' AND p.post_name<>'' "
        f"ORDER BY p.post_date DESC LIMIT {int(limit)};"
    )
    out = P.run_mysql(sql)
    targets = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].strip().isdigit():
            pid, title, slug = parts[0].strip(), parts[1].strip(), parts[2].strip()
            targets.append({
                "post_id": int(pid),
                "title": title,
                "url": SITE_URL + urllib.parse.quote(slug) + "/",
            })
    return targets


# 後方互換: 旧ハードコード(全て rebuild で消滅・現存しない)。既定では使わない。
TARGETS = [
    {"post_id": 2401, "title": "K-POPを日本から見る方法まとめ【ハブ】",
     "url": "https://www.kpopjournal.tokyo/kpop-streaming-guide-japan-2026-hub/"},
    {"post_id": 2333, "title": "MAMA AWARDS 2026",
     "url": "https://www.kpopjournal.tokyo/mama-awards-2026%e3%82%92%e6%97%a5%e6%9c%ac%e3%81%a7%e8%a6%8b%e3%82%8b%e6%96%b9%e6%b3%95%ef%bd%9cabema%e3%83%bblemino%e3%83%bb%e7%84%a1%e6%96%99%e8%a6%96%e8%81%b4%e3%82%ac%e3%82%a4%e3%83%89/"},
    {"post_id": 2334, "title": "K-POP音楽番組5大まとめ",
     "url": "https://www.kpopjournal.tokyo/k-pop%e9%9f%b3%e6%a5%bd%e7%95%aa%e7%b5%84%e3%82%92%e6%97%a5%e6%9c%ac%e3%81%8b%e3%82%89%e7%84%a1%e6%96%99%e3%81%a7%e8%a6%8b%e3%82%8b%e6%96%b9%e6%b3%95%e3%81%be%e3%81%a8%e3%82%81%e3%80%902026%e5%b9%b4/"},
    {"post_id": 2335, "title": "Music Bank",
     "url": "https://www.kpopjournal.tokyo/music-bank%ef%bc%88%eb%ae%a4%ec%a7%81%eb%b1%85%ed%81%ac%ef%bc%89%e3%82%92%e6%97%a5%e6%9c%ac%e3%81%8b%e3%82%89%e7%84%a1%e6%96%99%e3%81%a7%e8%a6%8b%e3%82%8b%e6%96%b9%e6%b3%95%ef%bd%9c2026%e5%b9%b4/"},
    {"post_id": 2336, "title": "INKIGAYO",
     "url": "https://www.kpopjournal.tokyo/inkigayo%ef%bc%88%e4%ba%ba%e6%b0%97%e6%ad%8c%e8%ac%a1%ef%bc%89%e3%82%92%e6%97%a5%e6%9c%ac%e3%81%8b%e3%82%89%e8%a6%8b%e3%82%8b%e6%96%b9%e6%b3%95%ef%bd%9c%e7%84%a1%e6%96%99%e3%83%bb%e6%9c%89%e6%96%99/"},
    {"post_id": 2337, "title": "SHOW CHAMPION",
     "url": "https://www.kpopjournal.tokyo/show-champion%e3%82%92%e6%97%a5%e6%9c%ac%e3%81%8b%e3%82%89%e7%84%a1%e6%96%99%e3%81%a7%e8%a6%8b%e3%82%8b%e6%96%b9%e6%b3%95%ef%bd%9c2026%e5%b9%b4%e9%85%8d%e4%bf%a1%e3%82%b5%e3%83%bc%e3%83%93%e3%82%b9/"},
    {"post_id": 2338, "title": "BTS ライブ・コンサート",
     "url": "https://www.kpopjournal.tokyo/bts%e3%81%ae%e3%83%a9%e3%82%a4%e3%83%96%e6%98%a0%e5%83%8f%e3%83%bb%e3%82%b3%e3%83%b3%e3%82%b5%e3%83%bc%e3%83%88%e3%82%92%e4%bb%8a%e3%81%99%e3%81%90%e8%a6%8b%e3%82%8b%e6%96%b9%e6%b3%95%e3%81%be/"},
    {"post_id": 2339, "title": "IVE MV・ライブ",
     "url": "https://www.kpopjournal.tokyo/ive%e3%81%aemv%e3%83%bb%e3%83%a9%e3%82%a4%e3%83%96%e6%98%a0%e5%83%8f%e3%82%92%e6%97%a5%e6%9c%ac%e3%81%8b%e3%82%89%e7%84%a1%e6%96%99%e3%81%a7%e8%a6%8b%e3%82%8b%e5%85%a8%e6%96%b9%e6%b3%95%e3%80%902026/"},
    {"post_id": 2340, "title": "aespa コンサート・MV",
     "url": "https://www.kpopjournal.tokyo/aespa%e3%81%ae%e3%82%b3%e3%83%b3%e3%82%b5%e3%83%bc%e3%83%88%e3%83%bbmv%e3%83%bb%e3%83%a9%e3%82%a4%e3%83%96%e3%82%92%e6%97%a5%e6%9c%ac%e3%81%a7%e8%a6%8b%e3%82%8b%e6%96%b9%e6%b3%95%e3%80%902026%e5%b9%b4/"},
    {"post_id": 2341, "title": "KCON JAPAN 2026",
     "url": "https://www.kpopjournal.tokyo/kcon-japan-2026%e3%81%ae%e3%83%a9%e3%82%a4%e3%83%96%e9%85%8d%e4%bf%a1%e3%83%bb%e8%a6%8b%e9%80%83%e3%81%97%e9%85%8d%e4%bf%a1%e3%82%92%e8%a6%8b%e3%82%8b%e6%96%b9%e6%b3%95%e5%ae%8c%e5%85%a8%e3%82%ac/"},
    {"post_id": 2342, "title": "NewJeans MV・活動",
     "url": "https://www.kpopjournal.tokyo/newjeans%e3%81%aemv%e3%83%bb%e6%b4%bb%e5%8b%95%e3%83%bb%e5%85%ac%e6%bc%94%e3%82%92%e6%97%a5%e6%9c%ac%e3%81%a7%e8%a6%8b%e3%82%8b%e5%85%a8%e6%96%b9%e6%b3%95%e3%80%902026%e5%b9%b4%e6%9c%80%e6%96%b0/"},
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
    parser.add_argument("--limit", type=int, default=20, help="チェックする現存記事数(新しい順)")
    parser.add_argument("--category", default="", help="カテゴリslugで絞る(例: popup)")
    parser.add_argument("--legacy", action="store_true", help="旧ハードコードTARGETSを使う(非推奨)")
    args = parser.parse_args()

    targets = TARGETS if args.legacy else get_targets_from_db(args.limit, args.category)

    print(f"[check_gsc_index_streaming] 実行日: {date.today()}")
    print(f"対象: {len(targets)}記事 ({'legacy固定' if args.legacy else 'DB動的取得'})\n")

    token = get_access_token()
    results = []

    for t in targets:
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
        print(f"{icon} [{t['post_id']}] {t['title'][:30]:<30}")
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
    unknown = sum(1 for r in results if "unknown" in r.get("coverageState","").lower())
    print(f"\n=== サマリー ===")
    print(f"インデックス済み: {indexed}/{len(results)}")
    print(f"クロール済み:     {crawled}/{len(results)}")
    print(f"未登録(unknown): {unknown}/{len(results)}")

    if args.save:
        # 最新スナップショットで上書き（append だと古い NEUTRAL が永久に残り、
        # audit_72h.py の先頭優先 dedup で最古レコードが採用される不具合の元になる）
        with open(LOG_FILE, "w") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n✅ ログ保存(上書き): {LOG_FILE}")


if __name__ == "__main__":
    main()
