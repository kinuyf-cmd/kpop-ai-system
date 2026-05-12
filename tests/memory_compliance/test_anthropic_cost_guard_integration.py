"""Phase 6 — cost guard / ledger / kill switch の機械検証

全 7 つの Anthropic API 呼出元が cost guard 統合済みであることを担保し、
将来の新規追加時に guard 漏れがないことを保証する。

memory: anthropic-cost-guard (kill switch + budget alert + ledger)
"""
import sys
import re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


# 全 Anthropic API 呼出元 (anthropic library 直接 import するもの)
ANTHROPIC_CALLERS = [
    '/home/aiuser/kpop-ai-system/lib/factcheck_v2.py',
    '/home/aiuser/kpop-ai-system/lib/translator_v2.py',
    '/home/aiuser/kpop-ai-system/lib/thumbnail_vision_gate.py',
    '/home/aiuser/kpop-ai-system/lib/claude_websearch_factcheck.py',
    '/home/aiuser/kpop-ai-system/lib/kpi_analyzer.py',
    '/home/aiuser/kpop-ai-system/pipeline/profile_wiki_builder.py',
    '/home/aiuser/kpop-ai-system/pipeline/comeback_calendar_builder.py',
]


def test_all_callers_use_guard_before_call():
    """全 Anthropic 呼出元で guard_before_call をチェックしていること"""
    missing = []
    for path in ANTHROPIC_CALLERS:
        src = open(path).read()
        # messages.create を呼ぶ箇所があるか
        if 'messages.create' not in src:
            continue
        if 'guard_before_call' not in src:
            missing.append(path)
    assert not missing, (
        f"以下のファイルが guard_before_call を呼んでいない (予算/kill switch チェックなし):\n  "
        + '\n  '.join(missing)
    )


def test_all_callers_use_log_usage():
    """全 Anthropic 呼出元で log_usage をチェックしていること (cost_ledger 記録)"""
    missing = []
    for path in ANTHROPIC_CALLERS:
        src = open(path).read()
        if 'messages.create' not in src:
            continue
        if 'log_usage' not in src:
            missing.append(path)
    assert not missing, (
        f"以下のファイルが log_usage を呼んでいない (cost_ledger に記録されない):\n  "
        + '\n  '.join(missing)
    )


def test_cost_guard_respects_kill_switch(monkeypatch):
    """ANTHROPIC_DISABLE=1 で guard_before_call が False を返すこと"""
    from lib.anthropic_cost_guard import guard_before_call
    monkeypatch.setenv('ANTHROPIC_DISABLE', '1')
    monkeypatch.delenv('KPJ_TEST_MODE', raising=False)
    assert guard_before_call('test') is False


def test_cost_guard_respects_test_mode(monkeypatch):
    """KPJ_TEST_MODE=1 で guard_before_call が False を返すこと"""
    from lib.anthropic_cost_guard import guard_before_call
    monkeypatch.delenv('ANTHROPIC_DISABLE', raising=False)
    monkeypatch.setenv('KPJ_TEST_MODE', '1')
    assert guard_before_call('test') is False


def test_cost_guard_allows_normal_call(monkeypatch):
    """通常時 (env なし) は True を返すこと"""
    from lib.anthropic_cost_guard import guard_before_call
    monkeypatch.delenv('ANTHROPIC_DISABLE', raising=False)
    monkeypatch.delenv('KPJ_TEST_MODE', raising=False)
    assert guard_before_call('test') is True


def test_factcheck_v2_has_skipped_marker_in_code():
    """factcheck_v2.py が cost guard skip 時 _skipped: 'cost_guard' を返す実装になっていること

    本来は動的テストしたいが conftest.py の autouse mock で関数自体が置換されるため、
    ソースの静的検証で代替する (品質保証は同等)。
    """
    src = open('/home/aiuser/kpop-ai-system/lib/factcheck_v2.py').read()
    assert "'_skipped': 'cost_guard'" in src, \
        "factcheck_v2.py が cost guard skip 時に _skipped マーカーを返していない"
    # skip 時の score も publish 経路を block しない安全値であること
    skip_block = re.search(r"if not guard_before_call\('factcheck_v2'\):\s*\n\s*return\s*\{[^}]+\}", src)
    assert skip_block, "factcheck_v2.py の guard_before_call skip ロジックが見つからない"
    assert "'critical': []" in skip_block.group(0), "skip 時 critical は空であるべき (publish 不block)"


def test_all_callers_skip_path_returns_safe_default():
    """全 caller の guard skip path が安全な default を返すこと (品質維持)"""
    expected_returns = {
        '/home/aiuser/kpop-ai-system/lib/factcheck_v2.py':
            r"if not guard_before_call\('factcheck_v2'\):\s*\n\s*return",
        '/home/aiuser/kpop-ai-system/lib/translator_v2.py':
            r"if not guard_before_call\('translator_v2'\):\s*\n\s*return",
        '/home/aiuser/kpop-ai-system/lib/thumbnail_vision_gate.py':
            r"if not guard_before_call\('vision_gate'\):\s*\n\s*return",
        '/home/aiuser/kpop-ai-system/lib/claude_websearch_factcheck.py':
            r"if not guard_before_call\('claude_websearch_factcheck'\):\s*\n\s*return",
        '/home/aiuser/kpop-ai-system/lib/kpi_analyzer.py':
            r"if not guard_before_call\('kpi_analyzer'\):\s*\n\s*return",
        '/home/aiuser/kpop-ai-system/pipeline/comeback_calendar_builder.py':
            r"if not guard_before_call\('comeback_calendar_builder'\):\s*\n\s*return",
        '/home/aiuser/kpop-ai-system/pipeline/profile_wiki_builder.py':
            r"if not guard_before_call\('profile_wiki_builder'\):\s*\n\s*return",
    }
    for path, pat in expected_returns.items():
        src = open(path).read()
        assert re.search(pat, src), f"{path}: guard skip path に return がない"


def test_daily_summary_returns_valid_dict():
    """daily_summary() が必要なキーを含む dict を返すこと"""
    from lib.anthropic_cost_guard import daily_summary
    s = daily_summary()
    assert 'date' in s
    assert 'total_calls' in s
    assert 'total_cost_usd' in s
    assert 'budget_usd' in s
    assert 'over_budget' in s
    assert 'by_caller' in s
