"""
2026-05-15: _resolve_artist_sources の fallback 順序検証。

Wikimedia は textual match で誤マッチが起きやすい (See Ya → F-16 / Aiki →
合気道 等) ため、人手検証済の artist_cache を先に試行する。

順序:
  1. resolve_youtube  (official_accounts 登録済のみ、attribution check)
  2. resolve_fallback_photo  (人手検証済 artist_cache)
  3. resolve_wikimedia  (allowlist guard 経由、ただし最後)
  4. メンバー→グループ fallback
"""
import inspect
import re
import sys

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_resolve_artist_sources_calls_cache_before_wikimedia():
    """_resolve_artist_sources のソース内で resolve_fallback_photo が
    resolve_wikimedia より上に書かれていること"""
    from lib import thumbnail_source_resolver as tsr
    src = inspect.getsource(tsr.resolve)
    # _resolve_artist_sources 関数全体を抜き出し
    m = re.search(r'def _resolve_artist_sources\(.*?\n(?=    \w|\Z)', src, re.S)
    assert m, '_resolve_artist_sources function not found in resolve()'
    body = m.group(0)
    # cache の位置 (fallback_photo) と Wikimedia の位置を比較
    cache_idx = body.find('resolve_fallback_photo(artist)')
    wiki_idx = body.find('resolve_wikimedia(artist)')
    assert cache_idx > -1, 'resolve_fallback_photo(artist) call not found'
    assert wiki_idx > -1, 'resolve_wikimedia(artist) call not found'
    assert cache_idx < wiki_idx, \
        f'order broken: artist_cache (idx={cache_idx}) は Wikimedia (idx={wiki_idx}) より先に呼ぶべき'


def test_group_fallback_also_cache_first():
    """メンバー→グループ fallback でも cache 優先順"""
    from lib import thumbnail_source_resolver as tsr
    src = inspect.getsource(tsr.resolve)
    # メンバー→グループ section (関数末尾近く)
    m = re.search(r"メンバー '\{artist\}' → グループ.*?return None", src, re.S)
    assert m, 'group fallback section not found'
    sect = m.group(0)
    cache_idx = sect.find('resolve_fallback_photo(group_name)')
    wiki_idx = sect.find('resolve_wikimedia(group_name)')
    assert cache_idx > -1 and wiki_idx > -1
    assert cache_idx < wiki_idx, \
        f'group fallback: cache (idx={cache_idx}) を Wikimedia (idx={wiki_idx}) より先に'


def test_youtube_still_first_priority():
    """YouTube は依然として artist_cache より先 (official_accounts 検証済のため最も信頼)"""
    src = open('/home/aiuser/kpop-ai-system/lib/thumbnail_source_resolver.py',
               encoding='utf-8').read()
    # _resolve_artist_sources 内で resolve_youtube(artist 呼出が
    # resolve_fallback_photo(artist) より先に出ること
    func_start = src.find('def _resolve_artist_sources(')
    assert func_start > -1
    body = src[func_start:func_start + 3000]  # 関数本体相当
    yt_idx = body.find('resolve_youtube(artist,')
    cache_idx = body.find('resolve_fallback_photo(artist)')
    assert yt_idx > -1, f'resolve_youtube(artist, ... not found in: {body[:500]!r}'
    assert cache_idx > -1
    assert yt_idx < cache_idx, 'YouTube は artist_cache より先であるべき'
