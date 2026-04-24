#!/usr/bin/env python3
"""
OGP・Twitterカード一括最適化スクリプト

直近の公開記事をスキャンし、以下を自動修復する:
  1. twitter:card → summary_large_image（大画像でCTR最大化）
  2. og:title / og:description の欠落補完
  3. og:image / twitter:image の欠落補完（featured imageから）
  4. og:type → article の設定

Usage:
  python3 lib/ogp_twitter_card_optimizer.py               # 直近50件をチェック＆修復
  python3 lib/ogp_twitter_card_optimizer.py --dry-run      # チェックのみ（修復しない）
  python3 lib/ogp_twitter_card_optimizer.py --days 7       # 直近7日の記事のみ
  python3 lib/ogp_twitter_card_optimizer.py --post-id 1234 # 特定記事のみ
"""
import argparse
import json
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

SITE_URL = "https://www.kpopjournal.tokyo"
WP_BASE = f"{SITE_URL}/wp-json/wp/v2"
LOGS_DIR = BASE_DIR / "logs"
OGP_LOG = LOGS_DIR / "ogp_optimization.jsonl"
JST = timezone(timedelta(hours=9))


def _get_wp_auth():
    auth_file = Path.home() / ".wp_auth"
    if not auth_file.exists():
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("WP_USER="):
                    user = line.split("=", 1)[1].strip()
                if line.startswith("WP_PASS="):
                    pw = line.split("=", 1)[1].strip().strip('"')
            import base64
            return f"Basic {base64.b64encode(f'{user}:{pw}'.encode()).decode()}"
        return None
    content = auth_file.read_text().strip()
    m = re.search(r'Authorization:\s*(Basic\s+\S+)', content, re.IGNORECASE)
    if m:
        return m.group(1)
    return f"Basic {content.split()[-1]}"


