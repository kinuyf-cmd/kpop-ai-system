"""memory_compliance テスト共通設定"""
import sys, os
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def pytest_collection_modifyitems(config, items):
    """memory_compliance テストには `compliance` マーカーを自動付与"""
    import pytest
    for item in items:
        if 'memory_compliance' in str(item.fspath):
            item.add_marker(pytest.mark.compliance)
