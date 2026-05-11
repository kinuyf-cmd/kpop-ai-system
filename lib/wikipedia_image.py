"""Wikipedia pageimage fetcher for artist hero photos.

Used by pipeline/profile_wiki_builder.py to source canonical group photos
when WP-derived featured images are unreliable.
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

CACHE_PATH = Path('/home/aiuser/kpop-ai-system/data/wikipedia_image_cache.json')

# 日本語 Wikipedia の正式記事名 (artist 名 → wiki page title)
WIKI_TITLE_JA = {
    'BTS': 'BTS (音楽グループ)',
    'BLACKPINK': 'BLACKPINK',
    'NewJeans': 'NewJeans',
    'aespa': 'AESPA',
    'IVE': 'IVE (グループ)',
    'LE SSERAFIM': 'LE SSERAFIM',
    'ITZY': 'ITZY',
    'TWICE': 'TWICE',
    'SEVENTEEN': 'SEVENTEEN (音楽グループ)',
    'Stray Kids': 'Stray Kids',
    'ENHYPEN': 'ENHYPEN',
    'TXT': 'TOMORROW X TOGETHER',
    'NMIXX': 'NMIXX',
    'BABYMONSTER': 'BABYMONSTER',
    'RIIZE': 'RIIZE',
    'ILLIT': 'ILLIT',
    'BOYNEXTDOOR': 'BOYNEXTDOOR',
    'KISS OF LIFE': 'KISS OF LIFE (グループ)',
    'IU': 'IU (歌手)',
    'KATSEYE': 'KATSEYE',
    'fromis_9': 'fromis_9',
}

WIKI_TITLE_EN = {
    'BTS': 'BTS',
    'BLACKPINK': 'Blackpink',
    'NewJeans': 'NewJeans',
    'aespa': 'Aespa',
    'IVE': 'Ive (group)',
    'LE SSERAFIM': 'Le Sserafim',
    'ITZY': 'Itzy',
    'TWICE': 'Twice',
    'SEVENTEEN': 'Seventeen (South Korean band)',
    'Stray Kids': 'Stray Kids',
    'ENHYPEN': 'Enhypen',
    'TXT': 'Tomorrow X Together',
    'NMIXX': 'NMIXX',
    'BABYMONSTER': 'BabyMonster',
    'RIIZE': 'RIIZE',
    'ILLIT': 'Illit (group)',
    'BOYNEXTDOOR': 'BoyNextDoor',
    'KISS OF LIFE': 'Kiss of Life (group)',
    'IU': 'IU (singer)',
    'KATSEYE': 'Katseye',
    'fromis_9': 'Fromis 9',
    # 2026-05-12 追加: グループ wiki 21→34 拡張時に Wikidata P154 lookup 用 title を登録
    'BIGBANG': 'BigBang (South Korean band)',
    'NCT': 'NCT (group)',
    'STAYC': 'StayC',
    'MOMOLAND': 'Momoland',
    'Hearts2Hearts': 'Hearts2Hearts',
    'BoA': 'BoA',
}


def _cache_load() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def _cache_save(c: dict):
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding='utf-8')


def _fetch_pageimage(lang: str, title: str, size: int = 1200) -> str:
    url = f'https://{lang}.wikipedia.org/w/api.php?' + urllib.parse.urlencode({
        'action': 'query',
        'prop': 'pageimages',
        'titles': title,
        'pithumbsize': size,
        'format': 'json',
        'redirects': 1,
    })
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'KpopJournal-IdolWiki/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        for pid, p in data.get('query', {}).get('pages', {}).items():
            if pid != '-1':
                thumb = p.get('thumbnail', {}).get('source')
                if thumb:
                    return thumb
    except Exception:
        pass
    return ''


def get_artist_image(artist: str, use_cache: bool = True, retries: int = 3) -> str:
    """Wikipedia pageimage を取得 (ja → en fallback、retry付き)"""
    cache = _cache_load() if use_cache else {}
    if use_cache and artist in cache and cache[artist].get('url'):
        return cache[artist]['url']

    title_ja = WIKI_TITLE_JA.get(artist, artist)
    title_en = WIKI_TITLE_EN.get(artist, artist)

    def _is_acceptable(u: str) -> bool:
        # logo, symbol, wordmark, signature 等の非実写は除外
        bad = ('logo', 'symbol', 'wordmark', 'signature', 'emblem', 'trademark')
        return bool(u) and not any(b in u.lower() for b in bad)

    img = ''
    for attempt in range(retries):
        candidate = _fetch_pageimage('ja', title_ja)
        if _is_acceptable(candidate):
            img = candidate
            break
        time.sleep(0.6 * (attempt + 1))
    if not img:
        for attempt in range(retries):
            candidate = _fetch_pageimage('en', title_en)
            if _is_acceptable(candidate):
                img = candidate
                break
            time.sleep(0.6 * (attempt + 1))

    if img and use_cache:
        cache[artist] = {'url': img}
        _cache_save(cache)
    return img


LOGO_CACHE_PATH = Path('/home/aiuser/kpop-ai-system/data/wikipedia_logo_cache.json')


def _logo_cache_load() -> dict:
    if LOGO_CACHE_PATH.exists():
        try:
            return json.loads(LOGO_CACHE_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}


def _logo_cache_save(c: dict):
    LOGO_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOGO_CACHE_PATH.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding='utf-8')


def _wikidata_logo(wiki_title_en: str) -> str:
    """Wikidata P154 (logo image) → Commons filename → Special:FilePath URL"""
    try:
        url = ('https://www.wikidata.org/w/api.php?' + urllib.parse.urlencode({
            'action': 'wbgetentities', 'sites': 'enwiki',
            'titles': wiki_title_en, 'props': 'claims', 'format': 'json',
        }))
        req = urllib.request.Request(url, headers={'User-Agent': 'KpopJournal-IdolWiki/1.0'})
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        for ent in data.get('entities', {}).values():
            for c in ent.get('claims', {}).get('P154', []):
                filename = c.get('mainsnak', {}).get('datavalue', {}).get('value', '')
                if filename:
                    return f'https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(filename)}'
    except Exception:
        pass
    return ''


# 検索ノイズが多い artist のみ手動上書き (Commons の自然検索で混入する別エンティティ対策)
LOGO_MANUAL_OVERRIDE: dict[str, str] = {
    # IU: 単独歌手・logo少ない / 'IU' は別大学IDと衝突しやすい
    'IU': '',
    # KISS OF LIFE: 商標衝突多い (Sade等)
    'KISS OF LIFE': '',
    # SEVENTEEN: 検索だと 'Seventeen Magazine' / Seventeen Seconds (Cure album) と衝突
    # Wikidata P154 未登録のため、Commons の検証済 PD ファイルを直接指定
    'SEVENTEEN': 'https://commons.wikimedia.org/wiki/Special:FilePath/Seventeen%20new%20logo.jpg',
    # BIGBANG: 'Wtilth logo' という無関係ファイルを誤マッチした実績あり (WIKI_TITLE未登録時)
    'BIGBANG': 'https://commons.wikimedia.org/wiki/Special:FilePath/Big%20Bang%20logo%20%282%29.png',
    # NCT: 検索だと DOJAEJUNG (NCT 127 サブユニット) ヒット
    'NCT': 'https://commons.wikimedia.org/wiki/Special:FilePath/NCT-logo.jpg',
    # fromis_9: 検索だと "To Heart" デビュー曲ロゴ。Wikidata P154 1st "Fromis 9 Logo.png" は 2018-2019 紫色 stadium-track 旧ロゴ。
    # 現行 (PLEDIS 移籍後 2022〜) は TEXT.svg (clean sans-serif "fromis_9")
    'fromis_9': 'https://commons.wikimedia.org/wiki/Special:FilePath/Fromis%209%20logo%20%28TEXT%29.svg',
    # MOMOLAND: Wikidata P154 無し / Commons 検索は "Boom Boom" 楽曲ロゴを誤マッチ。空にして非表示
    'MOMOLAND': '',
    # BoA: Wikidata P154 無し / Commons 検索は Bank of America 比較画像を誤マッチ。空にして非表示
    'BoA': '',
    # EXO: 検索だと "Exo Platform" (企業ソフトウェア) を誤マッチ。V-neck 公式ロゴ (Commons "Exo (musical group) logos" カテゴリ) を直接指定
    'EXO': 'https://commons.wikimedia.org/wiki/Special:FilePath/Exo-logo-v-neck%20design.png',
}


def _commons_logo_search(artist: str) -> str:
    """Wikimedia Commons の File:{Artist} logo* を検索して最適候補を返す"""
    if artist in LOGO_MANUAL_OVERRIDE:
        return LOGO_MANUAL_OVERRIDE[artist]
    try:
        q = f'{artist} logo'
        url = ('https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode({
            'action': 'query', 'list': 'search', 'srsearch': q,
            'srnamespace': 6, 'srlimit': 10, 'format': 'json',
        }))
        req = urllib.request.Request(url, headers={
            'User-Agent': 'KpopJournal-IdolWiki/1.0 (https://www.kpopjournal.tokyo)'
        })
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        hits = data.get('query', {}).get('search', [])

        def score(h):
            t = h['title'].lower()
            al = artist.lower()
            s = 0
            if 'logo' in t: s += 10
            if t.startswith(f'file:{al} logo') or t.startswith(f'file:logo of {al}'): s += 30
            if t.startswith(f'file:{al}'): s += 5
            if t.endswith('.svg'): s += 5
            elif t.endswith('.png'): s += 2
            # ノイズ語: 楽曲・別エンティティ・magazineなど
            for bad in (
                'album', 'fancy', 'cheer up', 'how you', 'song', 'single', 'mv', 'concept',
                'sade', 'rocko', 'vais', 'italo', 'wikidata', 'aleas', '1989', 'international',
                'magazine', 'seconds', 'mavi', 'cure',
            ):
                if bad in t: s -= 8
            return s

        hits.sort(key=score, reverse=True)
        for h in hits:
            if score(h) >= 10:
                filename = h['title'].replace('File:', '', 1)
                return f'https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(filename)}'
    except Exception:
        pass
    return ''


def get_artist_logo(artist: str, use_cache: bool = True) -> str:
    """Wikidata P154 → namu.wiki og:image fallback で artist のロゴ画像を取得"""
    cache = _logo_cache_load() if use_cache else {}
    if use_cache and artist in cache and cache[artist].get('url'):
        return cache[artist]['url']

    wiki_en = WIKI_TITLE_EN.get(artist, artist)
    url = _wikidata_logo(wiki_en)
    source = 'wikidata'
    if not url:
        url = _commons_logo_search(artist)
        source = 'commons'
    if url and use_cache:
        cache[artist] = {'url': url, 'source': source}
        _logo_cache_save(cache)
    return url


if __name__ == '__main__':
    import sys
    targets = sys.argv[1:] or list(WIKI_TITLE_JA.keys())
    for a in targets:
        u = get_artist_image(a, use_cache=True)
        lo = get_artist_logo(a, use_cache=True)
        print(f'{a}: hero={u or "—"}  logo={lo or "—"}')
        time.sleep(0.7)  # rate limit対策
