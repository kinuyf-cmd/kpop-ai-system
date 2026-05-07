"""韓国メディアcollector共通基盤"""
import json, os, urllib.request
from datetime import datetime, timedelta

SIGNALS = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'
os.makedirs(os.path.dirname(SIGNALS), exist_ok=True)

KPOP_KW = [
    'K-POP', 'KPOP', '케이팝', '아이돌', 'BTS', '방탄소년단', 'BLACKPINK', '블랙핑크',
    'aespa', '에스파', 'NewJeans', '뉴진스', 'SEVENTEEN', '세븐틴', 'TWICE', '트와이스',
    'IVE', '아이브', 'LE SSERAFIM', '르세라핌', 'ILLIT', '아일릿', 'ITZY', '있지',
    '방탄소년단', 'BABYMONSTER', '베이비몬스터', 'RIIZE', '라이즈', 'NMIXX', '엔믹스',
    'BOYNEXTDOOR', '보이넥스트도어',
    'ZEROBASEONE', '제로베이스원', 'I.O.I', 'Wanna One', '워너원', 'FIFTY FIFTY', '피프티피프티',
    'Red Velvet', '레드벨벳', 'TXT', '투모로우바이투게더', 'Stray Kids', '스트레이키즈',
    'ENHYPEN', '엔하이픈', 'NCT', 'ATEEZ', '에이티즈',
    '(G)I-DLE', '여자아이들', '(여자)아이들', 'TWS', '티더블유에스',
    'KISS OF LIFE', '키스오브라이프', '&TEAM', '앤팀', 'IU', '아이유', 'LISA', 'JENNIE', 'JISOO', 'ROSÉ', '로제',
    'THE BOYZ', '더보이즈', 'TREASURE', '트레저', 'KEP1ER', '케플러',
    'STAYC', '스테이씨', 'WJSN', '우주소녀', 'VIVIZ', '비비지', 'Billlie', '빌리',
    'Weeekly', '위클리', 'Kep1er', 'Cravity', '크래비티', 'P1Harmony', '피원하모니',
    'TEMPEST', '템페스트', 'ATBO', 'XG', 'EVNNE', 'EL7Z UP', '엘즈업',
    'monsta x', '몬스타엑스', '셔누', '형원', '민혁',
    '컴백', '신곡', '발매', '데뷔', '콘서트', '팬미팅', 'HYBE', 'SM', 'YG', 'JYP',
    # 韓国語一般K-POPキーワード（アーティスト名以外）
    '걸그룹', '보이그룹', '아이돌', '음방', '엠카', '인기가요', '뮤뱅', '엠넷',
    '가수', '솔로곡', '타이틀곡', '앨범', '음원', '차트', '1위', '시구',
    # 追加アーティスト名（韓国語）
    '지드래곤', '에릭남', '소녀시대', '빅뱅', '엑소', '동방신기',
    '슈퍼주니어', '마마무', '오마이걸', '에이핑크', '보아',
    '아이오아이', '카라', '씨스타', '프로미스나인', 'fromis_9',
    '청하', '효린', '솔라', '화사', '휘인', '문별', '태연', '제시',
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


# 事務所名のみでのクラスタリングは誤マッチの原因になるため、
# アーティスト名と区別して扱う
AGENCY_ONLY_KW = {'SM', 'YG', 'JYP', 'HYBE'}


def is_kpop_related(text):
    import re as _re
    tl = text.lower()
    # 韓国語の部分一致を防ぐ: 「아이유」が「(여자)아이들」にマッチしないように
    # 長いキーワードから先にマッチさせ、マッチ済み部分は除外
    # まず完全一致度の高い順（長い順）にソート
    sorted_kw = sorted(
        [kw for kw in KPOP_KW if kw not in AGENCY_ONLY_KW],
        key=lambda k: len(k), reverse=True
    )

    artist_matches = []
    _matched_text = tl
    for kw in sorted_kw:
        kw_lower = kw.lower()
        if kw_lower not in _matched_text:
            continue
        # 韓国語キーワード: 前後の文字で部分一致を除外
        # 例: 「아이유」が「아이들」にマッチしないように
        if _re.search(r'[\uac00-\ud7af]', kw):  # 韓国語を含むキーワード
            # 前後にハングルが続く場合は部分一致の可能性→スキップ
            pattern = _re.escape(kw_lower)
            m = _re.search(pattern, _matched_text)
            if m:
                start, end = m.start(), m.end()
                before = _matched_text[start-1] if start > 0 else ' '
                after = _matched_text[end] if end < len(_matched_text) else ' '
                # 前後がハングルなら部分一致の可能性（例: 아이유 in 아이들）
                if _re.match(r'[\uac00-\ud7af]', before) or _re.match(r'[\uac00-\ud7af]', after):
                    continue
        artist_matches.append(kw)
        # マッチした部分を除去して重複マッチ防止
        _matched_text = _matched_text.replace(kw_lower, ' ', 1)

    if artist_matches:
        return artist_matches
    # アーティスト名がなく事務所名のみマッチした場合も返す
    agency_matches = [kw for kw in KPOP_KW if kw in AGENCY_ONLY_KW and kw.lower() in tl]
    return agency_matches


def is_urgent(text):
    return any(kw in text for kw in URGENT_KW)


def trigger_breaking_if_urgent(new_signals):
    """urgency=high検出時に breaking_news_detector を非同期起動"""
    urgent = [s for s in new_signals if s.get('urgency') == 'high']
    if not urgent:
        return
    try:
        import subprocess
        subprocess.Popen(
            ['python3', '/home/aiuser/kpop-ai-system/pipeline/breaking_news_detector.py'],
            stdout=open('/home/aiuser/kpop-ai-system/logs/breaking_trigger.log', 'a'),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log(f"URGENT detected ({len(urgent)}) -> breaking_news_detector fired")
    except Exception as e:
        log(f"trigger fail: {e}")


def save_signals(signals):
    # 直近24hの既存URLで重複除去（同じ記事の再収集を防止）
    existing_urls = set()
    try:
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        with open(SIGNALS, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get('timestamp', '') > cutoff:
                        existing_urls.add(d.get('url', ''))
                except Exception:
                    pass
    except FileNotFoundError:
        pass

    new_signals = [s for s in signals if s.get('url', '') not in existing_urls]
    skipped = len(signals) - len(new_signals)

    with open(SIGNALS, 'a', encoding='utf-8') as f:
        for s in new_signals:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')
    if skipped:
        log(f"saved {len(new_signals)} signals (skipped {skipped} dups)")
    else:
        log(f"saved {len(new_signals)} signals")
    trigger_breaking_if_urgent(new_signals)


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
