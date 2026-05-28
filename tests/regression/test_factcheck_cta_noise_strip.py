"""factcheck v2 が CTA/アフィリ注入起因の指摘をキャッシュに残さないこと。

背景: 2026-05-27 に公開率17%(79件BLOCK)の原因調査で、
pid_cache(source_url pseudo-pid) が過去の注入後本文評価から
「エアトリリンク混入」「別記事見出し混入」を critical として
保持し続け、新しい翻訳記事の注入前評価にも返していた事実が判明。
_strip_cta_noise でキャッシュ書込時にこれらを除去する。
"""
from lib.factcheck_v2 import _strip_cta_noise, strip_cta_blocks_from_html


def test_strip_removes_airtri_critical():
    result = {
        'score': 30,
        'critical': [
            '本文末尾にエアトリ等の商業アフィリエイトリンクが複数挿入されており不自然',
            'ジョングクの出身地が誤って釜山と記載されている',
        ],
        'high': [],
        'medium': [],
    }
    out = _strip_cta_noise(result)
    assert len(out['critical']) == 1
    assert 'ジョングク' in out['critical'][0]


def test_strip_removes_heading_injection():
    result = {
        'score': 20,
        'critical': ['本文中に「IVE移籍」という見出し風テキストが挿入されている'],
        'high': ['本文末尾に推し活ガイドへのCTAが挿入されている'],
        'medium': [],
    }
    out = _strip_cta_noise(result)
    assert out['critical'] == []
    assert out['high'] == []


def test_html_strip_removes_cta_blocks():
    html = (
        '<p>BTSが新曲を発表しました。</p>'
        '<div data-cta="top" class="kpopj-cta-top">速報カテゴリへ→</div>'
        '<p>詳細は以下の通りです。</p>'
        '<div class="kpj-cta-block"><h3>ファンにおすすめ</h3>エアトリで韓国へ</div>'
    )
    out = strip_cta_blocks_from_html(html)
    assert 'BTSが新曲' in out
    assert '詳細は以下' in out
    assert 'エアトリ' not in out
    assert '速報カテゴリ' not in out
    assert 'kpj-cta-block' not in out
    assert 'data-cta' not in out


def test_html_strip_handles_empty_and_none():
    assert strip_cta_blocks_from_html('') == ''
    assert strip_cta_blocks_from_html(None) is None


def test_strip_preserves_legitimate_critical():
    result = {
        'score': 50,
        'critical': ['AMAsは例年11-12月開催だが5月開催と記述されている'],
        'high': ['メンバー人数が公式と矛盾'],
        'medium': [],
    }
    out = _strip_cta_noise(result)
    assert out == result
