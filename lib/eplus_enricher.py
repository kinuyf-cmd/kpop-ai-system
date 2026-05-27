"""eplus (イープラス) の K-POP 公演情報を robots 準拠経路で抽出

【2026-05-25 改修】eplus robots.txt は「Disallow: /sf/search」を明示するため、
旧実装(/sf/search クロール)は規約違反だった。robots が公開する
sitemap_daily_kkn.xml(Disallow対象外)→ /sf/detail/(Disallow対象外)へ切替。
detail ページの JSON-LD(<script type="application/ld+json"> @type=Event)から
公演名・startDate・location を取得し、K-POPアーティスト名ホワイトリストで
非K-POP(怪談・J-POP・演劇等)を除外する。

normalize_record が読む内部スキーマ風 dict を返す(後方互換):
  - koenbi_term: 'YYYYMMDD' / kaien_time: 'HHMM' / kogyo_name: タイトル
  - kanren_venue.{venue_name, todofuken_name} / kogyo_code / koen_detail_url_pc
HTML構造変更時は detail の application/ld+json を確認。
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


# robots.txt 準拠の収集経路(2026-05-25 改修)。
# eplus robots.txt は「Disallow: /sf/search」を明示するため、旧実装の
# /sf/search クロールは規約違反だった。robots が公開する sitemap
# (sitemap_daily_kkn.xml = Disallow対象外)→ /sf/detail/(Disallow対象外)
# の経路に切替。detail ページの JSON-LD(@type=Event)から日付/会場を取得し、
# K-POP アーティスト名(ホワイトリスト)で非K-POP(怪談・演劇等)を除外する。
SITEMAP_URL = 'https://eplus.jp/s/eplus.jp/sitemap_daily_kkn.xml'

# K-POP 判定ホワイトリスト(ticket_signals_to_event_input と同基準)。
EPLUS_KPOP_ARTISTS = [
    'BTS', 'BLACKPINK', 'TWICE', 'SEVENTEEN', 'Stray Kids', 'ENHYPEN', 'TXT',
    'TOMORROW X TOGETHER', 'ITZY', 'aespa', 'NewJeans', 'IVE', 'LE SSERAFIM',
    'NMIXX', 'NCT', 'EXO', 'Red Velvet', 'SHINee', 'SUPER JUNIOR', '&TEAM',
    'RIIZE', 'ZEROBASEONE', 'ZB1', 'BABYMONSTER', 'ILLIT', 'KISS OF LIFE',
    '(G)I-DLE', 'G-IDLE', 'MAMAMOO', 'ATEEZ', 'THE BOYZ', 'TREASURE', 'P1Harmony',
    'MONSTA X', 'GOT7', 'DAY6', 'fromis', 'Kep1er', 'STAYC', 'NEXZ', 'MEOVV',
    'Hearts2Hearts', 'YENA', 'MYNAME', 'SMTR', 'WI HA JUN', 'BOYNEXTDOOR',
    'xikers', 'TWS', 'CORTIS', 'Kwon Jin Ah', 'KANG JI YOUNG', 'LEE MINHYUK',
    'HAN SEUNG WOO', 'LEE JI HOON', 'LEE YOUNGJI', 'JANG HANEUM',
    # 2026-05-27 追加: l-tike 収集で取りこぼした「曖昧でない」K-POP実演者。
    # 英単語衝突なし(語境界一致で ikonic/falconry 等に誤爆しない)もののみ採用。
    # WINNER 等の一般英単語と同綴の組は下の _EPLUS_AMBIGUOUS 行きで別管理。
    'iKON', 'JAEJOONG', 'ジェジュン', 'WINNER',  # WINNER は _EPLUS_AMBIGUOUS で文脈語必須
    'ウィ・ハジュン',  # WI HA JUN の日本語表記(英語表記は既出だが和名タイトル対策)
    # 注: 'K-POP'/'KPOP' の汎用語はホワイトリストに入れない。eplus detail ページの
    # ジャンルラベル等で米倉千尋/DA PUMP 等の非K-POPが誤マッチするため、
    # 具体的なアーティスト名一致のみで判定する(誤検知を排除)。
]


# 一般英単語と同綴で誤マッチしやすい曖昧アーティスト名(小文字)。
# これらは単語境界一致でも一般名詞に当たる(例: "The Hidden Treasure" の
# treasure が TREASURE に完全一致)。文脈語(K-POP関連)が共起する時のみ採用。
# 実害: BABY SHARK LIVE!(Hidden Treasure) を K-POP の TREASURE と誤判定し
# IVE/TREASURE 等のイベント記事を捏造した事故(2026-05-26)。
# 2026-05-27: 'winner' を追加(WINNER は YG の実在K-POP組だが "award winner" 等の
# 一般英単語と衝突。文脈語が共起する時のみ K-POP と判定)。
_EPLUS_AMBIGUOUS = {'treasure', 'ive', 'ace', 'red velvet', 'winner'}
# 曖昧名を救う文脈語(これが本文/タイトルに有れば K-POP と判断)
_EPLUS_KPOP_CONTEXT = [
    'k-pop', 'kpop', 'ケイポップ', '韓国', 'コリア', 'korea', 'ソウル',
    'カムバック', 'comeback', 'アイドル', 'idol', 'ファンミーティング', 'fanmeeting',
    'ワールドツアー', 'world tour', '트레저', '아이브',
]


def _is_kpop(text: str) -> bool:
    """K-POP アーティスト名一致判定。ASCII の短い名(IVE/EXO 等)は
    単語境界一致で判定し、'LIVE' 内の 'IVE' のような部分一致誤検知を防ぐ。
    記号や日本語を含む名(&TEAM/(G)I-DLE 等)は単純部分一致。
    一般英単語と同綴の曖昧名(TREASURE 等)は文脈語が共起する時のみ採用。"""
    if not text:
        return False
    tl = text.lower()
    has_ctx = any(c in tl for c in _EPLUS_KPOP_CONTEXT)
    for a in EPLUS_KPOP_ARTISTS:
        al = a.lower()
        if a.isascii() and a.replace(' ', '').replace('-', '').isalnum():
            # 英数字のみの名は単語境界一致(前後が英数字でない位置のみヒット)
            if re.search(r'(?<![a-z0-9])' + re.escape(al) + r'(?![a-z0-9])', tl):
                # 曖昧名は文脈語が無ければ偽陽性として却下
                if al in _EPLUS_AMBIGUOUS and not has_ctx:
                    continue
                return True
        else:
            # &TEAM / (G)I-DLE / Kwon Jin Ah 等は部分一致
            if al in tl:
                return True
    return False


def _fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')


def _extract_jsonld_events(html: str) -> list[dict]:
    """detail ページの <script application/ld+json> から @type=Event を抽出。"""
    blocks = re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S)
    events = []
    for b in blocks:
        try:
            d = json.loads(b.strip())
        except Exception:
            continue
        items = d if isinstance(d, list) else [d]
        for it in items:
            if isinstance(it, dict) and (it.get('@type') in ('Event', 'MusicEvent') or it.get('startDate')):
                events.append(it)
    return events


def fetch_eplus_kpop(keyword: str = 'K-POP', max_pages: int = 5, *,
                     sleep_sec: float = 0.4, force: bool = False,
                     max_details: int = 60) -> list[dict]:
    """eplus の K-POP 公演を robots 準拠経路(sitemap→detail JSON-LD)で取得。

    旧シグネチャ互換のため keyword/max_pages 引数は残すが /sf/search は使わない。
    max_details でバッチ上限(タイムアウト回避。旧実装は266ページ展開で停止していた)。
    Returns: normalize_record が食える内部スキーマ風 dict の list。
    """
    cache = _load_cache()
    cache_key = 'sitemap:kkn'
    if not force and cache_key in cache and _is_fresh(cache[cache_key]):
        return cache[cache_key].get('records', [])

    try:
        sm = _fetch(SITEMAP_URL)
    except Exception as e:
        print(f'  eplus sitemap error: {e}')
        return []
    detail_urls = re.findall(r'<loc>(https://eplus\.jp/sf/detail/[^<]+)</loc>', sm)

    all_records = []
    seen_keys = set()
    checked = 0
    for durl in detail_urls:
        if checked >= max_details:
            break
        checked += 1
        try:
            html = _fetch(durl, timeout=15)
        except Exception:
            time.sleep(sleep_sec)
            continue
        # K-POP 判定は「その公演自身のタイトル」で行う。ページ全体や
        # og:title で判定すると、detail ページの関連公演/おすすめ欄に
        # K-POPアーティスト名があるだけで非K-POP公演(米倉千尋/DA PUMP等)が
        # 誤って通るため。og:title が非K-POPなら早期skip(ページ主題で粗ふるい)。
        og = re.search(r'<meta property="og:title" content="([^"]*)"', html)
        page_title = og.group(1) if og else ''
        events = _extract_jsonld_events(html)
        # og:title(=ページ主題の公演名)が K-POP でなければ skip
        if page_title and not _is_kpop(page_title):
            time.sleep(sleep_sec)
            continue
        code = durl.rstrip('/').rsplit('/', 1)[-1]
        for e in events:
            # 各 Event 名でも個別に K-POP 判定(関連公演の混入を二重に防ぐ)
            if not _is_kpop(e.get('name', '') or page_title):
                continue
            start = (e.get('startDate') or '')          # 2026-06-05T18:30 等
            date_part = start[:10].replace('-', '')      # YYYYMMDD
            loc = e.get('location') or {}
            venue = (loc.get('name') if isinstance(loc, dict) else '') or ''
            pref = ''
            if isinstance(loc, dict):
                addr = loc.get('address')
                if isinstance(addr, dict):
                    pref = addr.get('addressRegion', '') or ''
            tm = start[11:16].replace(':', '') if len(start) >= 16 else ''
            key = f'{code}|{date_part}|{venue}'
            if not date_part or key in seen_keys:
                continue
            seen_keys.add(key)
            # normalize_record が読む内部スキーマ風に詰める
            all_records.append({
                'kogyo_code': code,
                'koenbi_term': date_part,
                'kaien_time': tm,
                'kogyo_name': e.get('name', ''),
                'kanren_venue': {'venue_name': venue, 'todofuken_name': pref},
                'koen_detail_url_pc': f'/sf/detail/{code}',
            })
        time.sleep(sleep_sec)

    cache[cache_key] = {'cached_at': datetime.now().isoformat(), 'records': all_records}
    _save_cache(cache)
    print(f'  eplus(sitemap): checked {checked} details → {len(all_records)} K-POP records')
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
