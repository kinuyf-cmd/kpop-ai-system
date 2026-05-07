"""ローチケ (l-tike.com) の K-POP/韓流/アジア artist hub から公演を取得

ローチケは Akamai bot mitigation のため通常の curl/urllib では応答なし。
curl-impersonate (~/.local/bin/curl-impersonate/curl_chrome116) で
Chrome 116 の TLS fingerprint を模倣して突破。

各イベント詳細ページに ld+json (schema.org Event) が埋まっているため
そこから name/startDate/endDate/location.name/addressRegion を抽出。

データ源: 2026-05-07 調査
変更時は K-POP hub artist id (632997) と /concert/mevent/?mid= URL構造を再確認
"""
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

BASE = Path('/home/aiuser/kpop-ai-system')
CACHE_PATH = BASE / 'data' / 'ltike_enrichment_cache.json'
CACHE_TTL_SEC = 12 * 3600  # 12時間 (販売状況がそこそこ流動的)

# K-POP/韓流/アジア カテゴリ artist hub の固定ID
KPOP_HUB_URL = 'https://l-tike.com/artist/000000000632997/'

CURL_IMPERSONATE = Path.home() / '.local' / 'bin' / 'curl-impersonate' / 'curl_chrome116'


def _curl_impersonate_available() -> bool:
    return CURL_IMPERSONATE.exists() and os.access(CURL_IMPERSONATE, os.X_OK)


def _fetch(url: str, *, timeout: int = 20) -> str | None:
    """curl-impersonate でページを取得"""
    if not _curl_impersonate_available():
        return None
    try:
        r = subprocess.run(
            [str(CURL_IMPERSONATE), '-sL', url, '--max-time', str(timeout)],
            capture_output=True, timeout=timeout + 5,
        )
        if r.returncode != 0:
            return None
        return r.stdout.decode('utf-8', errors='replace')
    except Exception:
        return None


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.load(open(CACHE_PATH, encoding='utf-8'))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    json.dump(cache, open(CACHE_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


def _is_fresh(entry: dict, ttl: int = CACHE_TTL_SEC) -> bool:
    ts = entry.get('cached_at')
    if not ts:
        return False
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds() < ttl
    except Exception:
        return False


def discover_kpop_events() -> list[tuple[str, str]]:
    """K-POP/韓流/アジア hub から (path_prefix, mid) のリストを取得"""
    html = _fetch(KPOP_HUB_URL)
    if not html:
        return []
    seen = set()
    out = []
    # absolute and relative both
    for m in re.finditer(r'href="(?:https?://l-tike\.com)?/([a-z]+)/mevent/\?mid=(\d+)"', html):
        prefix, mid = m.group(1), m.group(2)
        if mid in seen:
            continue
        seen.add(mid)
        out.append((prefix, mid))
    return out


def fetch_ltike_event(prefix: str, mid: str, *, sleep_sec: float = 0.6, force: bool = False) -> dict | None:
    """1イベントの ld+json を取得

    Returns:
        {
          'mid': str,
          'title': str,
          'startDate': 'YYYY-MM-DD',
          'endDate': 'YYYY-MM-DD',
          'venue': str,
          'prefecture': str,
          'image': str,
          'url': str,
          'cached_at': str,
        }
    """
    cache = _load_cache()
    key = f'{prefix}:{mid}'

    if not force and key in cache and _is_fresh(cache[key]):
        return cache[key] if not cache[key].get('not_found') else None

    url = f'https://l-tike.com/{prefix}/mevent/?mid={mid}'
    html = _fetch(url)
    time.sleep(sleep_sec)
    if not html or len(html) < 1000:
        cache[key] = {'mid': mid, 'cached_at': datetime.now().isoformat(), 'not_found': True}
        _save_cache(cache)
        return None

    # ld+json Event
    event_data = None
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.+?)</script>', html, re.DOTALL):
        body = m.group(1).strip()
        try:
            data = json.loads(body)
        except Exception:
            continue
        if isinstance(data, list):
            for d in data:
                if isinstance(d, dict) and d.get('@type') == 'Event':
                    event_data = d
                    break
        elif isinstance(data, dict) and data.get('@type') == 'Event':
            event_data = data
        if event_data:
            break

    if not event_data:
        cache[key] = {'mid': mid, 'url': url, 'cached_at': datetime.now().isoformat(), 'not_found': True}
        _save_cache(cache)
        return None

    loc = event_data.get('location') or {}
    addr = loc.get('address') or {}
    images = event_data.get('image') or []
    image_url = images[0] if isinstance(images, list) and images else (images if isinstance(images, str) else '')

    start = event_data.get('startDate') or ''
    end = event_data.get('endDate') or ''
    # 'YYYY-MM-DD' or full ISO; keep just the date prefix
    start_date = start[:10] if len(start) >= 10 else ''
    end_date = end[:10] if len(end) >= 10 else ''

    result = {
        'mid': mid,
        'title': (event_data.get('name') or '').strip(),
        'startDate': start_date,
        'endDate': end_date,
        'venue': (loc.get('name') or '').strip(),
        'prefecture': (addr.get('addressRegion') or '').strip(),
        'image': image_url,
        'url': url,
        'cached_at': datetime.now().isoformat(),
    }
    cache[key] = result
    _save_cache(cache)
    return result


if __name__ == '__main__':
    import sys
    if not _curl_impersonate_available():
        print(f'curl-impersonate not found at {CURL_IMPERSONATE}')
        sys.exit(1)
    if len(sys.argv) >= 2 and sys.argv[1] == 'discover':
        events = discover_kpop_events()
        print(f'discovered {len(events)} K-POP event mids')
        for prefix, mid in events:
            print(f'  /{prefix}/mevent/?mid={mid}')
    elif len(sys.argv) >= 2 and sys.argv[1] == 'all':
        events = discover_kpop_events()
        print(f'enriching {len(events)} events...')
        for prefix, mid in events:
            r = fetch_ltike_event(prefix, mid)
            if r:
                end = f' → {r["endDate"]}' if r.get('endDate') and r['endDate'] != r['startDate'] else ''
                print(f'  {r["startDate"]}{end} {r["title"][:50]} @ {r["venue"]} ({r["prefecture"]})')
            else:
                print(f'  /{prefix}/mevent/?mid={mid}: 404 or no ld+json')
    else:
        print('Usage: ltike_enricher.py discover | all | <prefix> <mid>')
        if len(sys.argv) == 3:
            r = fetch_ltike_event(sys.argv[1], sys.argv[2])
            print(json.dumps(r, ensure_ascii=False, indent=2))
