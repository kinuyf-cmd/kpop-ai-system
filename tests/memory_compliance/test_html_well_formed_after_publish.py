"""
memory: feedback_codeblock_marker_ban + 2026-05-11新発見ルール
規定: 公開記事は <p>/<h2>/<h3> open/close 対称が必須。
2026-05-11発見: cta_injector の A8 HTML素材が <p>未閉じを含むため
14/15記事で unclosed_p 発生。BeautifulSoup正規化を generate_cta_block 内で必須化。
"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_cta_block_has_balanced_p_tags():
    """generate_cta_block の出力 <p> open/close が対称であること"""
    try:
        from lib.cta_injector import generate_cta_block, get_cta_programs_for_article
    except ImportError:
        import pytest; pytest.skip('cta_injector unavailable')

    # ダミーテーマで生成 (実プログラム必要なら skip)
    info = get_cta_programs_for_article('aespa新曲', '<p>aespaのCDが発売</p>' * 30)
    block = generate_cta_block(info.get('programs', []), 'aespa新曲')
    if not block:
        import pytest; pytest.skip('no programs available')

    opens = len(re.findall(r'<p[\s>]', block))
    closes = block.count('</p>')
    assert opens == closes, f"CTA block の <p> open={opens} close={closes} 不均衡"


def test_cta_injector_uses_bs_normalize():
    """generate_cta_block が BeautifulSoupで正規化していること"""
    import inspect
    from lib import cta_injector
    src = inspect.getsource(cta_injector.generate_cta_block)
    assert 'BeautifulSoup' in src, \
        "generate_cta_block に BeautifulSoup正規化がない (A8素材が壊れた場合の防御)"


def test_normalize_html_for_publish_fixes_unclosed_p():
    """normalize_html_for_publish が unclosed_p を BSで自動修正すること"""
    from lib.pre_publish_gate import normalize_html_for_publish
    broken = '<p>foo<p>bar</p>'  # 1件 open過剰
    out = normalize_html_for_publish(broken)
    opens = len(re.findall(r'<p[\s>]', out))
    closes = out.count('</p>')
    assert opens == closes, f"normalize後も不均衡: open={opens} close={closes}, out={out}"
