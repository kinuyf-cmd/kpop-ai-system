"""
2026-05-11: feature_article_generator が DuckDuckGo で得た一般ドメインを
source_signals に積んで pre_publish_gate をすり抜けさせていた。
publish 後 hook で BLOCK→draft化→x_queue ゴミ pid のループ事故 (post 20962)。

memory: feedback_source_required_for_publish.md
       feedback_recurrence_prevention.md
"""
import inspect
import sys

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_post_to_wp_filters_untrusted_sources():
    """post_to_wp は信頼ソース0件なら publish 試行をスキップする"""
    from pipeline.feature_article_generator import post_to_wp
    src = inspect.getsource(post_to_wp)
    assert 'is_trusted_source' in src or 'is_trusted_src' in src, \
        'post_to_wp に is_trusted_source の参照がない'
    assert 'return None' in src, 'skip 経路が無い'


def test_trusted_source_passes_filter(monkeypatch):
    """信頼ドメイン (Soompi) を渡せば skip しない (= unified_publish が呼ばれる)"""
    import pipeline.feature_article_generator as fg
    called = {'flag': False}

    def fake_unified_publish(**kw):
        called['flag'] = True
        return {'success': False, 'error': 'mock'}
    monkeypatch.setattr('lib.unified_publisher.unified_publish', fake_unified_publish)

    fg.post_to_wp(
        title='テスト', content='<p>本文</p>', category_id=10,
        source_url='https://www.soompi.com/article/X',
        source_signals=[{'url': 'https://www.soompi.com/article/X', 'title': 't'}],
    )
    assert called['flag'], '信頼ドメインなのに unified_publish が呼ばれていない'


def test_untrusted_source_skips_publish(monkeypatch, capsys):
    """一般ドメインのみなら unified_publish を呼ばずに None 返す"""
    import pipeline.feature_article_generator as fg
    called = {'flag': False}

    def fake_unified_publish(**kw):
        called['flag'] = True
        return {'success': True, 'post_id': 1}
    monkeypatch.setattr('lib.unified_publisher.unified_publish', fake_unified_publish)

    r = fg.post_to_wp(
        title='テスト', content='<p>本文</p>', category_id=10,
        source_url='https://random-blog.com/post',
        source_signals=[{'url': 'https://example.com/x', 'title': 't'}],
    )
    assert r is None
    assert called['flag'] is False, '一般ドメインなのに unified_publish が呼ばれた'
