"""
X/Twitter自動投稿（OAuth 1.0a 正規API版）

ライブラリとしても CLI としても使える。
  ライブラリ:  from google_metrics.post_to_x import post_tweet, validate_credentials
  CLI:        python3 post_to_x.py "投稿テキスト" [--reply-to TWEET_ID]

2026-05-26 関数化(施策0): 旧版はトップレベル実行のみで post_tweet/validate_credentials
を定義しておらず、lib/x_poster.py の `from post_to_x import post_tweet, validate_credentials`
が常に ImportError → 握りつぶしで 2段投稿(post_hook_and_reply)が死コードだった。
さらに --reply-to を読まず in_reply_to_tweet_id を送らないため返信が単発化していた。
本版で両方を解消する(CLI 挙動は後方互換)。
"""
import json, sys, os, hmac, hashlib, base64, time, uuid, argparse
import urllib.request, urllib.error, urllib.parse

CREDS_FILE = os.path.expanduser("~/.x_credentials")
_API_URL = "https://api.twitter.com/2/tweets"
# X_DRYRUN=1 で実際の API 送信をせず mock tweet_id を返す(検証用)
DRYRUN = bool(int(os.environ.get("X_DRYRUN", "0")))


def validate_credentials():
    """(creds_dict | None, errors:list[str]) を返す。4キー欠落・JSON不正を検出。"""
    errors = []
    if not os.path.exists(CREDS_FILE):
        return None, [f"{CREDS_FILE} が見つかりません"]
    try:
        with open(CREDS_FILE) as f:
            creds = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        return None, [f"~/.x_credentials 読み込み/JSON 不正: {e}"]
    for k in ("api_key", "api_secret", "access_token", "access_token_secret"):
        if not str(creds.get(k, "")).strip():
            errors.append(f"認証キー欠落: {k}")
    if errors:
        return None, errors
    return creds, []


def _oauth_header(method: str, url: str, creds: dict) -> str:
    """OAuth 1.0a 署名ヘッダを生成(従来の実装をそのまま関数化)。"""
    oauth_params = {
        "oauth_consumer_key": creds["api_key"],
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": creds["access_token"],
        "oauth_version": "1.0",
    }
    params_string = "&".join(
        f"{urllib.parse.quote(k, safe='')}=" + f"{urllib.parse.quote(v, safe='')}"
        for k, v in sorted(oauth_params.items())
    )
    base_string = f"{method}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(params_string, safe='')}"
    signing_key = f"{urllib.parse.quote(creds['api_secret'], safe='')}&{urllib.parse.quote(creds['access_token_secret'], safe='')}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()
    oauth_params["oauth_signature"] = signature
    return "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(oauth_params.items())
    )


def post_tweet(text: str, reply_to: str | None = None, creds: dict | None = None) -> tuple[str, str]:
    """ツイート投稿。成功で (tweet_id, "") を返す。失敗は (",", error_detail)。

    reply_to を指定すると in_reply_to_tweet_id 付きの返信として投稿する(致命バグB修正)。
    creds 未指定なら validate_credentials() で読み込む。
    """
    if not text or not text.strip():
        return "", "本文が空"
    if creds is None:
        creds, errors = validate_credentials()
        if creds is None:
            return "", "; ".join(errors)

    body = {"text": text}
    if reply_to:
        body["reply"] = {"in_reply_to_tweet_id": str(reply_to)}

    if DRYRUN:
        # 署名・送信をせず擬似IDを返す(検証用)
        return f"DRYRUN-{uuid.uuid4().hex[:12]}", ""

    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        _API_URL, data=payload,
        headers={
            "Authorization": _oauth_header("POST", _API_URL, creds),
            "Content-Type": "application/json",
            "User-Agent": "KPOPJournalBot/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            result = json.loads(res.read())
            return result.get("data", {}).get("id", ""), ""
    except urllib.error.HTTPError as e:
        return "", f"HTTP {e.code}: {e.read().decode()[:300]}"
    except Exception as e:  # noqa: BLE001 — ネットワーク等は文字列化して返す
        return "", str(e)[:300]


def get_public_metrics(ids: list[str], creds: dict | None = None) -> dict:
    """tweet_id のリストから public_metrics を取得し {tweet_id: metrics_dict} を返す。
    GET /2/tweets?ids=...&tweet.fields=public_metrics(OAuth1.0a)。最大100件/回。
    取得失敗・該当なしは空 dict をスキップ(エラーは握りつぶさず print)。"""
    ids = [str(i) for i in ids if str(i).strip() and str(i).isdigit()]
    if not ids:
        return {}
    if creds is None:
        creds, errors = validate_credentials()
        if creds is None:
            print("get_public_metrics: " + "; ".join(errors), file=sys.stderr)
            return {}
    out = {}
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        base = "https://api.twitter.com/2/tweets"
        query = "ids=" + ",".join(chunk) + "&tweet.fields=public_metrics"
        url = f"{base}?{query}"
        # 署名は GET、クエリパラメータも署名対象に含める必要がある
        req = urllib.request.Request(url, method="GET", headers={
            "Authorization": _oauth_header_with_params(
                "GET", base, creds, {"ids": ",".join(chunk), "tweet.fields": "public_metrics"}),
            "User-Agent": "KPOPJournalBot/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                data = json.loads(res.read())
            for t in data.get("data", []):
                out[t["id"]] = t.get("public_metrics", {})
        except urllib.error.HTTPError as e:
            print(f"get_public_metrics HTTP {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"get_public_metrics err: {e}", file=sys.stderr)
    return out


def _oauth_header_with_params(method: str, url: str, creds: dict, extra: dict) -> str:
    """GET 等でクエリパラメータも署名対象に含める版の OAuth1.0a ヘッダ。"""
    oauth_params = {
        "oauth_consumer_key": creds["api_key"],
        "oauth_nonce": uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": creds["access_token"],
        "oauth_version": "1.0",
    }
    all_params = {**oauth_params, **extra}
    params_string = "&".join(
        f"{urllib.parse.quote(k, safe='')}=" + f"{urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(all_params.items())
    )
    base_string = f"{method}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(params_string, safe='')}"
    signing_key = f"{urllib.parse.quote(creds['api_secret'], safe='')}&{urllib.parse.quote(creds['access_token_secret'], safe='')}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()
    oauth_params["oauth_signature"] = signature
    return "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(oauth_params.items())
    )


def _cli() -> int:
    ap = argparse.ArgumentParser(description="X/Twitter 投稿(OAuth1.0a)")
    ap.add_argument("text", nargs="?", default="", help="投稿テキスト")
    ap.add_argument("--reply-to", dest="reply_to", default=None, help="返信先 tweet_id")
    args = ap.parse_args()
    if not args.text:
        print('Usage: python3 post_to_x.py "投稿テキスト" [--reply-to TWEET_ID]')
        return 1
    creds, errors = validate_credentials()
    if creds is None:
        print("❌ " + "; ".join(errors))
        return 1
    tweet_id, err = post_tweet(args.text, reply_to=args.reply_to, creds=creds)
    if tweet_id:
        # 既存呼び出し側(post_to_x.sh)が "TWEET_ID=" を grep するため両方出力
        print(f"✅ X投稿成功: https://x.com/i/status/{tweet_id}")
        print(f"TWEET_ID={tweet_id}")
        print(f"  投稿文: {args.text[:80]}...")
        return 0
    print(f"❌ X投稿失敗: {err}")
    return 1


if __name__ == "__main__":
    sys.exit(_cli())
