"""韓国メディアcollector共通基盤"""
import json, os, re, urllib.request
from datetime import datetime, timedelta


def clean_title(raw: str) -> str:
    """韓国メディア記事タイトルから HTML / 連結タイトル / 記者署名を除去

    複数 collector が同種のクリーニングを重複実装していたのを共通化 (2026-05-11)。
    新規collector追加時は必ずこの関数経由で title を整形すること。

    処理:
      1. HTML タグ除去 (<...>)
      2. 空白 (改行/tab) を1スペースに正規化
      3. 記者署名「○○○ 기자」「MM.DD HH:MM」以降をカット
      4. 完結語 (했다/됐다/공개/발매/컴백 等) で隣接記事タイトルと分離
      5. 80字超は句読点で切断
    """
    if not raw:
        return ''
    # 1. HTML タグ除去
    title = re.sub(r'<[^>]+>', '', raw)
    # 2. 連続改行や複数tab列(隣接記事タイトルの境界)で先頭部分のみ採用
    # newsen/topstarnews 等は HTML strip 後に 「title1\n\t\t\t\ntitle2」形式で
    # 隣接記事タイトルが連結する。空白正規化前に分離する必要あり
    boundary = re.search(r'\n\s*\n|\t{3,}', title)
    if boundary and boundary.start() >= 10:
        title = title[:boundary.start()]
    # 3. 空白正規化
    title = re.sub(r'\s+', ' ', title).strip()
    # 3. 記者署名 / 日付以降カット
    title = re.split(r'\s*\d{2}\.\d{2}\s*\d{2}:\d{2}', title, 1)[0]
    title = re.split(r'\s+\S+\s*기자(\s|$)', title, 1)[0]
    # 4. 完結語で次記事分離
    m_split = re.split(
        r'(?<=했다)|(?<=됐다)|(?<=했다고)|(?<=공개)|(?<=발매)|(?<=출연)|(?<=결정)|(?<=컴백)|(?<=합류)(?=[A-Z]|[가-힯])',
        title, maxsplit=1
    )
    if len(m_split) > 1 and len(m_split[0]) >= 10:
        title = m_split[0].strip()
    # 5. 80字超は句読点で切断
    if len(title) > 80:
        for sep in ['…', '!', '?', '。', '．']:
            if sep in title[:80]:
                title = title.split(sep, 1)[0] + sep
                break
        else:
            title = title[:80]
    return title.strip()


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
    # 2026-05-10: 個別solo artists追加 (18881事案 — チョ・スンヨン未登録で誤分類)
    'WOODZ', '우즈', '조승연', 'チョ・スンヨン', 'チョスンヨン',
    'カン・ダニエル', '강다니엘', 'KANG DANIEL', 'カンダニエル',
    'BIBI', '비비', 'YOONA', '윤아', 'TAEYANG', '태양',
    # フルネーム形 (TXT/CATS EYE等の検出漏れ対策)
    'TOMORROW X TOGETHER', 'TOMORROW_X_TOGETHER',
    "CAT'S EYE", "CAT’S EYE", 'CATS EYE', 'KATSEYE',  # U+2019(’)対応
    'FANOMENON', 'WHIB',
    # 2026-05-10: 速報シグナル取りこぼし対策
    '씨야', 'See Ya', 'SEE YA',  # ガールズグループ復帰
    '코르티스', 'CORTIS',  # BIGHIT新人group
    'tripleS', '트리플에스',
    'PLAVE', '플레이브', 'CRAVITY', '크래비티',
    'VERIVERY', '베리베리',
    '양준일', 'Yang Joon Il',  # 名物SOLO singer
    '아이즈원', 'IZ*ONE', 'IZONE',
    '宇宙少女', 'Cosmic Girls',
]

URGENT_KW = [
    '긴급', '속보', '공식', '발표', '사고', '논란', '열애',
    '결혼', '탈퇴', '해체', '컴백', '신곡',
]


def log(msg):
    print(f"[{datetime.now().isoformat()}] {msg}")


# ─── コレクタの「無言で0件死」検知 (2026-08-17) ─────────────────────────────
# koreaherald がサイト構造変更で正規表現に1件もマッチせず、**0件のまま無言で
# 死んでいた**(38日どころか気付いた時点で何日続いていたか不明)。0件でもログに
# 何も出さないため誰も気付けなかった。点検すると同じ状態が更に2件あった
# (wowkorea / starnews)。偶然見つけただけで、仕組みが無ければ次も気付けない。
#
# 判定: 「今回0件」は異常とは言えない(深夜で新着なし・全部重複など正常な0件がある)。
# **連続して0件が続くこと**を異常とする。
COLLECT_HEALTH = '/home/aiuser/kpop-ai-system/logs/collector_health.jsonl'
ZERO_ALERT_THRESHOLD = 5   # これ以上連続0件なら壊れていると判断


