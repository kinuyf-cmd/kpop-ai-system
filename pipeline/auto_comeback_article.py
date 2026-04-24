#!/usr/bin/env python3
"""韓国メディアsignalsからカムバック記事を自動生成+WP投稿

条件緩和 (C-Fix9 Block3): 単一ソースも許可、信頼度ラベル付与
"""
import sys, os
sys.path.insert(0, '/home/aiuser/kpop-ai-system')

from dotenv import load_dotenv
load_dotenv()

from lib.korean_translator import translate_ko_to_ja
from pipeline.auto_event_article import (
    load_signals, is_processed, mark_processed,
    generate_article_content_v2, post_to_wp, post_to_wp_with_thumb, fetch_category_id,
    OFFICIAL_KW, CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW,
)
from datetime import datetime

COMEBACK_KW = ['컴백', '신곡', '발매', '신보', '앨범', '미니앨범', '정규', '싱글']


def is_comeback_signal(sig):
    return any(kw in sig.get('title', '') for kw in COMEBACK_KW)


def main(dry_run=False, max_articles=5):
    signals = load_signals(hours_back=24)
    cb_sigs = [s for s in signals if is_comeback_signal(s)]
    print(f"カムバック関連: {len(cb_sigs)}")

    from lib.collectors.korean_base import is_kpop_related
    groups = {}
    for sig in cb_sigs:
        artists = is_kpop_related(sig['title'])
        if not artists:
            continue
        groups.setdefault(artists[0], []).append(sig)

    qualified = []
    for artist, sigs in groups.items():
        if any(is_processed(s['url']) for s in sigs):
            continue
        sources = set(s.get('source_id', '') for s in sigs)
        has_multi = len(sources) >= 2
        has_official = any(any(kw in s['title'] for kw in OFFICIAL_KW) for s in sigs)
        if has_multi:
            confidence = CONFIDENCE_HIGH
        elif has_official:
            confidence = CONFIDENCE_MEDIUM
        else:
            confidence = CONFIDENCE_LOW
        qualified.append((artist, sigs, confidence))

    print(f"記事化候補: {len(qualified)}")
    cat_id = fetch_category_id('news')
    created = 0

    for artist, sigs, confidence in qualified[:max_articles]:
        best = max(sigs, key=lambda s: len(s['title']))
        print(f"\n=== {artist} (confidence={confidence}): {best['title'][:60]} ===")
        if dry_run:
            continue

        title_r = translate_ko_to_ja(best['title'], 'K-POPカムバック見出し')
        if not title_r['success']:
            continue
        raw_title = title_r['translated'].strip().strip('「」""')[:65]
        title_ja = f'【速報】{raw_title}' if confidence == 'low' else raw_title

        combined = "\n".join([s['title'] for s in sigs[:3]])
        body_r = translate_ko_to_ja(
            f"以下のK-POPカムバック報道から200-300字の日本語記事本文を事実ベースで作成。推測禁止:\n\n{combined}",
            'K-POPカムバック記事',
        )
        if not body_r['success']:
            continue

        content = generate_article_content_v2(sigs, body_r['translated'], confidence)
        best_url = best.get('url', '')
        result = post_to_wp_with_thumb(title_ja, content, cat_id, source_url=best_url)
        if result and result.get('id'):
            print(f"  WP公開 ID={result['id']}")
            created += 1
            for s in sigs:
                mark_processed({'ts': datetime.now().isoformat(), 'source_url': s['url'],
                                'wp_post_id': result['id'], 'kind': 'comeback', 'confidence': confidence})

    print(f"\n完了: {created}件")
    return created


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--max', type=int, default=5)
    args = ap.parse_args()
    main(dry_run=args.dry_run, max_articles=args.max)
