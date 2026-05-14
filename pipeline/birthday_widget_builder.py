#!/usr/bin/env python3
"""Build today/tomorrow idol birthday data for TOP-page sidebar widget.

Reads config/artist_profiles/*.json members[].birth (YYYY-MM-DD),
emits /home/aiuser/kpopjournal-frontend/public/data/birthdays.json.

Cron: 1 0 * * *  (daily 00:01 JST)
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

JST = timezone(timedelta(hours=9))
PROFILE_DIR = Path('/home/aiuser/kpop-ai-system/config/artist_profiles')
OUT_PATH = Path('/home/aiuser/kpopjournal-frontend/public/data/birthdays.json')
BIRTH_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')

try:
    from pipeline.profile_wiki_builder import PRIORITY_ARTISTS
    SLUG_TO_NAME = {a['slug']: a['name'] for a in PRIORITY_ARTISTS}
except Exception:
    SLUG_TO_NAME = {}


def slug_to_display(slug: str) -> str:
    return SLUG_TO_NAME.get(slug) or slug.replace('-', ' ').title()


def age_on(year: int, month: int, day: int, target) -> int:
    age = target.year - year
    if (target.month, target.day) < (month, day):
        age -= 1
    return age


def collect():
    today = datetime.now(JST).date()
    tomorrow = today + timedelta(days=1)
    today_md = (today.month, today.day)
    tomorrow_md = (tomorrow.month, tomorrow.day)

    today_list, tomorrow_list = [], []

    for p in sorted(PROFILE_DIR.glob('*.json')):
        slug = p.stem
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        group_name = slug_to_display(slug)
        for m in data.get('members', []):
            mt = BIRTH_RE.match(m.get('birth', '') or '')
            if not mt:
                continue
            y, mo, da = int(mt.group(1)), int(mt.group(2)), int(mt.group(3))
            base = {
                'group': group_name,
                'group_slug': slug,
                'name_en': m.get('name_en', ''),
                'name_ja': m.get('name_ja', ''),
                'name_kr': m.get('name_kr', ''),
                'birth': m['birth'],
                'year': y,
            }
            if (mo, da) == today_md:
                today_list.append({**base, 'age': age_on(y, mo, da, today)})
            elif (mo, da) == tomorrow_md:
                tomorrow_list.append({**base, 'age': age_on(y, mo, da, tomorrow)})

    today_list.sort(key=lambda e: (e['group'], e['name_en']))
    tomorrow_list.sort(key=lambda e: (e['group'], e['name_en']))

    return {
        'generated': datetime.now(JST).isoformat(timespec='seconds'),
        'today': {
            'date': f'{today.month}月{today.day}日',
            'date_iso': today.isoformat(),
            'members': today_list,
        },
        'tomorrow': {
            'date': f'{tomorrow.month}月{tomorrow.day}日',
            'date_iso': tomorrow.isoformat(),
            'members': tomorrow_list,
        },
    }


def main():
    data = collect()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    print(f'wrote {OUT_PATH}')
    for label, key in [('today', 'today'), ('tomorrow', 'tomorrow')]:
        bucket = data[key]
        print(f'  {label} ({bucket["date"]}): {len(bucket["members"])} members')
        for e in bucket['members']:
            print(f'    - {e["name_en"]} ({e["group"]}) {e["age"]}歳 / {e["year"]}年生')


if __name__ == '__main__':
    main()
