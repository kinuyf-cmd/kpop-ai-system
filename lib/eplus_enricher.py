"""eplus (イープラス) の検索結果ページから K-POP 公演情報を抽出

https://eplus.jp/sf/search?keyword=K-POP のページに inline で
<script type="application/json"> として全公演データが埋まっている。
field 名は eplus 内部スキーマ:
  - koenbi_term: '20260506' (公演日 YYYYMMDD)
  - kaien_time: '1700' (開演 HHMM)
  - kanren_venue.venue_name: 会場名
  - kanren_venue.todofuken_name: 都道府県
  - kogyo_code: 公演コード
  - kogyo_name: タイトル
  - kanren_word_list: アーティスト関連語
  - shutsuensha_list: 出演者

API で paginate されるので keyword + page 指定で全件取得可能。
データ源: 2026-05-07調査。HTML構造変更時は <script type="application/json"> grep で確認。
"""
import json
import os
import re
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from pathlib import Path

BASE = Path('/home/aiuser/kpop-ai-system')
CACHE_PATH = BASE / 'data' / 'eplus_enrichment_cache.json'
CACHE_TTL_SEC = 6 * 3600  # 6時間 (販売状況が変動しやすいので短め)

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


def _is_fresh(entry: dict, ttl: int = CACHE_TTL_SEC) -> bool:
    ts = entry.get('cached_at')
    if not ts:
        return False
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds() < ttl
    except Exception:
        return False


def _parse_yyyymmdd(s: str) -> str | None:
    if not s or len(s) != 8 or not s.isdigit():
        return None
    return f'{s[:4]}-{s[4:6]}-{s[6:8]}'


def _extract_records(html: str) -> list[dict]:
    """inline <script type="application/json"> から record_list を抽出"""
    for m in re.finditer(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL):
        body = m.group(1).strip()
        if not body.startswith('{'):
            continue
        try:
            data = json.loads(body)
        except Exception:
            continue
        records = (data.get('data') or {}).get('record_list')
        if records is not None:
            return records
    return []


def fetch_eplus_kpop(keyword: str = 'K-POP', max_pages: int = 5, *, sleep_sec: float = 0.6, force: bool = False) -> list[dict]:
    """eplusのK-POP検索結果から公演リストを取得

    Returns: 各 record の dict list (eplus内部スキーマそのまま)
    """
    cache = _load_cache()
    cache_key = f'search:{keyword}'
    if not force and cache_key in cache and _is_fresh(cache[cache_key]):
        return cache[cache_key].get('records', [])

    all_records = []
    seen_codes = set()
    for page in range(1, max_pages + 1):
        params = {'keyword': keyword}
        if page > 1:
            params['page'] = str(page)
        url = f'https://eplus.jp/sf/search?{urllib.parse.urlencode(params)}'
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                html = r.read().decode('utf-8', errors='replace')
        except Exception as e:
            print(f'  eplus page {page} error: {e}')
            break
        records = _extract_records(html)
        new_count = 0
        for rec in records:
            code = rec.get('kogyo_code')
            if code and code not in seen_codes:
                seen_codes.add(code)
                all_records.append(rec)
                new_count += 1
        if new_count == 0:
            break
        time.sleep(sleep_sec)

    cache[cache_key] = {
        'cached_at': datetime.now().isoformat(),
        'records': all_records,
    }
    _save_cache(cache)
    return all_records


def normalize_record(rec: dict) -> dict | None:
    """eplus内部スキーマ → 共通スキーマ {date, venue, prefecture, title, artist, url, open_time, start_time}"""
    date = _parse_yyyymmdd(rec.get('koenbi_term') or '')
    if not date:
        return None
    venue_obj = rec.get('kanren_venue') or {}
    venue = (venue_obj.get('venue_name') or '').strip()
    prefecture = (venue_obj.get('todofuken_name') or '').strip()
    if not venue:
        return None
    import html as _htmllib
    sub = rec.get('kanren_kogyo_sub') or {}
    title = (sub.get('kogyo_name_1') or rec.get('kogyo_name') or '').replace('\xa0', ' ').strip()
    title = _htmllib.unescape(title)  # &amp; → &
    code = rec.get('kogyo_code') or ''
    detail_path = rec.get('koen_detail_url_pc') or ''

    # 開演時刻 HHMM → HH:MM
    def _hhmm(s):
        if isinstance(s, str) and len(s) == 4 and s.isdigit():
            return f'{s[:2]}:{s[2:]}'
        return ''

    # artist: title の "SUPER JUNIOR-YESUNG" 形式から先頭を採用、なければ titleそのもの
    artist = title.split('-')[0].split(' ')[0].strip() if title else ''

    url = f'https://eplus.jp{detail_path}' if detail_path else (f'https://eplus.jp/sf/detail/{code}' if code else '')
    return {
        'date': date,
        'venue': venue,
        'prefecture': prefecture,
        'title': title,
        'artist': artist,
        'kogyo_code': code,
        'url': url,
        'open_time': _hhmm(rec.get('kaijo_time') or ''),
        'start_time': _hhmm(rec.get('kaien_time') or ''),
    }


if __name__ == '__main__':
    import sys
    kw = sys.argv[1] if len(sys.argv) > 1 else 'K-POP'
    recs = fetch_eplus_kpop(kw)
    print(f'eplus {kw}: {len(recs)} records')
    norm = []
    for r in recs:
        n = normalize_record(r)
        if n:
            norm.append(n)
    print(f'normalized: {len(norm)}')
    for n in norm[:15]:
        print(f'  {n["date"]} {n.get("artist","-"):15} {n["title"][:50]} @ {n["venue"]} ({n["prefecture"]})')
