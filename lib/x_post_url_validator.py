#!/usr/bin/env python3
"""
x_post_url_validator.py — X投稿前のURL事前検証

X投稿のURLリプライに含めるURLが実際にアクセス可能かを確認する。
soft-404（HTTP 200だが「記事が見つかりません」等を含���）も検出する。

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
    "お探しのページは見つ��りませんでした",
    "ページが見つかりません",
    "404",
]

# 日本語がslugに含まれている場合は���らかにバグ
def has_japanese_in_slug(url: str) -> bool:
    decoded = unquote(url)
    slug_part = decoded.rstrip("/").split("/")[-1]
    return any(ord(c) > 0x3000 for c in slug_part)


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

        body = r.text[:5000]
        for marker in SOFT_404_MARKERS:
            if marker in body:
                return {"ok": False, "status": 200, "reason": f"soft-404検出: '{marker}'"}

        return {"ok": True, "status": 200, "reason": "OK"}

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
