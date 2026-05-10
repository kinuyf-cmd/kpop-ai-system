"""Next.js ISRキャッシュのOn-Demand Revalidation

記事のdraft/trash化時にフロントエンドのキャッシュを即座にパージする。
soft-404 (200 + 「記事が見つかりません」) を防止。

Usage:
    from lib.frontend_cache import purge_paths
    purge_paths(['/le-sserafim-2025-comeback-decision/'])
"""
import json
import urllib.request
import urllib.error
from pathlib import Path

FRONTEND_URL = 'https://www.kpopjournal.tokyo'
REVALIDATE_SECRET = 'kpj-revalidate-2026'
LOG_PATH = Path('/home/aiuser/kpop-ai-system/logs/cache_purge.log')


def purge_paths(paths: list[str]) -> dict:
    """指定パスのISRキャッシュをパージ

    Args:
        paths: パスのリスト (例: ['/slug/', '/popup/seoul/1234/'])

    Returns:
        {'success': bool, 'results': list}
    """
    url = f'{FRONTEND_URL}/api/revalidate/'
    payload = json.dumps({
        'paths': paths,
        'secret': REVALIDATE_SECRET,
    }).encode()

    req = urllib.request.Request(url, data=payload, headers={
        'Content-Type': 'application/json',
        'User-Agent': 'kpj-cache-purge/1.0',
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
        _log(f'purge OK: {paths} → {result}')
        return {'success': True, **result}
    except urllib.error.HTTPError as e:
        err = e.read().decode('utf-8', errors='replace')[:200]
        _log(f'purge FAIL: {paths} → {e.code} {err}')
        return {'success': False, 'error': f'HTTP {e.code}: {err}'}
    except Exception as e:
        _log(f'purge ERR: {paths} → {e}')
        return {'success': False, 'error': str(e)[:200]}


def purge_post(slug: str) -> dict:
    """記事slugのキャッシュをパージ"""
    path = f'/{slug}/' if not slug.startswith('/') else slug
    return purge_paths([path])


def _log(msg: str):
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(f'[{datetime.now().isoformat()[:19]}] {msg}\n')
    except Exception:
        pass
