"""
memory: feedback_title_faithful_translation.md
規定: 「GPTがソースにないセンセーショナルな語句をタイトルに追加する問題。pre_publish_gateでソース固有名詞との乖離チェック」
"""
import sys, inspect
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_pre_publish_gate_has_title_divergence_check():
    """pre_publish_gate に source_title diverging チェックがあること"""
    from lib import pre_publish_gate
    src = inspect.getsource(pre_publish_gate)
    assert 'source_title' in src, "pre_publish_gate に source_title 引数/比較なし"
