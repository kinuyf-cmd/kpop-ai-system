#!/usr/bin/env python3
"""Korea Herald K-POP (koreaherald.com) — 韓国最大の英字紙"""
import sys, re
import html as html_mod
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, save_signals, log, clean_title
from datetime import datetime

KPOP_KW = [
    'BTS', 'BLACKPINK', 'aespa', 'NewJeans', 'SEVENTEEN', 'TWICE', 'IVE',
    'LE SSERAFIM', 'ILLIT', 'ITZY', 'TXT', 'Stray Kids', 'ENHYPEN', 'NCT',
    'ATEEZ', 'EXO', 'RIIZE', 'BABYMONSTER', 'NMIXX', 'GOT7', 'MAMAMOO',
    'HYBE', 'SM Entertainment', 'YG', 'JYP', 'K-pop', 'idol', 'comeback',
    'debut', 'album', 'concert', 'tour', 'Billboard', 'Grammy',
]


# 2026-08-17 根治: 見出しは <a> 直下の <p class="news_title"> に入っている。
# 旧実装は `<a ...>((?:<[^>]*>|[^<]){5,200})</a>` で <a> の中身を丸ごとテキストとして
# 拾っており、本文抜粋(news_text)や隣接要素まで巻き込んで複数見出しが1件に連結した
# (「6 Twice's Jeongyeon leaves JYP…」「…collab Most Read K-pop」等)。
# しかも現行HTMLではこの正規表現が **1件もマッチせず**、収集が無言で死んでいた。
# link と title を「同じ <a> ブロック内」で対応付けるため、まず <a> 単位で切り出す。
_ANCHOR_RE = re.compile(
    r'<a[^>]+href="((?:https://www\.koreaherald\.com)?/article/\d+)"(.*?)</a>',
    re.DOTALL | re.IGNORECASE)
_TITLE_RE = re.compile(
    r'<p[^>]*class="[^"]*news_title[^"]*"[^>]*>(.*?)</p>', re.DOTALL | re.IGNORECASE)


def parse_articles(html: str) -> list:
    """HTML から (title, url) を1記事ずつ取り出す。

    見出しが取れない場合は空を返す。構造変更で壊れた文字列を流すより、
    何も返さない方が安全(壊れた見出しは下流で誰の話題か特定できず、
    実際に別グループの功績として投稿する誤情報を生んだ)。
    """
    out = []
    seen = set()
    for m in _ANCHOR_RE.finditer(html or ''):
        link, inner = m.group(1), m.group(2)
        tm = _TITLE_RE.search(inner)
        if not tm:
            continue
        # Korea Herald は英字紙。clean_title は韓国語見出し向け(記者署名除去・
        # 完結語での分離・80字切断)で、英語見出しには 80字切断だけが効いて
        # 途中で切れる。ここでは news_title を1件だけ取れているので、
        # タグ除去とエンティティ復号だけ行う。
        raw = re.sub(r'<[^>]+>', '', tm.group(1))
        title = re.sub(r'\s+', ' ', html_mod.unescape(raw)).strip()
        if not title or len(title) < 10:
            continue
        url = link if link.startswith('http') else 'https://www.koreaherald.com' + link
        if url in seen:
            continue
        seen.add(url)
        out.append({'title': title, 'url': url})
    return out


def collect():
    signals = []
    try:
        html = fetch_html('https://www.koreaherald.com/Kpop')
    except Exception as e:
        log(f"KoreaHerald fetch error: {e}")
        return 0

    articles = parse_articles(html)
    if not articles:
        # 構造変更を検知できるようにログに残す(旧実装は0件でも無言だった)
        log("KoreaHerald: 0 (見出しを抽出できず — HTML構造変更の可能性)")
        return 0
    for a in articles:
        title = a['title']
        matched = [k for k in KPOP_KW if k.lower() in title.lower()]
        if not matched:
            continue
        signals.append({
            'timestamp': datetime.now().isoformat(),
            'source': 'korean_media',
            'source_id': 'koreaherald',
            'keyword': matched[0],
            'title': title[:300],
            'url': a['url'],
            'engagement_score': 3.0,
            'language': 'en',
            'urgency': 'normal',
            'raw_data': {'all_keywords': matched},
        })
    save_signals(signals[:20])
    log(f"KoreaHerald: {len(signals[:20])}")
    return len(signals[:20])


if __name__ == '__main__':
    collect()
