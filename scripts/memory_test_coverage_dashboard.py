#!/usr/bin/env python3
"""memory_compliance test カバレッジダッシュボード (2026-05-11新設)

Usage:
  python3 scripts/memory_test_coverage_dashboard.py             # 標準出力
  python3 scripts/memory_test_coverage_dashboard.py --json      # JSON出力
  python3 scripts/memory_test_coverage_dashboard.py --weekly    # 週次snapshot追加
"""
import os, glob, json, sys
from datetime import datetime, timezone

MEMORY_DIR = '/home/aiuser/.claude/projects/-home-aiuser-kpop-ai-system/memory'
TEST_DIR = '/home/aiuser/kpop-ai-system/tests/memory_compliance'
WEEKLY_LOG = '/home/aiuser/kpop-ai-system/logs/coverage_weekly.jsonl'


def main():
    args = sys.argv[1:]
    json_mode = '--json' in args
    weekly = '--weekly' in args

    def _strip_prefix(name, prefix, suffix):
        """prefix/suffix を1回だけ除去 (replace は多重置換されるため使えない)"""
        if name.startswith(prefix):
            name = name[len(prefix):]
        if name.endswith(suffix):
            name = name[:-len(suffix)]
        return name

    feedback_memos = sorted(_strip_prefix(os.path.basename(p), 'feedback_', '.md')
                            for p in glob.glob(f'{MEMORY_DIR}/feedback_*.md'))
    test_files = sorted(_strip_prefix(os.path.basename(p), 'test_', '.py')
                        for p in glob.glob(f'{TEST_DIR}/test_*.py'))

    # マッピング: memory key → test exists
    memo_set = set(feedback_memos)
    test_set = set(test_files)
    covered = memo_set & test_set
    uncovered = memo_set - test_set
    extra = test_set - memo_set  # memory無いがtestあり (cross-cutting test)

    # 戦略系memoryは test 化対象外にカウント
    STRATEGIC = {
        'content_quality_revolution', 'idol_youtube_content', 'music_show_rankings',
        'pv_maximization_principles', 'winner_article_expansion',
        'kpopjournal_design_direction', 'keyword_cannibalization',
        'kpi_logic_audit',
    }
    PROCEDURAL_NO_TEST = {
        'fix_all_paths', 'never_override_user_rules', 'no_excuses_follow_rules',
    }
    testable = memo_set - STRATEGIC - PROCEDURAL_NO_TEST
    testable_covered = covered & testable
    testable_uncovered = testable - covered

    coverage_pct = round(100 * len(testable_covered) / max(1, len(testable)), 1)

    summary = {
        'ts': datetime.now(timezone.utc).isoformat(),
        'memo_total': len(memo_set),
        'test_total': len(test_set),
        'testable_memo': len(testable),
        'testable_covered': len(testable_covered),
        'testable_uncovered_count': len(testable_uncovered),
        'testable_uncovered_list': sorted(testable_uncovered),
        'coverage_pct': coverage_pct,
        'strategic_excluded': len(STRATEGIC),
        'procedural_excluded': len(PROCEDURAL_NO_TEST),
        'extra_tests_no_memo': sorted(extra),
    }

    if json_mode:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print('=' * 70)
        print(f'📊 memory_compliance test カバレッジ ({summary["ts"][:10]})')
        print('=' * 70)
        print(f'memory file 総数      : {summary["memo_total"]}')
        print(f'test file 総数        : {summary["test_total"]}')
        print(f'test化対象 memo       : {summary["testable_memo"]} (戦略{len(STRATEGIC)}+procedural{len(PROCEDURAL_NO_TEST)} 除外)')
        print(f'  └ test済           : {summary["testable_covered"]}')
        print(f'  └ 未test           : {summary["testable_uncovered_count"]}')
        print(f'')
        print(f'カバレッジ            : {coverage_pct}%')
        bar_len = int(coverage_pct / 2)
        print(f'  [{"█" * bar_len}{"░" * (50 - bar_len)}] {coverage_pct}%')
        print(f'')
        if testable_uncovered:
            print(f'未test memo ({len(testable_uncovered)}件):')
            for m in sorted(testable_uncovered):
                print(f'  - feedback_{m}.md')

    if weekly:
        os.makedirs(os.path.dirname(WEEKLY_LOG), exist_ok=True)
        with open(WEEKLY_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(summary, ensure_ascii=False) + '\n')
        if not json_mode:
            print(f'\nweekly snapshot saved: {WEEKLY_LOG}')


if __name__ == '__main__':
    main()
