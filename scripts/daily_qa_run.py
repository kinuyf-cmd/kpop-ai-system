#!/usr/bin/env python3
"""Daily QA full pytest run + memory rule coverage (2026-05-12新設)

毎朝 cron で:
  1. `pytest tests/` を全走 (regression 検知)
  2. memory feedback rule の test 化カバレッジ計測 (`memory_test_coverage_dashboard --json`)

失敗 / coverage regression は Discord error チャネル通知。
Stop hook 経由の memory_compliance テストは私 (claude) が動かない夜間に走らないため
daily で全件を回して regression を早期検知する。

cron想定:
  15 5 * * * cd /home/aiuser/kpop-ai-system && python3 scripts/daily_qa_run.py >> logs/daily_qa.log 2>&1

env:
  DAILY_QA_NOTIFY_OK=1     : 成功時も morning チャネルへ通知 (default: 失敗時のみ)
  DAILY_QA_COVERAGE_FLOOR  : coverage_pct がこの値を下回ったら regression 扱い (default: 80.0)
"""
import os, re, sys, json, subprocess
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.discord_channel_router import send_to_channel, ChannelType

JST = timezone(timedelta(hours=9))
ROOT = '/home/aiuser/kpop-ai-system'
NOTIFY_ON_SUCCESS = os.environ.get('DAILY_QA_NOTIFY_OK', '0') == '1'
COVERAGE_FLOOR = float(os.environ.get('DAILY_QA_COVERAGE_FLOOR', '80.0'))


def run_pytest():
    r = subprocess.run(
        ['python3', '-m', 'pytest', 'tests/', '-q', '--tb=short',
         '--no-header', '-p', 'no:warnings'],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )
    out = (r.stdout or '') + (r.stderr or '')
    return {
        'rc': r.returncode,
        'out': out,
        'failed': int((re.search(r'(\d+) failed', out) or [None, '0'])[1]),
        'passed': int((re.search(r'(\d+) passed', out) or [None, '0'])[1]),
        'error': int((re.search(r'(\d+) error', out) or [None, '0'])[1]),
    }


def run_coverage():
    """memory_test_coverage_dashboard.py --json を実行して dict 返却"""
    r = subprocess.run(
        ['python3', 'scripts/memory_test_coverage_dashboard.py', '--json'],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    try:
        return json.loads(r.stdout)
    except Exception as e:
        return {'error': str(e), 'stdout': r.stdout[:500], 'stderr': r.stderr[:500]}


def main():
    now = datetime.now(JST)
    print(f"=== Daily QA Run {now.strftime('%Y-%m-%d %H:%M JST')} ===")

    # --- 1. pytest 全走 ---
    pt = run_pytest()
    print(pt['out'])
    pytest_failed = pt['rc'] != 0 or pt['failed'] > 0 or pt['error'] > 0

    # --- 2. memory rule coverage ---
    cov = run_coverage()
    if 'error' in cov:
        cov_pct = None
        cov_summary = f"[coverage取得失敗] {cov['error']}"
        coverage_regression = False
    else:
        cov_pct = cov.get('coverage_pct', 0)
        uncov_list = cov.get('testable_uncovered_list', [])
        cov_summary = (
            f"memory={cov['memo_total']} test={cov['test_total']} "
            f"coverage={cov_pct}% ({cov['testable_covered']}/{cov['testable_memo']}) "
            f"uncovered={cov['testable_uncovered_count']}"
        )
        coverage_regression = cov_pct < COVERAGE_FLOOR

    print(f"\n--- coverage ---\n{cov_summary}")
    if cov_pct is not None and cov.get('testable_uncovered_list'):
        print(f"未test memo ({len(cov['testable_uncovered_list'])}件):")
        for m in cov['testable_uncovered_list']:
            print(f"  - feedback_{m}.md")

    # --- 3. 判定 + 通知 ---
    if pytest_failed:
        title = f"🔴 Daily QA 失敗  failed={pt['failed']} error={pt['error']} passed={pt['passed']}"
        tail = '\n'.join(pt['out'].splitlines()[-30:])[:1500]
        body = (
            f"```\n{tail}\n```\n"
            f"coverage: {cov_summary}\n"
            f"log: logs/daily_qa.log  rc={pt['rc']}"
        )
        send_to_channel(ChannelType.ERROR, title, body)
        print(f"\n[notify] Discord error: {pt['failed']} failed / {pt['error']} error")
        sys.exit(1)

    if coverage_regression:
        uncov_list = cov.get('testable_uncovered_list', [])
        uncov_show = '\n'.join(f'  - feedback_{m}.md' for m in uncov_list[:10])
        title = f"⚠️ memory coverage 低下 {cov_pct}% (floor={COVERAGE_FLOOR}%)"
        body = (
            f"pytest: {pt['passed']} pass (OK)\n\n"
            f"memory coverage 不足: {cov['testable_uncovered_count']}件未test\n"
            f"```\n{uncov_show}\n```\n"
            f"floor={COVERAGE_FLOOR}% を下回ったため通知。"
            f"閾値調整は env DAILY_QA_COVERAGE_FLOOR で可。"
        )
        send_to_channel(ChannelType.ERROR, title, body)
        print(f"\n[notify] Discord error: coverage regression {cov_pct}% < {COVERAGE_FLOOR}%")
        # coverage 低下は pytest 失敗ほど致命ではないので exit 0 (cron 連続失敗扱いにしない)

    if NOTIFY_ON_SUCCESS and not coverage_regression:
        send_to_channel(
            ChannelType.MORNING,
            f"✅ Daily QA pass ({pt['passed']} tests, coverage {cov_pct}%)",
            f"pytest全 {pt['passed']} 通過 / memory coverage {cov_pct}% @ {now.strftime('%H:%M JST')}"
        )

    print(f"\n[OK] pytest {pt['passed']} passed / coverage {cov_pct}%")


if __name__ == '__main__':
    main()
