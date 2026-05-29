"""lib.wikimedia._wikidata_p18_image のHTTPモック unit test。

wikidata APIを呼ばずに、(a)正常ケース (b)description非K-POPで弾く (c)P18空
(d)レスポンス形状異常 のガードを固定する。
"""
import io
import json
import urllib.request
from unittest.mock import patch


def _fake_resp(payload):
    return io.BytesIO(json.dumps(payload).encode('utf-8'))


def _stub_urlopen(*responses):
    """順に返すurlopenスタブ。複数URLを順番に消費する"""
    it = iter(responses)
    def _open(req, timeout=15):
        return next(it)
    return _open


class TestWikidataP18:
    def test_returns_file_title_on_kpop_match(self):
        from lib import wikimedia as w
        search = {'search': [
            {'id': 'Q1', 'description': 'Family name'},          # 非K-POP→skip
            {'id': 'Q999', 'description': 'South Korean boy band'},  # match
        ]}
        claims = {'claims': {'P18': [
            {'mainsnak': {'datavalue': {'value': 'CORTIS Demo.png'}}}
        ]}}
        with patch.object(urllib.request, 'urlopen',
                          side_effect=_stub_urlopen(_fake_resp(search), _fake_resp(claims))):
            r = w._wikidata_p18_image('CORTIS')
        assert r == {'qid': 'Q999', 'title': 'File:CORTIS Demo.png'}

    def test_returns_none_when_no_kpop_description(self):
        from lib import wikimedia as w
        search = {'search': [
            {'id': 'Q1', 'description': 'Family name'},
            {'id': 'Q2', 'description': 'steroid hormone'},
        ]}
        with patch.object(urllib.request, 'urlopen',
                          side_effect=_stub_urlopen(_fake_resp(search))):
            r = w._wikidata_p18_image('Cortis')
        assert r is None

    def test_returns_none_when_p18_missing(self):
        from lib import wikimedia as w
        search = {'search': [{'id': 'Q3', 'description': 'K-pop girl group'}]}
        claims = {'claims': {}}
        with patch.object(urllib.request, 'urlopen',
                          side_effect=_stub_urlopen(_fake_resp(search), _fake_resp(claims))):
            r = w._wikidata_p18_image('SomeGroup')
        assert r is None

    def test_returns_none_when_value_is_non_string(self):
        """P18 value が dict など想定外の型でも例外にせずNone"""
        from lib import wikimedia as w
        search = {'search': [{'id': 'Q4', 'description': 'Korean singer'}]}
        claims = {'claims': {'P18': [
            {'mainsnak': {'datavalue': {'value': {'id': 'Q123'}}}},  # dict型
        ]}}
        with patch.object(urllib.request, 'urlopen',
                          side_effect=_stub_urlopen(_fake_resp(search), _fake_resp(claims))):
            r = w._wikidata_p18_image('X')
        assert r is None

    def test_handles_malformed_search_response(self):
        """search欠落でもAttributeErrorを出さない"""
        from lib import wikimedia as w
        # ja試行→en試行の両方が空応答でNoneに収束
        with patch.object(urllib.request, 'urlopen',
                          side_effect=_stub_urlopen(_fake_resp({}), _fake_resp({}))):
            r = w._wikidata_p18_image('X')
        assert r is None

    def test_japanese_search_falls_back_to_english(self):
        """ja で見つからない時 en で再検索する"""
        from lib import wikimedia as w
        ja_empty = {'search': []}
        en_hit = {'search': [{'id': 'Q500', 'description': 'south korean girl group'}]}
        claims = {'claims': {'P18': [
            {'mainsnak': {'datavalue': {'value': 'Foo.jpg'}}}
        ]}}
        with patch.object(urllib.request, 'urlopen',
                          side_effect=_stub_urlopen(_fake_resp(ja_empty), _fake_resp(en_hit), _fake_resp(claims))):
            r = w._wikidata_p18_image('FooGroup')
        assert r == {'qid': 'Q500', 'title': 'File:Foo.jpg'}

    def test_japanese_description_keyword_matches(self):
        """日本語description「韓国のアイドル」等でも採用"""
        from lib import wikimedia as w
        search = {'search': [{'id': 'Q600', 'description': '韓国の女性歌手'}]}
        claims = {'claims': {'P18': [
            {'mainsnak': {'datavalue': {'value': 'Bar.jpg'}}}
        ]}}
        with patch.object(urllib.request, 'urlopen',
                          side_effect=_stub_urlopen(_fake_resp(search), _fake_resp(claims))):
            r = w._wikidata_p18_image('Bar')
        assert r == {'qid': 'Q600', 'title': 'File:Bar.jpg'}
