#!/usr/bin/env python3
"""artist_aliases.json を再生成する(手動分を保持しつつ自動分をマージ)。

サムネ resolver の normalize_artist_name 用。ハングル/カタカナ表記→正規英語名。

ソース:
  1. config/artist_master.json の name_ko/name_ja → name_en(自動)
  2. data/artist_aliases_manual.json(ログ調査で判明した降格アーティスト等の手動分)

手動分が自動分を上書きする(手動の方が精度が高い前提)。
code-review #4 指摘(再生成スクリプト未作成で手動分消失リスク)への対処として、
手動分を別ファイルに分離し、再生成しても消えないようにした。
"""
import json
import os
import re

BASE = os.path.join(os.path.dirname(__file__), '..', '..')
MASTER = os.path.join(BASE, 'config', 'artist_master.json')
MANUAL = os.path.join(BASE, 'data', 'artist_aliases_manual.json')
OUT = os.path.join(BASE, 'data', 'artist_aliases.json')


def from_master() -> dict:
    """artist_master の多言語名 → name_en マップ。括弧内表記も分解。"""
    aliases = {}
    try:
        d = json.load(open(MASTER, encoding='utf-8'))
    except Exception:
        return aliases
    for a in d.get('artists', []):
        en = (a.get('name_en') or '').strip()
        if not en:
            continue
        for f in ('name_ko', 'name_ja'):
            v = (a.get(f) or '').strip()
            if v and v != en:
                aliases[v] = en
                # name_ja の括弧書き(BTS（防弾少年団）→ 防弾少年団)も拾う
                m = re.search(r'[（(]([^）)]+)[）)]', v)
                if m:
                    inner = m.group(1).strip()
                    if inner and inner != en:
                        aliases[inner] = en
    return aliases


def from_manual() -> dict:
    try:
        d = json.load(open(MANUAL, encoding='utf-8'))
        return d.get('aliases', {}) or {}
    except Exception:
        return {}


def main():
    auto = from_master()
    manual = from_manual()
    merged = dict(auto)
    merged.update(manual)  # 手動分が優先
    out = {
        "_comment": ("アーティスト名エイリアス→正規英語名(サムネ resolver normalize用)。"
                     "このファイルは tools/seo/build_artist_aliases.py の生成物。"
                     "手動編集は data/artist_aliases_manual.json に行い再生成すること。"),
        "_generated_from": ["config/artist_master.json", "data/artist_aliases_manual.json"],
        "_counts": {"auto": len(auto), "manual": len(manual), "merged": len(merged)},
        "aliases": dict(sorted(merged.items())),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f"auto={len(auto)} manual={len(manual)} merged={len(merged)} → {OUT}")


if __name__ == '__main__':
    main()
