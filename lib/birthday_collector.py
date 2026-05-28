"""birthday_collector.py — Idol Wiki ACF + artist_master.json から
アーティスト/メンバー誕生日マスターを集約し JSON 出力する。

出力: data/birthday_master.json
  [
    {"name": "JISOO", "group": "BLACKPINK", "group_id": 60,
     "birthday": "1995-01-03", "source": "idol_wiki",
     "wp_post_id": 60},
    ...
  ]

Idol Wiki ACF を主、artist_master.json を補完として使用。
重複は name+birthday key で dedup(idol_wiki 優先)。

Usage:
  python3 lib/birthday_collector.py
"""
from __future__ import annotations
import json
import subprocess
import re
from pathlib import Path

ROOT = Path('/home/aiuser/kpop-ai-system')
OUT = ROOT / 'data/birthday_master.json'
MASTER_JSON = ROOT / 'config/artist_master.json'

WP_RO = '/usr/local/sbin/kpop/kpop-wp-ro'


def _run_wp(args: list[str]) -> str:
    cmd = ['sudo', '-n', WP_RO] + args
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout


def _list_idol_artists() -> list[tuple[int, str]]:
    out = _run_wp(['post', 'list', '--post_type=idol_artist',
                   '--posts_per_page=300', '--format=csv',
                   '--fields=ID,post_title', '--orderby=ID'])
    rows = []
    for line in out.strip().splitlines()[1:]:
        m = re.match(r'^(\d+),"?(.+?)"?$', line)
        if m:
            rows.append((int(m.group(1)), m.group(2)))
    return rows


def _normalize_birthday(raw: str) -> str | None:
    """YYYYMMDD or YYYY-MM-DD → YYYY-MM-DD。不正は None。"""
    if not raw:
        return None
    s = raw.strip()
    if re.match(r'^\d{8}$', s):
        return f'{s[:4]}-{s[4:6]}-{s[6:8]}'
    if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
        return s
    return None


def _clean_member_name(raw: str) -> str:
    """'JISOO (김지수)' → 'JISOO'。脱退/除外などの注記行は空文字を返す。"""
    s = raw.strip().strip('"')
    if any(x in s for x in ('脱退', '除外', '※', 'TBD')):
        return ''
    s = re.sub(r'\s*\([^)]*\)\s*$', '', s).strip()
    return s


def collect_from_idol_wiki() -> list[dict]:
    entries: list[dict] = []
    for gid, gname in _list_idol_artists():
        out = _run_wp(['post', 'meta', 'list', str(gid), '--format=csv'])
        members: dict[int, dict] = {}
        for line in out.splitlines():
            m = re.match(r'^\d+,members_(\d+)_member_(name|birthday),"?(.*?)"?$', line)
            if not m:
                continue
            idx, field, val = int(m.group(1)), m.group(2), m.group(3)
            members.setdefault(idx, {})[field] = val
        for idx, rec in members.items():
            name = _clean_member_name(rec.get('name', ''))
            bd = _normalize_birthday(rec.get('birthday', ''))
            if not name or not bd:
                continue
            entries.append({
                'name': name,
                'group': gname,
                'group_id': gid,
                'birthday': bd,
                'source': 'idol_wiki',
                'wp_post_id': gid,
            })
    return entries


def collect_from_master_json() -> list[dict]:
    if not MASTER_JSON.exists():
        return []
    data = json.loads(MASTER_JSON.read_text(encoding='utf-8'))
    artists = data.get('artists') or []
    entries: list[dict] = []
    for a in artists:
        gname = a.get('name_en') or a.get('name_ja') or a.get('id', '')
        for m in a.get('members') or []:
            name = (m.get('name') or '').strip()
            bd = _normalize_birthday(m.get('birthday') or '')
            if not name or not bd:
                continue
            entries.append({
                'name': name,
                'group': gname,
                'group_id': None,
                'birthday': bd,
                'source': 'master_json',
                'wp_post_id': None,
            })
    return entries


def main():
    wiki = collect_from_idol_wiki()
    master = collect_from_master_json()
    # 重複除去: name(lower)+birthday を key、idol_wiki 優先
    seen: dict[tuple[str, str], dict] = {}
    for e in wiki:
        seen[(e['name'].lower(), e['birthday'])] = e
    added_from_master = 0
    for e in master:
        k = (e['name'].lower(), e['birthday'])
        if k not in seen:
            seen[k] = e
            added_from_master += 1
    result = sorted(seen.values(), key=lambda x: (x['birthday'][5:], x['group'], x['name']))
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'[birthday_collector] total={len(result)} '
          f'(idol_wiki={len(wiki)} master_json+={added_from_master}) → {OUT}')


if __name__ == '__main__':
    main()
