#!/usr/bin/env python3
"""
x_post_url_validator.py — X投稿前のURL事前検証

X投稿のURLリプライに含めるURLが実際にアクセス可能かを確認する。
soft-404（HTTP 200だが「記事が見つかりません」等を含む）も検出する。

使い方:
    python3 lib/x_post_url_validator.py "https://www.kpopjournal.tokyo/some-slug/"
    → 終了コード 0: OK, 1: NG

    python3 lib/x_post_url_validator.py "https://..." --json
    → JSON出力: {"ok": true/false, "status": 200, "reason": "..."}
"""

import sys
import json
import requests
from urllib.parse import unquote

SOFT_404_MARKERS = [
    "記事が見つかりません",
    "お探しのページは見つかりませんでした",
    "ページが見つかりません",
    "404",
]

# 日本語がslugに含まれている場合は明らかにバグ
def has_japanese_in_slug(url: str) -> bool:
    decoded = unquote(url)
    slug_part = decoded.rstrip("/").split("/")[-1]
    return any(ord(c) > 0x3000 for c in slug_part)


def validate_ogp_image(html_body: str, page_url: str) -> dict:
    """OGP画像の基本検証（X投稿前チェック）

    チェック項目:
      1. og:image メタタグが存在するか
      2. og:image URLにアクセスできるか (HEAD request)
      3. 画像サイズが妥当か (最低100KB — 極小はプレースホルダの可能性)
    """
    import re

    # og:image 抽出
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html_body)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html_body)
    if not m:
        return {"ok": False, "reason": "og:imageメタタグが存在しない"}

    og_image = m.group(1)
    if not og_image or len(og_image) < 10:
        return {"ok": False, "reason": "og:imageが空または不正"}

    # og:image URLのアクセス確認
    try:
        img_resp = requests.head(og_image, timeout=8, headers={"User-Agent": "KpopJournal-OGP/1.0"})
        if img_resp.status_code != 200:
            return {"ok": False, "reason": f"og:image HTTP {img_resp.status_code}", "og_image": og_image}

        # Content-Length確認（極小画像はプレースホルダの可能性）
        cl = img_resp.headers.get("Content-Length", "0")
        if cl.isdigit() and int(cl) < 10000:
            return {"ok": False, "reason": f"og:image極小({cl}bytes) — プレースホルダの可能性", "og_image": og_image}

    except Exception as e:
        return {"ok": False, "reason": f"og:imageアクセス不可: {str(e)[:60]}", "og_image": og_image}

    # og-default.png検出（記事固有のサムネなし → X投稿すべきでない）
    if "og-default" in og_image:
        return {"ok": False, "reason": "og-default.png使用（記事固有サムネなし）", "og_image": og_image}

    return {"ok": True, "og_image": og_image}


def validate_url(url: str) -> dict:
    if not url or url == "（URL取得失敗）" or url == "（投稿失敗）":
        return {"ok": False, "status": 0, "reason": "URL未設定"}

    if has_japanese_in_slug(url):
        return {"ok": False, "status": 0, "reason": "日本語slugを検出（slug生成バグ）"}

    if "kpopjournal.tokyo" not in url:
        return {"ok": False, "status": 0, "reason": "対象ドメイン外"}

    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "KpopJournal-URLValidator/1.0"})
        status = r.status_code

        if status == 404:
            return {"ok": False, "status": 404, "reason": "HTTP 404"}

        if status != 200:
            return {"ok": False, "status": status, "reason": f"HTTP {status}"}

        body = r.text[:15000]
        for marker in SOFT_404_MARKERS:
            if marker in body:
                return {"ok": False, "status": 200, "reason": f"soft-404検出: '{marker}'"}

        # OGP画像検証
        ogp_result = validate_ogp_image(body, url)
        if not ogp_result["ok"]:
            return {"ok": False, "status": 200, "reason": f"OGP問題: {ogp_result['reason']}",
                    "ogp_issue": ogp_result}

        return {"ok": True, "status": 200, "reason": "OK", "og_image": ogp_result.get("og_image", "")}

    except requests.Timeout:
        return {"ok": False, "status": 0, "reason": "タイムアウト"}
    except Exception as e:
        return {"ok": False, "status": 0, "reason": f"接続エラー: {str(e)[:80]}"}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 x_post_url_validator.py <url> [--json]", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]
    use_json = "--json" in sys.argv

    result = validate_url(url)

    if use_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        if result["ok"]:
            print(f"OK: {url}")
        else:
            print(f"NG: {result['reason']} — {url}")

    sys.exit(0 if result["ok"] else 1)
