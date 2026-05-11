#!/usr/bin/env python3
"""collector → simple_publish bridge (2026-05-11新設)

trend_signals.jsonl の信頼ソース URL を simple_publish_from_source に流す。
重複URL/低品質ソースは除外。

Usage:
  python3 pipeline/simple_publish_bridge.py --limit 5         # draft化のみ
  python3 pipeline/simple_publish_bridge.py --limit 5 --publish # 即publish
  python3 pipeline/simple_publish_bridge.py --since-hours 6   # 直近6h signals

cron想定:
  0 7-21/3 * * * cd /home/aiuser/kpop-ai-system && python3 pipeline/simple_publish_bridge.py --limit 3 >> logs/simple_publish_bridge.log 2>&1
"""
import sys, json, os, argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.simple_publish_pipeline import simple_publish_from_source

SIGNALS = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'
PROCESSED_LOG = '/home/aiuser/kpop-ai-system/data/simple_publish_processed.jsonl'

# 信頼ソース (og:image + 翻訳しやすい英語/日本語)
TRUSTED_DOMAINS = {
    'soompi.com': 4.0,         # 信頼度高
    'koreaboo.com': 3.5,
    'allkpop.com': 3.5,
    'kpophit.com': 3.0,
    'kstyle.com': 3.5,
    'kpoppost.com': 3.0,
    'hellokpop.com': 3.0,
}


def load_processed_urls() -> set:
    if not os.path.exists(PROCESSED_LOG):
        return set()
    urls = set()
    with open(PROCESSED_LOG, encoding='utf-8') as f:
        for line in f:
            try:
                urls.add(json.loads(line).get('source_url', ''))
            except Exception:
                continue
    return urls


def record_processed(record: dict):
    os.makedirs(os.path.dirname(PROCESSED_LOG), exist_ok=True)
    with open(PROCESSED_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def select_candidates(since_hours: int = 6, limit: int = 10) -> list:
    """trend_signals.jsonl から信頼ソース+未処理URLを優先順に取得"""
    if not os.path.exists(SIGNALS):
        return []
    cutoff = datetime.now()
    cutoff = cutoff.replace(tzinfo=None) - timedelta(hours=since_hours)
    processed = load_processed_urls()
    candidates = []
    with open(SIGNALS, encoding='utf-8') as f:
        for line in f:
            try:
                s = json.loads(line)
            except Exception:
                continue
            try:
                ts = datetime.fromisoformat(s.get('timestamp', '').replace('Z', ''))
                if ts.tzinfo is not None:
                    ts = ts.replace(tzinfo=None)
            except Exception:
                continue
            if ts < cutoff:
                continue
            url = s.get('url', '')
            if not url or url in processed:
                continue
            domain = next((d for d in TRUSTED_DOMAINS if d in url), '')
            if not domain:
                continue
            score = TRUSTED_DOMAINS[domain] + s.get('engagement_score', 0)
            if s.get('urgency') == 'high':
                score += 1.0
            candidates.append((score, s))

    candidates.sort(key=lambda x: -x[0])
    return [s for _, s in candidates[:limit]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=3)
    ap.add_argument('--since-hours', type=int, default=6)
    ap.add_argument('--publish', action='store_true', help='直publishする (default: draft)')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    candidates = select_candidates(since_hours=args.since_hours, limit=args.limit)
    print(f'[bridge] 候補 {len(candidates)} 件 (直近{args.since_hours}h, trusted domain)')
    if not candidates:
        return

    status = 'publish' if args.publish else 'draft'
    succeeded = 0
    for s in candidates:
        url = s['url']
        title = s.get('title', '')[:60]
        print(f'\n[bridge] {url[:80]}')
        print(f'   title: {title}')
        if args.dry_run:
            print('   (dry-run skip)')
            continue
        try:
            result = simple_publish_from_source(url, status=status)
            if result.get('post_id'):
                succeeded += 1
                record_processed({**result, 'source_signal': s})
        except Exception as e:
            print(f'   ERR: {e}')
            record_processed({'source_url': url, 'error': str(e)[:200],
                              'ts': datetime.now(timezone.utc).isoformat()})

    print(f'\n[bridge] 成功 {succeeded}/{len(candidates)}')


if __name__ == '__main__':
    main()
