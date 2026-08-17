#!/usr/bin/env python3
"""lib/collectors/wowkorea_collector.py のテスト。

背景 (2026-08-17):
  コレクタ健全性チェックの導入で、wowkorea が0件のまま無言死していたと判明。
  真因は2つ:
    1. 収集先 https://www.wowkorea.jp/news/enter/ が **404**。
       404ページを HTTP 200 で返すため fetch は成功し、エラーにならない。
       (正しくは https://www.wowkorea.jp/news/)
    2. 記事URLが /news/read/<id> から /news/pickup/<id>.html に変更されていた。

  実HTMLでは見出しは <h2> 内のリンクテキストにあり、同じ記事への画像リンクの
  alt 属性にも見出しが入る(=同じURLで2回マッチしうる)。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.collectors.wowkorea_collector import parse_articles  # noqa: E402


# 実際の wowkorea.jp/news/ の構造(2026-08-17取得)を縮めたもの
SAMPLE = '''
<div class="card">
  <a href="/news/pickup/531785.html">
    <img class="img-fluid lazy" src="/img/news/106/531785/445457_640W.webp"
     alt="【全文】「BLACKPINK」JENNIEも頭を下げた…デビュー10周年をめぐる議論に謝罪" width="640">
  </a>
  <h2 class="card-title">
    <a href="/news/pickup/531785.html">【全文】「BLACKPINK」JENNIEも頭を下げた…デビュー10周年をめぐる議論に謝罪</a>
  </h2>
</div>
<div class="card">
  <a href="/news/pickup/531781.html">
    <img class="img-fluid lazy" src="/img/news/106/531781/445453_tmb.webp"
     alt="「BBGIRLS」ユナ、朝のお天気キャスターに挑戦" width="320">
  </a>
  <h2 class="card-title">
    <a href="/news/pickup/531781.html">「BBGIRLS」ユナ、朝のお天気キャスターに挑戦</a>
  </h2>
</div>
<div class="card">
  <h2 class="card-title">
    <a href="/news/pickup/531700.html">「TWICE」ナヨン、日本ツアー追加公演が決定</a>
  </h2>
</div>
'''


def test_記事を抽出できる():
    got = parse_articles(SAMPLE)
    titles = [a["title"] for a in got]
    assert "「BBGIRLS」ユナ、朝のお天気キャスターに挑戦" in titles


def test_同じ記事を重複して返さない():
    """画像リンクと見出しリンクで同じURLが2回出るため、URLで一意化する。"""
    got = parse_articles(SAMPLE)
    urls = [a["url"] for a in got]
    assert len(urls) == len(set(urls))


def test_URLを絶対URLにする():
    got = parse_articles(SAMPLE)
    for a in got:
        assert a["url"].startswith("https://www.wowkorea.jp/news/pickup/")


def test_見出しにHTMLタグが混ざらない():
    got = parse_articles(SAMPLE)
    for a in got:
        assert "<" not in a["title"] and ">" not in a["title"]


def test_全3記事を取れる():
    got = parse_articles(SAMPLE)
    assert len(got) == 3


def test_記事が無い構造では空を返す():
    """404ページを掴んでも壊れた値を返さない(今回の真因の再発防止)。"""
    assert parse_articles("<html><title>ページが見つかりません</title></html>") == []
