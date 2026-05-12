#!/usr/bin/env python3
"""memory 棚卸し: 90日触れられていない & MEMORY.md でリンクされていない memory を archived/ へ移動。

cron: 週1回 (月曜10時)
"""
import re
import shutil
import time
from pathlib import Path

MEM_DIR = Path('/home/aiuser/.claude/projects/-home-aiuser-kpop-ai-system/memory')
INDEX = MEM_DIR / 'MEMORY.md'
ARCHIVE = MEM_DIR / 'archived'
LOG = Path('/home/aiuser/kpop-ai-system/logs/memory_archive.log')
STALE_DAYS = 90


def linked_in_index() -> set[str]:
    if not INDEX.exists():
        return set()
    text = INDEX.read_text(encoding='utf-8')
    return set(re.findall(r'\(([a-z0-9_]+\.md)\)', text))


def main() -> None:
    cutoff = time.time() - STALE_DAYS * 86400
    linked = linked_in_index()
    moved = []
    skipped_linked = []

    for f in MEM_DIR.glob('*.md'):
        if f.name in ('MEMORY.md',):
            continue
        if f.stat().st_mtime > cutoff:
            continue
        if f.name in linked:
            skipped_linked.append(f.name)
            continue
        ARCHIVE.mkdir(exist_ok=True)
        shutil.move(str(f), str(ARCHIVE / f.name))
        moved.append(f.name)

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a', encoding='utf-8') as lf:
        ts = time.strftime('%Y-%m-%dT%H:%M:%S')
        lf.write(f'[{ts}] moved={len(moved)} stale_but_linked={len(skipped_linked)} cutoff={STALE_DAYS}d\n')
        for n in moved:
            lf.write(f'  -> archived/{n}\n')
        for n in skipped_linked:
            lf.write(f'  (kept, still linked in MEMORY.md): {n}\n')

    print(f'moved {len(moved)} files to archived/, kept {len(skipped_linked)} stale-but-linked')


if __name__ == '__main__':
    main()
