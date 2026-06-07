#!/usr/bin/env python3
"""
x_metrics_collector.py — X(Twitter)投稿の実エンゲージ計測を日次スナップショット化。

目的(2026-06-06設計): フォロワー242人・1投稿impression2-5・url_link_clicks=0 という
リーチ欠如をデータで追跡し、「どの投稿が伸びたか」を実測で蓄積する。育成施策の
効果判定の土台。推測でなく実測で回す([[x-reach-bottleneck-242-followers]])。

入力:
  ~/.x_credentials              OAuth1.0a 4キー(post_to_x.py と共通)
出力(追記):
  logs/x_metrics.jsonl          1行=1日のスナップショット
    { ts, account{followers,following,tweets}, window_n,
      totals{impression,engagement,url_link_clicks},
      avg_impression_per_post, top[ {tweet_id,text,impression,like,rt,reply,link_clicks} ] }

Usage:
  venv_kpi/bin/python3 lib/x_metrics_collector.py            # 直近100投稿を計測しスナップショット追記
  venv_kpi/bin/python3 lib/x_metrics_collector.py --max 50   # 取得件数指定
  venv_kpi/bin/python3 lib/x_metrics_collector.py --dry-run  # 取得して表示のみ(追記しない)

設計メモ:
  - GET /2/users/{id}/tweets を1コールで最大100件取得(個別取得よりレート効率が良い)
  - organic_metrics は user-context OAuth1.0a が必須(public_metrics でも impression は取れる)
  - 失敗時は標準のフォールバック=スナップショットを書かず非ゼロ終了(欠測を捏造しない)
"""
import json
import os
import sys
import hmac
import hashlib
import base64
import time
import uuid
import argparse
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CREDS_FILE = os.path.expanduser("~/.x_credentials")
OUT = BASE / "logs" / "x_metrics.jsonl"
JST = timezone(timedelta(hours=9))
API = "https://api.twitter.com/2"


def _load_creds():
    with open(CREDS_FILE) as f:
        creds = json.load(f)
    for k in ("api_key", "api_secret", "access_token", "access_token_secret"):
        if not str(creds.get(k, "")).strip():
            raise SystemExit(f"認証キー欠落: {k} (~/.x_credentials)")
    return creds


def _oauth_header(method, url, creds, params=None):
    """OAuth1.0a HMAC-SHA1。クエリパラメータも署名対象に含める(GET用)。"""
    oauth = {
        "oauth_consumer_key": creds["api_key"],
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": creds["access_token"],
        "oauth_version": "1.0",
    }
    allp = dict(oauth)
    if params:
        allp.update(params)
    base = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(allp.items())
    )
    sigbase = f"{method}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(base, safe='')}"
    key = (
        f"{urllib.parse.quote(creds['api_secret'], safe='')}"
        f"&{urllib.parse.quote(creds['access_token_secret'], safe='')}"
    )
    sig = base64.b64encode(
        hmac.new(key.encode(), sigbase.encode(), hashlib.sha1).digest()
    ).decode()
    oauth["oauth_signature"] = sig
    return "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(str(v), safe="")}"'
        for k, v in sorted(oauth.items())
    )


def _get(path, creds, params=None):
    url = f"{API}{path}"
    hdr = _oauth_header("GET", url, creds, params)
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full, headers={"Authorization": hdr})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def collect(max_results=100):
    creds = _load_creds()
    me = _get("/users/me", creds,
              {"user.fields": "public_metrics,username"})["data"]
    uid = me["id"]
    acc = me.get("public_metrics", {})

    rows = _get(
        f"/users/{uid}/tweets", creds,
        {"max_results": str(max_results),
         "tweet.fields": "public_metrics,created_at",
         "exclude": "retweets"},
    ).get("data", [])

    items = []
    for t in rows:
        m = t.get("public_metrics", {})
        items.append({
            "tweet_id": t["id"],
            "text": t.get("text", "")[:80],
            "created_at": t.get("created_at", ""),
            "impression": m.get("impression_count", 0),
            "like": m.get("like_count", 0),
            "rt": m.get("retweet_count", 0),
            "reply": m.get("reply_count", 0),
            # url_link_clicks は organic_metrics 側。public_metrics には無いので
            # 一覧では取得せず、必要時に個別取得(レート節約)。ここでは 0 留保。
            "link_clicks": None,
        })

    tot_imp = sum(i["impression"] for i in items)
    tot_eng = sum(i["like"] + i["rt"] + i["reply"] for i in items)
    snap = {
        "ts": datetime.now(JST).isoformat(),
        "account": {
            "username": me.get("username"),
            "followers": acc.get("followers_count"),
            "following": acc.get("following_count"),
            "tweets": acc.get("tweet_count"),
        },
        "window_n": len(items),
        "totals": {
            "impression": tot_imp,
            "engagement": tot_eng,
        },
        "avg_impression_per_post": round(tot_imp / max(len(items), 1), 2),
        "top": sorted(items, key=lambda x: -x["impression"])[:10],
    }
    return snap


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=100, help="取得件数(最大100)")
    ap.add_argument("--dry-run", action="store_true", help="追記せず表示のみ")
    args = ap.parse_args()

    try:
        snap = collect(min(args.max, 100))
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        print(f"[x_metrics] HTTPError {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[x_metrics] ERROR {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    a = snap["account"]
    print(f"@{a['username']} followers={a['followers']} "
          f"| 直近{snap['window_n']}投稿 imp合計={snap['totals']['impression']} "
          f"(平均{snap['avg_impression_per_post']}/投稿) "
          f"eng={snap['totals']['engagement']}")
    print("TOP3:")
    for t in snap["top"][:3]:
        print(f"  imp{t['impression']:>4} like{t['like']:>2} RT{t['rt']:>2} "
              f"rep{t['reply']:>2}  {t['text'][:46]}")

    if args.dry_run:
        print("(--dry-run: 追記なし)")
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "a") as f:
        f.write(json.dumps(snap, ensure_ascii=False) + "\n")
    print(f"→ {OUT} に追記")


if __name__ == "__main__":
    main()
