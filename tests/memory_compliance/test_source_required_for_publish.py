"""
memory: feedback_source_required_for_publish.md
規定: 「ソースURLなしfeature記事は全面BLOCK」
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_no_source_feature_blocks():
    """feature記事で source_url無し → BLOCK判定"""
    from lib.pre_publish_gate import pre_publish_gate
    r = pre_publish_gate(
        title='テスト記事',
        body_html='<p>' + 'A' * 600 + '</p>',
        post_type='post',
        kind='feature',
        source_url=None,
    )
    assert r['verdict'] == 'BLOCK', f"feature×no_source で BLOCK判定でない: {r['verdict']}"
    types = {i['type'] for i in r['issues']}
    assert 'feature_no_source' in types or any('feature' in t and 'source' in t for t in types), \
        f"feature_no_source が検出されない: {types}"


def test_news_no_source_blocks():
    """news記事で source/signal両方無し → BLOCK"""
    from lib.pre_publish_gate import pre_publish_gate
    r = pre_publish_gate(
        title='ニューステスト',
        body_html='<p>' + 'A' * 600 + '</p>',
        post_type='post',
        kind='news',
        source_url=None,
        source_signals=None,
    )
    types = {i['type'] for i in r['issues']}
    assert 'no_source_no_signal' in types, f"news_no_source 検出なし: {types}"
