#!/usr/bin/env python3
"""
113クラスター リンク構造検証スクリプト
"""
import json, re, urllib.request, os
from pathlib import Path

BASE = Path("/home/aiuser/kpop-ai-system")
WP_API = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"

ARTICLE_IDS = list(range(2432, 2442))  # 2432-2441
HUB_113 = 2442
HUB_111 = 2401

# 各記事のslug（WPリンク構造確認用）
ARTICLE_SLUGS = {
    2432: "kpop-beginner-guide-2026",
    2433: "kpop-comeback-meaning-guide",
    2434: "kpop-music-show-howto-guide",
    2435: "weverse-guide-beginner",
    2436: "kpop-live-concert-beginner",
    2437: "kpop-generation-guide",
    2438: "kpop-fanculture-beginner",
    2439: "kpop-enjoy-without-korean",
    2440: "kpop-agency-beginner-guide",
    2441: "kpop-abema-lemino-beginner",
}

def wp_auth():
    auth_path = os.path.expanduser("~/.wp_auth")
    with open(auth_path) as f:
        for line in f:
            m = re.match(r'header\s*=\s*"Authorization:\s*Basic\s+([^"]+)"', line.strip())
            if m: return m.group(1).strip()
    return ""

def fetch_content(pid):
    url = f"{WP_API}/{pid}?context=edit"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {wp_auth()}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
        return d.get("content", {}).get("raw", "") or d.get("content", {}).get("rendered", "")

def check_links():
    results = []
    print("=== 113クラスター リンク構造検証 ===\n")

    # 2442(113ハブ)の本文取得
    hub113_content = fetch_content(HUB_113)
    # 2401(111ハブ)の本文取得
    hub111_content = fetch_content(HUB_111)

    print(f"{'ID':<6} {'→113ハブ':<10} {'→111ハブ':<10} {'113ハブ→':<12} {'111ハブ→':<12}")
    print("-" * 55)

    for pid in ARTICLE_IDS:
        content = fetch_content(pid)
        # →113ハブ: kpop-hub-link クラス or 2442 言及
        to_113hub = bool(re.search(r'kpop-hub-link|/kpop-beginner-hub', content))
        # →111ハブ: kpop-view-guide or 2401 or kpop-streaming-guide-2026
        to_111hub = bool(re.search(r'kpop-view-guide|kpop-streaming-guide-2026', content))
        # 113ハブ→この記事（slug or post_id）
        slug = ARTICLE_SLUGS.get(pid, str(pid))
        from_113hub = bool(re.search(slug + r"|" + str(pid), hub113_content))
        # 111ハブ→この記事
        from_111hub = bool(re.search(slug + r"|" + str(pid), hub111_content))

        ok = lambda b: "✅" if b else "❌"
        print(f"{pid:<6} {ok(to_113hub):<10} {ok(to_111hub):<10} {ok(from_113hub):<12} {ok(from_111hub):<12}")
        results.append({
            "pid": pid,
            "to_113hub": to_113hub,
            "to_111hub": to_111hub,
            "from_113hub": from_113hub,
            "from_111hub": from_111hub,
        })

    # 2442←→2401の相互リンク
    hub113_to_111 = bool(re.search(r'kpop-streaming-guide|kpop-view-guide|2401', hub113_content))
    hub111_to_113 = bool(re.search(r'kpop-beginner-hub|2442|初心者.*ガイド|113', hub111_content))
    ok = lambda b: "✅" if b else "❌"
    print(f"\n113ハブ→111ハブ: {ok(hub113_to_111)}")
    print(f"111ハブ→113ハブ: {ok(hub111_to_113)}")

    issues = [r for r in results if not (r["to_113hub"] and r["to_111hub"])]
    if issues:
        print(f"\n⚠️  要修正: {len(issues)}件")
        for r in issues:
            missing = []
            if not r["to_113hub"]: missing.append("→113ハブ欠け")
            if not r["to_111hub"]: missing.append("→111ハブ欠け")
            print(f"  [{r['pid']}] {', '.join(missing)}")
    else:
        print("\n✅ 全記事リンク構造 問題なし")

    return results

if __name__ == "__main__":
    check_links()
