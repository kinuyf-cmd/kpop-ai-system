"""
2026-05-11新ルール: factcheck cache を盲信しない仕組み
今日のセッションで cached HIGH を真実扱いした事故 (19453 MY WORLD 誤記見逃し) の再発防止。

検証:
  - _already_proofread の TTL が 24h より短い (頻繁に再実行される)
  - force=True オプションで cache無視できる
  - cache hit 時も visible なログ出力 (silent skipしない)
"""
import sys, inspect
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_proofread_cache_ttl_under_24h():
    """_already_proofread の TTL が 24h以内"""
    from pipeline import llm_proofreader
    src = inspect.getsource(llm_proofreader._already_proofread)
    # cutoff = ... timedelta(hours=N)
    import re
    m = re.search(r'timedelta\(hours=(\d+)\)', src)
    assert m, "TTL定数が見つからない"
    ttl_hours = int(m.group(1))
    assert ttl_hours <= 24, f"TTL {ttl_hours}h は長すぎる (24h以内推奨)"


def test_proofread_cache_supports_force():
    """force=True option で cacheスキップ可能"""
    from pipeline import llm_proofreader
    sig = inspect.signature(llm_proofreader._already_proofread)
    assert 'force' in sig.parameters, \
        "_already_proofread に force パラメータなし — cache強制無視できない"


def test_audit_completion_check_runs_memory_compliance():
    """Stop hook が cache mtime + memory_compliance test 両方確認"""
    p = '/home/aiuser/kpop-ai-system/.claude/hooks/audit_completion_check.py'
    src = open(p, encoding='utf-8').read()
    # mtime check
    assert 'mtime' in src or 'getmtime' in src, "audit_steps mtime check なし"
    # memory_compliance test invocation
    assert 'memory_compliance' in src and 'pytest' in src, \
        "memory_compliance test invocation なし"
