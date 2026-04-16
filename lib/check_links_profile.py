#!/usr/bin/env python3
"""
112クラスター リンク構造検証スクリプト

チェック項目:
- 2475〜2484の10記事: →112ハブ / →111ハブ / →113ハブ / 112ハブ→この記事
- 112ハブ↔111ハブ
- 112ハブ↔113ハブ
- hubページ(pages)からの送リンク（2323/2331/2332/2329）
"""
import json, re, urllib.request, os
from pathlib import Path

BASE = Path("/home/aiuser/kpop-ai-system")
WP_API = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
WP_PAGES_API = "https://www.kpopjournal.tokyo/wp-json/wp/v2/pages"

ARTICLE_IDS = list(range(2475, 2485))  # 2475-2484
HUB_112 = 2485
HUB_111 = 2401
HUB_113 = 2442

# hubページ（固定ページ）
HUB_PAGES = [2323, 2331, 2332, 2329]

# 各記事のslug（WPリンク構造確認用）
ARTICLE_SLUGS = {
    2475: "bts-profile-2026",
    2476: "ive-profile-2026",
    2477: "aespa-profile-2026",
    2478: "newjeans-profile-2026",
    2479: "seventeen-profile-2026",
    2480: "blackpink-profile-2026",
    2481: "straykids-profile-2026",
    2482: "twice-profile-2026",
    2483: "nct-profile-2026",
    2484: "kpop-4th-gen-2026",
}


def wp_auth():
    auth_path = os.path.expanduser("~/.wp_auth")
    with open(auth_path) as f:
        for line in f:
            m = re.match(r'header\s*=\s*"Authorization:\s*Basic\s+([^"]+)"', line.strip())
            if m: return m.group(1).strip()
    return ""


def fetch_content(pid, api=WP_API):
    url = f"{api}/{pid}?context=edit"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {wp_auth()}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read())
            return d.get("content", {}).get("raw", "") or d.get("content", {}).get("rendered", "")
    except Exception as e:
        return f"[ERROR: {e}]"


def check_links():
    results = []
    print("=== 112クラスター リンク構造検証 ===\n")

    # 各ハブ本文取得
    hub112_content = fetch_content(HUB_112)
    hub111_content = fetch_content(HUB_111)
    hub113_content = fetch_content(HUB_113)

    print(f"{'ID':<6} {'→112ハブ':<10} {'→111ハブ':<10} {'→113ハブ':<10} {'112ハブ→':<12}")
    print("-" * 55)

    for pid in ARTICLE_IDS:
        content = fetch_content(pid)
        # →112ハブ: kpop-hub-link クラス or kpop-profile-hub-2026
        to_112hub = bool(re.search(r'kpop-hub-link|/kpop-profile-hub|kpop-profile-hub-2026', content))
        # →111ハブ: kpop-view-guide or kpop-streaming-guide-2026
        to_111hub = bool(re.search(r'kpop-view-guide|kpop-streaming-guide-2026', content))
        # →113ハブ: kpop-beginner-hub-2026 or kpop-beginner-hub
        to_113hub = bool(re.search(r'kpop-beginner-hub', content))
        # 112ハブ→この記事（slug or post_id）
        slug = ARTICLE_SLUGS.get(pid, str(pid))
        from_112hub = bool(re.search(slug + r"|" + str(pid), hub112_content))

        ok = lambda b: "✅" if b else "❌"
        print(f"{pid:<6} {ok(to_112hub):<10} {ok(to_111hub):<10} {ok(to_113hub):<10} {ok(from_112hub):<12}")
        results.append({
            "pid": pid,
            "to_112hub": to_112hub,
            "to_111hub": to_111hub,
            "to_113hub": to_113hub,
            "from_112hub": from_112hub,
        })

    # ハブ間相互リンク確認
    print()
    hub112_to_111 = bool(re.search(r'kpop-streaming-guide|kpop-view-guide|2401', hub112_content))
    hub111_to_112 = bool(re.search(r'kpop-profile-hub|2485|プロフィール.*ガイド|112', hub111_content))
    hub112_to_113 = bool(re.search(r'kpop-beginner-hub|2442|初心者.*ガイド|113', hub112_content))
    hub113_to_112 = bool(re.search(r'kpop-profile-hub|2485|プロフィール.*ガイド|112', hub113_content))

    ok = lambda b: "✅" if b else "❌"
    print(f"112ハブ→111ハブ: {ok(hub112_to_111)}")
    print(f"111ハブ→112ハブ: {ok(hub111_to_112)}")
    print(f"112ハブ→113ハブ: {ok(hub112_to_113)}")
    print(f"113ハブ→112ハブ: {ok(hub113_to_112)}")

    # hubページ（固定ページ）からのリンク確認
    print(f"\n=== hubページ（固定ページ）からの送リンク確認 ===")
    for page_id in HUB_PAGES:
        page_content = fetch_content(page_id, api=WP_PAGES_API)
        has_link = bool(re.search(r'kpop-profile-hub|2485|プロフィール.*ガイド', page_content))
        print(f"  page/{page_id} → 112ハブ: {ok(has_link)}")

    # 問題サマリー
    issues = [r for r in results if not (r["to_112hub"] and r["to_111hub"])]
    if issues:
        print(f"\n⚠️  要修正: {len(issues)}件")
        for r in issues:
            missing = []
            if not r["to_112hub"]: missing.append("→112ハブ欠け")
            if not r["to_111hub"]: missing.append("→111ハブ欠け")
            if not r["to_113hub"]: missing.append("→113ハブ欠け")
            print(f"  [{r['pid']}] {', '.join(missing)}")
    else:
        print("\n✅ 全記事リンク構造 問題なし")

    return results


if __name__ == "__main__":
    check_links()
