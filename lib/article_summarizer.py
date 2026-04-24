#!/usr/bin/env python3
"""
article_summarizer.py - Track D 記事構造ナタリー化
記事HTMLから3行まとめを生成し、記事内に挿入する。
"""

import argparse
import json
import re
import sys
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    """HTMLからテキストを抽出するパーサー。ヘッダータグ内のテキストはスキップ。"""

    def __init__(self):
        super().__init__()
        self._texts: list[str] = []
        self._skip = False
        self._skip_tags = {"h1", "h2", "h3", "h4", "h5", "h6", "script", "style"}

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self._skip_tags:
            self._skip = True

    def handle_endtag(self, tag):
        if tag.lower() in self._skip_tags:
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._texts.append(data)

    def get_text(self) -> str:
        return " ".join(self._texts)


def _extract_text(html: str) -> str:
    """HTMLからプレーンテキストを抽出する（ヘッダーを除く）。"""
    parser = _TextExtractor()
    parser.feed(html)
    return parser.get_text()


def _split_sentences(text: str) -> list[str]:
    """日本語・英語の文を分割する。"""
    # Japanese sentence endings: 。！？ and English: . ! ?
    parts = re.split(r'(?<=[。！？\.\!\?])\s*', text)
    sentences = []
    for p in parts:
        p = p.strip()
        if p:
            sentences.append(p)
    return sentences


def generate_summary(article_html: str) -> str:
    """
    記事HTMLから3行まとめHTMLを生成する。
    - HTMLからテキスト抽出
    - 最初の実質的な3文（20文字超）を選択
    - 3行まとめHTMLとしてフォーマット
    """
    text = _extract_text(article_html)

    sentences = _split_sentences(text)

    # Pick first 3 substantive sentences (>20 chars)
    key_sentences: list[str] = []
    for s in sentences:
        if len(s) > 20:
            key_sentences.append(s)
            if len(key_sentences) == 3:
                break

    # Fallback: if fewer than 3 sentences, use first 500 chars split into chunks
    if len(key_sentences) < 3:
        remaining = text[:500]
        chunks = [remaining[i:i + 150].strip() for i in range(0, len(remaining), 150)]
        for c in chunks:
            if c and len(key_sentences) < 3:
                key_sentences.append(c)

    # Ensure exactly 3 items
    while len(key_sentences) < 3:
        key_sentences.append("...")

    li_items = "".join(f"<li>{s}</li>" for s in key_sentences[:3])
    summary_html = (
        '<div class="kpj-summary">'
        "<h4>この記事の3行まとめ</h4>"
        f"<ul>{li_items}</ul>"
        "</div>"
    )
    return summary_html


def insert_summary_into_html(full_html: str, summary_html: str) -> str:
    """
    まとめHTMLを記事内に挿入する。
    挿入位置: 最初の</p>の後、最初の<h2>の前。
    """
    # Find first </p>
    p_end = re.search(r'</p>', full_html, re.IGNORECASE)
    # Find first <h2>
    h2_start = re.search(r'<h2[^>]*>', full_html, re.IGNORECASE)

    if p_end and h2_start and p_end.end() <= h2_start.start():
        # Insert between </p> and <h2>
        insert_pos = p_end.end()
        return full_html[:insert_pos] + "\n" + summary_html + "\n" + full_html[insert_pos:]
    elif h2_start:
        # No </p> before <h2>, insert before <h2>
        insert_pos = h2_start.start()
        return full_html[:insert_pos] + summary_html + "\n" + full_html[insert_pos:]
    elif p_end:
        # No <h2>, insert after first </p>
        insert_pos = p_end.end()
        return full_html[:insert_pos] + "\n" + summary_html + "\n" + full_html[insert_pos:]
    else:
        # Fallback: prepend
        return summary_html + "\n" + full_html


def main():
    parser = argparse.ArgumentParser(description="記事HTMLから3行まとめを生成・挿入する")
    parser.add_argument("--html", type=str, help="記事HTML文字列")
    parser.add_argument("--file", type=str, help="記事JSONファイルパス（content キーにHTMLを格納）")
    args = parser.parse_args()

    if not args.html and not args.file:
        parser.print_help()
        sys.exit(1)

    article_html = ""
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            data = json.load(f)
            article_html = data.get("content", data.get("html", ""))
    elif args.html:
        article_html = args.html

    if not article_html:
        print("ERROR: 記事HTMLが空です", file=sys.stderr)
        sys.exit(1)

    summary = generate_summary(article_html)
    result = insert_summary_into_html(article_html, summary)
    print(result)


if __name__ == "__main__":
    main()
