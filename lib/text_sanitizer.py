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
    # TITLE: プレフィックス除去
    (re.compile(r'^\s*TITLE:\s*', re.MULTILINE), ''),
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


def sanitize_gpt_html(html: str) -> str:
    """GPT生成HTMLの汚染を除去 (教訓#61: CSS/style/body/h1混入対策)

    strip_template_labels に加え、以下を除去:
    - <style>...</style> ブロック
    - inline style属性
    - <body>/<html>/<head>/<meta>/<!DOCTYPE> タグ
    - <h1>...</h1> (WP側で出力するため)
    - unclosed <p> タグの自動閉じ
    - 「いかがでしょうか」等のcasual表現
    """
    if not html:
        return html

    # テンプレートラベル除去
    html = strip_template_labels(html)

    # style block除去
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # inline style attributes
    html = re.sub(r'\s+style="[^"]*"', '', html)
    # body/html/head/meta/DOCTYPE
    html = re.sub(r'</?(?:body|html|head|meta|!DOCTYPE)[^>]*>', '', html, flags=re.IGNORECASE)
    # h1 tags (title is rendered by WP)
    html = re.sub(r'<h1[^>]*>.*?</h1>', '', html, flags=re.DOTALL | re.IGNORECASE)

    # casual expressions (全バリエーション)
    html = re.sub(r'いかがでしょうか[、。!？]?', '', html)
    html = re.sub(r'いかがでしたか[、。!？]?', '', html)
    html = re.sub(r'いかがですか[、。!？]?', '', html)
    # メタ表現除去（LLM生成物の自己言及を除去）
    html = re.sub(r'この記事では[、。]?', '', html)
    html = re.sub(r'(?:ご)?参考になれば幸いです[、。!]?', '', html)
    html = re.sub(r'ご参考ください[、。!]?', '', html)
    html = re.sub(r'まとめると[、。]', '', html)

    # 文字重複修正 (5文字以上の連続→2文字に)
    html = re.sub(r'(.)\1{4,}', r'\1\1', html)

    # unclosed <p> fix (常に修正、閾値なし)
    # Phase 1: <p>内にブロック要素があれば</p>を挿入して閉じる
    html = re.sub(r'(<p[^>]*>[^<]*?)(<(?:h[2-6]|div|section|ul|ol|table|hr)[\s>])', r'\1</p>\n\2', html)
    # Phase 2: 残りの未閉じ<p>を末尾で閉じる
    open_p = len(re.findall(r'<p(?:\s[^>]*)?>', html))
    close_p = len(re.findall(r'</p>', html))
    if open_p > close_p:
        for _ in range(open_p - close_p):
            html = html.rstrip() + '</p>\n'
    # Phase 3: 孤児</p>を除去（close > open の場合）
    elif close_p > open_p:
        diff = close_p - open_p
        for _ in range(diff):
            # 末尾から孤児</p>を探して除去
            pos = html.rfind('</p>')
            if pos >= 0:
                before = html[:pos]
                opens_before = len(re.findall(r'<p(?:\s[^>]*)?>', before))
                closes_before = before.count('</p>')
                if closes_before >= opens_before:
                    html = html[:pos] + html[pos + 4:]

    return html.strip()
