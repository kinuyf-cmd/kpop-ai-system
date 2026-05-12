"""
memory: feedback_pipeline_must_use_source_reader.md
規定: auto_event_article / auto_comeback_article / breaking_news_detector は
       LLM 呼び出し前に lib.source_reader.read_sources でソース本文を取得し、
       200字未満なら生成中止すること。headline だけで GPT に投げるのは捏造の温床。
"""
import sys, os, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


PIPELINE_FILES = [
    '/home/aiuser/kpop-ai-system/pipeline/auto_event_article.py',
    '/home/aiuser/kpop-ai-system/pipeline/auto_comeback_article.py',
    '/home/aiuser/kpop-ai-system/pipeline/breaking_news_detector.py',
]


def test_all_pipelines_import_source_reader():
    """3 pipeline が lib.source_reader.read_sources を import していること"""
    for p in PIPELINE_FILES:
        src = open(p, encoding='utf-8').read()
        assert 'from lib.source_reader import read_sources' in src, \
            f"{p} に `from lib.source_reader import read_sources` が無い"


def test_all_pipelines_call_read_sources():
    """3 pipeline が read_sources(...) を実際に呼んでいること"""
    for p in PIPELINE_FILES:
        src = open(p, encoding='utf-8').read()
        assert re.search(r'\bread_sources\s*\(', src), \
            f"{p} に read_sources(...) 呼出が無い"


def test_all_pipelines_block_on_short_source():
    """source_text 取得失敗時に BLOCK / 生成中止しているガード句があること。

    明示パターン `len(source_text) < 200` でも、暗黙パターン `if source_text:`
    (read_sources は内部で 200字未満を空文字に変換する契約) でも可。
    """
    for p in PIPELINE_FILES:
        src = open(p, encoding='utf-8').read()
        explicit = re.search(r'len\(\s*source_text\s*\)\s*<\s*200', src)
        implicit = re.search(r'\bif\s+source_text\s*[:)]', src) or \
                   re.search(r'\bif\s+not\s+source_text\b', src)
        assert explicit or implicit, \
            f"{p} に source_text の guard (`< 200` or `if source_text:`) が無い"


def test_source_reader_module_signature():
    """lib.source_reader.read_sources が想定 API か"""
    from lib.source_reader import read_sources
    import inspect
    sig = inspect.signature(read_sources)
    assert 'signals' in sig.parameters, \
        "read_sources(signals, ...) のシグネチャが変わっている"
