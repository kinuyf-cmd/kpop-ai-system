"""
X/Twitter自動投稿（OAuth 1.0a 正規API版）

Usage:
  python3 post_to_x.py "投稿テキスト"
  python3 post_to_x.py "投稿テキスト" --reply-to TWEET_ID
  python3 post_to_x.py "投稿テキスト" --alt-text "画像ALTテキスト"

Output:
  ✅ X投稿成功: https://x.com/i/status/TWEET_ID
  TWEET_ID=TWEET_ID   ← シェルスクリプトから取得用
"""
import json, sys, os, hmac, hashlib, base64, time, uuid, argparse
import urllib.request, urllib.error, urllib.parse

CREDS_FILE = os.path.expanduser("~/.x_credentials")

parser = argparse.ArgumentParser(description="X/Twitter投稿")
parser.add_argument("text", help="投稿テキスト")
parser.add_argument("--reply-to", default="", help="返信先ツイートID")
parser.add_argument("--alt-text", default="", help="画像ALTテキスト（将来拡張用）")
args = parser.parse_args()

text = args.text.strip()
reply_to = args.reply_to.strip()

if not text:
    print("Usage: python3 post_to_x.py \"投稿テキスト\"")
    sys.exit(1)

if not os.path.exists(CREDS_FILE):
    print("❌ ~/.x_credentials が見つかりません")
    sys.exit(1)

with open(CREDS_FILE) as f:
    creds = json.load(f)

api_key            = creds["api_key"]
api_secret         = creds["api_secret"]
access_token       = creds["access_token"]
access_token_secret = creds["access_token_secret"]


def make_oauth_header(method: str, endpoint: str) -> str:
    """OAuth 1.0a 署名ヘッダを生成"""
    params = {
        "oauth_consumer_key":     api_key,
        "oauth_nonce":            uuid.uuid4().hex,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp":        str(int(time.time())),
        "oauth_token":            access_token,
        "oauth_version":          "1.0",
    }
    params_string = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(params.items())
    )
    base_string = f"{method}&{urllib.parse.quote(endpoint, safe='')}&{urllib.parse.quote(params_string, safe='')}"
    signing_key = f"{urllib.parse.quote(api_secret, safe='')}&{urllib.parse.quote(access_token_secret, safe='')}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()
    params["oauth_signature"] = signature
    return "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(params.items())
    )


def post_tweet(text: str, reply_to_id: str = "") -> str:
    """ツイートを投稿し tweet_id を返す。失敗時は例外を送出。"""
    endpoint = "https://api.twitter.com/2/tweets"
    body: dict = {"text": text}
    if reply_to_id:
        body["reply"] = {"in_reply_to_tweet_id": reply_to_id}

    auth_header = make_oauth_header("POST", endpoint)
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization":  auth_header,
            "Content-Type":   "application/json",
            "User-Agent":     "KPOPJournalBot/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        result = json.loads(res.read())
    return result.get("data", {}).get("id", "")


try:
    tweet_id = post_tweet(text, reply_to)
    if tweet_id:
        tweet_url = f"https://x.com/i/status/{tweet_id}"
        if reply_to:
            print(f"✅ X返信投稿成功: {tweet_url}")
        else:
            print(f"✅ X投稿成功: {tweet_url}")
        print(f"  投稿文: {text[:80]}{'...' if len(text)>80 else ''}")
        print(f"TWEET_ID={tweet_id}")   # シェルスクリプトから grep で取得
    else:
        print("✅ X投稿完了 (IDなし)")
        print("TWEET_ID=")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"❌ X投稿失敗 (HTTP {e.code}): {body[:300]}")
    sys.exit(1)
except Exception as e:
    print(f"❌ X投稿失敗: {e}")
    sys.exit(1)
