#!/usr/bin/env python3
"""X投稿ラッパー: google_metrics/post_to_x.py (~/.x_credentials) を直接利用"""
import sys, os, json
from datetime import datetime

sys.path.insert(0, '/home/aiuser/kpop-ai-system/google_metrics')

LOG = '/home/aiuser/kpop-ai-system/logs/x_posts.jsonl'

# 既存モジュールをimport
_validate = None
_post = None
try:
    from post_to_x import validate_credentials as _validate, post_tweet as _post
except Exception as e:
    print(f"post_to_x import warning: {e}", file=sys.stderr)


def post_tweet(text: str, url: str = None) -> dict:
    """X投稿 (unified_publisher等から呼ばれる)

    Args:
        text: タイトル/本文
        url: 記事URL (末尾追加、Xで23字短縮)

    Returns:
        {'success': bool, 'tweet_id': str|None, 'error': str|None}
    """
    if _validate is None or _post is None:
        return {'success': False, 'error': 'post_to_x module import失敗'}

    # credential検証
    creds, errors = _validate()
    if errors or creds is None:
        return {'success': False, 'error': '; '.join(errors[:2]) if errors else 'credential invalid'}

    # テキスト構築
    if url:
        available = 280 - 24  # URL=23字+改行
        if len(text) > available:
            text = text[:available - 1] + '…'
        full_text = f"{text}\n{url}"
    else:
        full_text = text[:280]

    try:
        tweet_id, attempts = _post(full_text, '', creds)
        _log({
            'ts': datetime.now().isoformat(),
            'tweet_id': tweet_id,
            'text': full_text[:120],
            'url': url,
            'attempts': attempts,
            'status': 'ok',
        })
        return {'success': True, 'tweet_id': tweet_id}
    except Exception as e:
        err = str(e)[:200]
        _log({
            'ts': datetime.now().isoformat(),
            'text': full_text[:120],
            'url': url,
            'status': 'error',
            'error': err,
        })
        return {'success': False, 'error': err}


def _log(d):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(d, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    t = sys.argv[1] if len(sys.argv) > 1 else 'X連携テスト'
    u = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(post_tweet(t, u), ensure_ascii=False, indent=2))
