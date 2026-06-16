#!/usr/bin/env python3
"""indexnow.py — Bing/Yahoo/Yandex への即時インデックス通知(IndexNow)。

GSC Indexing API(Google専用)の対になるBing系の経路。GA4実測でBing 2,766/Yahoo 1,036
session/90日(=Google比84%/31%)の第2・第3チャネルを伸ばすため、公開/更新時に
IndexNow へ URL を送信して即時クロールを促す([[reach-channels-diagnosis-20260616]])。

keyファイルはサイトに web 配信済(uploads 経由で設置、keyLocation 指定):
  key=KEY_FILE の内容、keyLocation=KEY_LOCATION。

使い方:
  python3 lib/indexnow.py --url "https://www.kpopjournal.tokyo/foo/"
  python3 lib/indexnow.py --urls url1 url2 ...   # まとめて(最大10000)
"""
from __future__ import annotations
import argparse
import json
import sys
import urllib.request
import urllib.error

HOST = "www.kpopjournal.tokyo"
KEY = "e293fd57bfba4719b06206c8b391aad9"
# keyファイルはサイトルートに設置(root配下のURLを送信するため必須)。
# owner作業: /var/www/wp_stg/{KEY}.txt に KEY 文字列を設置(ads.txt と同方式)。
KEY_LOCATION = f"https://{HOST}/{KEY}.txt"
ENDPOINT = "https://api.indexnow.org/indexnow"  # Bing/Yandex/Seznam 等が共有
UA = "KpopJournalBot/1.0 (+https://www.kpopjournal.tokyo/about; indexnow)"


def submit(urls: list[str]) -> tuple[int, str]:
    """URLリストを IndexNow に送信。(http_status, body) を返す。

    IndexNow は同一ホストの URL のみ受け付ける。202=受理。
    """
    urls = [u for u in urls if u.startswith(f"https://{HOST}/")][:10000]
    if not urls:
        return 0, "no valid same-host urls"
    payload = json.dumps({
        "host": HOST,
        "key": KEY,
        "keyLocation": KEY_LOCATION,
        "urlList": urls,
    }).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=payload, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "ignore")[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:200]
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, f"network error: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="単一URL")
    ap.add_argument("--urls", nargs="*", help="複数URL")
    args = ap.parse_args()
    urls = []
    if args.url:
        urls.append(args.url)
    if args.urls:
        urls.extend(args.urls)
    if not urls:
        print("usage: indexnow.py --url <URL> | --urls <URL...>", file=sys.stderr)
        return 2
    status, body = submit(urls)
    ok = status in (200, 202)
    print(f"IndexNow {'OK' if ok else 'FAIL'} status={status} urls={len(urls)} :: {body}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
