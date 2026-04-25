#!/usr/bin/env python3
"""OAuth認証コード→トークン交換（localhost不要・コード手動コピー方式）

Step 1 - 認証URLを生成:
  python3 tools/oauth_exchange.py --auth-url

Step 2 - オーナーがブラウザで認証URL を開き、許可後に表示されるエラーページの
         アドレスバーから code パラメータをコピー:
         http://localhost/?code=4/0XXXX&scope=...  ← この 4/0XXXX 部分

Step 3 - コードをトークンに交換:
  python3 tools/oauth_exchange.py "4/0XXXX"
  python3 tools/oauth_exchange.py "http://localhost/?code=4/0XXXX&scope=..."
"""
import sys, json, urllib.request, urllib.parse, os

CLIENT_FILE = '/home/aiuser/kpop-ai-system/google_metrics/oauth_client.json'
TOKEN_FILE = '/home/aiuser/kpop-ai-system/google_metrics/oauth_token.json'

SCOPES = [
    'https://www.googleapis.com/auth/webmasters.readonly',
    'https://www.googleapis.com/auth/analytics.readonly',
    'https://www.googleapis.com/auth/adsense.readonly',
    'https://www.googleapis.com/auth/gmail.readonly',
]


def print_auth_url():
    """認証URLを生成して表示（オーナーのブラウザで開く用）"""
    client = json.load(open(CLIENT_FILE))['installed']
    params = urllib.parse.urlencode({
        'client_id': client['client_id'],
        'redirect_uri': 'http://localhost',
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'access_type': 'offline',
        'prompt': 'consent',
    })
    url = f"{client['auth_uri']}?{params}"

    print("=" * 60)
    print("GSC OAuth 認証URL（オーナーに送信してください）")
    print("=" * 60)
    print()
    print(url)
    print()
    print("-" * 60)
    print("【オーナー向け手順】")
    print("1. 上のURLをブラウザで開く")
    print("2. Googleアカウントでログインし、アクセスを許可")
    print("3. 「このサイトにアクセスできません」エラーが出るが正常")
    print("4. アドレスバーのURLをそのままコピー")
    print("   例: http://localhost/?code=4/0AanRRr...")
    print("5. コピーしたURLまたはcode部分を送信")
    print("-" * 60)


def exchange_code(raw):
    """認証コードをトークンに交換"""
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


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print("Usage:")
        print("  python3 oauth_exchange.py --auth-url          # 認証URLを生成")
        print("  python3 oauth_exchange.py <code_or_url>       # コード→トークン交換")
        sys.exit(0)

    if sys.argv[1] == '--auth-url':
        print_auth_url()
    else:
        exchange_code(sys.argv[1])


if __name__ == '__main__':
    main()
