#!/usr/bin/env python3
"""チケットガイドcollector - K-POP公演情報

Sources:
  - pia (t2.pia.jp/music): K-POPカテゴリのHTML
  - tickebo (ticket.tickebo.jp): イベントID範囲スキャン
    Vue SPAだがOGメタは静的レンダリングされるため、
    各 event.html?info=ID のog:title/og:imageを抽出してK-POP関連を判定
"""
import json, os, re, time, urllib.request, urllib.error
from datetime import datetime

BASE = '/home/aiuser/kpop-ai-system'
OUT = f'{BASE}/data/trend_signals.jsonl'
STATE_PATH = f'{BASE}/data/tickebo_state.json'

PIA_URL = 'http://t2.pia.jp/music/'

KEYWORDS = [
    'BTS', 'BLACKPINK', 'NewJeans', 'aespa', 'SEVENTEEN', 'TWICE',
    'IVE', 'LE SSERAFIM', 'ILLIT', 'Stray Kids', 'TXT', 'ENHYPEN',
    'ATEEZ', 'ITZY', 'NCT', 'NMIXX', 'RIIZE', 'TREASURE', 'BABYMONSTER',
    'EXO', 'MONSTA X', 'GOT7', 'ASTRO', 'DAY6', '(G)I-DLE', 'SHINee',
    'Red Velvet', 'BIGBANG', 'K-POP',
]

UA = 'Mozilla/5.0 KPOPJournal/1.0'


def _fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', errors='replace')


def _match_keywords(text):
    """K-POPキーワードマッチ。短いASCII名は単語境界判定で誤マッチ回避

    例: "IVE" が "LIVE in the DARK" にヒットしないように
    """
    text_lower = text.lower()
    matched = []
    for k in KEYWORDS:
        kl = k.lower()
        # 短く曖昧なASCIIアーティスト名は\b単語境界で
        if k.isascii() and len(k) <= 5:
            if re.search(r'(?:^|[^a-z0-9])' + re.escape(kl) + r'(?:[^a-z0-9]|$)', text_lower):
                matched.append(k)
        else:
            if kl in text_lower:
                matched.append(k)
    return matched


def collect_pia():
    """PIAのK-POPタグページから event_bundle_cd を発見し、各詳細ページを enrich

    旧版は t2.pia.jp/music の category linkを集めるだけで日付/会場が取れなかった。
    2026-05-07 改修で lib.pia_enricher 経由で詳細ページから date/venue/prefecture を取得。
    """
    try:
        from lib.pia_enricher import discover_kpop_events, fetch_pia_performances
    except Exception as e:
        print(f'pia_enricher import error: {e}')
        return []
    try:
        bundles = discover_kpop_events()
    except Exception as e:
        print(f'pia discover error: {e}')
        return []
    print(f'  pia: discovered {len(bundles)} bundles')
    signals = []
    for bundle_cd in bundles:
        try:
            r = fetch_pia_performances(bundle_cd)
        except Exception as e:
            print(f'  pia enrich {bundle_cd}: {e}')
            continue
        if r is None:
            continue
        title = r.get('title') or bundle_cd
        # discover_kpop_events は K-POPタグ (0000078) で絞り込み済 → 追加 keyword filter はかけない
        matched = _match_keywords(f"{title} {r.get('description', '')}")
        # ロングテール (PARK YUCHUN/CNBLUE/Kangin等) はキーワード未登録のまま通す。
        # artist は keyword ヒット時のみ採用 (誤推定より空欄のほうが安全)
        signals.append({
            'timestamp': datetime.now().isoformat(),
            'source': 'ticket_guide',
            'source_id': 'pia',
            'keyword': matched[0] if matched else 'K-POP',
            'title': title[:200],
            'url': f'http://t.pia.jp/pia/event/event.do?eventBundleCd={bundle_cd}',
            'engagement_score': 2.0,
            'language': 'ja',
            'raw_data': {
                'all_keywords': matched,  # 空配列 = artist不明
                'category': 'event',
                'event_bundle_cd': bundle_cd,
                'image': r.get('image', ''),
                'performances': r.get('performances', []),  # [{date, venue, prefecture, date_end?}]
            },
        })
    return signals


