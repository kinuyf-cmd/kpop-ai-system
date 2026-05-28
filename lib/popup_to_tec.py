"""popup_to_tec.py — category=popup の記事を TEC のイベントとして同期。

戦略:
- category=popup の published post を全件走査
- ACF/post_meta から開催期間(period_start/period_end など)を取得
- 取れたら "🛍 [popup title]" として tribe_events を作成、kpj_event_kind=popup
- 既存(kpj_source_post_id=元 post ID) はskip(冪等)

Usage:
  python3 lib/popup_to_tec.py --dry-run
  python3 lib/popup_to_tec.py
  python3 lib/popup_to_tec.py --rollback   # popup イベント全削除
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
from datetime import date, datetime
from pathlib import Path

ROOT = Path('/home/aiuser/kpop-ai-system')
LOG = ROOT / 'logs/popup_to_tec.jsonl'
WP_RW = '/usr/local/sbin/kpop/kpop-wp-rw.sh'
WP_RO = '/usr/local/sbin/kpop/kpop-wp-ro'


def _wp(args: list[str], rw: bool = False) -> tuple[int, str, str]:
    cmd = ['sudo', '-n', (WP_RW if rw else WP_RO)] + args
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return p.returncode, p.stdout, p.stderr


def _log(rec: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open('a') as f:
        f.write(json.dumps({**rec, 'ts': datetime.now().isoformat()},
                           ensure_ascii=False) + '\n')


def _list_popup_posts() -> list[tuple[int, str]]:
    code, out, _ = _wp([
        'post', 'list', '--category_name=popup',
        '--post_status=publish', '--posts_per_page=500',
        '--format=csv', '--fields=ID,post_title',
    ])
    if code != 0:
        return []
    rows = []
    for line in out.strip().splitlines()[1:]:
        head, _, rest = line.partition(',')
        try:
            rows.append((int(head), rest.strip('"')))
        except ValueError:
            continue
    return rows


def _parse_date(s: str) -> str | None:
    """YYYY-MM-DD / YYYY/MM/DD / YYYYMMDD → YYYY-MM-DD"""
    if not s:
        return None
    s = s.strip()
    s = s.replace('/', '-').replace('.', '-')
    if re.match(r'^\d{8}$', s):
        return f'{s[:4]}-{s[4:6]}-{s[6:8]}'
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})', s)
    if m:
        return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    return None


def _get_period(pid: int) -> tuple[str | None, str | None, str | None]:
    """ACFから期間+場所を取得。戻り値: (start, end, location)"""
    code, out, _ = _wp(['post', 'meta', 'list', str(pid), '--format=csv'])
    if code != 0:
        return None, None, None
    start = end = loc = None
    for line in out.splitlines():
        cols = line.split(',', 2)
        if len(cols) < 3:
            continue
        k = cols[1]
        v = cols[2].strip().strip('"')
        if k in ('popup_period_start', 'period_start', 'popup_start',
                  'start_date', 'event_start_date'):
            start = _parse_date(v) or start
        elif k in ('popup_period_end', 'period_end', 'popup_end',
                    'end_date', 'event_end_date'):
            end = _parse_date(v) or end
        elif k in ('popup_address', 'location', 'venue', 'popup_venue', 'place'):
            if v:
                loc = v
    return start, end, loc


def _existing_popup_event_source_ids() -> set[int]:
    sql = (
        "SELECT meta_value FROM wp_postmeta "
        "WHERE meta_key='kpj_source_post_id' "
        "AND post_id IN (SELECT post_id FROM wp_postmeta "
        "WHERE meta_key='kpj_event_kind' AND meta_value='popup')"
    )
    code, out, _ = _wp(['db', 'query', sql])
    seen: set[int] = set()
    if code != 0:
        return seen
    for line in out.strip().splitlines()[1:]:
        try:
            seen.add(int(line.strip()))
        except ValueError:
            continue
    return seen


def create_one(src_id: int, title: str, dry_run: bool) -> str:
    start, end, loc = _get_period(src_id)
    if not start:
        return 'skipped:no_start_date'
    if not end:
        end = start  # 単日扱い
    title_clean = re.sub(r'\s+', ' ', title).strip()
    new_title = f'🛍 {title_clean}'
    src_url = f'/?p={src_id}'
    desc = (
        f'<p>🛍️ <strong>{title_clean}</strong></p>'
        + (f'<p>会場: {loc}</p>' if loc else '')
        + f'<p>期間: {start} 〜 {end}</p>'
        f'<p><a href="{src_url}">詳細を見る</a></p>'
    )
    if dry_run:
        return f'planned:{start}~{end}'
    code, out, err = _wp([
        'post', 'create', '--post_type=tribe_events',
        '--post_status=publish',
        f'--post_title={new_title}',
        f'--post_content={desc}',
        '--porcelain',
    ], rw=True)
    if code != 0:
        return f'error:create:{err[:120]}'
    try:
        pid = int(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return f'error:parse:{out[:80]}'
    meta_pairs = [
        ('_EventStartDate', f'{start} 00:00:00'),
        ('_EventEndDate', f'{end} 23:59:59'),
        ('_EventStartDateUTC', f'{start} 00:00:00'),
        ('_EventEndDateUTC', f'{end} 23:59:59'),
        ('_EventAllDay', 'yes'),
        ('_EventTimezone', 'Asia/Tokyo'),
        ('kpj_event_kind', 'popup'),
        ('kpj_source_post_id', str(src_id)),
    ]
    if loc:
        meta_pairs.append(('kpj_popup_venue', loc))
    for k, v in meta_pairs:
        c, _, e = _wp(['post', 'meta', 'update', str(pid), k, v], rw=True)
        if c != 0:
            return f'error:meta:{k}:{e[:80]}'
    return f'created:{pid}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--rollback', action='store_true')
    args = ap.parse_args()

    if args.rollback:
        code, out, _ = _wp(['db', 'query',
            "SELECT post_id FROM wp_postmeta "
            "WHERE meta_key='kpj_event_kind' AND meta_value='popup'"])
        ids = [l.strip() for l in out.strip().splitlines()[1:] if l.strip()]
        print(f'rollback: {len(ids)} popup events')
        for pid in ids:
            _wp(['post', 'delete', pid, '--force'], rw=True)
        return

    popups = _list_popup_posts()
    existing = _existing_popup_event_source_ids() if not args.dry_run else set()
    print(f'popup posts: {len(popups)}, already synced: {len(existing)}')
    stats = {'created': 0, 'skipped': 0, 'error': 0, 'no_period': 0}
    for src_id, title in popups:
        if src_id in existing:
            stats['skipped'] += 1
            continue
        r = create_one(src_id, title, args.dry_run)
        if r.startswith('created') or r.startswith('planned'):
            stats['created'] += 1
        elif 'no_start_date' in r:
            stats['no_period'] += 1
        else:
            stats['error'] += 1
        _log({'src_id': src_id, 'title': title[:50], 'result': r})
    print(json.dumps(stats, indent=1))


if __name__ == '__main__':
    main()