def _wp_get(path):
    auth = _get_wp_auth()
    if not auth:
        raise RuntimeError("WP認証情報が見つかりません")
    url = f"{WP_BASE}{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": auth,
        "User-Agent": "kpop-ogp-optimizer/1.0",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _wp_patch(path, data):
    auth = _get_wp_auth()
    if not auth:
        raise RuntimeError("WP認証情報が見つかりません")
    url = f"{WP_BASE}{path}"
    payload = json.dumps(data, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": auth,
        "Content-Type": "application/json",
        "User-Agent": "kpop-ogp-optimizer/1.0",
    }, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def check_live_ogp(url: str) -> dict:
    """公開ページのHTMLをフェッチしてOGP/Twitter cardの状態を返す"""
    result = {
        "og_title": None, "og_description": None, "og_image": None,
        "og_type": None, "twitter_card": None, "twitter_image": None,
        "issues": [],
    }
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; Twitterbot/1.0)"
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        result["issues"].append(f"FETCH_ERROR: {e}")
        return result

    def find_meta(prop_attr, prop_val):
        # property="og:xxx" or name="twitter:xxx"
        patterns = [
            rf'<meta[^>]+{prop_attr}=["\']' + re.escape(prop_val) + rf'["\'][^>]+content=["\']([^"\']*)["\']',
            rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+{prop_attr}=["\']' + re.escape(prop_val) + rf'["\']',
        ]
        for pat in patterns:
            m = re.findall(pat, html, re.IGNORECASE)
            if m:
                return m[0]
        return None

    result["og_title"] = find_meta("property", "og:title")
    result["og_description"] = find_meta("property", "og:description")
    result["og_image"] = find_meta("property", "og:image")
    result["og_type"] = find_meta("property", "og:type")
    result["twitter_card"] = find_meta("name", "twitter:card")
    result["twitter_image"] = find_meta("name", "twitter:image")

    if not result["og_title"]:
        result["issues"].append("OG_TITLE_MISSING")
    if not result["og_description"]:
        result["issues"].append("OG_DESC_MISSING")
    if not result["og_image"]:
        result["issues"].append("OG_IMAGE_MISSING")
    if result["twitter_card"] != "summary_large_image":
        result["issues"].append(f"TWITTER_CARD_NOT_LARGE: {result['twitter_card'] or 'missing'}")
    if not result["twitter_image"] and not result["og_image"]:
        result["issues"].append("TWITTER_IMAGE_MISSING")

    return result


def fix_post_meta(post_id: int, dry_run: bool = False) -> dict:
    """WP API経由で記事のOGP/Twitter cardメタを修復"""
    try:
        post = _wp_get(f"/posts/{post_id}?context=edit")
    except Exception as e:
        return {"post_id": post_id, "status": "error", "error": str(e)}

    meta = post.get("meta", {})
    title = post.get("title", {}).get("raw", "")
    content = post.get("content", {}).get("raw", "")
    featured_media = post.get("featured_media", 0)
    link = post.get("link", "")

    # description生成（コンテンツの最初の2文から）
    desc = meta.get("_aioseo_description", "")
    if not desc:
        plain = re.sub(r'<[^>]+>', '', content)
        plain = re.sub(r'\s+', ' ', plain).strip()
        sentences = re.split(r'[。！？\.\!\?]', plain)
        desc = "。".join(s.strip() for s in sentences[:2] if s.strip())
        if desc:
            desc = desc[:155] + "。"

    patch = {}
    fixes = []

    # OG title
    if not meta.get("_aioseo_og_title"):
        patch["_aioseo_og_title"] = title
        fixes.append("og_title")

    # OG description
    if not meta.get("_aioseo_og_description") and desc:
        patch["_aioseo_og_description"] = desc[:160]
        fixes.append("og_description")

    # Twitter title
    if not meta.get("_aioseo_twitter_title"):
        patch["_aioseo_twitter_title"] = title
        fixes.append("twitter_title")

    # Twitter description
    if not meta.get("_aioseo_twitter_description") and desc:
        patch["_aioseo_twitter_description"] = desc[:200]
        fixes.append("twitter_description")

    # Twitter card type → summary_large_image
    if meta.get("_aioseo_twitter_card") != "summary_large_image":
        patch["_aioseo_twitter_card"] = "summary_large_image"
        fixes.append("twitter_card_type")

    # OG type → article
    og_type = meta.get("_aioseo_og_object_type", "")
    if not og_type or og_type == "default":
        patch["_aioseo_og_object_type"] = "article"
        fixes.append("og_type")

    # OG image / Twitter image
    if not meta.get("_aioseo_og_image_custom_url") and featured_media:
        try:
            media = _wp_get(f"/media/{featured_media}")
            media_url = media.get("source_url", "")
            if media_url:
                patch["_aioseo_og_image_custom_url"] = media_url
                fixes.append("og_image")
                if not meta.get("_aioseo_twitter_image_custom_url"):
                    patch["_aioseo_twitter_image_custom_url"] = media_url
                    fixes.append("twitter_image")
        except Exception:
            pass

    result = {
        "post_id": post_id,
        "title": title[:60],
        "link": link,
        "fixes": fixes,
        "status": "no_changes" if not patch else ("dry_run" if dry_run else "fixed"),
    }

    if patch and not dry_run:
        try:
            _wp_patch(f"/posts/{post_id}", {"meta": patch})
            result["status"] = "fixed"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

    return result


def _log_result(results: list):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(JST).isoformat(),
        "total": len(results),
        "fixed": sum(1 for r in results if r["status"] == "fixed"),
        "no_changes": sum(1 for r in results if r["status"] == "no_changes"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "details": results,
    }
    with open(OGP_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser(description="OGP・Twitterカード一括最適化")
    parser.add_argument("--dry-run", action="store_true", help="チェックのみ")
    parser.add_argument("--days", type=int, default=30, help="直近N日の記事を対象")
    parser.add_argument("--post-id", type=int, help="特定記事のみ処理")
    parser.add_argument("--limit", type=int, default=50, help="処理件数上限")
    args = parser.parse_args()

    print(f"[OGP最適化] {'DRY-RUN' if args.dry_run else '修復モード'}")

    if args.post_id:
        post_ids = [args.post_id]
    else:
        # 直近の公開記事を取得
        after = (datetime.now(JST) - timedelta(days=args.days)).strftime("%Y-%m-%dT00:00:00")
        try:
            posts = _wp_get(f"/posts?status=publish&per_page={args.limit}&after={after}&orderby=date&order=desc&_fields=id")
            post_ids = [p["id"] for p in posts]
        except Exception as e:
            print(f"  WP API取得エラー: {e}")
            sys.exit(1)

    print(f"  対象: {len(post_ids)}件")

    results = []
    for i, pid in enumerate(post_ids, 1):
        result = fix_post_meta(pid, dry_run=args.dry_run)
        results.append(result)

        status_icon = {"fixed": "+", "no_changes": "=", "dry_run": "?", "error": "!"}
        icon = status_icon.get(result["status"], "?")
        fixes_str = ", ".join(result.get("fixes", [])) or "-"
        print(f"  [{icon}] #{pid} {result.get('title','')[:40]}  fixes={fixes_str}")

    _log_result(results)

    fixed = sum(1 for r in results if r["status"] == "fixed")
    needs_fix = sum(1 for r in results if r.get("fixes"))
    errors = sum(1 for r in results if r["status"] == "error")

    print(f"\n[結果] 修復: {fixed}件 / 要修復: {needs_fix}件 / エラー: {errors}件 / 対象: {len(results)}件")


if __name__ == "__main__":
    main()
