#!/usr/bin/env python3
"""Google Trends collector

  - 主力: Daily Trending RSS (https://trends.google.com/trending/rss?geo=JP)
    レート制限の対象外。K-POPキーワードフィルタで関連トレンドのみ取得
  - 補助: pytrends related_queries (rising) — 動けば取得、429時は早期終了
"""
import json, os, re, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timedelta

OUT = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'

ARTISTS = [
    'BTS', 'BLACKPINK', 'NewJeans', 'aespa', 'SEVENTEEN',
    'TWICE', 'IVE', 'LE SSERAFIM', 'ILLIT', 'Stray Kids',
]

# K-POP関連トレンド判定用の広めのキーワード集合
KPOP_KEYWORDS = [
    *ARTISTS,
    'TXT', 'ENHYPEN', 'ATEEZ', 'ITZY', 'NCT', 'NMIXX', 'RIIZE',
    'TREASURE', 'BABYMONSTER', 'EXO', 'MONSTA X', 'GOT7', 'ASTRO',
    'DAY6', '(G)I-DLE', 'SHINee', 'Red Velvet', 'BIGBANG', 'TWS',
    'K-POP', 'KPOP', 'K-pop', 'Kポップ', 'ケーポップ', '韓流',
    'カムバック', 'コムバック', 'comeback', 'デビュー', '新曲', 'MV',
]

DAILY_RSS_URL = 'https://trends.google.com/trending/rss?geo=JP'
_RSS_NS = {'ht': 'https://trends.google.com/trending/rss'}


def _kpop_match(text):
    """K-POP関連キーワードを検出。短いASCII名は単語境界マッチで誤マッチ回避"""
    text_lower = text.lower()
    matched = []
    for k in KPOP_KEYWORDS:
        kl = k.lower()
        if k.isascii() and len(k) <= 5:
            if re.search(r'(?:^|[^a-z0-9])' + re.escape(kl) + r'(?:[^a-z0-9]|$)', text_lower):
                matched.append(k)
        else:
            if kl in text_lower:
                matched.append(k)
    return matched


def collect_daily_trends_rss():
    """Daily Trending RSS から K-POP 関連のみ抽出"""
    try:
        req = urllib.request.Request(DAILY_RSS_URL, headers={'User-Agent': 'Mozilla/5.0'})
        xml_bytes = urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:
        print(f'  daily_rss fetch error: {e}')
        return []

    try:
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        print(f'  daily_rss parse error: {e}')
        return []

    signals = []
    for it in root.findall('.//item'):
        title = (it.findtext('title') or '').strip()
        if not title:
            continue
        traffic = (it.findtext('ht:approx_traffic', '', _RSS_NS) or '').strip()
        # ニュース見出しもK-POP判定材料に含める
        news_blob = ' '.join(
            (n.findtext('ht:news_item_title', '', _RSS_NS) or '')
            for n in it.findall('ht:news_item', _RSS_NS)
        )
        haystack = f'{title} {news_blob}'
        matched = _kpop_match(haystack)
        if not matched:
            continue
        # traffic "200+" 等から数値抽出
        traffic_num = 0
        m = re.search(r'(\d+)', traffic)
        if m:
            traffic_num = int(m.group(1))
        # engagement_score: 100+→1.0, 1000+→2.0, 10000+→3.0 程度
        score = 1.0
        if traffic_num >= 1000:
            score = 2.0
        if traffic_num >= 10000:
            score = 3.0
        signals.append({
            'timestamp': datetime.now().isoformat(),
            'source': 'gtrends',
            'source_id': 'google_trending_rss_jp',
            'keyword': matched[0],
            'title': title[:200],
            'url': f'https://trends.google.com/trends/explore?q={urllib.parse.quote(title)}&geo=JP',
            'engagement_score': score,
            'language': 'ja',
            'raw_data': {
                'all_keywords': matched,
                'approx_traffic': traffic,
                'news_sample': news_blob[:300],
            },
        })

    print(f'  daily_rss: {len(signals)} K-POP関連トレンド検出')
    return signals


