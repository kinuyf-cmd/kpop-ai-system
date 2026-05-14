"""
2026-05-15 (作業日 5-14): cluster_dedup の single-proper-noun 盲点根治の機械検証。

事故 (5/14 監査): 23416「TAEYANG、スタイリストの不手際を告白」と
23421「TAEYANG、スタイル脱却の理由を語る」が title 単独では proper_overlap=1
(TAEYANG のみ) で擦り抜け、両方 publish された。本文はどちらも同じ
Epik High 動画「양을 놀리는 방법」を引用しており、Korean fragment が一致。

対策: cluster_dedup_check に candidate_source_url + candidate_body を渡し、
sliding-window buffer に保存された source_url / body_snippet と突合する。
"""
import sys

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_extract_korean_fragments_finds_quoted_hangul():
    from lib.cluster_dedup import _extract_korean_fragments
    text = '最近、エピックハイのメンバーが出演する動画「양을 놀리는 방법」が公開された。'
    frags = _extract_korean_fragments(text)
    # quoted 内 hangul と raw hangul の両方が拾われる
    assert '양을 놀리는 방법' in frags
    assert any('놀리는' in f for f in frags)


def test_extract_korean_fragments_empty_text():
    from lib.cluster_dedup import _extract_korean_fragments
    assert _extract_korean_fragments('') == set()
    assert _extract_korean_fragments(None) == set()


def test_extract_korean_fragments_no_hangul():
    from lib.cluster_dedup import _extract_korean_fragments
    text = 'BTS V がメキシコのファンを感動させた'
    assert _extract_korean_fragments(text) == set()


def test_record_publish_persists_source_url_and_body_snippet(tmp_path, monkeypatch):
    import lib.cluster_dedup as cd
    buf = tmp_path / 'recent.jsonl'
    monkeypatch.setattr(cd, 'RECENT_PUBLISH_BUFFER', str(buf))
    cd.record_publish('テスト', post_id=1, source='test',
                      source_url='https://example.com/article-A',
                      body='本文「양을 놀리는 방법」を含む')
    import json
    line = buf.read_text(encoding='utf-8').strip()
    d = json.loads(line)
    assert d.get('source_url') == 'https://example.com/article-A'
    assert '양을 놀리는' in d.get('body_snippet', '')


def test_cluster_dedup_check_catches_source_url_match(tmp_path, monkeypatch):
    """同一 source_url の記事は dup として検出される"""
    import lib.cluster_dedup as cd
    buf = tmp_path / 'recent.jsonl'
    monkeypatch.setattr(cd, 'RECENT_PUBLISH_BUFFER', str(buf))
    monkeypatch.setattr(cd, 'fetch_recent_wp_titles', lambda **kw: [])
    cd.record_publish('既存記事', post_id=100, source='test',
                      source_url='https://soompi.com/article-X')
    is_dup, matched = cd.cluster_dedup_check(
        '別タイトルの記事', source='test',
        candidate_source_url='https://soompi.com/article-X')
    assert is_dup is True
    assert matched == '既存記事' or 'soompi.com' in matched


def test_cluster_dedup_check_catches_korean_fragment_overlap(tmp_path, monkeypatch):
    """同一 Korean 引用フレーズの記事は dup として検出される (23416/23421 ケース)"""
    import lib.cluster_dedup as cd
    buf = tmp_path / 'recent.jsonl'
    monkeypatch.setattr(cd, 'RECENT_PUBLISH_BUFFER', str(buf))
    monkeypatch.setattr(cd, 'fetch_recent_wp_titles', lambda **kw: [])

    cd.record_publish(
        'TAEYANG、スタイリストの不手際を告白', post_id=23416, source='test',
        body='動画「양을 놀리는 방법」が公開された。タブロは...')
    is_dup, matched = cd.cluster_dedup_check(
        'TAEYANG、スタイル脱却の理由を語る', source='test',
        candidate_body='動画「양을 놀리는 방법」が公開された。エピックハイ...')
    assert is_dup is True, '同一 Korean フレーズで dup 判定されなかった'
    assert '23416' in str(matched) or 'スタイリスト' in matched


def test_cluster_dedup_check_no_false_positive_without_shared_signal(tmp_path, monkeypatch):
    """無関係な記事 (異なる固有名詞、異なる本文) は dup と判定されない"""
    import lib.cluster_dedup as cd
    buf = tmp_path / 'recent.jsonl'
    monkeypatch.setattr(cd, 'RECENT_PUBLISH_BUFFER', str(buf))
    monkeypatch.setattr(cd, 'fetch_recent_wp_titles', lambda **kw: [])
    cd.record_publish('IVE ウォニョン 新曲発売', post_id=1, source='test',
                      body='IVE のウォニョンが新曲を発表した')
    is_dup, _ = cd.cluster_dedup_check(
        'aespa カリナ コンサート開催', source='test',
        candidate_body='aespa のカリナがソウルでコンサートを開く')
    assert is_dup is False


def test_backwards_compat_record_publish_without_kwargs(tmp_path, monkeypatch):
    """既存呼出 (title だけ) も動くこと"""
    import lib.cluster_dedup as cd
    buf = tmp_path / 'recent.jsonl'
    monkeypatch.setattr(cd, 'RECENT_PUBLISH_BUFFER', str(buf))
    cd.record_publish('既存タイトル', post_id=999, source='legacy')
    # _read_recent_buffer 後方互換
    titles = cd._read_recent_buffer(hours=1)
    assert '既存タイトル' in titles


def test_simple_publish_pipeline_passes_source_url_and_body():
    src = open('/home/aiuser/kpop-ai-system/lib/simple_publish_pipeline.py',
               encoding='utf-8').read()
    assert 'candidate_source_url=source_url' in src
    assert 'candidate_body=body_ja' in src
    assert 'source_url=source_url, body=body_ja' in src


def test_unified_publisher_passes_source_url_and_body():
    src = open('/home/aiuser/kpop-ai-system/lib/unified_publisher.py',
               encoding='utf-8').read()
    assert 'candidate_source_url=source_url' in src
    assert 'candidate_body=_body_text' in src


def test_breaking_news_detector_passes_body():
    src = open('/home/aiuser/kpop-ai-system/pipeline/breaking_news_detector.py',
               encoding='utf-8').read()
    assert 'source_url=_src_url' in src
    assert 'body=r.get(' in src


def test_cluster_generator_passes_body():
    src = open('/home/aiuser/kpop-ai-system/lib/cluster_generator.py',
               encoding='utf-8').read()
    assert 'candidate_body=html' in src
    assert 'body=html or' in src
