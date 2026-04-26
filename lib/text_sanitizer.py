#!/usr/bin/env python3
"""テキスト前処理: GPT生成テンプレートラベル除去 + 共通サニタイズ

使い方:
  from lib.text_sanitizer import strip_template_labels
  content = strip_template_labels(content)
"""
import re

# GPT生成時に混入しうるセクション識別子ラベル
# 行頭 or <p>直後の「リード文:」「導入文:」「本文:」「セクションN:」等を除去
_LABEL_PATTERNS = [
    # <hN>リード文</hN> 見出しごと除去
    (re.compile(r'<h[1-6][^>]*>\s*リード\s*文\s*[:：]?\s*</h[1-6]>\s*'), ''),
    (re.compile(r'<h[1-6][^>]*>\s*(?:導入文|結論文?|結び)\s*[:：]?\s*</h[1-6]>\s*'), ''),
    # <p>タグ直後のラベル
    (re.compile(r'(<p[^>]*>)\s*リード\s*文\s*[:：]\s*'), r'\1'),
    (re.compile(r'(<p[^>]*>)\s*(?:導入文|結論文?|結び)\s*[:：]\s*'), r'\1'),
    (re.compile(r'(<p[^>]*>)\s*セクション\s*\d+\s*[:：]\s*'), r'\1'),
    # 行頭のラベル (HTML外)
    (re.compile(r'^\s*リード\s*文\s*[:：]\s*', re.MULTILINE), ''),
    (re.compile(r'^\s*(?:導入文|結論文?|結び)\s*[:：]\s*', re.MULTILINE), ''),
    (re.compile(r'^\s*セクション\s*\d+\s*[:：]\s*', re.MULTILINE), ''),
    # 日本語直前のラベル (文中)
    (re.compile(r'リード\s*文\s*[:：]\s*(?=[\u3000-\u9fff\u30a0-\u30ff\u3040-\u309f])'), ''),
]


def strip_template_labels(text: str) -> str:
    """GPT生成テンプレートのセクション識別子ラベルを除去"""
    if not text:
        return text
    for pat, rep in _LABEL_PATTERNS:
        text = pat.sub(rep, text)
    return text
