"""2026-05-11 AI翻訳調表現 検出パターン規定 test

事故内容: 5/11 監査で 21006 RIIZE/ANTON「心温まる瞬間を提供した」、20445 BLACKPINK
リサ「呼び起こしています」等の AI翻訳調表現が散見。ネイティブ日本語では使われない
直訳テンプレが多用され、SEO/CTR を低下させる可能性。

修正: proofreader prompt に AI翻訳調検出パターンを明記し high として報告するよう指示。
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_proofreader_prompt_has_ai_translation_pattern_section():
    """proofreader prompt に AI翻訳調パターンの判定基準が明記されていること"""
    src = open('/home/aiuser/kpop-ai-system/pipeline/llm_proofreader.py').read()
    assert 'AI翻訳調' in src, 'AI翻訳調 detection 文言が prompt に存在しない'
    # 具体例パターン
    for pattern in ['呼び起こしています', '心温まる', '彼の/彼女の']:
        assert pattern in src, f'AI翻訳調 サンプル "{pattern}" が prompt に未記載'


def test_proofreader_prompt_specifies_threshold():
    """AI翻訳調は false positive 抑制のため一定回数以上の反復で報告するよう
    threshold (4回以上等) が指定されていること"""
    src = open('/home/aiuser/kpop-ai-system/pipeline/llm_proofreader.py').read()
    # 「N回以上」または「複数回」「反復」等の閾値表現
    has_threshold = any(t in src for t in ['4回以上', '5回以上', '複数回', '反復', '繰り返し'])
    assert has_threshold, 'AI翻訳調 threshold が不明確 (false positive リスク)'
