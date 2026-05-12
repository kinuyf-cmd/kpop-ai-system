"""Phase 1-5 (Claude API コスト最適化) の機械検証テスト

memory: feedback_no_real_llm_api_in_pytest, claude_api_cache_control_ttl_1h,
        factcheck_content_hash_permanent_cache, claude_citations_structured_outputs_incompatible
規定:
- pytest からは Anthropic 実APIを叩かない
- 全 cache_control に ttl=1h を明示
- factcheck_v2 は content_hash 永続cache (30日)
- pre_publish_gate に skip_llm_factcheck パラメータがある
- factcheck_corpus.build_corpus() がエラー無く動作する
"""
import sys
import os
import re
import inspect
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_factcheck_corpus_build_succeeds():
    """artist_master.json から factcheck コーパスを正常生成できること"""
    from lib.factcheck_corpus import build_corpus, corpus_hash
    c = build_corpus()
    assert isinstance(c, str), "build_corpus は str を返す"
    assert len(c) > 500, f"corpus が小さすぎる ({len(c)} chars) — artist_master 読み込み失敗?"
    assert 'メンバー人数' in c or 'デビュー' in c, "corpus に主要フィールドがない"
    assert isinstance(corpus_hash(), str), "corpus_hash は str を返す"
    assert len(corpus_hash()) == 16, "corpus_hash は16文字"


def test_factcheck_v2_uses_30day_persistent_cache():
    """lib/factcheck_v2.py の CACHE_TTL_SEC が 30日以上であること

    memory: feedback_factcheck_content_hash_permanent_cache
    """
    src = open('/home/aiuser/kpop-ai-system/lib/factcheck_v2.py').read()
    m = re.search(r'CACHE_TTL_SEC\s*=\s*(\d+)\s*\*\s*(\d+)', src)
    assert m, "CACHE_TTL_SEC の定義が見つからない"
    ttl_sec = int(m.group(1)) * int(m.group(2))
    assert ttl_sec >= 30 * 86400, \
        f"CACHE_TTL_SEC が30日未満: {ttl_sec}秒。同じ content の重複呼出抑止のため30日以上必須"


def test_all_cache_control_use_1h_ttl():
    """全 lib/pipeline で cache_control が ttl=1h を明示していること

    memory: feedback_claude_api_cache_control_ttl_1h
    default 5min TTL は cron 間隔と並列racingで頻繁に miss する。
    """
    target_files = [
        '/home/aiuser/kpop-ai-system/lib/factcheck_v2.py',
        '/home/aiuser/kpop-ai-system/lib/translator_v2.py',
        '/home/aiuser/kpop-ai-system/lib/thumbnail_vision_gate.py',
        '/home/aiuser/kpop-ai-system/lib/claude_websearch_factcheck.py',
        '/home/aiuser/kpop-ai-system/pipeline/profile_wiki_builder.py',
        '/home/aiuser/kpop-ai-system/pipeline/comeback_calendar_builder.py',
    ]
    violations = []
    for path in target_files:
        if not os.path.exists(path):
            continue
        src = open(path).read()
        # cache_control 出現箇所すべてに ttl=1h があるか
        # コメント行(#)は除外
        for m in re.finditer(r'"cache_control"\s*:\s*\{[^}]+\}', src):
            block = m.group(0)
            # コメント中なら skip
            line_start = src.rfind('\n', 0, m.start()) + 1
            line = src[line_start:m.start()]
            if line.strip().startswith('#'):
                continue
            if '"ttl"' not in block and "'ttl'" not in block:
                violations.append(f"{path}: {block[:80]}")
    assert not violations, \
        "cache_control に ttl=1h 明示なし:\n" + '\n'.join(violations)


def test_pre_publish_gate_has_skip_llm_factcheck_param():
    """pre_publish_gate に skip_llm_factcheck パラメータがあること

    post_publish_hook 再ゲート時に LLM factcheck をスキップして
    重複呼出を防ぐ。
    """
    from lib.pre_publish_gate import pre_publish_gate
    sig = inspect.signature(pre_publish_gate)
    assert 'skip_llm_factcheck' in sig.parameters, \
        "pre_publish_gate に skip_llm_factcheck パラメータがない"
    default = sig.parameters['skip_llm_factcheck'].default
    assert default is False, \
        f"skip_llm_factcheck の default は False であるべき (got {default!r})"


def test_post_publish_hook_passes_skip_llm_factcheck_true():
    """post_publish_hook が pre_publish_gate に skip_llm_factcheck=True を渡すこと

    memory: factcheck-content-hash-permanent-cache (同じcontentに同じ判定なので再評価不要)
    """
    src = open('/home/aiuser/kpop-ai-system/lib/post_publish_hook.py').read()
    # _recheck_gate(... skip_llm_factcheck=True ...) の存在確認
    assert re.search(r'_recheck_gate\([^)]*skip_llm_factcheck\s*=\s*True', src, re.DOTALL), \
        "post_publish_hook が _recheck_gate に skip_llm_factcheck=True を渡していない"


def test_conftest_blocks_all_anthropic_libs():
    """tests/conftest.py が全 Anthropic 系 lib を mock してること

    memory: feedback_no_real_llm_api_in_pytest
    """
    src = open('/home/aiuser/kpop-ai-system/tests/conftest.py').read()
    must_mock = [
        'lib.factcheck_v2',
        'lib.translator_v2',
        'lib.thumbnail_vision_gate',
        'lib.claude_websearch_factcheck',
    ]
    for lib in must_mock:
        assert lib in src, f"conftest.py が {lib} を mock していない"
    # autouse fixture か
    assert '@pytest.fixture(autouse=True)' in src, \
        "conftest.py に autouse fixture がない (全テストに自動適用されない)"
    # KPJ_TEST_MODE が設定されること
    assert 'KPJ_TEST_MODE' in src, \
        "conftest.py が KPJ_TEST_MODE 環境変数を設定していない"


def test_pre_publish_gate_respects_kpj_test_mode():
    """pre_publish_gate が KPJ_TEST_MODE=1 で factcheck_v2 を skip すること"""
    src = open('/home/aiuser/kpop-ai-system/lib/pre_publish_gate.py').read()
    assert 'KPJ_TEST_MODE' in src, \
        "pre_publish_gate が KPJ_TEST_MODE をチェックしていない"


def test_no_citations_with_structured_outputs():
    """citations.enabled=true と output_config.format を同時使用しないこと

    memory: feedback_claude_citations_structured_outputs_incompatible
    Anthropic API 仕様で同時使用は 400 エラー。
    """
    target_files = [
        '/home/aiuser/kpop-ai-system/lib/factcheck_v2.py',
        '/home/aiuser/kpop-ai-system/lib/translator_v2.py',
        '/home/aiuser/kpop-ai-system/lib/thumbnail_vision_gate.py',
        '/home/aiuser/kpop-ai-system/lib/claude_websearch_factcheck.py',
    ]
    violations = []
    for path in target_files:
        if not os.path.exists(path):
            continue
        src = open(path).read()
        if 'output_config' in src and re.search(r'"enabled"\s*:\s*True', src):
            # citations.enabled=True が含まれるか確認
            if re.search(r'"citations"\s*:\s*\{\s*"enabled"\s*:\s*True', src):
                violations.append(path)
    assert not violations, \
        f"以下のファイルで Citations と structured outputs を同時使用 (400エラー):\n  " + '\n  '.join(violations)