def record_collect_result(source_id, count):
    """コレクタ1回の収集件数を記録する。save_signals から自動で呼ばれる。"""
    if not source_id:
        return
    try:
        os.makedirs(os.path.dirname(COLLECT_HEALTH), exist_ok=True)
        with open(COLLECT_HEALTH, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'ts': datetime.now().isoformat(),
                                'source_id': source_id,
                                'count': int(count)}, ensure_ascii=False) + '\n')
    except OSError:
        pass


def consecutive_zero_count(source_id):
    """そのコレクタが直近何回連続で0件だったか。1件でも取れた時点でリセット。"""
    try:
        with open(COLLECT_HEALTH, encoding='utf-8') as f:
            lines = f.read().splitlines()
    except (FileNotFoundError, OSError):
        return 0
    n = 0
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue      # 壊れた行はスキップ(記録の破損で検知を止めない)
        if d.get('source_id') != source_id:
            continue
        if int(d.get('count', 0) or 0) > 0:
            break         # 成功でリセット
        n += 1
    return n


# 2026-05-15: Mozilla/5.0 (Linux) KPOPJournal/1.0 を bot 識別する韓国 media が
# 増え、starnews / mnet で 403 を観測。10+ collector が共通利用するため、
# 実 Chrome UA に統一して 403 を回収する (Accept-Language は維持)。
# 識別は From ヘッダで透明性を確保。
_BROWSER_UA = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)


