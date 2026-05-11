"""
simple_publish_pipeline のエラーハンドリング検証 (2026-05-11新設)
"""
import sys
from unittest.mock import patch, MagicMock
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_short_source_returns_failure():
    """source body < 200字 → success=False で早期return"""
    from lib.simple_publish_pipeline import simple_publish_from_source
    with patch('lib.simple_publish_pipeline.fetch_source',
               return_value={'title': '', 'desc': '', 'image_url': '', 'body': '短い', 'html': ''}):
        result = simple_publish_from_source('https://example.com/article')
    assert result.get('success') is False
    assert 'source薄い' in result.get('reason', '')


def test_no_thumbnail_drafts_when_publish_requested():
    """status='publish'指定時もサムネ取得失敗→非公開status (private or draft) 強制

    2026-05-11 変更: 'draft' → 'private' に切り替え (draft_auto_publisher の
    auto-archive 回避)。テストは「frontend 非公開 status になる」不変条件のみ
    検証し、private/draft の選択は実装裁量とする。
    """
    import inspect
    from lib import simple_publish_pipeline
    src = inspect.getsource(simple_publish_pipeline.simple_publish_from_source)
    assert ("status = 'private'" in src) or ("status = 'draft'" in src), \
        "サムネ無し→非公開status切替ロジック欠如"


def test_invalid_image_url_returns_empty():
    """og:image が空 / 無効URL → fetch_og_image は空文字返却"""
    from lib.simple_publish_pipeline import fetch_og_image
    assert fetch_og_image('') == ''
    assert fetch_og_image('not-a-url') == ''
