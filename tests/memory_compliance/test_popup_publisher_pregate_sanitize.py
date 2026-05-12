"""2026-05-12 発見: popup_publisher.py で pre_publish_gate が「翻訳前タイトル」と
「sanitize 前コンテンツ」を見て BLOCK 連発していた。

修正: gate 呼び出し前に title 翻訳 + content sanitize を実施する規定。
ここでは sanitize_gpt_html が codeblock マーカーを除去できることを機械検証する。
title 翻訳の実 LLM 呼び出しは別途 E2E 領域。
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_sanitize_removes_codeblock_marker_html():
    """`\\`\\`\\`html\\n...\\n\\`\\`\\`` パターンの除去"""
    from lib.text_sanitizer import sanitize_gpt_html
    raw = "```html\n<p>本文です</p>\n```"
    out = sanitize_gpt_html(raw)
    assert '```' not in out, f'codeblock marker not removed: {out!r}'
    assert '<p>本文です</p>' in out


def test_sanitize_removes_codeblock_marker_plain():
    """言語指定なし ``` も除去"""
    from lib.text_sanitizer import sanitize_gpt_html
    raw = "```\n<p>content</p>\n```"
    out = sanitize_gpt_html(raw)
    assert '```' not in out, f'plain codeblock not removed: {out!r}'


def test_gate_rejects_codeblock_marker():
    """pre_publish_gate 自体は codeblock マーカーを BLOCK 検出すること
    (sanitize は呼び出し側で済ませる責務)"""
    from lib.pre_publish_gate import pre_publish_gate
    raw_body = "```html\n<p>content</p>\n```"
    r = pre_publish_gate(
        '正常タイトル20文字以上のサンプルテキスト',
        raw_body, post_type='popup', kind='popup',
        source_url='https://example.com/popup'
    )
    types = [iss.get('type') for iss in r.get('issues', [])]
    assert 'codeblock_marker' in types, f'expected codeblock_marker BLOCK: {types}'


def test_gate_passes_after_sanitize():
    """sanitize 後の content は gate で codeblock_marker BLOCK されないこと"""
    from lib.pre_publish_gate import pre_publish_gate
    from lib.text_sanitizer import sanitize_gpt_html
    raw_body = "```html\n" + ("<p>あいうえお</p>" * 50) + "\n```"
    sanitized = sanitize_gpt_html(raw_body)
    r = pre_publish_gate(
        '正常タイトル20文字以上のサンプルテキスト',
        sanitized, post_type='popup', kind='popup',
        source_url='https://example.com/popup'
    )
    types = [iss.get('type') for iss in r.get('issues', [])]
    assert 'codeblock_marker' not in types, f'sanitize did not strip: types={types}'
