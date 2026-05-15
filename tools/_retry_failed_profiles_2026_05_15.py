#!/usr/bin/env python3
"""2026-05-15 bulk run 失敗 5件の profile_wiki_builder.build_one() 再実行。

WP category と artist_master stub は既に作成済。LLM profile fetch のみ retry。
PROFILE_FETCH_TIMEOUT を 300s に拡張。
"""
from __future__ import annotations
import os
import sys
import time
import traceback
from pathlib import Path

os.environ['PROFILE_USE_WEBSEARCH'] = '1'
os.environ['PROFILE_FETCH_TIMEOUT'] = '300'
sys.path.insert(0, '/home/aiuser/kpop-ai-system')

from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

import anthropic
from pipeline import profile_wiki_builder as pwb

RETRIES = [
    ('&TEAM', 'andteam'),
    ('KiiiKiii', 'kiiikiii'),
    ('IDID', 'idid'),
    ('2PM', '2pm'),
    ('KickFlip', 'kickflip'),
    # 2026-05-15 stub guard 導入で発覚した既存 stub:
    ('ALL(H)OURS', 'allhours'),
    ('Aoen', 'aoen'),
    ('GIRLSET', 'girlset'),
    ('1VERSE', '1verse'),
    ('CORTIS', 'cortis'),
]

LOG = Path('/home/aiuser/kpop-ai-system/logs/retry_failed_profiles_2026_05_15.log')


def log(msg: str) -> None:
    line = f'[{time.strftime("%H:%M:%S")}] {msg}'
    print(line, flush=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text('', encoding='utf-8')
    log(f'=== retry start: {len(RETRIES)} artists, timeout=300s ===')
    client = anthropic.Anthropic()
    ok = ng = 0
    for i, (name, slug) in enumerate(RETRIES, 1):
        log(f'--- [{i}/{len(RETRIES)}] {name} (slug={slug}) ---')
        try:
            r = pwb.build_one(client, name, slug)
            if r:
                ok += 1
                log(f'  ✓ done: {name}')
            else:
                ng += 1
                log(f'  ✗ failed: {name}')
        except Exception as e:
            ng += 1
            log(f'  ✗ exception: {name}: {type(e).__name__}: {e}')
            log(traceback.format_exc())
        log(f'  progress: ok={ok} ng={ng} remaining={len(RETRIES)-i}')

    try:
        pwb.update_internal_link_dictionary()
        pwb.update_frontend_slug_list()
        log('  ✓ link dict + slug list updated')
    except Exception as e:
        log(f'  ✗ post-update err: {e}')

    log(f'\n=== retry done: {ok} ok / {ng} ng ===')


if __name__ == '__main__':
    main()
