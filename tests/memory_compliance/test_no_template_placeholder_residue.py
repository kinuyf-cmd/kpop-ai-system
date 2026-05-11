"""
2026-05-11発見: 本文に `[ソース名]` `[サイト名]` 等のテンプレ未置換が残る事故
→ pre_publish_gate で検出する規定
"""
import sys, inspect
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_pre_publish_gate_detects_template_placeholder():
    """`[ソース名]` 等のプレースホルダー残存を検出すること"""
    from lib.pre_publish_gate import _check_contamination
    body = '<p>記事本文。</p><p>※ 本記事は[ソース名]の報道を翻訳・編集したものです。</p>'
    issues = _check_contamination(body)
    types_detail = ' '.join(str(i) for i in issues)
    assert '[ソース名]' in types_detail or any('placeholder' in str(i).lower() or 'template' in str(i).lower() for i in issues), \
        f"[ソース名] placeholder未検出: {issues}"
