"""
memory: feedback_codeblock_marker_ban.md
規定: 「```html等のゴミが記事に混入する事故の再発防止。GPT生成/スクレイプ両方で除去」
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_pre_publish_gate_detects_code_block_marker():
    """本文に ```html / ``` 残存があると BLOCK or WARN として検出されること"""
    from lib.pre_publish_gate import _check_contamination

    body = '''<p>記事冒頭。</p>
```html
<div>some html</div>
```
<p>記事末尾。</p>'''

    issues = _check_contamination(body)
    types = {i.get('type') for i in issues}
    # contamination系のいずれかで検出されること
    assert any(t in types for t in ('codeblock_marker', 'markdown_marker', 'cta_misplaced',
                                     'kcon_inline_contamination')) or \
           any('```' in (i.get('detail', '') + i.get('value', '')) for i in issues), \
           f"```html マーカー検出失敗: issues={issues}"


def test_no_false_positive_on_clean_html():
    """クリーンなHTMLには検出が出ないこと"""
    from lib.pre_publish_gate import _check_contamination

    body = '<p>普通の記事本文です。</p><h2>セクション</h2><p>続き。</p>'
    issues = _check_contamination(body)
    cb_issues = [i for i in issues if 'codeblock' in str(i).lower() or 'markdown' in str(i).lower()]
    assert not cb_issues, f"クリーンHTMLで誤検出: {cb_issues}"


def test_sanitize_gpt_html_strips_codeblock_markers():
    """sanitize_gpt_html が ```html ... ``` を除去すること (2026-05-11追加)
    生成段階で除去できれば pre_publish_gate の BLOCK 自体が発生しない。
    """
    from lib.text_sanitizer import sanitize_gpt_html

    cases = [
        ('```html\n<h2>X</h2>\n```', '小文字 ```html'),
        ('```HTML\n<p>A</p>\n```', '大文字 ```HTML'),
        ('```\n<h2>X</h2>\n```', '言語指定なし'),
        ('<h2>X</h2>\n```html\n<p>A</p>\n```\n<h2>Y</h2>', '中段に混入'),
    ]
    for src, label in cases:
        out = sanitize_gpt_html(src)
        assert '```' not in out, f"{label}: ```残存 in={src!r} out={out!r}"


def test_sanitize_gpt_html_preserves_clean_html():
    """sanitize_gpt_html がクリーンHTMLを破壊しないこと"""
    from lib.text_sanitizer import sanitize_gpt_html

    src = '<h2>正常見出し</h2>\n<p>本文内容です。</p>'
    out = sanitize_gpt_html(src)
    assert '<h2>正常見出し</h2>' in out
    assert '<p>本文内容です。</p>' in out
