#!/usr/bin/env python3
"""毎時35分: 韓国K-POPニュース複数ソース収集 (RSS方式)

2026-04-28 改修: Naver HTML scraping → Soompi RSS + Donga RSS 統合
"""
import json, sys, os
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime
from lib.korea_naver_scraper import collect_all


def main():
    out_dir = 'data/signals/korea_official'
    os.makedirs(out_dir, exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')

    print(f'=== korea_official_collector: {today} ===')
    items = collect_all()

    # 既存データとマージ
    out_path = f'{out_dir}/{today}_korea_signals.json'
    try:
        existing = json.load(open(out_path)) if os.path.exists(out_path) else []
    except Exception:
        existing = []
    existing.extend(items)

    # 重複排除 (urlベース)
    seen = set()
    dedup = []
    for n in existing:
        u = n.get('url', '')
        if u and u not in seen:
            dedup.append(n)
            seen.add(u)

    json.dump(dedup, open(out_path, 'w'), ensure_ascii=False, indent=2)
    print(f'今回 {len(items)}件取得、累計 {len(dedup)}件 (重複排除後)')


if __name__ == '__main__':
    main()
