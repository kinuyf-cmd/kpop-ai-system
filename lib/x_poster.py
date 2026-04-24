#!/usr/bin/env python3
"""X (Twitter) API v2 自動投稿

credentialない場合はskip、エラー出さず継続
"""
import os, json, urllib.request, urllib.error, base64, hashlib, hmac, time, secrets
from urllib.parse import quote
from dotenv import load_dotenv
load_dotenv()

LOG = '/home/aiuser/kpop-ai-system/logs/x_posts.jsonl'


def _oauth1_sign(method, url, oauth_params, consumer_secret, token_secret):
    all_params = dict(oauth_params)
    sorted_params = sorted(all_params.items())
    param_str = '&'.join(f"{quote(str(k), safe='')}={quote(str(v), safe='')}" for k, v in sorted_params)
    base_str = f"{method.upper()}&{quote(url, safe='')}&{quote(param_str, safe='')}"
    signing_key = f"{quote(consumer_secret, safe='')}&{quote(token_secret, safe='')}"
    return base64.b64encode(
        hmac.new(signing_key.encode(), base_str.encode(), hashlib.sha1).digest()
    ).decode()


def post_tweet(text: str, url: str = None) -> dict:
    ck = os.getenv('X_API_KEY')
    cs = os.getenv('X_API_SECRET')
    at = os.getenv('X_ACCESS_TOKEN')
    ats = os.getenv('X_ACCESS_TOKEN_SECRET')

    if not all([ck, cs, at, ats]):
        return {'success': False, 'error': 'X credential未設定、skip'}

    if url:
        available = 280 - 24
        if len(text) > available:
            text = text[:available - 1] + '…'
        full_text = f"{text}\n{url}"
    else:
        full_text = text[:280]

    api_url = 'https://api.twitter.com/2/tweets'
    oauth_params = {
        'oauth_consumer_key': ck,
        'oauth_nonce': secrets.token_hex(16),
        'oauth_signature_method': 'HMAC-SHA1',
        'oauth_timestamp': str(int(time.time())),
        'oauth_token': at,
        'oauth_version': '1.0',
    }
    signature = _oauth1_sign('POST', api_url, oauth_params, cs, ats)
    oauth_params['oauth_signature'] = signature

    auth_header = 'OAuth ' + ', '.join(
        f'{k}="{quote(v, safe="")}"' for k, v in sorted(oauth_params.items())
    )

    body = json.dumps({'text': full_text}).encode()
    req = urllib.request.Request(api_url, data=body, headers={
        'Authorization': auth_header,
        'Content-Type': 'application/json',
    }, method='POST')

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read())
            tid = res.get('data', {}).get('id', '')
            _log({'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'tweet_id': tid, 'status': 'ok'})
            return {'success': True, 'tweet_id': tid}
    except urllib.error.HTTPError as e:
        err = e.read().decode('utf-8', errors='replace')[:300]
        _log({'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'status': 'http_error', 'error': err})
        return {'success': False, 'error': f'HTTP {e.code}: {err[:200]}'}
    except Exception as e:
        _log({'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'status': 'error', 'error': str(e)})
        return {'success': False, 'error': str(e)[:200]}


def _log(d):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(d, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else 'X API test'
    u = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(post_tweet(t, u), ensure_ascii=False, indent=2))
