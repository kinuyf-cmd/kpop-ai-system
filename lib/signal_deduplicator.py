#!/usr/bin/env python3
"""signal重複排除モジュール

3段階の重複検出:
1. URL完全一致 (最強、即除去)
2. タイトル正規化一致 (記号/空白差吸収)
3. アーティスト+タイトル先頭一致 (24h以内)

使用箇所: auto_event_article, auto_comeback_article, breaking_news_detector
"""
import re
import json
import os
from datetime import datetime, timedelta
from collections import defaultdict


def _normalize_title(title):
    """タイトル正規化 (重複検出用)"""
    if not title:
        return ''
    title = re.sub(r'[【\[\(][^】\]\)]*[】\]\)]', '', title)
    title = re.sub(r'[!?！?。、\s\u3000\-_…]+', '', title)
    return title.lower()[:60]


def _extract_url(signal):
    """signalから優先URL抽出"""
    return (signal.get('source_url') or
            signal.get('url') or
            signal.get('link') or '')


def deduplicate(signals):
    """signalリストから重複を排除

    Returns:
        (unique_signals, duplicate_count, duplicate_log)
    """
    if not signals:
        return [], 0, []

    seen_urls = set()
    seen_titles = set()
    seen_artist_titles = set()

    unique = []
    duplicates = []

    for s in signals:
        url = _extract_url(s)
        title = s.get('title') or s.get('source_title', '')
        artist = s.get('artist', '')

        # 1. URL完全一致
        if url and url in seen_urls:
            duplicates.append({'reason': 'url_exact', 'url': url, 'title': title[:50]})
            continue

        # 2. タイトル正規化一致
        norm = _normalize_title(title)
        if len(norm) > 10 and norm in seen_titles:
            duplicates.append({'reason': 'title_normalized', 'title': title[:50]})
            continue

        # 3. アーティスト+タイトル先頭30字一致
        if artist and norm:
            key = f'{artist}::{norm[:30]}'
            if key in seen_artist_titles:
                duplicates.append({'reason': 'artist_title_similar', 'artist': artist, 'title': title[:50]})
                continue
            seen_artist_titles.add(key)

        if url:
            seen_urls.add(url)
        if norm and len(norm) > 10:
            seen_titles.add(norm)
        unique.append(s)

    return unique, len(duplicates), duplicates


def load_signals_24h(jsonl_path='/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'):
    """過去24h のsignalを読込"""
    if not os.path.exists(jsonl_path):
        return []
    cutoff = datetime.now() - timedelta(hours=24)
    signals = []
    with open(jsonl_path, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                ts_str = d.get('timestamp', '') or d.get('ts', '')
                if ts_str:
                    ts = datetime.fromisoformat(ts_str[:19])
                    if ts >= cutoff:
                        signals.append(d)
            except Exception:
                pass
    return signals


def stats(signals):
    """重複排除前後の統計"""
    unique, dup_count, dup_log = deduplicate(signals)
    by_reason = defaultdict(int)
    for d in dup_log:
        by_reason[d['reason']] += 1
    return {
        'original': len(signals),
        'unique': len(unique),
        'duplicates': dup_count,
        'dedup_rate': round(dup_count / max(1, len(signals)) * 100, 1),
        'by_reason': dict(by_reason),
    }


if __name__ == '__main__':
    signals = load_signals_24h()
    s = stats(signals)
    print(json.dumps(s, ensure_ascii=False, indent=2))
