"""artist_master.json の整合性を保証する回帰テスト。

artist_master.json は2つの用途を持ち、壊すと別々の事故になる:

  1. thumbnail_source_resolver の Wikimedia allowlist
     未登録名は Wikimedia を叩かない (See Ya → F-16 / Aiki → 合気道 型の
     誤マッチ事故への構造的根治)。登録すると誤マッチのリスクを負うため、
     「実際に取得して本人写真だと目視確認できたもの」だけを登録する。

  2. factcheck_v2 の corpus (lib/factcheck_corpus.py)
     「確定データ」として矛盾検出の根拠に使われる。裏取りできていない
     メンバー構成やデビュー日を書くと factcheck が誤判定する。
     検証していない項目は「書かない」のが正しく、空文字で埋めてはならない。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

MASTER = Path('/home/aiuser/kpop-ai-system/config/artist_master.json')


def _artists():
    return json.loads(MASTER.read_text(encoding='utf-8'))['artists']


def test_ids_and_names_are_unique():
    """id / name_en の重複は allowlist と corpus の両方を壊す。"""
    arts = _artists()
    ids = [a['id'] for a in arts]
    names = [a['name_en'] for a in arts]
    assert len(ids) == len(set(ids)), f'id 重複: {sorted(set(x for x in ids if ids.count(x) > 1))}'
    assert len(names) == len(set(names)), (
        f'name_en 重複: {sorted(set(x for x in names if names.count(x) > 1))}')


def test_required_fields_present():
    """allowlist 照合に使う name_en と id は必須。"""
    for a in _artists():
        assert a.get('id'), f'id 欠落: {a}'
        assert a.get('name_en'), f'name_en 欠落: {a.get("id")}'
        assert a.get('type') in ('group', 'solo'), (
            f'{a["name_en"]}: type は group/solo のいずれか (got {a.get("type")})')


def test_no_empty_placeholder_values():
    """空文字の placeholder を禁止する。

    corpus は値があれば「確定情報」として出力するため、空文字や '不明' を
    入れると factcheck に無意味な行が渡る。未検証項目はキーごと省略する。
    """
    for a in _artists():
        for k, v in a.items():
            if isinstance(v, str):
                assert v.strip() != '', f'{a["name_en"]}: {k} が空文字 (キーごと省略すべき)'
            assert v != '不明', f'{a["name_en"]}: {k} が「不明」(キーごと省略すべき)'


def test_members_have_names_when_present():
    """members を書くなら name は必須 (corpus が人数と名前を出力するため)。"""
    for a in _artists():
        for m in a.get('members', []):
            assert m.get('name'), f'{a["name_en"]}: members に name の無い要素がある'


def test_corpus_builds_and_contains_registered_artists():
    """corpus が例外なく生成され、登録アーティストが載ること。"""
    from lib.factcheck_corpus import build_corpus
    build_corpus.cache_clear()
    c = build_corpus()
    assert c, 'corpus が空'
    for a in _artists()[:5]:
        assert a['name_en'] in c, f'{a["name_en"]} が corpus に出力されていない'


def test_corpus_omits_unknown_agency():
    """agency 未検証のエントリで「所属事務所: 不明」を出力しないこと。

    corpus は factcheck が「確定データ」として読む。裏取りしていない項目に
    「不明」と書くと、確定情報の中に無意味な行が混ざりトークンを浪費する上、
    「不明であることが確定している」とも読める。未検証項目は行ごと省略する。
    """
    from lib.factcheck_corpus import _format_artist
    out = _format_artist({'id': 'x', 'name_en': 'TestGroup', 'type': 'group'})
    assert '不明' not in out, f'未検証 agency が「不明」として出力されている:\n{out}'
    assert '所属事務所' not in out, f'agency 未指定なのに行が出ている:\n{out}'
    assert 'TestGroup' in out


def test_registered_names_are_loadable_by_resolver():
    """resolver の allowlist が artist_master を読めること。"""
    sys.path.insert(0, '/home/aiuser/kpop-ai-system/lib')
    import thumbnail_source_resolver as tsr
    tsr._REGISTERED_ARTIST_NAMES = None  # cache 無効化
    names = tsr._load_registered_artist_names()
    for a in _artists():
        assert a['name_en'].lower() in names, (
            f'{a["name_en"]} が allowlist に載っていない = Wikimedia がスキップされる')
