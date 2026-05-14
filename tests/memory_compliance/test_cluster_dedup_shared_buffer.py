"""
2026-05-14: lib.cluster_dedup の共通 sliding-window buffer を全 publisher に
統合した事の機械検証。新 publisher を追加した時にここで CI が落ちて気付く
ためのガード。memory: feedback_cluster_dedup_shared_buffer.md
"""
import sys
import inspect

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_cluster_dedup_module_api():
    """lib.cluster_dedup が check/record の API を露出している"""
    from lib import cluster_dedup
    assert hasattr(cluster_dedup, 'cluster_dedup_check')
    assert hasattr(cluster_dedup, 'record_publish')
    assert hasattr(cluster_dedup, 'is_duplicate_title')


def test_simple_publish_pipeline_calls_cluster_dedup():
    from lib import simple_publish_pipeline
    src = inspect.getsource(simple_publish_pipeline)
    assert 'cluster_dedup_check' in src, \
        'simple_publish_pipeline が cluster_dedup_check を呼んでない'
    assert 'record_publish' in src, \
        'simple_publish_pipeline が record_publish を呼んでない'


def test_cluster_generator_calls_cluster_dedup():
    src = open('/home/aiuser/kpop-ai-system/lib/cluster_generator.py',
               encoding='utf-8').read()
    assert 'cluster_dedup_check' in src, \
        'cluster_generator が cluster_dedup_check を呼んでない'
    assert 'record_publish' in src, \
        'cluster_generator が record_publish を呼んでない'


def test_breaking_news_detector_calls_cluster_dedup():
    src = open('/home/aiuser/kpop-ai-system/pipeline/breaking_news_detector.py',
               encoding='utf-8').read()
    assert 'cluster_dedup' in src or '_shared_buf' in src, \
        'breaking_news_detector が共通 buffer を参照してない'
    assert 'record_publish' in src, \
        'breaking_news_detector が record_publish を呼んでない'


def test_unified_publisher_calls_cluster_dedup():
    src = open('/home/aiuser/kpop-ai-system/lib/unified_publisher.py',
               encoding='utf-8').read()
    assert 'cluster_dedup_check' in src, \
        'unified_publisher が cluster_dedup_check を呼んでない'
    assert 'record_publish' in src, \
        'unified_publisher が record_publish を呼んでない'


def test_post_publish_hook_recheck_with_cluster_dedup():
    """publish 後の post_publish_hook でも cluster_dedup を再判定すること
    (WP indexing lag より早い連続 publish で pre-gate を擦り抜けた時の最終 backstop)"""
    src = open('/home/aiuser/kpop-ai-system/lib/post_publish_hook.py',
               encoding='utf-8').read()
    assert 'cluster_dedup_check' in src, \
        'post_publish_hook が cluster_dedup_check で post-publish recheck してない'
    assert 'exclude_post_id' in src, \
        'post_publish_hook で self-match 除外 (exclude_post_id) してない'


def test_is_duplicate_title_basic_proper_noun_overlap():
    """KATSEYE / TOUR / 開催 等で 2 個以上の固有名詞一致 → dup 判定"""
    from lib.cluster_dedup import is_duplicate_title
    cand = 'KATSEYE THE WILDWORLD TOUR 開催決定'
    recent = ['KATSEYE WILDWORLD TOUR 日本公演発表']
    is_dup, matched = is_duplicate_title(cand, recent)
    assert is_dup, 'KATSEYE WILDWORLD TOUR の重複が dup 判定されてない'


def test_is_duplicate_title_unrelated_no_match():
    """無関係なタイトル同士は dup 判定されない"""
    from lib.cluster_dedup import is_duplicate_title
    cand = 'BTS V ニューヨーク到着'
    recent = ['IVE ウォニョン 新作グラビア発表', 'aespa カリナ 新曲発売']
    is_dup, _ = is_duplicate_title(cand, recent)
    assert not is_dup, '無関係タイトルが誤って dup 判定された'


def test_recent_buffer_round_trip(tmp_path, monkeypatch):
    """record_publish → _read_recent_buffer の round-trip 動作"""
    import lib.cluster_dedup as cd
    buf_path = str(tmp_path / 'recent.jsonl')
    monkeypatch.setattr(cd, 'RECENT_PUBLISH_BUFFER', buf_path)
    cd.record_publish('テスト記事タイトル', post_id=99999, source='test')
    titles = cd._read_recent_buffer(hours=1)
    assert 'テスト記事タイトル' in titles
