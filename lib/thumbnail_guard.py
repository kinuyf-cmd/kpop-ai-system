"""サムネ上書き保護ゲート — 全経路がこの関数を経由する

MV画像 (v6_mv_ / v6_kpop_thumb でdalleを含まない) が設定済みの場合、
上書きをブロックする。force=True の場合のみ強制上書き可能。
"""
import json, os, urllib.request, base64
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode() if WP_USER else ''

LOG_PATH = '/home/aiuser/kpop-ai-system/logs/thumbnail_guard.log'


def _log(msg):
    from datetime import datetime
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, 'a') as f:
        f.write(f'[{datetime.now().isoformat()}] {msg}\n')


def is_protected(post_id, post_type='posts'):
    """既存サムネがMV画像として保護対象かを判定"""
    endpoint = post_type if post_type != 'post' else 'posts'
    try:
        url = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}/{post_id}?_fields=featured_media'
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        fm_id = data.get('featured_media', 0)
        if not fm_id:
            return False

        url2 = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{fm_id}?_fields=media_details'
        req2 = urllib.request.Request(url2, headers={'Authorization': f'Basic {AUTH}'})
        media = json.loads(urllib.request.urlopen(req2, timeout=10).read())
        filename = media.get('media_details', {}).get('file', '')

        # MV画像の判定: v6_mv_ または (v6_kpop_thumb かつ dalle を含まない)
        is_mv = 'v6_mv_' in filename
        is_v6_real = 'v6_kpop_thumb' in filename and 'dalle' not in filename.lower()

        return is_mv or is_v6_real
    except:
        return False


def safe_update_featured_media(post_id, new_media_id, post_type='posts', force=False, source='unknown'):
    """サムネ更新の唯一のエントリポイント。保護対象なら上書きを拒否。"""
    if not force and is_protected(post_id, post_type):
        msg = f'BLOCKED: post {post_id} のMV画像上書きを拒否 (source={source})'
        print(f'  🛡️ {msg}')
        _log(msg)
        return {'success': False, 'reason': 'mv_protected', 'blocked': True}

    endpoint = post_type if post_type != 'post' else 'posts'
    try:
        url = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}/{post_id}'
        body = json.dumps({'featured_media': new_media_id}).encode()
        req = urllib.request.Request(url, data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=15)
        _log(f'OK: post {post_id} featured_media={new_media_id} (source={source})')
        return {'success': True, 'media_id': new_media_id}
    except Exception as e:
        _log(f'ERR: post {post_id} {e}')
        return {'success': False, 'error': str(e)}
