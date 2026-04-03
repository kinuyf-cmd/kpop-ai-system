"""
X/Twitter自動投稿（OAuth 1.0a 正規API版）

Usage:
  python3 ~/google_metrics/post_to_x.py "投稿テキスト"
"""
import json, sys, os, hmac, hashlib, base64, time, uuid
import urllib.request, urllib.error, urllib.parse

CREDS_FILE = os.path.expanduser("~/.x_credentials")

if not os.path.exists(CREDS_FILE):
    print("❌ ~/.x_credentials が見つかりません")
    sys.exit(1)

text = sys.argv[1] if len(sys.argv) > 1 else ""
if not text:
    print("Usage: python3 post_to_x.py \"投稿テキスト\"")
    sys.exit(1)

with open(CREDS_FILE) as f:
    creds = json.load(f)

api_key = creds["api_key"]
api_secret = creds["api_secret"]
access_token = creds["access_token"]
access_token_secret = creds["access_token_secret"]

# Twitter API v2: POST /2/tweets
url = "https://api.twitter.com/2/tweets"
method = "POST"

# OAuth 1.0a署名生成
oauth_params = {
    "oauth_consumer_key": api_key,
    "oauth_nonce": uuid.uuid4().hex,
    "oauth_signature_method": "HMAC-SHA1",
    "oauth_timestamp": str(int(time.time())),
    "oauth_token": access_token,
    "oauth_version": "1.0",
}

params_string = "&".join(
    f"{urllib.parse.quote(k, safe='')}" + "=" + f"{urllib.parse.quote(v, safe='')}"
    for k, v in sorted(oauth_params.items())
)
base_string = f"{method}&{urllib.parse.quote(url, safe='')}&{urllib.parse.quote(params_string, safe='')}"
signing_key = f"{urllib.parse.quote(api_secret, safe='')}&{urllib.parse.quote(access_token_secret, safe='')}"

signature = base64.b64encode(
    hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
).decode()

oauth_params["oauth_signature"] = signature

auth_header = "OAuth " + ", ".join(
    f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
    for k, v in sorted(oauth_params.items())
)

payload = json.dumps({"text": text}).encode()

req = urllib.request.Request(
    url,
    data=payload,
    headers={
        "Authorization": auth_header,
        "Content-Type": "application/json",
        "User-Agent": "KPOPJournalBot/1.0",
    },
)

try:
    with urllib.request.urlopen(req, timeout=30) as res:
        result = json.loads(res.read())
        tweet_id = result.get("data", {}).get("id", "")
        if tweet_id:
            print(f"✅ X投稿成功: https://x.com/i/status/{tweet_id}")
            print(f"  投稿文: {text[:80]}...")
        else:
            print(f"✅ X投稿完了")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"❌ X投稿失敗 (HTTP {e.code}): {body[:300]}")
    sys.exit(1)
except Exception as e:
    print(f"❌ X投稿失敗: {e}")
    sys.exit(1)
