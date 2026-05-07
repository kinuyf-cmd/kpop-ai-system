#!/usr/bin/env python3
"""日本ポップアップ情報収集 — 毎時45分 cron実行
Fashion Press / Walker+ / PR TIMES検索 から K-POP関連ポップアップを収集し
popup_signals.jsonl に追加
"""
import sys
import os
import json

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
SIGNALS = '/home/aiuser/kpop-ai-system/data/popup_signals.jsonl'
LOG = '/home/aiuser/kpop-ai-system/logs/japan_popup.log'


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
    from lib.japan_popup_sources import collect_japan
    from lib.signal_validator import validate_signals_batch

    print(f"=== 日本ポップアップ収集: {datetime.now(JST).isoformat()} ===")

    existing_urls = load_existing_urls()
    items = collect_japan()

    new_items = [it for it in items if it.get('url') and it['url'] not in existing_urls]

    # シグナル品質ゲート (鮮度チェック、URL確認は収集時はスキップ=高速)
    if new_items:
        vr = validate_signals_batch(new_items, check_url=False)
        if vr['rejected']:
            print(f"  品質ゲートREJECT: {vr['stats']['rejected']}件")
            for r in vr['rejected'][:3]:
                print(f"    ✗ {r.get('title','')[:40]} → {r.get('_reject_reasons','')}")
        new_items = vr['valid']

    if new_items:
        os.makedirs(os.path.dirname(SIGNALS), exist_ok=True)
        with open(SIGNALS, 'a', encoding='utf-8') as f:
            for item in new_items:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')

    print(f"収集: {len(items)}件 → 新規: {len(new_items)}件 (既存{len(existing_urls)}件)")
    for it in new_items[:5]:
        print(f"  + [{it['source']}] {it['title'][:50]} ({it['city']})")

    return {'total': len(items), 'new': len(new_items)}


if __name__ == '__main__':
    main()
