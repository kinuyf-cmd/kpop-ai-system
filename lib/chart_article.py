#!/usr/bin/env python3
"""chart_article.py — Soompi K-POP チャートの週次まとめ記事を組み立てる

owner依頼 (2026-08-23): チャート更新のたびに、その内容の記事を作る。

著作権 (citation-rules 準拠):
  順位・曲名・アーティスト名は事実データであり著作物ではないため掲載できるが、
  Soompi のチャートに依拠している以上、出典(媒体名+タイトル+URL)は必ず明記する。
  歌詞は引用不可。記事の主は自社の解説(順位変動の読み解き)で、引用は従。

Usage:
  from lib.chart_article import build_article, build_title, build_slug
"""
from __future__ import annotations

import html as _html
import json
import re
from datetime import datetime

_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}


def _parse_week(title: str):
    """Soompi のチャートタイトルから (年, 月, 週) を取る。"""
    m = re.search(r"(\d{4}),\s*([A-Z][a-z]+)\s*Week\s*(\d+)", str(title or ""))
    if not m:
        return None
    mon = _MONTHS.get(m.group(2))
    if not mon:
        return None
    return int(m.group(1)), mon, int(m.group(3))


def week_label(title: str) -> str:
    w = _parse_week(title)
    return f"{w[0]}年{w[1]}月 第{w[2]}週" if w else ""


def build_title(chart: dict) -> str:
    w = _parse_week(chart.get("title", ""))
    top = (chart.get("items") or [{}])[0]
    head = f"{w[1]}月第{w[2]}週" if w else "最新週"
    t = f"K-POPチャート{head}｜1位は{top.get('artist','')}「{top.get('song','')}」"
    return t[:60]


def build_slug(chart: dict) -> str:
    w = _parse_week(chart.get("title", ""))
    if not w:
        return "kpop-music-chart-latest"
    return f"kpop-music-chart-{w[0]}-{w[1]:02d}-week{w[2]}"


def _rank_map(prev):
    out = {}
    for it in (prev or {}).get("items", []):
        key = (str(it.get("song", "")).lower(), str(it.get("artist", "")).lower())
        out[key] = it.get("rank")
    return out


def _movement(it, prevmap):
    """前週比。(記号つき文字列, 説明) を返す。"""
    key = (str(it.get("song", "")).lower(), str(it.get("artist", "")).lower())
    p = prevmap.get(key)
    r = it.get("rank")
    if p is None:
        return ("NEW", "初登場")
    if p == r:
        return ("→", "前週と同順位")
    if p > r:
        return (f"↑{p - r}", f"前週{p}位から{p - r}ランク上昇")
    return (f"↓{r - p}", f"前週{p}位から{r - p}ランク下降")


def _esc(s):
    return _html.escape(str(s or ""), quote=False)


def build_article(chart: dict, prev: dict | None = None) -> str:
    items = chart.get("items") or []
    label = week_label(chart.get("title", "")) or "最新週"
    src_url = chart.get("url", "")
    prevmap = _rank_map(prev)
    top = items[0] if items else {}

    rows = []
    ups, news = [], []
    for it in items:
        # 前週データが無い週は「変動不明」であって「全曲が初登場」ではない。
        # 実生成で全10曲を初登場と書いてしまったため、prevmap が空なら判定しない。
        mark, desc = _movement(it, prevmap) if prevmap else ("—", "")
        if not prevmap:
            pass
        elif mark == "NEW":
            news.append(it)
        elif mark.startswith("↑"):
            ups.append((it, desc))
        album = f"<br><span class=\"kpj-chart-album\">{_esc(it.get('album'))}</span>" if it.get("album") else ""
        rows.append(
            f"<tr><td>{it.get('rank')}</td>"
            f"<td><strong>{_esc(it.get('song'))}</strong>{album}</td>"
            f"<td>{_esc(it.get('artist'))}</td>"
            f"<td>{mark}</td></tr>")

    # 自社の読み解き(記事の「主」)
    notes = []
    if top:
        notes.append(
            f"<p>今週の1位は<strong>{_esc(top.get('artist'))}</strong>の"
            f"「{_esc(top.get('song'))}」。"
            + (f"収録アルバムは『{_esc(top.get('album'))}』です。" if top.get("album") else "")
            + "</p>")
    if news:
        n = "、".join(f"{_esc(i.get('artist'))}「{_esc(i.get('song'))}」({i.get('rank')}位)" for i in news[:3])
        notes.append(f"<p><strong>今週の初登場</strong>は {n} です。"
                     "新譜がそのまま上位に入る週は、カムバック直後のファンダム票が動いていることが多く、"
                     "翌週に順位を維持できるかが定着の目安になります。</p>")
    if ups:
        n = "、".join(f"{_esc(i.get('artist'))}「{_esc(i.get('song'))}」({d})" for i, d in ups[:3])
        notes.append(f"<p><strong>順位を上げた曲</strong>は {n}。"
                     "配信開始直後より数週かけて上がる曲は、SNSやショート動画での波及で"
                     "リスナーが広がっているサインです。</p>")
    if not prevmap:
        notes.append("<p>※ 前週データが無いため、今回は順位変動を表示していません。"
                     "次回更新分から前週比を掲載します。</p>")

    faq = [
        (f"{label}のK-POPチャート1位は誰ですか?",
         f"{top.get('artist','')}の「{top.get('song','')}」が1位です。"
         f"順位はSoompiのK-Pop Music Chartに基づいています。"),
        ("このチャートは何を集計したものですか?",
         "Soompiが公開しているK-Pop Music Chartの週次順位です。"
         "当サイトでは順位データを引用し、前週比や初登場曲などの読み解きを加えて紹介しています。"
         "集計方法の詳細は出典元をご確認ください。"),
        ("チャートはいつ更新されますか?",
         "Soompi側の公開に合わせて週に1回更新されます。当サイトでは新しい週が公開され次第、"
         "自動で取り込んで最新の順位を掲載しています。"),
    ]
    faq_html = "".join(f"<h3>{_esc(q)}</h3><p>{_esc(a)}</p>" for q, a in faq)
    schema = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q,
         "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]}

    fetched = str(chart.get("fetched_at", ""))[:10] or datetime.now().strftime("%Y-%m-%d")

    return (
        f"<p>{_esc(label)}のK-POPミュージックチャートTOP{len(items)}をまとめました。"
        "順位の入れ替わりと、今週の注目ポイントを合わせて紹介します。</p>"
        f"<h2>{_esc(label)} K-POPチャート TOP{len(items)}</h2>"
        "<table><thead><tr><th>順位</th><th>曲名</th><th>アーティスト</th>"
        "<th>前週比</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        f"<h2>今週のポイント</h2>{''.join(notes)}"
        f"<h2>K-POPチャートに関するよくある質問</h2>{faq_html}"
        f'<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False)}</script>'
        "<h2>出典</h2>"
        f'<p class="kpj-source">順位データ出典: <cite>Soompi「'
        f'{_esc(chart.get("title", ""))}」</cite> '
        f'<a href="{_esc(src_url)}" target="_blank" rel="nofollow noopener">{_esc(src_url)}</a>'
        f'(取得日: {_esc(fetched)})</p>'
    )
