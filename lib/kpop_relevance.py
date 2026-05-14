#!/usr/bin/env python3
"""K-POP 関連性チェック (2026-05-14 simple_publish_pipeline から extract)

og:title に K-POP artist 名が含まれるかを判定する。collector 段階で
取りこぼした non-kpop content (ドラマ/俳優 等) を publish 直前で
弾くための gate。

Public API:
  is_kpop_relevant(title: str) -> bool
"""
import json
import re
from pathlib import Path

_KPOP_NAMES_CACHE = None
_CONFIG_BASE = Path('/home/aiuser/kpop-ai-system/config')

# registry 未登録だが速報対象となる主要 K-POP groups/solo
_SUPPLEMENT_NAMES = frozenset({
    'SHINee', 'Red Velvet', 'EXO', 'ATEEZ', 'TXT', 'TOMORROW X TOGETHER',
    'MONSTA X', '(G)I-DLE', 'GIDLE', 'MAMAMOO', 'ZEROBASEONE', 'ZB1',
    'P1Harmony', 'fromis_9', 'KISS OF LIFE', 'CORTIS', 'WJSN', 'NMIXX',
    'BIGBANG', '2NE1', '2PM', 'SUPER JUNIOR', "Girls' Generation", 'SNSD',
    'GD', 'G-DRAGON', 'BIBI', 'Bewhy', '비와이', 'JESSI', '제시',
    '샤이니', '레드벨벳', '엑소', '에이티즈', '몬스타엑스', '여자아이들',
})


def _load_kpop_names() -> frozenset:
    """artist_master + artist_profiles + 補助 whitelist から K-POP artist 名集合を構築"""
    global _KPOP_NAMES_CACHE
    if _KPOP_NAMES_CACHE is not None:
        return _KPOP_NAMES_CACHE
    names = set()
    try:
        master = json.loads((_CONFIG_BASE / 'artist_master.json').read_text(encoding='utf-8'))
        for a in master.get('artists', []):
            for k in ('name_en', 'name_ko', 'name_ja'):
                if a.get(k):
                    names.add(a[k])
            for m in a.get('members', []):
                for k in ('name', 'name_ko', 'name_ja'):
                    if m.get(k):
                        names.add(m[k])
    except Exception:
        pass
    for p in (_CONFIG_BASE / 'artist_profiles').glob('*.json'):
        try:
            d = json.loads(p.read_text(encoding='utf-8'))
            names.add(p.stem.replace('-', '').upper())
            names.add(p.stem)
            for m in d.get('members', []):
                for k in ('name_en', 'name_kr', 'name_ja', 'real_name_en'):
                    if m.get(k):
                        names.add(m[k])
        except Exception:
            pass
    names.update(_SUPPLEMENT_NAMES)
    _KPOP_NAMES_CACHE = frozenset(n for n in names if len(n) >= 2)
    return _KPOP_NAMES_CACHE


def is_kpop_relevant(title: str) -> bool:
    """og:title に K-POP artist 名が含まれるか判定。
    short ASCII 名 (≤4 chars) は word boundary 必須、長い/非ASCII は substring。"""
    if not title:
        return False
    names = _load_kpop_names()
    t_lower = title.lower()
    for n in names:
        if all(c.isascii() for c in n) and len(n) <= 4:
            if re.search(rf'\b{re.escape(n)}\b', title, re.I):
                return True
        else:
            if n.lower() in t_lower:
                return True
    return False
