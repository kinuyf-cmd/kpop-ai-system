#!/usr/bin/env python3
"""user指摘1件を data/user_pointed_issues.jsonl に記録 (2026-05-11新設)

Usage:
  python3 scripts/log_user_pointed_issue.py \\
    --pattern thumbnail_priority_inverted \\
    --user-prompt "なぜソース先からとってきていないのですか？" \\
    --fix "resolve()内のpriority順を逆転、unified_publisher/auto_repair に source_url plumbing" \\
    --severity high \\
    --recurrence_test test_og_image_universal_attempt.py
"""
import argparse, json, os
from datetime import datetime, timezone


LOG_PATH = '/home/aiuser/kpop-ai-system/data/user_pointed_issues.jsonl'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pattern', required=True, help='エラーパターン名 (error_patterns.jsonと同期)')
    ap.add_argument('--user-prompt', required=True, help='ユーザーが指摘した発話')
    ap.add_argument('--fix', required=True, help='修正内容')
    ap.add_argument('--severity', default='medium', choices=['low', 'medium', 'high', 'critical'])
    ap.add_argument('--recurrence_test', default='', help='追加した memory_compliance test file名')
    ap.add_argument('--session', default='', help='session id')
    args = ap.parse_args()

    record = {
        'ts': datetime.now(timezone.utc).isoformat(),
        'pattern': args.pattern,
        'user_prompt': args.user_prompt,
        'fix': args.fix,
        'severity': args.severity,
        'recurrence_test': args.recurrence_test,
        'session_id': args.session,
    }
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(f'logged: {args.pattern} ({args.severity})')


if __name__ == '__main__':
    main()
