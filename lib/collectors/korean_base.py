"""韓国メディアcollector共通基盤"""
import json, os, urllib.request
from datetime import datetime

SIGNALS = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'
os.makedirs(os.path.dirname(SIGNALS), exist_ok=True)

KPOP_KW = [
    'K-POP', 'KPOP', '케이팝', '아이돌', 'BTS', '방탄소년단', 'BLACKPINK', '블랙핑크',
    'aespa', '에스파', 'NewJeans', '뉴진스', 'SEVENTEEN', '세븐틴', 'TWICE', '트와이스',
    'IVE', '아이브', 'LE SSERAFIM', '르세라핌', 'ILLIT', '아일릿', 'ITZY', '있지',
    'Red Velvet', '레드벨벳', 'TXT', '투모로우바이투게더', 'Stray Kids', '스트레이키즈',
    'ENHYPEN', '엔하이픈', 'NCT', 'ATEEZ', '에이티즈', '(G)I-DLE', '여자아이들', 'TWS',
    'KISS OF LIFE', '키스오브라이프', '&TEAM', 'IU', '아이유', 'LISA', 'JENNIE', 'JISOO',
    '컴백', '신곡', '발매', '데뷔', '콘서트', '팬미팅', 'HYBE', 'SM', 'YG', 'JYP',
]

URGENT_KW = [
    '긴급', '속보', '공식', '발표', '사고', '논란', '열애',
    '결혼', '탈퇴', '해체', '컴백', '신곡',
]


def log(msg):
    print(f"[{datetime.now().isoformat()}] {msg}")


def fetch_html(url, timeout=20):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Linux) KPOPJournal/1.0',
        'Accept-Language': 'ko,ja;q=0.9,en;q=0.8',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')


def is_kpop_related(text):
    tl = text.lower()
    return [kw for kw in KPOP_KW if kw.lower() in tl]


def is_urgent(text):
    return any(kw in text for kw in URGENT_KW)


def save_signals(signals):
    with open(SIGNALS, 'a', encoding='utf-8') as f:
        for s in signals:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')
    log(f"saved {len(signals)} signals")


def make_signal(source_id, title, url, keywords, urgent=False, lang='ko', raw=None):
    return {
        'timestamp': datetime.now().isoformat(),
        'source': 'korean_media',
        'source_id': source_id,
        'keyword': keywords[0] if keywords else '',
        'title': title[:300],
        'url': url,
        'engagement_score': 3.0 if urgent else 2.0,
        'language': lang,
        'urgency': 'high' if urgent else 'normal',
        'raw_data': {'all_keywords': keywords, **(raw or {})},
    }
