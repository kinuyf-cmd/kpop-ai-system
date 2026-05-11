"""
memory: feedback_generate_after_verify.md
規定: 「事実をTavilyで集めてから書かせる。書かせてから検証は40%エラー率の原因」
"""
import sys, inspect, os
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_source_reader_module_exists():
    """source事前読み取りパスが存在"""
    from lib import source_reader
    assert hasattr(source_reader, 'read_source')


def test_proofreader_uses_source_section():
    """proofreader が source記事の本文をプロンプトに注入すること"""
    from pipeline import llm_proofreader
    src = inspect.getsource(llm_proofreader)
    assert 'source_section' in src or 'read_source' in src, \
        "proofreader にソース本文注入ロジックなし"
