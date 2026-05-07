"""PIA (チケットぴあ) の event 詳細ページから公演情報を抽出

t.pia.jp/pia/event/event.do?eventBundleCd=<bundle_cd> を取得し、
"YYYY/M/D(曜) ... 会場名 (都道府県)" パターンで複数公演を抽出。

PIAはld+jsonを提供しないが、公演リストが半角/全角混在のplain textで
規則的に並んでいるため正規表現で安定抽出可能。

データ源: 2026-05-07調査時の構造
変更があれば 2026/M/D(曜) パターンを再確認すること。
"""
import json
import os
import re
import time
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

BASE = Path('/home/aiuser/kpop-ai-system')
CACHE_PATH = BASE / 'data' / 'pia_enrichment_cache.json'
CACHE_TTL_SEC = 7 * 24 * 3600

UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'

DATE_RE = re.compile(r'(20\d{2})/(\d{1,2})/(\d{1,2})\s*[\(（]([月火水木金土日])[\)）]')


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
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds() < CACHE_TTL_SEC
    except Exception:
        return False


def _strip_html(html: str) -> str:
    """HTML→plain text。script/styleは除去。"""
    s = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    s = re.sub(r'<style[^>]*>.*?</style>', '', s, flags=re.DOTALL)
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', s)


def _aggregate_consecutive(perfs: list[dict]) -> list[dict]:
    """連続する同会場の公演を date_end でまとめる (popup展示等が31日連続並ぶのを防ぐ)"""
    if not perfs:
        return []
    from datetime import datetime as _dt, timedelta as _td
    # sort
    sorted_perfs = sorted(perfs, key=lambda x: (x['venue'], x['date']))
    out = []
    cur = None
    for p in sorted_perfs:
        try:
            d = _dt.strptime(p['date'], '%Y-%m-%d')
        except Exception:
            out.append(p)
            cur = None
            continue
        if cur and cur['venue'] == p['venue']:
            try:
                last = _dt.strptime(cur.get('date_end') or cur['date'], '%Y-%m-%d')
                if (d - last).days <= 1:
                    cur['date_end'] = p['date']
                    continue
            except Exception:
                pass
        cur = dict(p)
        out.append(cur)
    # 元の date 昇順に戻す
    out.sort(key=lambda x: x['date'])
    return out


def _extract_performances(text: str) -> list[dict]:
    """plain text から (date, venue, prefecture) リストを抽出

    PIAの公演リストは以下のパターン:
        "YYYY/M/D(曜) [何か] 会場名 [全角paren付きサブ表記] ( 都道府県 ) 販売状態..."
    venue部分には会場サブ表記の全角paren（ＴＯＫＹＯ）が含まれうるので
    ２段抽出: 都道府県paren を発見 → そこから後ろ向きに date/venue を探す
    """
    perfs = []
    seen = set()
    PREF_RE = re.compile(r'[\(（]\s*([一-龠ぁ-んァ-ヶ]{1,8}(?:都|道|府|県))\s*[\)）]')
    # 曜日後に「・祝」「・休」等のサフィックス許容 (例: (日・祝))
    DATE_VENUE_RE = re.compile(
        r'(20\d{2})/(\d{1,2})/(\d{1,2})\s*[\(（]([月火水木金土日])(?:・[祝休])?[\)）]\s*(.{2,80}?)$'
    )
    for pm in PREF_RE.finditer(text):
        prefecture = unicodedata.normalize('NFKC', pm.group(1)).strip()
        # 直前80文字に date+venue
        before = text[max(0, pm.start() - 100):pm.start()]
        dm = DATE_VENUE_RE.search(before)
        if not dm:
            continue
        try:
            date_str = f'{int(dm.group(1)):04d}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}'
        except Exception:
            continue
        raw_venue = dm.group(5).strip()
        # remove trailing 会場サブparenthesis like ＴＯＫＹＯ
        raw_venue = re.sub(r'[\(（][^\)）]{1,20}[\)）]\s*$', '', raw_venue).strip()
        venue = unicodedata.normalize('NFKC', raw_venue).strip()
        # ノイズ除去: 「詳細はこちら」「販売」等の販売UI文言を含むのは破棄
        if any(noise in venue for noise in ['詳細はこちら', '販売', '受付', '一般発売', '先行', '/', '～', '~', '会場', '23:59']):
            continue
        venue = re.sub(r'&nbsp;', '', venue).strip()
        if not venue or len(venue) < 2 or len(venue) > 30:
            continue
        key = (date_str, venue)
        if key in seen:
            continue
        seen.add(key)
        perfs.append({
            'date': date_str,
            'venue': venue,
            'prefecture': prefecture,
        })
    return perfs


def fetch_pia_performances(event_bundle_cd: str, *, sleep_sec: float = 0.5, force: bool = False) -> dict | None:
    """PIA event detail を取得して公演リストを返す

    Args:
        event_bundle_cd: 'b2665156' 形式

    Returns:
        {
          'event_bundle_cd': str,
          'title': str,
          'description': str,
          'image': str,
          'performances': [{date, venue, prefecture}],
          'cached_at': str,
        }
        404/失敗時は None
    """
    cache = _load_cache()
    key = event_bundle_cd

    if not force and key in cache and _is_fresh(cache[key]):
        return cache[key] if not cache[key].get('not_found') else None

    url = f'http://t.pia.jp/pia/event/event.do?eventBundleCd={event_bundle_cd}'
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            cache[key] = {'event_bundle_cd': event_bundle_cd, 'cached_at': datetime.now().isoformat(), 'not_found': True}
            _save_cache(cache)
            time.sleep(sleep_sec)
        return None
    except Exception:
        return None
    finally:
        time.sleep(sleep_sec)

    # OG meta
    og_title = ''
    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
    if m:
        og_title = m.group(1).split('|')[0].strip()
    og_desc = ''
    m = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', html)
    if m:
        og_desc = m.group(1).strip()
    og_image = ''
    m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
    if m:
        og_image = m.group(1).strip()

    text = _strip_html(html)
    performances = _extract_performances(text)

    performances = _aggregate_consecutive(performances)

    result = {
        'event_bundle_cd': event_bundle_cd,
        'title': og_title,
        'description': og_desc,
        'image': og_image,
        'performances': performances,
        'cached_at': datetime.now().isoformat(),
    }
    cache[key] = result
    _save_cache(cache)
    return result


def discover_kpop_events(*, sleep_sec: float = 0.5) -> list[dict]:
    """PIAのK-POPタグページから event_bundle_cd を発見"""
    url = 'https://t.pia.jp/pia/tag/tag.do?tagCd=0000078'
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f'PIA discover error: {e}')
        return []
    # event detail URLs
    seen = set()
    bundles = []
    for m in re.finditer(r'eventBundleCd=([a-zA-Z0-9_]+)', html):
        cd = m.group(1)
        if cd in seen:
            continue
        seen.add(cd)
        bundles.append(cd)
    time.sleep(sleep_sec)
    return bundles


if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 2 and sys.argv[1] == 'discover':
        bundles = discover_kpop_events()
        print(f'discovered {len(bundles)} K-POP event bundles')
        for cd in bundles[:20]:
            print(' ', cd)
    elif len(sys.argv) >= 2:
        for arg in sys.argv[1:]:
            r = fetch_pia_performances(arg)
            if r is None:
                print(f'{arg}: not found')
                continue
            print(f'{arg}: {r["title"]}')
            for p in r['performances']:
                print(f'  {p["date"]} @ {p["venue"]} ({p["prefecture"]})')
    else:
        print('Usage: pia_enricher.py discover | <bundle_cd> [<bundle_cd> ...]')
