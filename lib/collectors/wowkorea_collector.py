#!/usr/bin/env python3
"""Wow!Korea (wowkorea.jp) Japanese K-POP/Korean entertainment scraper"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, save_signals, log
from datetime import datetime

KPOP_KW_JP = [
    'K-POP', 'KPOP', 'BTS', 'BLACKPINK', 'aespa', 'NewJeans', 'SEVENTEEN', 'TWICE', 'IVE',
    'LE SSERAFIM', 'ILLIT', 'ITZY', 'Red Velvet', 'TXT', 'Stray Kids', 'ENHYPEN', 'NCT',
    'ATEEZ', 'TWS', 'KISS OF LIFE', 'IU', 'LISA', 'JENNIE', 'JISOO', 'HYBE', 'SM', 'YG', 'JYP',
]
URGENT_JP = ['速報', '緊急', '公式', '発表', '逮捕', '解散', '脱退', '訃報']


# 2026-08-17 根治: 収集先 /news/enter/ は **404**(404ページをHTTP 200で返すため
# fetch は成功扱いになり、エラーも出ないまま0件で無言死していた)。正しくは /news/。
# 記事URLも /news/read/<id> から /news/pickup/<id>.html に変わっていた。
# /news/ は総合ニュース面で、K-POP記事は10件中2件しかなかった。
# K-POP専用面(/news/kpop/)なら1ページで66記事取れるので、そちらを使う。
NEWS_URL = 'https://www.wowkorea.jp/news/kpop/'

# 見出しは <h2> 内のリンクテキストにある。同じ記事への画像リンクの alt にも
# 見出しが入るため、両方から拾って URL で一意化する。
_ANCHOR_TEXT_RE = re.compile(
    r'<a[^>]+href="(/news/pickup/\d+\.html)"[^>]*>([^<]{5,200})</a>', re.DOTALL)
_ANCHOR_ALT_RE = re.compile(
    r'<a[^>]+href="(/news/pickup/\d+\.html)"[^>]*>\s*<img[^>]+alt="([^"]{5,200})"',
    re.DOTALL)


def parse_articles(html: str) -> list:
    """HTML から (title, url) を1記事ずつ取り出す。取れなければ空を返す。

    404ページを掴んだ場合も空になる(壊れた値を下流に流さない)。
    """
    out = []
    seen = set()
    for pat in (_ANCHOR_TEXT_RE, _ANCHOR_ALT_RE):
        for m in pat.finditer(html or ''):
            path = m.group(1)
            title = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', m.group(2))).strip()
            url = 'https://www.wowkorea.jp' + path
            if url in seen or len(title) < 5:
                continue
            seen.add(url)
            out.append({'title': title, 'url': url})
    return out


def collect():
    signals = []
    try:
        html = fetch_html(NEWS_URL)
    except Exception as e:
        log(f"Wowkorea fetch error: {e}")
        return 0

    articles = parse_articles(html)
    if not articles:
        # 構造変更/404を検知できるようにする(旧実装は0件でも無言だった)
        log("Wow!Korea: 0 (記事を抽出できず — URL変更/HTML構造変更の可能性)")
        save_signals([], source_id='wowkorea')
        return 0
    for a in articles:
        title, url = a['title'], a['url']
        matched = [k for k in KPOP_KW_JP if k.lower() in title.lower()]
        if not matched:
            continue
        urgent = any(k in title for k in URGENT_JP)
        signals.append({
            'timestamp': datetime.now().isoformat(),
            'source': 'japanese_media',
            'source_id': 'wowkorea',
            'keyword': matched[0],
            'title': title[:300],
            'url': url,
            'engagement_score': 3.0 if urgent else 2.0,
            'language': 'ja',
            'urgency': 'high' if urgent else 'normal',
            'raw_data': {'all_keywords': matched},
        })
        if len(signals) >= 20:
            break
    save_signals(signals, source_id='wowkorea')
    log(f"Wow!Korea: {len(signals)}")
    return len(signals)


if __name__ == '__main__':
    collect()
