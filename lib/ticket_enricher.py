"""tickebo (ticket board) の内部APIから公演詳細を取得

Vue SPA が叩く /web/api/evt/sales-list?acceptanceNo=<event_id> を直接呼び、
各公演の日付・会場・開場開演時刻を取得する。

og:title だけでは日付/会場が抽出できなかった ticket_guide signals を
本物のイベントに昇格させるための enricher。

API discovered 2026-05-07 from /show/1/script/EVT-01-01_performancesList.js
変更時は EVT-01-01_performancesList.js を grep して仕様変更を確認。
"""
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

BASE = Path('/home/aiuser/kpop-ai-system')
CACHE_PATH = BASE / 'data' / 'tickebo_enrichment_cache.json'
CACHE_TTL_SEC = 7 * 24 * 3600  # 1週間

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'


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


def _is_fresh(entry: dict) -> bool:
    ts = entry.get('cached_at')
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(ts)
        return (datetime.now() - dt).total_seconds() < CACHE_TTL_SEC
    except Exception:
        return False


def fetch_tickebo_performances(event_id: int, *, sleep_sec: float = 0.4, force: bool = False) -> dict | None:
    """tickebo API から公演リストを取得。キャッシュ利用。

    Returns:
        {
          'event_id': int,
          'title': str,
          'performers': list[str],
          'performances': [
            {'date': 'YYYY-MM-DD', 'venue': str, 'open_time': 'HH:MM', 'start_time': 'HH:MM', 'event_cd': str}
          ],
          'cached_at': str (ISO),
        }
        取得失敗時は None
    """
    cache = _load_cache()
    key = str(event_id)

    if not force and key in cache and _is_fresh(cache[key]):
        return cache[key]

    url = f'https://ticket.tickebo.jp/web/api/evt/sales-list?acceptanceNo={event_id}'
    req = urllib.request.Request(url, headers={
        'User-Agent': UA,
        'Accept': 'application/json',
        'Referer': f'https://ticket.tickebo.jp/show/event.html?info={event_id}',
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            cache[key] = {'event_id': event_id, 'cached_at': datetime.now().isoformat(), 'not_found': True}
            _save_cache(cache)
            time.sleep(sleep_sec)
            return None
        return None
    except Exception:
        return None
    finally:
        time.sleep(sleep_sec)

    eg = data.get('eventGroup', {}) or {}
    events = data.get('events', []) or []

    performances = []
    for ev in events:
        date = ev.get('eventOn')
        if not date:
            continue
        performances.append({
            'date': date,
            'venue': ev.get('venueNm') or '',
            'open_time': ev.get('openVenueTm') or '',
            'start_time': ev.get('openEventTm') or '',
            'event_cd': ev.get('eventCd') or '',
        })

    result = {
        'event_id': event_id,
        'title': eg.get('eventGroupTitleWeb') or '',
        'performers': eg.get('performerNmWebs') or [],
        'first_day': eg.get('firstDayOfEvent'),
        'last_day': eg.get('lastDayOfEvent'),
        'performances': performances,
        'cached_at': datetime.now().isoformat(),
    }
    cache[key] = result
    _save_cache(cache)
    return result


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('Usage: ticket_enricher.py <event_id> [<event_id> ...] [--force]')
        sys.exit(1)
    force = '--force' in sys.argv
    for arg in sys.argv[1:]:
        if arg.startswith('--'):
            continue
        eid = int(arg)
        r = fetch_tickebo_performances(eid, force=force)
        if r is None:
            print(f'{eid}: not found')
        else:
            print(f'{eid}: {r["title"]} ({r.get("first_day")} - {r.get("last_day")})')
            for p in r['performances']:
                print(f'  {p["date"]} {p["open_time"]}/{p["start_time"]} @ {p["venue"]}')
