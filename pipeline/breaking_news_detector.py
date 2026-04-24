#!/usr/bin/env python3
"""速報検出→即時記事化

条件:
- urgency='high' のsignalが過去15分以内に発生
- または同一アーティストで過去15分以内に2ソース以上
- 1日最大3件
"""
import sys, os, json
from datetime import datetime, timedelta

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

from lib.korean_translator import translate_ko_to_ja
from pipeline.auto_event_article import (
    is_processed, mark_processed,
    generate_article_content_v2, post_to_wp, fetch_category_id,
)

SIGNALS_PATH = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'
BREAKING_LOG = '/home/aiuser/kpop-ai-system/logs/breaking_articles.jsonl'
DAILY_BREAKING_LIMIT = 3


def load_recent(minutes=15):
    if not os.path.exists(SIGNALS_PATH):
        return []
    cutoff = datetime.now() - timedelta(minutes=minutes)
    result = []
    with open(SIGNALS_PATH, encoding='utf-8') as f:
        for line in f:
            try:
                sig = json.loads(line)
                ts = datetime.fromisoformat(sig.get('timestamp', '')[:19])
                if ts >= cutoff:
                    result.append(sig)
            except Exception:
                pass
    return result


def today_breaking_count():
    if not os.path.exists(BREAKING_LOG):
        return 0
    today = datetime.now().date().isoformat()
    return sum(1 for l in open(BREAKING_LOG, encoding='utf-8')
               if l.strip() and json.loads(l).get('date') == today)


def detect_breaking(signals):
    from lib.collectors.korean_base import is_kpop_related
    candidates = []
    seen = set()

    # 1. urgency=high
    for s in signals:
        if s.get('urgency') != 'high':
            continue
        arts = is_kpop_related(s.get('title', ''))
        if not arts or arts[0] in seen:
            continue
        if is_processed(s['url']):
            continue
        seen.add(arts[0])
        candidates.append((arts[0], [s], 'urgent'))

    # 2. 同一アーティスト+複数ソース (15分以内)
    by_artist = {}
    for s in signals:
        arts = is_kpop_related(s.get('title', ''))
        if not arts:
            continue
        by_artist.setdefault(arts[0], []).append(s)

    for artist, sigs in by_artist.items():
        if artist in seen:
            continue
        sources = set(s.get('source_id', '') for s in sigs)
        if len(sources) >= 2 and not any(is_processed(s['url']) for s in sigs):
            seen.add(artist)
            candidates.append((artist, sigs, 'multi'))

    return candidates


def publish_breaking(artist, sigs, typ):
    best = max(sigs, key=lambda s: len(s.get('title', '')))

    title_r = translate_ko_to_ja(best['title'], 'K-POP速報ニュース見出し')
    if not title_r['success']:
        return None

    raw_title = title_r['translated'].strip().strip('「」""')[:60]
    title_ja = f'【速報】{raw_title}'

    combined = "\n".join([s['title'] for s in sigs[:3]])
    body_r = translate_ko_to_ja(
        f"以下のK-POP速報を元に、150-250字の日本語記事を事実ベースで。推測禁止:\n\n{combined}",
        'K-POP速報記事本文',
    )
    if not body_r['success']:
        return None

    confidence = 'high' if typ == 'multi' else 'medium'
    content = generate_article_content_v2(sigs, body_r['translated'], confidence)
    cat_id = fetch_category_id('news')
    result = post_to_wp(title_ja, content, cat_id)

    if result and result.get('id'):
        for s in sigs:
            mark_processed({
                'ts': datetime.now().isoformat(), 'source_url': s['url'],
                'wp_post_id': result['id'], 'kind': 'breaking',
                'confidence': confidence, 'type': typ,
            })
        os.makedirs(os.path.dirname(BREAKING_LOG), exist_ok=True)
        with open(BREAKING_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'date': datetime.now().date().isoformat(),
                'ts': datetime.now().isoformat(),
                'post_id': result['id'],
                'title': title_ja,
                'artist': artist,
                'type': typ,
            }) + '\n')

        # GSC Indexing通知
        try:
            from lib.gsc_indexing import notify_url_updated
            post_url = result.get('link', '')
            if post_url:
                notify_url_updated(post_url)
        except Exception:
            pass

    return result


def main(dry_run=False):
    count_today = today_breaking_count()
    print(f"本日の速報記事: {count_today}/{DAILY_BREAKING_LIMIT}")
    if count_today >= DAILY_BREAKING_LIMIT:
        print("本日の速報上限到達")
        return 0

    signals = load_recent(minutes=15)
    print(f"過去15分のsignals: {len(signals)}件")

    candidates = detect_breaking(signals)
    print(f"速報候補: {len(candidates)}件")

    published = 0
    for artist, sigs, typ in candidates[:DAILY_BREAKING_LIMIT - count_today]:
        best = max(sigs, key=lambda s: len(s.get('title', '')))
        print(f"\n=== {artist} ({typ}): {best['title'][:60]} ===")
        if dry_run:
            continue
        r = publish_breaking(artist, sigs, typ)
        if r:
            print(f"  速報公開 ID={r.get('id')}")
            published += 1

    print(f"\n速報記事化: {published}件")
    return published


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    main(dry_run=args.dry_run)
