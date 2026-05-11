"""2026-05-11 CTA <p>不整合事故の再発防止テスト

事故内容: 5/11 の breaking 9件が <p> open=N close=N-3 で gate_block → draft化。
真因: cta_injector の A8 アフィリエイト link が <a>...</a>\\n<img/> 形式で <p> 未ラップ。
これを WP に POST すると wpautop が自動 <p> 補完するが、末尾の </div> 直前で
</p> 閉じが落ちる WP quirk により 3-tag 不均衡を生む。

修正後: cta_injector が link_html を <p class="kpj-cta-link"> で明示包み。
wpautop が介入しないため不均衡が生まれない。
"""
import re
import sys

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_cta_block_has_balanced_p_tags():
    """生成された CTA block が <p>/</p> 数で釣り合っていること"""
    from lib.cta_injector import generate_cta_block, get_cta_programs_for_article
    info = get_cta_programs_for_article('テスト記事', '<p>dummy</p>' * 10)
    programs = info.get('programs', [])
    if not programs:
        # affiliate config 未設定の環境ではskip
        import pytest
        pytest.skip('No CTA programs available (affiliate config not loaded)')
    block = generate_cta_block(programs[:3], 'テスト記事')
    if not block:
        import pytest
        pytest.skip('Empty CTA block (no a8 materials registered)')
    p_opens = len(re.findall(r'<p[\s>]', block))
    p_closes = block.count('</p>')
    assert p_opens == p_closes, (
        f'CTA block <p> 不均衡: open={p_opens} close={p_closes}\n'
        f'block[:500]={block[:500]!r}'
    )


def test_cta_injector_wraps_a8_link_in_p():
    """cta_injector の生成テンプレートが link_html を <p> で包んでいること"""
    src = open('/home/aiuser/kpop-ai-system/lib/cta_injector.py').read()
    # 「<p class="kpj-cta-link">{link_html}</p>」または同等の包みがあること
    assert ('<p class="kpj-cta-link">' in src and '{link_html}</p>' in src) or (
        re.search(r'<p[^>]*>.*\{link_html\}.*</p>', src, re.DOTALL)
    ), (
        'link_html が <p>...</p> で包まれていない。'
        'wpautop が CTA を壊す事故が再発する可能性'
    )


def test_a8_link_template_p_imbalance_now_fixed_in_pre_publish_gate():
    """gate の <p>/</p> count check が機能していること (defense-in-depth)"""
    from lib.pre_publish_gate import _check_html_structure
    # 意図的に不均衡な body
    bad_body = '<p>hello<p>world<p>foo</p>'  # open=3 close=1
    issues = _check_html_structure(bad_body)
    types = [i.get('type', '') for i in issues]
    assert 'unclosed_p' in types, (
        f'gate が <p>不均衡を検出できていない: types={types}'
    )
