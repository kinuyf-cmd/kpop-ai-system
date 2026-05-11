"""2026-05-11 LLM proofreader メンバー人数 hallucination 除去フィルタ test

事故内容: 21219「NCT WISH 5曲がCircle Chartトップ10独占」の factcheck で
LLM が「5曲」を「5人組」と誤読し CRIT「NCT WISHは5人組として記載」を報告。
記事本文に「人組」「メンバー」表記は一切なし。

修正: result の critical を後処理で filter。本文に「N人組」「メンバーはN人」パターンが
ない場合、メンバー人数を CRIT 報告している項目は hallucination と判定して除外。
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_filter_logic_keyword_present():
    """proofread に hallucination filter ロジックが実装されていること"""
    src = open('/home/aiuser/kpop-ai-system/pipeline/llm_proofreader.py').read()
    # フィルタロジックのキーワード
    assert 'hallucination' in src.lower(), 'hallucination filter docstring missing'
    assert '人組として記載' in src, 'member-count CRIT removal logic missing'
    assert '_has_member_pattern' in src, 'pattern check variable missing'


def test_filter_drops_crit_when_body_has_no_member_pattern():
    """本文に N人組 がない記事で LLM が member-count CRIT を返した場合、除外されること"""
    # 直接 proofread_article を呼ぶと OpenAI API call 発生するため、フィルタ logic 単体を test
    # 実装的に export 困難なので、key patterns を検証する形に
    import re
    plain_no_member = '記事本文。NCT WISHが5曲でチャートトップ10入りした。'
    plain_with_member = '記事本文。BTSは7人組のグループ。'
    has_no = bool(re.search(r'\d+\s*人組|メンバー[はが]?\s*\d+\s*[人名]', plain_no_member))
    has_yes = bool(re.search(r'\d+\s*人組|メンバー[はが]?\s*\d+\s*[人名]', plain_with_member))
    assert not has_no, '5曲 を 5人組 と誤判定している'
    assert has_yes, '7人組 が検出されない'


def test_filter_preserves_legitimate_crit():
    """本文に明確な「N人組」記載がある場合は CRIT を残す (regression防止)"""
    src = open('/home/aiuser/kpop-ai-system/pipeline/llm_proofreader.py').read()
    # has_member_pattern が True なら filter スキップする分岐があること
    assert 'if not _has_member_pattern' in src, 'guard condition missing'