def _load_state():
    if os.path.exists(STATE_PATH):
        try:
            return json.load(open(STATE_PATH, encoding='utf-8'))
        except Exception:
            pass
    return {'last_max_id': 15500, 'seen_ids': []}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    state['seen_ids'] = state.get('seen_ids', [])[-500:]
    json.dump(state, open(STATE_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


_OG_TITLE_RE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', re.I)
_OG_IMAGE_RE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', re.I)
_OG_DESC_RE = re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)', re.I)
_TICKEBO_404_MARKER = 'ERR-02-03_404'


def _fetch_tickebo_event(event_id):
    """1イベントのOGメタを取得。存在しない/404はNone。"""
    url = f'https://ticket.tickebo.jp/show/event.html?info={event_id}'
    try:
        html = _fetch(url, timeout=15)
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return None
        raise
    if _TICKEBO_404_MARKER in html:
        return None
    title_m = _OG_TITLE_RE.search(html)
    if not title_m:
        return None
    return {
        'event_id': event_id,
        'url': url,
        'title': title_m.group(1).strip(),
        'image': (_OG_IMAGE_RE.search(html) or [None, None])[1] if _OG_IMAGE_RE.search(html) else '',
        'description': (_OG_DESC_RE.search(html) or [None, ''])[1] if _OG_DESC_RE.search(html) else '',
    }


def collect_tickebo(scan_window=200, sleep_sec=0.4):
    """ID範囲スキャン: last_max_id+1 から scan_window 件先までを舐める

    K-POP関連のみシグナル化。発見した最大IDを state に保存。
    1リクエスト約 sleep_sec 秒、200件で約80秒程度。
    """
    state = _load_state()
    seen = set(state.get('seen_ids', []))
    start_id = state.get('last_max_id', 15500) + 1
    end_id = start_id + scan_window

    signals = []
    new_max = state.get('last_max_id', 15500)
    found_count = 0
    for event_id in range(start_id, end_id):
        if event_id in seen:
            continue
        try:
            ev = _fetch_tickebo_event(event_id)
        except Exception as e:
            print(f'  tickebo id={event_id} error: {e}')
            time.sleep(sleep_sec)
            continue
        seen.add(event_id)
        if ev is None:
            time.sleep(sleep_sec)
            continue
        found_count += 1
        new_max = max(new_max, event_id)
        # K-POPフィルタ
        haystack = f"{ev['title']} {ev.get('description', '')}"
        matched = _match_keywords(haystack)
        if not matched:
            time.sleep(sleep_sec)
            continue
        # 公演詳細を内部APIから取得 (date/venue/openTime/startTime)
        try:
            from lib.ticket_enricher import fetch_tickebo_performances
            enriched = fetch_tickebo_performances(event_id, sleep_sec=0)
        except Exception as e:
            print(f'  tickebo enrich {event_id}: {e}')
            enriched = None
        performances = enriched.get('performances', []) if enriched else []
        signals.append({
            'timestamp': datetime.now().isoformat(),
            'source': 'ticket_guide',
            'source_id': 'tickebo',
            'keyword': matched[0],
            'title': ev['title'][:200],
            'url': ev['url'],
            'engagement_score': 2.5,
            'language': 'ja',
            'raw_data': {
                'all_keywords': matched,
                'category': 'event',
                'event_id': event_id,
                'image': ev.get('image', ''),
                'performances': performances,  # [{date, venue, open_time, start_time, event_cd}]
            },
        })
        time.sleep(sleep_sec)

    state['last_max_id'] = new_max
    state['seen_ids'] = sorted(seen)
    _save_state(state)
    print(f'  tickebo: scan {start_id}-{end_id-1} → existing events {found_count}, K-POP signals {len(signals)} (max_id={new_max})')
    return signals


def collect_eplus():
    """eplus 検索結果から K-POP 公演を取得 (inline JSONから直接抽出)"""
    try:
        from lib.eplus_enricher import fetch_eplus_kpop, normalize_record
    except Exception as e:
        print(f'eplus_enricher import error: {e}')
        return []
    # eplus の record_list は 1record = 1公演 (同kogyo_codeで複数日が並ぶ)。
    # 同一公演 (kogyo_code) の複数公演をまとめて1 signalにし performances リストにする
    signals = []
    grouped: dict[str, dict] = {}
    # eplus /sf/search は1キーワード20件 (ページネーションが効かない) なので
    # 多重キーワードで K-POP の長尾アーティストまでカバー
    EPLUS_KEYWORDS = (
        'K-POP', '韓流', 'BTS', 'BLACKPINK', 'aespa', 'NewJeans', 'SEVENTEEN',
        'TWICE', 'IVE', 'LE SSERAFIM', 'ITZY', 'NCT', 'NMIXX', 'RIIZE',
        'TREASURE', 'BABYMONSTER', 'SHINee', 'ENHYPEN', 'Stray Kids', 'TXT',
        '&TEAM', 'BOYNEXTDOOR', 'CRAVITY', 'P1Harmony', 'TWS', 'KCON',
    )
    for keyword in EPLUS_KEYWORDS:
        try:
            recs = fetch_eplus_kpop(keyword=keyword)
        except Exception as e:
            print(f'  eplus {keyword}: {e}')
            continue
        for rec in recs:
            n = normalize_record(rec)
            if not n:
                continue
            code = n['kogyo_code']
            perf = {
                'date': n['date'],
                'venue': n['venue'],
                'prefecture': n['prefecture'],
                'open_time': n['open_time'],
                'start_time': n['start_time'],
            }
            if code not in grouped:
                grouped[code] = {
                    'title': n['title'],
                    'artist': n['artist'],
                    'url': n['url'],
                    'performances': [],
                    'seen_perf_keys': set(),
                }
            g = grouped[code]
            pkey = (perf['date'], perf['venue'])
            if pkey in g['seen_perf_keys']:
                continue
            g['seen_perf_keys'].add(pkey)
            g['performances'].append(perf)
    for code, g in grouped.items():
        signals.append({
            'timestamp': datetime.now().isoformat(),
            'source': 'ticket_guide',
            'source_id': 'eplus',
            'keyword': g['artist'] or 'K-POP',
            'title': g['title'][:200],
            'url': g['url'],
            'engagement_score': 2.0,
            'language': 'ja',
            'raw_data': {
                'all_keywords': [g['artist']] if g['artist'] else [],
                'category': 'event',
                'kogyo_code': code,
                'performances': g['performances'],
            },
        })
    return signals


def collect():
    all_signals = []
    print(f'[ticket_collector] pia {PIA_URL}')
    pia_sigs = collect_pia()
    print(f'  pia: {len(pia_sigs)} signals')
    all_signals.extend(pia_sigs)

    print('[ticket_collector] tickebo (ID scan)')
    tickebo_sigs = collect_tickebo()
    all_signals.extend(tickebo_sigs)

    print('[ticket_collector] eplus (search)')
    eplus_sigs = collect_eplus()
    print(f'  eplus: {len(eplus_sigs)} signals')
    all_signals.extend(eplus_sigs)

    with open(OUT, 'a', encoding='utf-8') as f:
        for s in all_signals:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')

    print(f'Ticket guide: {len(all_signals)} signals')
    return len(all_signals)


if __name__ == '__main__':
    collect()
