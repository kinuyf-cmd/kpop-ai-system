#!/usr/bin/env python3
"""Pre-commit hook: bundling commit guard (2026-05-15新設)

memory feedback_avoid_commit_bundling の機械強制版。
CLAUDE.md 規定「M-state 100行超なら退避→HEAD戻し→再適用→commit→復元」を
機械的に強制する。

検知ロジック:
  1. cron-managed glob: data/*_cache.*, data/cost_ledger.*, config/comeback*,
     config/x_post_queue*, config/artist_master.json, config/auto_directives.json,
     config/events_manual.json, config/internal_link_dictionary.json が staged
     されていれば flag (cron 自動更新ファイルの巻き込み)
  2. 過大 staged: 単一ファイル > 500 行変更 (binary 除く)

flagged が 1件以上あれば exit 2 で BLOCK。
override: `KPJ_ALLOW_BUNDLE=1 git commit ...`
"""
from __future__ import annotations
import os
import sys
import subprocess
import fnmatch


CRON_MANAGED_GLOBS = [
    'data/*_cache.json',
    'data/*_cache.jsonl',
    'data/cost_ledger.jsonl',
    'data/*_enrichment_cache.json',
    'data/*_state.json',
    'data/*.jsonl.bak*',
    'config/comeback_calendar*.json',
    'config/x_post_queue*.json',
    'config/x_post_queue.json.bak*',
    'config/artist_master.json',
    'config/auto_directives.json',
    'config/events_manual.json',
    'config/internal_link_dictionary.json',
    'config/concrete_vs_abstract.json',
]

OVERSIZE_THRESHOLD = 500


def is_cron_managed(path: str) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in CRON_MANAGED_GLOBS)


def main() -> int:
    if os.environ.get('KPJ_ALLOW_BUNDLE') == '1':
        print('[bundling-guard] KPJ_ALLOW_BUNDLE=1 → bypass')
        return 0

    try:
        out = subprocess.check_output(
            ['git', 'diff', '--cached', '--numstat'],
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print(f'[bundling-guard] git diff 失敗 (skip): {e}', file=sys.stderr)
        return 0

    flagged_cron = []
    flagged_oversize = []
    for line in out.strip().splitlines():
        parts = line.split('\t')
        if len(parts) < 3:
            continue
        ins, dele, path = parts[0], parts[1], parts[2]
        if ins == '-' or dele == '-':  # binary
            continue
        try:
            total = int(ins) + int(dele)
        except ValueError:
            continue
        if is_cron_managed(path):
            flagged_cron.append((path, total))
        elif total > OVERSIZE_THRESHOLD:
            flagged_oversize.append((path, total))

    if not flagged_cron and not flagged_oversize:
        return 0

    print('', file=sys.stderr)
    print('❌ [bundling-guard] 巻き込み commit の疑い:', file=sys.stderr)
    if flagged_cron:
        print('', file=sys.stderr)
        print('  📦 cron 自動更新 ファイル が staged されています:', file=sys.stderr)
        for path, lines in flagged_cron:
            print(f'    - {path} ({lines}行)', file=sys.stderr)
    if flagged_oversize:
        print('', file=sys.stderr)
        print(f'  📦 単一ファイル > {OVERSIZE_THRESHOLD}行 の大規模変更:', file=sys.stderr)
        for path, lines in flagged_oversize:
            print(f'    - {path} ({lines}行)', file=sys.stderr)
    print('', file=sys.stderr)
    print('  CLAUDE.md feedback_avoid_commit_bundling 規定により block。', file=sys.stderr)
    print('  対処:', file=sys.stderr)
    print('    1. git restore --staged <path>  で巻き込みを外す', file=sys.stderr)
    print('    2. 意図的な commit なら: KPJ_ALLOW_BUNDLE=1 git commit ...', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
