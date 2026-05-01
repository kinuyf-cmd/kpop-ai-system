#!/usr/bin/env python3
"""毎時50分: 日本商業施設のK-POP関連イベント収集"""
import sys
import os
import json

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
SIGNALS = '/home/aiuser/kpop-ai-system/data/popup_signals.jsonl'


def load_existing_urls():
    urls = set()
    if os.path.exists(SIGNALS):
        with open(SIGNALS, encoding='utf-8') as f:
            for line in f:
                try:
                    urls.add(json.loads(line).get('url', ''))
                except Exception:
                    pass
    return urls


def main():
    from lib.japan_venue_sources import collect_japan_venues

    print(f"=== 商業施設収集: {datetime.now(JST).isoformat()} ===")

    existing_urls = load_existing_urls()
    items = collect_japan_venues()

    new_items = [it for it in items if it.get('url') and it['url'] not in existing_urls]

    if new_items:
        os.makedirs(os.path.dirname(SIGNALS), exist_ok=True)
        with open(SIGNALS, 'a', encoding='utf-8') as f:
            for item in new_items:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')

    print(f"取得: {len(items)}件 → 新規: {len(new_items)}件")
    for it in new_items[:5]:
        print(f"  + [{it['venue']}] {it['title'][:50]}")

    return {'total': len(items), 'new': len(new_items)}


if __name__ == '__main__':
    main()
