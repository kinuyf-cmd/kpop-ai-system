#!/usr/bin/env python3
"""韓国メディアsignalsからカムバック記事を自動生成+WP投稿"""
import sys, os
sys.path.insert(0, '/home/aiuser/kpop-ai-system')

from dotenv import load_dotenv
load_dotenv()

from lib.korean_translator import translate_ko_to_ja
from pipeline.auto_event_article import (
    load_signals, is_processed, mark_processed,
    generate_article_content, post_to_wp, fetch_category_id,
    OFFICIAL_KW,
)
from datetime import datetime

COMEBACK_KW = ['컴백', '신곡', '발매', '신보', '앨범', '미니앨범', '정규', '싱글']


def is_comeback_signal(sig):
    return any(kw in sig.get('title', '') for kw in COMEBACK_KW)


def main(dry_run=False, max_articles=3):
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
        sources = set(s.get('source_id', '') for s in sigs)
        has_multi = len(sources) >= 2
        has_official = any(any(kw in s['title'] for kw in OFFICIAL_KW) for s in sigs)
        if (has_multi or has_official) and not any(is_processed(s['url']) for s in sigs):
            qualified.append((artist, sigs))

    print(f"記事化候補: {len(qualified)}")
    cat_id = fetch_category_id('news')
    created = 0

    for artist, sigs in qualified[:max_articles]:
        best = max(sigs, key=lambda s: len(s['title']))
        print(f"\n=== {artist}: {best['title'][:60]} ===")
        if dry_run:
            continue

        title_r = translate_ko_to_ja(best['title'], 'K-POPカムバック見出し')
        if not title_r['success']:
            continue
        title_ja = title_r['translated'].strip().strip('「」""')[:70]

        combined = "\n".join([s['title'] for s in sigs[:3]])
        body_r = translate_ko_to_ja(
            f"以下のK-POPカムバック報道から200-300字の日本語記事本文を事実ベースで作成。推測禁止:\n\n{combined}",
            'K-POPカムバック記事',
        )
        if not body_r['success']:
            continue

        result = post_to_wp(title_ja, generate_article_content(sigs, body_r['translated']), cat_id)
        if result and result.get('id'):
            print(f"  WP公開 ID={result['id']}")
            created += 1
            for s in sigs:
                mark_processed({'ts': datetime.now().isoformat(), 'source_url': s['url'],
                                'wp_post_id': result['id'], 'kind': 'comeback'})

    print(f"\n完了: {created}件")
    return created


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--max', type=int, default=3)
    args = ap.parse_args()
    main(dry_run=args.dry_run, max_articles=args.max)