def fetch_html(url, timeout=20):
    req = urllib.request.Request(url, headers={
        'User-Agent': _BROWSER_UA,
        'Accept-Language': 'ko,ja;q=0.9,en;q=0.8',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'From': 'crawler@kpopjournal.tokyo',
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')


# 事務所名のみでのクラスタリングは誤マッチの原因になるため、
# アーティスト名と区別して扱う
AGENCY_ONLY_KW = {'SM', 'YG', 'JYP', 'HYBE'}


# 「アーティスト名ではない」一般K-POPキーワード（デビュー/発売/컴백等）。
# 速報判定の go/no-go には使うが arts[0] には選ばれてはいけない（artist field汚染防止）
# 2026-05-07: queueに데뷔/발매/SM等が"artist"として混入していた問題への対処
GENERIC_EVENT_KW = {
    'K-POP', 'KPOP', '케이팝', '아이돌',
    '컴백', '신곡', '발매', '데뷔', '콘서트', '팬미팅',
    '걸그룹', '보이그룹', '음방', '엠카', '인기가요', '뮤뱅', '엠넷',
    '가수', '솔로곡', '타이틀곡', '앨범', '음원', '차트', '1위', '시구',
}


def is_kpop_related(text):
    """K-POP関連シグナルかつアーティスト名を抽出。
    返却順序保証: 固有アーティスト名 → ジェネリック語 → 事務所名
    breaking_news_detector の arts[0] が必ず固有名詞優先で選ばれる

    マッチ規則 (2026-05-07):
      - ハングルKW: substring + 前文字hangul排除 (後ろは助詞許容)
      - ASCII KW: 単語境界 \b で囲む (live → IVE / sam smith → SM 等の誤検知防止)
    """
    import re as _re
    tl = text.lower()
    sorted_kw = sorted(
        [kw for kw in KPOP_KW if kw not in AGENCY_ONLY_KW],
        key=lambda k: len(k), reverse=True
    )

    proper_artist_matches = []
    generic_matches = []
    _matched_text = tl
    for kw in sorted_kw:
        kw_lower = kw.lower()
        has_hangul = bool(_re.search(r'[\uac00-\ud7af]', kw))
        if has_hangul:
            # ハングルKW: substring検出 + 直前ハングルなら部分一致疑いで却下
            # 直後はハングル許容 (助詞만/는/이/가/의/에 等を弾かないため)
            if kw_lower not in _matched_text:
                continue
            m = _re.search(_re.escape(kw_lower), _matched_text)
            if m and m.start() > 0:
                before = _matched_text[m.start()-1]
                if _re.match(r'[\uac00-\ud7af]', before):
                    continue
        else:
            # ASCII KW: ASCII単語境界必須 (\bがCJK文字を語と認識する問題回避)
            # BTS新曲 / (G)I-DLE Tour なども正しくマッチ
            found = False
            for m in _re.finditer(_re.escape(kw_lower), _matched_text):
                s, e = m.start(), m.end()
                before_ok = s == 0 or not (_matched_text[s-1].isascii() and _matched_text[s-1].isalnum())
                after_ok = e == len(_matched_text) or not (_matched_text[e].isascii() and _matched_text[e].isalnum())
                if before_ok and after_ok:
                    found = True
                    break
            if not found:
                continue
        if kw in GENERIC_EVENT_KW:
            generic_matches.append(kw)
        else:
            proper_artist_matches.append(kw)
        _matched_text = _matched_text.replace(kw_lower, ' ', 1)

    if proper_artist_matches or generic_matches:
        # 2026-05-10: 主語優先 — タイトル内で先に出現するartistを返す
        # (元: 長さDESC順 → 18881事案で「BLACKPINK ジス…BOYNEXTDOOR…」の先頭BOYNEXTDOORが負けてた)
        proper_artist_matches.sort(key=lambda kw: tl.find(kw.lower()))
        return proper_artist_matches + generic_matches
    # AGENCY_ONLY: ASCII略号は単語境界必須 ("Sam Smith"の"sm"誤検知防止)
    agency_matches = []
    for kw in KPOP_KW:
        if kw not in AGENCY_ONLY_KW:
            continue
        # ASCII単語境界 (Sam Smith の sm 誤検知防止)
        for m in _re.finditer(_re.escape(kw.lower()), tl):
            s, e = m.start(), m.end()
            before_ok = s == 0 or not (tl[s-1].isascii() and tl[s-1].isalnum())
            after_ok = e == len(tl) or not (tl[e].isascii() and tl[e].isalnum())
            if before_ok and after_ok:
                agency_matches.append(kw)
                break
    return agency_matches


def is_urgent(text):
    return any(kw in text for kw in URGENT_KW)


def trigger_breaking_if_urgent(new_signals):
    """urgency=high検出時に breaking_news_detector を非同期起動。

    Day11 ストリーム3: 本流から korean_base + soompi_collector のみ移植した段階。
    速報側(pipeline/breaking_news_detector.py = ストリーム4)は WP認証平文を含む
    publisher 一式に依存するため未移植(Day12 で env化込みで対応)。
    detector が無い間は urgent signal を検出しても「保留」ログのみ残し、
    存在しないスクリプトの subprocess 起動は試みない(誤動作・ログ汚染防止)。
    """
    urgent = [s for s in new_signals if s.get('urgency') == 'high']
    if not urgent:
        return
    detector = '/home/aiuser/kpop-ai-system/pipeline/breaking_news_detector.py'
    if not os.path.exists(detector):
        log(f"URGENT detected ({len(urgent)}) -> breaking_news_detector 未移植のため保留(Day12)")
        return
    try:
        import subprocess
        # detector は anthropic/Pillow/numpy 等(P1-P6 移植)を要求するため venv_kpi の
        # python で起動する。bare 'python3'(system)は anthropic 不在で
        # ModuleNotFoundError で即死する(2026-05-23 移植配線)。venv が無ければ
        # フォールバックで python3。
        _venv_py = '/home/aiuser/kpop-ai-system/venv_kpi/bin/python'
        _py = _venv_py if os.path.exists(_venv_py) else 'python3'
        subprocess.Popen(
            [_py, detector],
            stdout=open('/home/aiuser/kpop-ai-system/logs/breaking_trigger.log', 'a'),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log(f"URGENT detected ({len(urgent)}) -> breaking_news_detector fired")
    except Exception as e:
        log(f"trigger fail: {e}")


def save_signals(signals, source_id=None):
    """収集結果を trend_signals.jsonl に追記する。

    source_id は健全性記録用。省略時は signals から拾う(0件だと拾えないため、
    **0件になりうるコレクタは明示的に渡すこと**。渡さないと無言死を検知できない)。
    """
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

    # 健全性記録: 収集**候補**の件数(重複除去前)で判定する。重複除去後の0件は
    # 「同じ記事を再取得しただけ」で正常だが、除去前が0件なら抽出が壊れている。
    sid = source_id or (signals[0].get('source_id') if signals else None)
    if sid:
        record_collect_result(sid, len(signals))
        zeros = consecutive_zero_count(sid)
        if zeros >= ZERO_ALERT_THRESHOLD:
            log(f"⚠️ {sid}: {zeros}回連続で0件 — 抽出が壊れている可能性"
                f"(HTML構造変更/403等)。tools/check_collector_health.py を確認")

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
