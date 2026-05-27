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
        self._skip_tags = {"h1", "h2", "h3", "h4", "h5", "h6", "script", "style",
                           "table", "thead", "tbody", "tr", "td", "th", "nav", "aside"}

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
    """HTMLからプレーンテキストを抽出する（ヘッダー・画像帰属・CTA・内部誘導リンク除く）。

    要約は本文の「地の文」だけを対象にする。記事本文には以下の非・地の文が
    混ざるため、文抽出の前に構造的に除去する（除去対象は本文書換えでなく要約用の
    一時テキストのみ。記事DBには影響しない）:
      - 画像帰属行 / 免責文
      - CTAブロック（class が kpj-* / kpopj-* / kpopj-cta-* / data-cta 属性つき div）
      - 本文末尾や段落内に注入された「関連記事」誘導リンク（自ドメイン記事への <a>）
    """
    # 画像帰属行・免責文を事前に除去
    html = re.sub(r'<p[^>]*>画像[：:].*?</p>', '', html, flags=re.DOTALL)
    html = re.sub(r'<p[^>]*>※当サイト.*?</p>', '', html, flags=re.DOTALL)
    # CTAブロック除去: class が kpj-(cta|hybrid|disclosure) または kpopj-cta*、
    # もしくは data-cta 属性を持つ <div> を中身ごと削除。
    html = re.sub(r'<div[^>]*class="(?:kpj-(?:cta|hybrid|disclosure)|kpopj-cta)[^"]*"[^>]*>.*?</div>',
                  '', html, flags=re.DOTALL)
    html = re.sub(r'<div[^>]*\bdata-cta=[^>]*>.*?</div>', '', html, flags=re.DOTALL)
    # 自ドメイン記事への誘導 <a>（関連記事リンク/カテゴリCTA）をテキストごと除去。
    # 地の文の inline 内部リンクも巻き込むが、要約用テキストなので実害は軽微。
    html = re.sub(r'<a\b[^>]*href="https?://(?:www\.)?kpopjournal\.tokyo/[^"]*"[^>]*>.*?</a>',
                  '', html, flags=re.DOTALL | re.IGNORECASE)
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
        if not p:
            continue
        # 引用符をまたいで文分割された断片対策: 先頭に取り残された閉じ括弧・読点
        # （」』）)、，等）を剥がす。剥がした結果が極端に短ければ断片として捨てる。
        p = re.sub(r'^[」』）\)】〕》、，,。\.\—\-…\s]+', '', p)
        if len(p) < 10:
            continue
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
    # 画像帰属・CTA・注釈を除外
    _skip_patterns = ['画像:', '画像：', '元記事より', '※当サイト', '※Amazon', 'PR ', 'こんな方におすすめ']
    key_sentences: list[str] = []
    for s in sentences:
        if len(s) > 20 and not any(p in s for p in _skip_patterns):
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


def _remove_duplicate_lead(full_html: str, summary_sentences: list[str]) -> str:
    """3行まとめと重複するリード文（最初の<p>）を削除する。

    GPT生成記事は5W1Hリード文を冒頭に置くが、3行まとめがその文を
    そのまま抽出するため重複する。まとめ挿入後に冒頭段落を削除する。
    """
    if not summary_sentences:
        return full_html

    # 最初の<h2>より前の<p>...</p>を取得
    h2_pos = re.search(r'<h2[^>]*>', full_html, re.IGNORECASE)
    search_region = full_html[:h2_pos.start()] if h2_pos else full_html[:2000]

    # 最初の<p>...</p>ブロックを取得
    first_p = re.search(r'<p[^>]*>(.*?)</p>', search_region, re.DOTALL | re.IGNORECASE)
    if not first_p:
        return full_html

    first_p_text = re.sub(r'<[^>]+>', '', first_p.group(1)).strip()
    if len(first_p_text) < 30:
        return full_html

    # 3行まとめの文と最初の段落の類似度チェック
    overlap = sum(1 for s in summary_sentences if s[:30] in first_p_text)
    if overlap >= 2:
        # 2文以上重複 → 最初の段落を削除
        return full_html[:first_p.start()] + full_html[first_p.end():]

    return full_html


def insert_summary_into_html(full_html: str, summary_html: str) -> str:
    """
    まとめHTMLを記事内に挿入する。
    挿入位置: 最初の<h2>の直前。
    挿入後に、3行まとめと重複するリード文を削除する。
    """
    # 3行まとめのテキストを抽出（重複チェック用）
    summary_texts = re.findall(r'<li>([^<]+)</li>', summary_html)

    # Find first <h2>
    h2_start = re.search(r'<h2[^>]*>', full_html, re.IGNORECASE)

    if h2_start:
        insert_pos = h2_start.start()
        result = full_html[:insert_pos] + summary_html + "\n" + full_html[insert_pos:]
    else:
        # No <h2>, insert after first </p>
        p_end = re.search(r'</p>', full_html, re.IGNORECASE)
        if p_end:
            insert_pos = p_end.end()
            result = full_html[:insert_pos] + "\n" + summary_html + "\n" + full_html[insert_pos:]
        else:
            result = summary_html + "\n" + full_html

    # 重複リード文を削除
    result = _remove_duplicate_lead(result, summary_texts)
    return result


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
