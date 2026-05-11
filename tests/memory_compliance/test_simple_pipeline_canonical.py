"""
2026-05-11新ルール: simple_publish_pipeline が canonical 実装として保護されること
他 generator はこの pipeline に統合されるか、同等のog:image priorityを守る
"""
import sys, inspect
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_simple_pipeline_module_exists():
    """canonical pipeline が import可能"""
    from lib import simple_publish_pipeline as spp
    assert hasattr(spp, 'simple_publish_from_source')
    assert hasattr(spp, 'fetch_source')
    assert hasattr(spp, 'fetch_og_image')


def test_simple_pipeline_default_status_draft():
    """安全のため default status='draft' であること"""
    from lib.simple_publish_pipeline import simple_publish_from_source
    sig = inspect.signature(simple_publish_from_source)
    assert sig.parameters['status'].default == 'draft', \
        f"default status は draft でない: {sig.parameters['status'].default}"


def test_simple_pipeline_validates_og_image():
    """fetch_og_image がportrait/極小拒否ロジックを持つ"""
    from lib import simple_publish_pipeline
    src = inspect.getsource(simple_publish_pipeline.fetch_og_image)
    assert 'portrait' in src.lower() and 'h > w' in src, \
        "portrait拒否ロジックなし"
    assert 'too small' in src.lower() or 'w <' in src, \
        "極小拒否ロジックなし"


def test_simple_pipeline_drafts_on_no_thumbnail():
    """サムネ取得失敗 → status='draft'強制"""
    from lib import simple_publish_pipeline
    src = inspect.getsource(simple_publish_pipeline.simple_publish_from_source)
    assert 'status = \'draft\'' in src or "status='draft'" in src, \
        "サムネ無し時のdraft強制ロジックなし"


def test_simple_pipeline_loc_under_300():
    """canonical pipeline は単純さを保つ (300行以下)"""
    import os
    p = '/home/aiuser/kpop-ai-system/lib/simple_publish_pipeline.py'
    line_count = sum(1 for _ in open(p, encoding='utf-8'))
    assert line_count < 300, f"{line_count}行 — canonical pipelineが肥大化"
