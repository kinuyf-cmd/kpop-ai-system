#!/usr/bin/env python3
"""KCON JAPAN 2026 公式サイト・SNS監視コレクター

5/8-10の期間中、5分間隔でKCON関連情報を収集しtrend_signalsに注入。
breaking_news_detectorがurgency=highとして拾い、即時記事化する。

cron: */5 * 8,9,10 5 * (5/8-10の5分間隔)
"""
import sys
import os
import json
import re
import time
import urllib.request
import urllib.parse

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv('/home/aiuser/kpop-ai-system/.env')

JST = timezone(timedelta(hours=9))
BASE = '/home/aiuser/kpop-ai-system'
SIGNALS_PATH = os.path.join(BASE, 'data/trend_signals.jsonl')
STATE_PATH = os.path.join(BASE, 'data/kcon_monitor_state.json')
LOG_PATH = os.path.join(BASE, 'logs/kcon_monitor.log')

# KCON関連キーワード (タイトル/本文にこれらが含まれればシグナル生成)
KCON_KEYWORDS = [
    'KCON 2026', 'KCON JAPAN', 'KCON Day', '#KCONJAPAN', '#KCON2026',
    'KCON lineup', 'KCON setlist', 'KCON stage', 'KCON concert',
    'KCON セトリ', 'KCON 出演', 'KCON ステージ', 'KCON 速報',
    'KCON 幕張', '幕張メッセ KCON',
]

# 監視ソース
SOURCES = [
    {
        'id': 'soompi_kcon',
        'name': 'Soompi',
        'url': 'https://www.soompi.com/feed',
        'type': 'rss',
    },
    {
        'id': 'allkpop_kcon',
        'name': 'allkpop',
        'url': 'https://feeds.feedburner.com/allkpop',
        'type': 'rss',
    },
]

# K-POPアーティスト名 (シグナルのkeyword抽出用)
ARTISTS = [
    'BTS', 'BLACKPINK', 'aespa', 'NewJeans', 'SEVENTEEN', 'TWICE', 'IVE',
    'LE SSERAFIM', 'Stray Kids', 'ENHYPEN', 'TXT', 'ITZY', 'NMIXX',
    'KATSEYE', 'BABYMONSTER', 'ATEEZ', 'NCT', 'RIIZE', 'ILLIT',
    'TREASURE', 'fromis_9', 'GOT7', 'DAY6', 'PLAVE', 'TWS', 'BOYNEXTDOOR',
    'KISS OF LIFE', 'tripleS', 'Kep1er', 'ZEROBASEONE',
]


def _fetch(url):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'KPOPJournal-KCONMonitor/1.0'
        })
        return urllib.request.urlopen(req, timeout=15).read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"  fetch err: {e}")
        return ''


def _load_state():
    try:
        return json.loads(open(STATE_PATH, encoding='utf-8').read())
    except Exception:
        return {'seen_urls': []}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _is_kcon_related(text):
    """テキストがKCON関連かどうか判定"""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in KCON_KEYWORDS)


def _extract_artist(text):
    """テキストからK-POPアーティスト名を抽出"""
    for artist in ARTISTS:
        if artist.lower() in text.lower():
            return artist
    return 'KCON'


def parse_rss(html, source_id, state):
    """RSSフィードからKCON関連アイテムを抽出"""
    signals = []
    seen = set(state.get('seen_urls', []))

    items = re.findall(
        r'<item>\s*<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>\s*<link>(.*?)</link>',
        html, re.DOTALL
    )

    for title_raw, link in items:
        title = re.sub(r'<[^>]+>', '', title_raw).strip()
        link = link.strip()

        if link in seen:
            continue
        if not _is_kcon_related(title):
            continue

        artist = _extract_artist(title)
        signals.append({
            'timestamp': datetime.now(JST).isoformat(),
            'source': 'kcon_monitor',
            'source_id': source_id,
            'keyword': artist,
            'title': title[:300],
            'url': link,
            'engagement_score': 15.0,  # KCON関連は高優先
            'language': 'en',
            'urgency': 'high',  # breaking_news_detectorが即座に拾う
            'raw_data': {
                'event': 'KCON JAPAN 2026',
                'article_type': 'kcon_breaking',
            },
        })
        seen.add(link)

    state['seen_urls'] = list(seen)[-200:]  # 直近200件まで保持
    return signals


def inject_signals(signals):
    """trend_signals.jsonlに追加"""
    if not signals:
        return
    # 重複除去 (korean_baseと同じロジック)
    existing_urls = set()
    try:
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        with open(SIGNALS_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get('timestamp', '') > cutoff:
                        existing_urls.add(d.get('url', ''))
                except Exception:
                    pass
    except FileNotFoundError:
        pass

    new = [s for s in signals if s.get('url', '') not in existing_urls]
    with open(SIGNALS_PATH, 'a', encoding='utf-8') as f:
        for s in new:
            f.write(json.dumps(s, ensure_ascii=False) + '\n')

    return len(new)


def main():
    now = datetime.now(JST)
    print(f"=== kcon_monitor: {now.strftime('%Y-%m-%d %H:%M')} ===")

    state = _load_state()
    all_signals = []

    for src in SOURCES:
        html = _fetch(src['url'])
        if not html:
            continue
        signals = parse_rss(html, src['id'], state)
        all_signals.extend(signals)
        if signals:
            print(f"  {src['name']}: {len(signals)}件のKCONシグナル")
        time.sleep(1)

    injected = inject_signals(all_signals)
    _save_state(state)

    print(f"  合計: {len(all_signals)}件検出 / {injected}件注入")

    # urgency=highのシグナルがあれば即座にbreaking_news_detectorを起動
    if injected and injected > 0:
        try:
            import subprocess
            subprocess.Popen(
                ['python3', '-m', 'pipeline.breaking_news_detector'],
                cwd=BASE,
                stdout=open(os.path.join(BASE, 'logs/breaking_trigger.log'), 'a'),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            print(f"  breaking_news_detector triggered ({injected} signals)")
        except Exception as e:
            print(f"  trigger err: {e}")


if __name__ == '__main__':
    main()
