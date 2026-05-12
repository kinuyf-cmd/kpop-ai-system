#!/usr/bin/env python3
"""user指摘頻度メトリクス可視化 (2026-05-11新設)

Usage:
  python3 scripts/user_pointed_issue_metrics.py             # 標準集計
  python3 scripts/user_pointed_issue_metrics.py --json      # JSON
  python3 scripts/user_pointed_issue_metrics.py --weekly    # 週次snapshot追加
"""
import os, json, sys
from collections import Counter
from datetime import datetime, timezone, timedelta

LOG_PATH = '/home/aiuser/kpop-ai-system/data/user_pointed_issues.jsonl'
WEEKLY_LOG = '/home/aiuser/kpop-ai-system/logs/issue_metrics_weekly.jsonl'


def main():
    args = sys.argv[1:]
    json_mode = '--json' in args
    weekly = '--weekly' in args

    if not os.path.exists(LOG_PATH):
        print('No user_pointed_issues.jsonl yet — run scripts/log_user_pointed_issue.py first')
        return

    records = []
    with open(LOG_PATH, encoding='utf-8') as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except Exception:
                continue

    now = datetime.now(timezone.utc)
    last_7d = [r for r in records
               if datetime.fromisoformat(r['ts']) >= now - timedelta(days=7)]
    last_30d = [r for r in records
                if datetime.fromisoformat(r['ts']) >= now - timedelta(days=30)]
    last_90d = [r for r in records
                if datetime.fromisoformat(r['ts']) >= now - timedelta(days=90)]

    test_covered = sum(1 for r in records if r.get('recurrence_test'))
    test_uncovered = len(records) - test_covered
    pattern_freq = Counter(r['pattern'] for r in records)
    repeat_patterns = {p: c for p, c in pattern_freq.items() if c > 1}

    severity_count = Counter(r.get('severity', 'medium') for r in records)

    summary = {
        'ts': now.isoformat(),
        'total': len(records),
        'last_7d': len(last_7d),
        'last_30d': len(last_30d),
        'last_90d': len(last_90d),
        'test_covered': test_covered,
        'test_uncovered': test_uncovered,
        'unique_patterns': len(pattern_freq),
        'repeat_patterns': repeat_patterns,
        'severity_count': dict(severity_count),
    }

    if json_mode:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print('=' * 70)
        print(f'📈 user 指摘頻度メトリクス ({summary["ts"][:10]})')
        print('=' * 70)
        print(f'累計指摘件数         : {summary["total"]}')
        print(f'  └ test 化済        : {test_covered}')
        print(f'  └ test 未化         : {test_uncovered} (未test=リスク残)')
        print(f'')
        print(f'時系列:')
        print(f'  直近 7日            : {summary["last_7d"]} 件')
        print(f'  直近 30日           : {summary["last_30d"]} 件')
        print(f'  直近 90日           : {summary["last_90d"]} 件')
        print(f'')
        print(f'severity 内訳         : {dict(severity_count)}')
        print(f'ユニークpattern        : {summary["unique_patterns"]}')
        if repeat_patterns:
            print(f'')
            print(f'⚠️ 再発pattern (test不十分):')
            for p, c in sorted(repeat_patterns.items(), key=lambda x: -x[1]):
                print(f'  {p}: {c}回')

    if weekly:
        os.makedirs(os.path.dirname(WEEKLY_LOG), exist_ok=True)
        with open(WEEKLY_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(summary, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
