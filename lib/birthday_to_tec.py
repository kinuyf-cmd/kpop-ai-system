"""birthday_to_tec.py — birthday_master.json から TEC に誕生日イベントを投入。

戦略:
- 各メンバーの誕生日について「今年」「来年」の2年分を Events として作成
- meta_key `kpj_event_kind=birthday` でタグ付け(後で一括削除/抽出可)
- 既存の同名(name+date) は skip(冪等)
- end_date は start_date と同日、all-day flag をtrue
- title: 🎂 {name} ({group}) Birthday
- description: meta から自動構築、Idol Wiki ハブへのリンク含む

Usage:
  python3 lib/birthday_to_tec.py --dry-run   # 投入予定の件数だけ表示
  python3 lib/birthday_to_tec.py             # 実投入

ロールバック:
  python3 lib/birthday_to_tec.py --rollback   # kpj_event_kind=birthday の全削除
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path('/home/aiuser/kpop-ai-system')
DATA = ROOT / 'data/birthday_master.json'
LOG = ROOT / 'logs/birthday_to_tec.jsonl'

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


def _existing_birthday_events() -> set[tuple[str, str]]:
    """既に投入済みの (name.lower(), YYYY-MM-DD) を返す。冪等用。

    実装注: wp post list --meta_key が現環境で結果を返さないため、
    SQL を直接叩く(read-only wrapper で許可)。
    """
    sql = (
        "SELECT pm_name.post_id, pm_name.meta_value, pm_date.meta_value "
        "FROM wp_postmeta pm_name "
        "JOIN wp_postmeta pm_kind ON pm_kind.post_id=pm_name.post_id "
        "  AND pm_kind.meta_key='kpj_event_kind' AND pm_kind.meta_value='birthday' "
        "JOIN wp_postmeta pm_date ON pm_date.post_id=pm_name.post_id "
        "  AND pm_date.meta_key='_EventStartDate' "
        "WHERE pm_name.meta_key='kpj_birthday_name'"
    )
    code, out, _ = _wp(['db', 'query', sql])
    seen: set[tuple[str, str]] = set()
    if code != 0:
        return seen
    for line in out.strip().splitlines()[1:]:
        parts = line.split('\t')
        if len(parts) < 3:
            continue
        name = parts[1].strip()
        date_str = parts[2].split(' ', 1)[0]
        if name and date_str:
            seen.add((name.lower(), date_str))
    return seen


def _build_description(entry: dict) -> str:
    name = entry['name']
    group = entry['group']
    birth = entry['birthday']
    year_born = birth[:4]
    parts = [
        f'<p>🎂 <strong>{name}</strong> ({group}) の誕生日です。</p>',
        f'<p>生年: {year_born}年</p>',
    ]
    if entry.get('wp_post_id'):
        parts.append(
            f'<p><a href="/?p={entry["wp_post_id"]}">{group} のプロフィールを見る</a></p>'
        )
    return '\n'.join(parts)


def _years_to_create(today: date) -> list[int]:
    return [today.year, today.year + 1]


def create_one(entry: dict, year: int, dry_run: bool) -> str:
    """create or skip 一件。戻り値: 'created' / 'skipped' / 'error:...'"""
    mm_dd = entry['birthday'][5:]
    date_str = f'{year}-{mm_dd}'
    title = f'🎂 {entry["name"]} ({entry["group"]}) Birthday'
    desc = _build_description(entry)
    if dry_run:
        return 'created'  # 集計用

    # tribe_events として作成
    code, out, err = _wp([
        'post', 'create',
        '--post_type=tribe_events',
        '--post_status=publish',
        f'--post_title={title}',
        f'--post_content={desc}',
        '--porcelain',
    ], rw=True)
    if code != 0:
        return f'error:create:{err[:120]}'
    try:
        pid = int(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return f'error:parse_pid:{out[:80]}'

    # meta: _EventStartDate, _EventEndDate, _EventAllDay, kpj_event_kind, kpj_birthday_name
    for k, v in [
        ('_EventStartDate', f'{date_str} 00:00:00'),
        ('_EventEndDate', f'{date_str} 23:59:59'),
        ('_EventStartDateUTC', f'{date_str} 00:00:00'),
        ('_EventEndDateUTC', f'{date_str} 23:59:59'),
        ('_EventAllDay', 'yes'),
        ('_EventTimezone', 'Asia/Tokyo'),
        ('kpj_event_kind', 'birthday'),
        ('kpj_birthday_name', entry['name']),
        ('kpj_birthday_group', entry['group']),
    ]:
        c, _, e = _wp(['post', 'meta', 'update', str(pid), k, v], rw=True)
        if c != 0:
            return f'error:meta:{k}:{e[:80]}'
    return f'created:{pid}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--rollback', action='store_true')
    ap.add_argument('--limit', type=int, default=0,
                    help='テスト用: 投入件数上限')
    args = ap.parse_args()

    if args.rollback:
        code, out, _ = _wp([
            'post', 'list', '--post_type=tribe_events',
            '--meta_key=kpj_event_kind', '--meta_value=birthday',
            '--posts_per_page=2000', '--format=ids',
        ])
        ids = out.strip().split()
        print(f'rollback: {len(ids)} events 削除予定')
        if not ids or args.dry_run:
            return
        for pid in ids:
            _wp(['post', 'delete', pid, '--force'], rw=True)
        print(f'rollback: 削除完了 ({len(ids)})')
        return

    entries = json.loads(DATA.read_text(encoding='utf-8'))
    if args.limit:
        entries = entries[:args.limit]
    existing = _existing_birthday_events() if not args.dry_run else set()
    today = date.today()
    years = _years_to_create(today)

    stats = {'created': 0, 'skipped': 0, 'error': 0, 'planned': 0}
    for e in entries:
        for y in years:
            stats['planned'] += 1
            mmdd = e['birthday'][5:]
            key = (e['name'].lower(), f'{y}-{mmdd}')
            if key in existing:
                stats['skipped'] += 1
                continue
            r = create_one(e, y, args.dry_run)
            if r.startswith('created'):
                stats['created'] += 1
                if not args.dry_run:
                    _log({'name': e['name'], 'group': e['group'],
                          'date': f'{y}-{mmdd}', 'result': r})
            else:
                stats['error'] += 1
                _log({'name': e['name'], 'group': e['group'],
                      'date': f'{y}-{mmdd}', 'result': r})

    print(json.dumps(stats, indent=1))


if __name__ == '__main__':
    main()
