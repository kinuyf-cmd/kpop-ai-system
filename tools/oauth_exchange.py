#!/usr/bin/env python3
"""OAuth認証コード→トークン交換

使い方: python3 tools/oauth_exchange.py "http://localhost/?code=4/0XXXX&scope=..."
または:  python3 tools/oauth_exchange.py "4/0XXXX" (codeだけ)
"""
import sys, json, urllib.request, urllib.parse, os

CLIENT_FILE = '/home/aiuser/kpop-ai-system/google_metrics/oauth_client.json'
TOKEN_FILE = '/home/aiuser/kpop-ai-system/google_metrics/oauth_token.json'

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 oauth_exchange.py <code_or_redirect_url>")
        sys.exit(1)

    raw = sys.argv[1]

    # URLからcode抽出
    if raw.startswith('http'):
        parsed = urllib.parse.urlparse(raw)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get('code', [''])[0]
    else:
        code = raw.strip()

    if not code:
        print("code not found")
        sys.exit(1)

    print(f"code: {code[:20]}...")

    client = json.load(open(CLIENT_FILE))['installed']

    body = urllib.parse.urlencode({
        'code': code,
        'client_id': client['client_id'],
        'client_secret': client['client_secret'],
        'redirect_uri': 'http://localhost',
        'grant_type': 'authorization_code',
    }).encode()

    req = urllib.request.Request(client['token_uri'], data=body,
                                 headers={'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        r = urllib.request.urlopen(req, timeout=30)
        token = json.loads(r.read())
        token['client_id'] = client['client_id']
        token['client_secret'] = client['client_secret']
        token['token_uri'] = client['token_uri']

        json.dump(token, open(TOKEN_FILE, 'w'), indent=2)
        os.chmod(TOKEN_FILE, 0o600)
        print(f"\n✅ トークン保存: {TOKEN_FILE}")
        print(f"  access_token: {token.get('access_token','')[:20]}...")
        print(f"  refresh_token: {'あり' if token.get('refresh_token') else 'なし'}")
        print(f"  scope: {token.get('scope','')[:100]}")
    except urllib.error.HTTPError as e:
        err = e.read().decode('utf-8', errors='replace')
        print(f"🔴 トークン交換失敗: HTTP {e.code}")
        print(err[:500])
    except Exception as e:
        print(f"🔴 error: {e}")


if __name__ == '__main__':
    main()
