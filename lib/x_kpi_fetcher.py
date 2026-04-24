#!/usr/bin/env python3
"""
x_kpi_fetcher.py — X(Twitter) KPI取得・保存 v1.0

X API v2 を使用して以下のKPIを取得し、logs/x_kpi.jsonl に蓄積する:
  - フォロワー数（前日比）
  - 直近ツイートのインプレッション数合計
  - エンゲージメント率（いいね・RT・返信の合計 / インプレッション）
  - 最もバズった投稿（インプレッション最大）
  - クリック数（url_link_clicks）

Discord通知:
  daily_ceo_report チャネルに日次サマリーを送信。

Usage:
  python3 lib/x_kpi_fetcher.py              # 通常実行
  python3 lib/x_kpi_fetcher.py --dry-run    # API呼び出しなし（ダミーデータ）
  python3 lib/x_kpi_fetcher.py --status     # credential状態確認のみ
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
import urllib.error
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
LOGS_DIR = BASE_DIR / "logs"
CREDS_FILE = os.path.expanduser("~/.x_credentials")
SNS_CONFIG = BASE_DIR / "config" / "sns_config.json"
KPI_FILE = LOGS_DIR / "x_kpi.jsonl"
DISCORD_WEBHOOKS = BASE_DIR / "config" / "discord_webhooks.json"

JST = timezone(timedelta(hours=9))
NOW_JST = datetime.now(JST)
TODAY = NOW_JST.strftime("%Y-%m-%d")

# X API v2 endpoints
USER_ME_URL = "https://api.twitter.com/2/users/me"
USER_TWEETS_URL = "https://api.twitter.com/2/users/{user_id}/tweets"


def load_credentials():
    if not os.path.exists(CREDS_FILE):
        return None, "credentials file not found (~/.x_credentials)"
    try:
        creds = json.load(open(CREDS_FILE))
    except Exception as e:
        return None, f"credentials parse error: {e}"

    required = ["api_key", "api_secret", "access_token", "access_token_secret"]
    missing = [k for k in required if not creds.get(k)]
    if missing:
        return None, f"missing keys: {', '.join(missing)}"
    return creds, None


def is_x_enabled():
    if not SNS_CONFIG.exists():
        return True
    try:
        cfg = json.loads(SNS_CONFIG.read_text())
        return cfg.get("twitter", {}).get("enabled", True)
    except Exception:
        return True


def _oauth_signature(method, url, params, api_secret, token_secret):
    param_str = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}"
                         for k, v in sorted(params.items()))
    base = f"{method}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(param_str, safe='')}"
    key = f"{urllib.parse.quote(api_secret, safe='')}&{urllib.parse.quote(token_secret, safe='')}"
    sig = base64.b64encode(
        hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    ).decode()
    return sig


def _oauth_header(method, url, creds, extra_params=None):
    oauth = {
        "oauth_consumer_key": creds["api_key"],
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": creds["access_token"],
        "oauth_version": "1.0",
    }
    all_params = {**oauth}
    if extra_params:
        all_params.update(extra_params)

    oauth["oauth_signature"] = _oauth_signature(
        method, url, all_params,
        creds["api_secret"], creds["access_token_secret"]
    )
    auth_str = ", ".join(
        f'{k}="{urllib.parse.quote(str(v), safe="")}"'
        for k, v in sorted(oauth.items())
    )
    return f"OAuth {auth_str}"


def api_get(url, creds, params=None):
    if params:
        qs = urllib.parse.urlencode(params)
        full_url = f"{url}?{qs}"
    else:
        full_url = url
        params = {}

    auth = _oauth_header("GET", url, creds, params)
    req = urllib.request.Request(full_url, headers={
        "Authorization": auth,
        "User-Agent": "KpopJournal/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return None, f"HTTP {e.code}: {body[:200]}"
    except Exception as e:
        return None, str(e)


def get_user_info(creds):
    params = {"user.fields": "public_metrics,username,name"}
    return api_get(USER_ME_URL, creds, params)


def get_recent_tweets(creds, user_id, max_results=20):
    url = USER_TWEETS_URL.format(user_id=user_id)
    params = {
        "max_results": str(max_results),
        "tweet.fields": "public_metrics,created_at",
    }
    return api_get(url, creds, params)


def compute_kpi(user_data, tweets_data):
    user = user_data.get("data", {})
    pm = user.get("public_metrics", {})
    followers = pm.get("followers_count", 0)
    following = pm.get("following_count", 0)
    tweet_count = pm.get("tweet_count", 0)

    tweets = tweets_data.get("data", []) if tweets_data else []

    total_impressions = 0
    total_likes = 0
    total_retweets = 0
    total_replies = 0
    total_clicks = 0
    best_tweet = None
    best_impressions = 0

    for t in tweets:
        m = t.get("public_metrics", {})
        imp = m.get("impression_count", 0)
        likes = m.get("like_count", 0)
        rts = m.get("retweet_count", 0)
        replies = m.get("reply_count", 0)
        clicks = m.get("url_link_clicks", 0)

        total_impressions += imp
        total_likes += likes
        total_retweets += rts
        total_replies += replies
        total_clicks += clicks

        if imp > best_impressions:
            best_impressions = imp
            best_tweet = {
                "id": t.get("id"),
                "text": t.get("text", "")[:120],
                "impressions": imp,
                "likes": likes,
                "retweets": rts,
                "created_at": t.get("created_at", ""),
            }

    total_engagement = total_likes + total_retweets + total_replies
    engagement_rate = (total_engagement / total_impressions) if total_impressions > 0 else 0

    return {
        "date": TODAY,
        "ts": NOW_JST.isoformat(),
        "followers": followers,
        "following": following,
        "tweet_count": tweet_count,
        "recent_tweets_analyzed": len(tweets),
        "total_impressions": total_impressions,
        "total_likes": total_likes,
        "total_retweets": total_retweets,
        "total_replies": total_replies,
        "total_clicks": total_clicks,
        "engagement_rate": round(engagement_rate, 4),
        "best_tweet": best_tweet,
    }


def load_previous_kpi():
    if not KPI_FILE.exists():
        return None
    lines = KPI_FILE.read_text(errors="replace").strip().splitlines()
    for line in reversed(lines):
        try:
            d = json.loads(line)
            if d.get("date") != TODAY:
                return d
        except Exception:
            continue
    return None


def save_kpi(kpi):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(KPI_FILE, "a") as f:
        f.write(json.dumps(kpi, ensure_ascii=False) + "\n")


def build_discord_message(kpi, prev):
    followers = kpi["followers"]
    diff = ""
    if prev and prev.get("followers"):
        delta = followers - prev["followers"]
        sign = "+" if delta >= 0 else ""
        diff = f"（{sign}{delta}）"

    eng_pct = f"{kpi['engagement_rate']:.2%}"
    lines = [
        f"📊 **X KPI日次レポート** | {kpi['date']}",
        f"",
        f"👥 フォロワー: **{followers:,}** {diff}",
        f"👁 インプレッション: **{kpi['total_impressions']:,}**（直近{kpi['recent_tweets_analyzed']}件）",
        f"💬 エンゲージメント率: **{eng_pct}**",
        f"  ❤️ {kpi['total_likes']:,} | 🔁 {kpi['total_retweets']:,} | 💬 {kpi['total_replies']:,}",
        f"🔗 クリック数: **{kpi['total_clicks']:,}**",
    ]

    if kpi.get("best_tweet"):
        bt = kpi["best_tweet"]
        lines.append(f"")
        lines.append(f"🔥 **最もバズった投稿:**")
        lines.append(f"  {bt['text'][:80]}...")
        lines.append(f"  👁 {bt['impressions']:,} | ❤️ {bt['likes']:,} | 🔁 {bt['retweets']:,}")

    return "\n".join(lines)


def send_discord(message):
    if not DISCORD_WEBHOOKS.exists():
        print("  Discord webhook設定なし — スキップ")
        return
    try:
        hooks = json.loads(DISCORD_WEBHOOKS.read_text())
        webhook = hooks.get("daily_ceo_report", "")
    except Exception:
        return

    if not webhook:
        return

    payload = json.dumps({"content": message[:1900]}).encode()
    req = urllib.request.Request(
        webhook, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print("  Discord通知完了")
    except Exception as e:
        print(f"  Discord通知失敗: {e}")


def run_fetch():
    print(f"[x_kpi_fetcher] {NOW_JST.strftime('%Y-%m-%d %H:%M JST')}")

    if not is_x_enabled():
        print("  ⏭️ Xアカウント停止中（sns_config.json: enabled=false）— スキップ")
        return

    creds, err = load_credentials()
    if err:
        print(f"  ❌ credential エラー: {err}")
        return

    print("  X API呼び出し中...")

    user_data, err = get_user_info(creds)
    if err:
        print(f"  ❌ ユーザー情報取得失敗: {err}")
        return

    user_id = user_data.get("data", {}).get("id")
    if not user_id:
        print("  ❌ user_id取得失敗")
        return

    username = user_data.get("data", {}).get("username", "unknown")
    print(f"  ユーザー: @{username} (ID: {user_id})")

    tweets_data, err = get_recent_tweets(creds, user_id)
    if err:
        print(f"  ⚠️ ツイート取得失敗（ユーザー情報のみで続行）: {err}")
        tweets_data = None

    kpi = compute_kpi(user_data, tweets_data)
    prev = load_previous_kpi()

    save_kpi(kpi)
    print(f"  ✅ KPI保存完了 → {KPI_FILE}")

    print(f"  フォロワー: {kpi['followers']:,}")
    print(f"  インプレッション: {kpi['total_impressions']:,}")
    print(f"  エンゲージメント率: {kpi['engagement_rate']:.2%}")
    print(f"  クリック数: {kpi['total_clicks']:,}")

    msg = build_discord_message(kpi, prev)
    send_discord(msg)


def run_status():
    print(f"[x_kpi_fetcher] credential & config状態確認")
    print(f"  X enabled: {is_x_enabled()}")
    creds, err = load_credentials()
    if err:
        print(f"  ❌ {err}")
    else:
        print(f"  ✅ credentials OK (api_key: {creds['api_key'][:8]}...)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.status:
        run_status()
        return

    if args.dry_run:
        print("[x_kpi_fetcher] --dry-run モード")
        dummy = {
            "date": TODAY, "ts": NOW_JST.isoformat(),
            "followers": 0, "following": 0, "tweet_count": 0,
            "recent_tweets_analyzed": 0,
            "total_impressions": 0, "total_likes": 0,
            "total_retweets": 0, "total_replies": 0,
            "total_clicks": 0, "engagement_rate": 0,
            "best_tweet": None, "dry_run": True,
        }
        save_kpi(dummy)
        print(f"  ✅ ダミーKPI保存完了 → {KPI_FILE}")
        return

    run_fetch()


if __name__ == "__main__":
    main()