def collect():
    # 主力: Daily Trending RSS（レート制限なし）
    print('[gtrends] daily_rss')
    rss_signals = collect_daily_trends_rss()

    # 補助: pytrends related_queries（429時は早期終了）
    print('[gtrends] pytrends related_queries')
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("  pytrends not installed → RSSのみで継続")
        return _save_with_dedup(rss_signals)

    # pytrends 4.9.2 は urllib3<2 の method_whitelist を呼ぶため、
    # urllib3 v2 環境では Retry.__init__ で TypeError になる。
    # pytrends.request が module top で from ... import Retry しているので、
    # 同モジュールの Retry シンボル自体を alias 受容版に差し替える。
    try:
        import pytrends.request as _pr
        _OrigRetry = _pr.Retry
        if not getattr(_OrigRetry, '_kpj_compat_patched', False):
            class _CompatRetry(_OrigRetry):
                def __init__(self, *args, **kwargs):
                    if 'method_whitelist' in kwargs:
                        kwargs['allowed_methods'] = kwargs.pop('method_whitelist')
                    super().__init__(*args, **kwargs)
            _CompatRetry._kpj_compat_patched = True
            _pr.Retry = _CompatRetry
    except Exception as e:
        print(f"  pytrends Retry patch skip: {e}")

    try:
        pytrends = TrendReq(
            hl='ja-JP', tz=540, timeout=(10, 25),
            retries=3, backoff_factor=2.0,
        )
    except Exception as e:
        print(f"  pytrends init error: {e} → RSSのみで継続")
        return _save_with_dedup(rss_signals)

    import time, random
    # 4回/日実行 × 2アーティスト/回 = 8アーティスト/日でローテーション
    # 実行時刻ベースでオフセットを決め、毎回異なるアーティストを取得
    _hour = datetime.now().hour
    _offset = {8: 0, 12: 2, 16: 4, 22: 6}.get(_hour, random.randint(0, len(ARTISTS)-2))
    _batch = ARTISTS[_offset:_offset+2]

    signals = []
    rate_limited = 0
    for artist in _batch:
        try:
            pytrends.build_payload([artist], timeframe='now 7-d', geo='JP')
            related = pytrends.related_queries()
            if not related or artist not in related:
                time.sleep(60)
                continue
            rising = related[artist].get('rising')
            if rising is None or rising.empty:
                time.sleep(60)
                continue
            for _, row in rising.head(5).iterrows():
                signals.append({
                    'timestamp': datetime.now().isoformat(),
                    'source': 'gtrends',
                    'source_id': 'google_trends_jp',
                    'keyword': artist,
                    'title': f"{artist} {row['query']}",
                    'url': f"https://trends.google.co.jp/trends/explore?q={artist}",
                    'engagement_score': float(min(row.get('value', 100), 500)) / 100,
                    'language': 'ja',
                    'raw_data': {
                        'rising_query': row['query'],
                        'value': int(row.get('value', 0)),
                    },
                })
        except Exception as e:
            msg = str(e)
            print(f"gtrends error for {artist}: {msg}")
            if '429' in msg:
                # 429が出たら以降のアーティストは諦めて早期終了
                # （連打すると更にブロックされる）
                rate_limited += 1
                if rate_limited >= 1:
                    print(f"  → 429検出、本実行は中断（次回のcron実行まで待機）")
                    break
        # ベース90秒 + ジッター30秒で429回避を強化
        time.sleep(90 + random.randint(0, 30))

    return _save_with_dedup(rss_signals + signals)


def _dedup_key(s):
    """RSS/pytrends 両対応のユニークキー"""
    rd = s.get('raw_data') or {}
    rising = rd.get('rising_query', '')
    if rising:
        return f"py:{s.get('keyword', '')}_{rising}"
    return f"rss:{s.get('source_id','')}|{s.get('title','')[:120]}"


def _save_with_dedup(signals):
    """直近24hのgtrends signals と重複排除して保存"""
    existing_keys = set()
    try:
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        with open(OUT, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get('timestamp', '') > cutoff and d.get('source') == 'gtrends':
                        existing_keys.add(_dedup_key(d))
                except Exception:
                    pass
    except FileNotFoundError:
        pass

    new_signals = [s for s in signals if _dedup_key(s) not in existing_keys]

    with open(OUT, 'a', encoding='utf-8') as f:
        for s in new_signals:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')

    print(f"Google Trends: {len(new_signals)} new signals (skipped {len(signals) - len(new_signals)} dups)")
    return len(new_signals)


if __name__ == '__main__':
    collect()
