#!/usr/bin/env python3
"""lib/collectors/koreaherald_collector.py のテスト。

背景 (2026-08-17):
  X会話投稿のネタ元を trend_signals にしたとき、koreaherald のシグナルだけ
  見出しが壊れていた(順位番号や隣の記事が混入し80字で切断)。
  例: 「6 Twice's Jeongyeon leaves JYP after 11 years, joins Varo Entertainment」
      「BTS' Jungkook hits 1.2b mark on Spotify with Charlie Puth collab Most Read K-pop」
  そのため lib/x_trend_topics.py で UNRELIABLE_SOURCES として除外していた。

  真因: 見出しは <p class="news_title"> に入っているのに、収集側は
  <a>...</a> の中身全体をテキストとして拾っており、本文抜粋(news_text)や
  隣接要素まで巻き込んでいた。さらに現在のHTML構造では正規表現が
  **1件もマッチせず**、この収集自体が無言で死んでいた(実測 matches=0)。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.collectors.koreaherald_collector import parse_articles  # noqa: E402


# 実際の koreaherald.com/Kpop の構造(2026-08-17 取得)を縮めたもの
SAMPLE = '''
<a href="https://www.koreaherald.com/article/10843012">
<div class="news_txt">
<p class="news_title">Stray Kids make Billboard history with 9th straight No. 1</p>
<p class="news_text ellipsis4">Stray Kids have made Billboard 200 history, becoming
the first act to debut their first nine charting albums at No. 1 with the release</p>
</div>
</a>
<a href="https://www.koreaherald.com/article/10843024">
<div class="news_txt">
<p class="news_title ellipsis2">Piano-shaped pastries mark Big Bang&apos;s 20 years</p>
</div>
<div class="news_img"><img src="https://wimg.heraldcorp.com/x.png"></div>
</a>
<a href="https://www.koreaherald.com/article/10841800">
<div class="news_txt">
<p class="news_title ellipsis2">Katseye follows intuition, embraces freedom in 3rd EP</p>
</div>
</a>
'''


def test_見出しを1件ずつ正しく取る():
    got = parse_articles(SAMPLE)
    titles = [a["title"] for a in got]
    assert "Stray Kids make Billboard history with 9th straight No. 1" in titles


def test_本文抜粋を見出しに混ぜない():
    """news_text(本文抜粋)が見出しに連結されると、どれが見出しか分からなくなる。"""
    got = parse_articles(SAMPLE)
    for a in got:
        assert "becoming the first act" not in a["title"], a["title"]


def test_隣の記事の見出しを連結しない():
    """従来は1つの <a> が兄弟要素まで飲み込み、複数見出しが1件になっていた。"""
    got = parse_articles(SAMPLE)
    for a in got:
        assert not ("Stray Kids" in a["title"] and "Big Bang" in a["title"])
        assert not ("Big Bang" in a["title"] and "Katseye" in a["title"])


def test_URLを記事ごとに正しく紐づける():
    got = parse_articles(SAMPLE)
    m = {a["title"]: a["url"] for a in got}
    assert m["Stray Kids make Billboard history with 9th straight No. 1"].endswith("10843012")


def test_HTMLエンティティを復号する():
    got = parse_articles(SAMPLE)
    titles = " ".join(a["title"] for a in got)
    assert "&apos;" not in titles
    assert "Big Bang's 20 years" in titles


def test_相対リンクも絶対URLにする():
    html = ('<a href="/article/123"><div class="news_txt">'
            '<p class="news_title">BTS announces new album</p></div></a>')
    got = parse_articles(html)
    assert got and got[0]["url"] == "https://www.koreaherald.com/article/123"


def test_見出しが取れない構造では何も返さない():
    """構造変更で取れなくなったとき、壊れた文字列を返すより空を返す方が安全。
    (実際に現行HTMLで旧実装は0マッチのまま無言で死んでいた)"""
    assert parse_articles("<div>no articles here</div>") == []
