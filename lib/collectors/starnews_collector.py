#!/usr/bin/env python3
"""StarNews Korea (starnewskorea.com) — 韓国芸能専門メディア（英語版）"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import fetch_html, save_signals, log
from datetime import datetime

KPOP_KW = [
    'BTS', 'BLACKPINK', 'aespa', 'NewJeans', 'SEVENTEEN', 'TWICE', 'IVE',
    'LE SSERAFIM', 'ILLIT', 'ITZY', 'Red Velvet', 'TXT', 'Stray Kids', 'ENHYPEN', 'NCT',
    'ATEEZ', 'EXO', 'RIIZE', 'KATSEYE', 'BABYMONSTER', 'GOT7', 'MAMAMOO', 'NMIXX',
    'HYBE', 'SM', 'YG', 'JYP', 'K-pop', 'idol', 'comeback', 'debut', 'album',
]
URGENT_KW = ['breaking', 'confirmed', 'exclusive', 'wins', 'dating', 'married', 'arrested']

# 2026-08-17 調査結果(修理せず保留と判断):
#   コレクタ健全性チェックで0件死を検知。原因を切り分けたところ、fetch も
#   正規表現マッチ(17件)も成功しているが、**Naver検索が意図した媒体を返していない**。
#   取れるのは stardailynews / 톱스타뉴스 のトロット歌手投票記事(しかも3ヶ月前)で、
#   starnews の記事ではない。K-POPキーワードに一致しないため結果0件になる。
#   → 検索クエリ経由という設計自体が破綻しており、パターン修正では直らない。
#   直すなら starnews を直接叩く実装が必要(Next.jsでスクレイピング困難というのが
#   検索経由にした元の理由)。他12コレクタで直近48hに362シグナル確保できており
#   ネタは足りているため、労力対効果で保留する。
#   再開するなら: RSS/APIの有無を先に確認すること。HTMLスクレイピングは同じ轍。
SECTIONS = [
    # StarNewsはNext.jsでスクレイピング困難 → Naver検索経由
    ('starnews', 'https://search.naver.com/search.naver?where=news&query=%EC%8A%A4%ED%83%80%EB%89%B4%EC%8A%A4+%EC%BC%80%EC%9D%B4%ED%8C%9D'),
]


def collect():
    signals = []
    for source_id, url in SECTIONS:
        try:
            html = fetch_html(url)
        except Exception as e:
            log(f"{source_id} fetch error: {e}")
            continue

        patterns = [
            re.compile(r'href="(https?://[^"]*(?:starnews|star\.mt)[^"]+)"[^>]*>((?:<[^>]*>|[^<]){5,200})</a>', re.DOTALL),
            re.compile(r'href="(https?://[^"]*news[^"]+\d{8,}[^"]*)"[^>]*>((?:<[^>]*>|[^<]){5,100})</a>', re.DOTALL),
        ]
        seen = set()
        for pat in patterns:
            for m in pat.finditer(html):
                link, title = m.group(1), m.group(2).strip()
                if link in seen or len(title) < 10:
                    continue
                seen.add(link)
                full_url = link if link.startswith('http') else 'https://www.starnewskorea.com' + link
                matched = [k for k in KPOP_KW if k.lower() in title.lower()]
                if not matched:
                    continue
                urgent = any(k.lower() in title.lower() for k in URGENT_KW)
                signals.append({
                    'timestamp': datetime.now().isoformat(),
                    'source': 'korean_media',
                    'source_id': 'starnews',
                    'keyword': matched[0],
                    'title': title[:300],
                    'url': full_url,
                    'engagement_score': 3.5 if urgent else 2.0,
                    'language': 'en',
                    'urgency': 'high' if urgent else 'normal',
                    'raw_data': {'all_keywords': matched},
                })
    save_signals(signals[:30], source_id='starnews')
    log(f"StarNews: {len(signals[:30])}")
    return len(signals[:30])


if __name__ == '__main__':
    collect()
