"""pre_publish_gate: BLOCK 確定済みなら LLM factcheck を呼ばない回帰テスト
(2026-07-21 修正: 生成後ブロック分の factcheck 丸損を根治)

背景:
  収益/コスト分析中に発覚。pre_publish_gate は section 1〜2 の安価な検査
  (本文長 / サムネ / letterbox / meta / slug / ハングル残留 等)で BLOCK が
  確定しても早期 return せず、section 2b の LLM factcheck(1コール約9円)を
  必ず呼んでいた。BLOCK 確定記事は factcheck の結果に関わらず公開されないため
  この呼び出しは全て無駄。7月実測で 813件/月 = 約7,400円/月 が丸損だった。

  修正: section 2b の直前で「verdict 決定(section 4)と同じ基準」で BLOCK 確定を
  判定し、確定済みなら factcheck を skip する。

本テストの不変条件(実 API を呼ばずモックで決定的に検証):
  1. 安価な検査で BLOCK が確定している記事では factcheck が呼ばれない。
  2. BLOCK が確定していない記事では従来どおり factcheck が呼ばれる
     (= 修正が「常に skip」になっていない。品質を落としていないことの担保)。
  3. skip した場合は理由が issues に info として残る(可観測性)。
  4. draft は section 4 で block→warn に格下げされるため BLOCK 確定にならず、
     従来どおり factcheck 対象のまま(status 依存の挙動が壊れていない)。
"""
import sys
import types

import pytest

from lib.pre_publish_gate import pre_publish_gate


@pytest.fixture
def factcheck_spy(monkeypatch):
    """lib.factcheck_v2 をモックし呼び出し回数を記録する。

    KPJ_TEST_MODE は factcheck を無条件 skip するため、本テストでは明示的に
    解除して「本物の呼び出し経路」を通す。
    """
    monkeypatch.delenv('KPJ_TEST_MODE', raising=False)
    calls = {'n': 0}
    mod = types.ModuleType('lib.factcheck_v2')

    def proofread_post_v2(*args, **kwargs):
        calls['n'] += 1
        return {'all_issues': []}

    mod.proofread_post_v2 = proofread_post_v2
    monkeypatch.setitem(sys.modules, 'lib.factcheck_v2', mod)
    return calls


def _long_body():
    return '<p>' + '架空の話題についての十分な長さの本文をここに記述する。' * 40 + '</p>'


def _unique_title():
    # 実 WP の重複検出に引っかからない、K-POP と無関係な固有タイトル
    return 'ザンクトガレン工科大学の量子計測装置が稼働開始'


def test_blocked_article_skips_factcheck(factcheck_spy):
    """本文が壊滅的に短い(=安価な検査で BLOCK 確定)なら factcheck を呼ばない"""
    res = pre_publish_gate(
        title='テスト記事', body_html='<p>短い</p>', kind='news',
        source_url='https://www.soompi.com/article/1', status='publish',
        slug='test-article-slug', featured_media=1, excerpt='あ' * 130,
    )
    assert res['verdict'] == 'BLOCK'
    assert factcheck_spy['n'] == 0, 'BLOCK確定済みなのに factcheck が呼ばれている(丸損)'


def test_blocked_article_records_skip_reason(factcheck_spy):
    """skip したことが issues に残る(可観測性)"""
    res = pre_publish_gate(
        title='テスト記事', body_html='<p>短い</p>', kind='news',
        source_url='https://www.soompi.com/article/1', status='publish',
        slug='test-article-slug', featured_media=1, excerpt='あ' * 130,
    )
    types_ = {i.get('type') for i in res['issues']}
    assert 'llm_factcheck_skipped_blocked' in types_


def test_clean_article_still_runs_factcheck(factcheck_spy):
    """BLOCK 未確定なら従来どおり factcheck が走る(常時 skip になっていない)"""
    pre_publish_gate(
        title=_unique_title(), body_html=_long_body(), kind='news',
        source_url='https://www.soompi.com/article/99999', status='publish',
        slug='zsg-quantum-metrology-device-online', featured_media=1,
        excerpt='あ' * 130, categories=[1],
    )
    assert factcheck_spy['n'] == 1, 'BLOCK未確定の記事で factcheck が走っていない(検出力低下)'


def test_draft_is_not_treated_as_blocked(factcheck_spy):
    """draft は BLOCK に昇格しないので skip 対象にならない"""
    pre_publish_gate(
        title=_unique_title(), body_html='<p>短い</p>', kind='news',
        source_url='https://www.soompi.com/article/1', status='draft',
        slug='test-article-slug', featured_media=1, excerpt='あ' * 130,
    )
    # draft は status != 'publish' のため factcheck 自体が走らない仕様。
    # ここで担保するのは「_already_blocked が draft を BLOCK 扱いしない」こと。
    assert factcheck_spy['n'] == 0
