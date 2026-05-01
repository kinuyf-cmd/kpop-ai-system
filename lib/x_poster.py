#!/usr/bin/env python3
"""X投稿ラッパー: google_metrics/post_to_x.py (~/.x_credentials) を直接利用

スパム防止3層防御:
  1. レート制限: 1時間あたり MAX_POSTS_PER_HOUR 投稿まで
  2. 類似テキスト検知: 直近投稿と類似度が高い場合はキュー送り
  3. フック+リプライ方式: URLはリプライで挿入、ハッシュタグでユニーク化
"""
import sys, os, json
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, '/home/aiuser/kpop-ai-system/google_metrics')

BASE = Path('/home/aiuser/kpop-ai-system')
LOG = str(BASE / 'logs' / 'x_posts.jsonl')
RETRY_QUEUE = BASE / 'config' / 'x_retry_queue.json'

MAX_POSTS_PER_HOUR = 3
SIMILARITY_THRESHOLD = 0.7  # 70%以上類似ならキュー送り

# 既存モジュールをimport
_validate = None
_post = None
try:
    from post_to_x import validate_credentials as _validate, post_tweet as _post
except Exception as e:
    print(f"post_to_x import warning: {e}", file=sys.stderr)


def _recent_posts(hours: int = 1) -> list[dict]:
    """直近N時間の投稿ログを取得"""
    if not os.path.exists(LOG):
        return []
    cutoff = datetime.now() - timedelta(hours=hours)
    recent = []
    try:
        with open(LOG, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry.get('ts', '2000-01-01'))
                    if ts >= cutoff and entry.get('status') == 'ok':
                        recent.append(entry)
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        pass
    return recent


def _text_similarity(a: str, b: str) -> float:
    """簡易テキスト類似度（文字集合のJaccard係数）"""
    if not a or not b:
        return 0.0
    set_a = set(a[:100])
    set_b = set(b[:100])
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _add_to_retry_queue(text: str, url: str, post_id: int = None):
    """レート制限超過時にリトライキューに追加"""
    queue_data = {'created': datetime.now().strftime('%Y-%m-%d'), 'reason': 'rate_limit', 'queue': []}
    if RETRY_QUEUE.exists():
        try:
            queue_data = json.loads(RETRY_QUEUE.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass

    if not isinstance(queue_data.get('queue'), list):
        queue_data['queue'] = []

    entry = {'text': text[:200], 'url': url, 'added_at': datetime.now().isoformat()}
    if post_id:
        entry['post_id'] = post_id
    queue_data['queue'].append(entry)
    RETRY_QUEUE.write_text(json.dumps(queue_data, ensure_ascii=False, indent=2), encoding='utf-8')


def post_tweet(text: str, url: str = None, post_id: int = None) -> dict:
    """X投稿 (unified_publisher等から呼ばれる)

    URL込み単一投稿方式: OGPカード表示のためURLをメイン投稿に含める。
    レート制限(1h/3件)+類似テキスト検知+ハッシュタグでスパム判定を防止。

    Args:
        text: タイトル/本文
        url: 記事URL (メイン投稿に含める)
        post_id: WordPress記事ID（監査のログ照合用）

    Returns:
        {'success': bool, 'tweet_id': str|None, 'error': str|None, 'queued': bool}
    """
    if _validate is None or _post is None:
        return {'success': False, 'error': 'post_to_x module import失敗'}

    # --- レート制限チェック ---
    recent = _recent_posts(hours=1)
    if len(recent) >= MAX_POSTS_PER_HOUR:
        _add_to_retry_queue(text, url, post_id)
        return {
            'success': False, 'queued': True,
            'error': f'レート制限: 直近1時間に{len(recent)}件投稿済み (上限{MAX_POSTS_PER_HOUR}件)。キューに追加'
        }

    # --- 類似テキスト検知 ---
    for r in recent:
        if _text_similarity(text, r.get('text', '')) > SIMILARITY_THRESHOLD:
            _add_to_retry_queue(text, url, post_id)
            return {
                'success': False, 'queued': True,
                'error': '類似テキスト検知: 直近投稿と類似度が高いためキューに追加'
            }

    # --- credential検証 ---
    creds, errors = _validate()
    if errors or creds is None:
        return {'success': False, 'error': '; '.join(errors[:2]) if errors else 'credential invalid'}

    # --- テキスト構築: URL込み+ハッシュタグでユニーク化 ---
    # URL=23字(t.co短縮) + ハッシュタグ約20字 + 改行3字 = 約46字を予約
    max_title = 280 - 46 - (24 if url else 0)
    hook_text = text[:max_title].rstrip()
    parts = [hook_text, '\n\n#KPOPJOURNAL #KPOP']
    if url:
        parts.append(f'\n{url}')
    full_text = ''.join(parts)[:280]

    try:
        tweet_id, attempts = _post(full_text, '', creds)
        entry = {
            'ts': datetime.now().isoformat(),
            'tweet_id': tweet_id,
            'text': full_text[:120],
            'url': url,
            'attempts': attempts,
            'status': 'ok',
        }
        if post_id:
            entry['post_id'] = post_id

        _log(entry)
        return {'success': True, 'tweet_id': tweet_id}
    except Exception as e:
        err = str(e)[:200]
        entry = {
            'ts': datetime.now().isoformat(),
            'text': full_text[:120],
            'url': url,
            'status': 'error',
            'error': err,
        }
        if post_id:
            entry['post_id'] = post_id
        _log(entry)
        return {'success': False, 'error': err}


def _log(d):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(d, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    t = sys.argv[1] if len(sys.argv) > 1 else 'X連携テスト'
    u = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(post_tweet(t, u), ensure_ascii=False, indent=2))
