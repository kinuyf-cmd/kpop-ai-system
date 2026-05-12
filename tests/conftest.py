"""tests/conftest.py — 全 pytest セッション共通設定

目的: テストから Anthropic / OpenAI 実APIを叩かないようにする。
背景: 2026-05-10 FACTCHECK_V2=1 本番化以降、tests/memory_compliance/test_*.py が
mock 無しで pre_publish_gate() を呼ぶことで Claude Sonnet 4.6 が実発火し、
1テスト ≒ $0.08、daily_qa cron + 開発期 pytest で月 ~$145 を浪費していた。

このファイルは pytest 自動 discovery により tests/ 配下の全テストに適用される。
個別テストファイルで明示的に unpatch したい場合は @pytest.mark.real_api を付与。
"""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

# テストランタイム識別 — lib/factcheck_v2 等が直接見ても skip 判断できるようにする
os.environ.setdefault('KPJ_TEST_MODE', '1')


def _fake_factcheck_result():
    """factcheck_v2 系の標準モック応答"""
    return {
        'score': 95,
        'critical': [],
        'high': [],
        'medium': [],
    }


def _fake_translation():
    return '[mocked translation]'


def _fake_vision_validate():
    return {
        'people_count': 1,
        'expected_artist': True,
        'verdict': 'PASS',
        'confidence': 0.95,
    }


def _fake_websearch_factcheck():
    return {
        'verdict': 'PASS',
        'confidence': 0.85,
        'sources': [],
        'has_signal': True,
    }


@pytest.fixture(autouse=True)
def block_external_apis(request, monkeypatch):
    """全テストで外部 LLM API を mock。

    real_api marker が付いている test は除外 (将来の統合テスト用)。
    """
    if request.node.get_closest_marker('real_api'):
        yield
        return

    # Claude (Anthropic) 系全ライブラリを mock
    # import先で patch する (lazy import なので import元側を patch する必要)
    patches = []

    # lib.factcheck_v2 全形態
    try:
        import lib.factcheck_v2
        patches.append(
            patch.object(lib.factcheck_v2, 'proofread_post_v2',
                         return_value=_fake_factcheck_result())
        )
    except ImportError:
        pass

    # lib.translator_v2
    try:
        import lib.translator_v2
        patches.append(
            patch.object(lib.translator_v2, 'translate_ko_to_ja_v2',
                         return_value=_fake_translation())
        )
    except ImportError:
        pass

    # lib.thumbnail_vision_gate
    try:
        import lib.thumbnail_vision_gate
        patches.append(
            patch.object(lib.thumbnail_vision_gate, 'vision_validate',
                         return_value=_fake_vision_validate())
        )
    except ImportError:
        pass

    # lib.claude_websearch_factcheck
    try:
        import lib.claude_websearch_factcheck
        patches.append(
            patch.object(lib.claude_websearch_factcheck,
                         'verify_with_claude_websearch',
                         return_value=_fake_websearch_factcheck())
        )
    except ImportError:
        pass

    # lib.kpi_analyzer
    try:
        import lib.kpi_analyzer
        if hasattr(lib.kpi_analyzer, 'analyze_with_code_execution'):
            patches.append(
                patch.object(lib.kpi_analyzer, 'analyze_with_code_execution',
                             return_value={'text': '[mocked]', 'charts': []})
            )
    except ImportError:
        pass

    # OpenAI 系 (pipeline.llm_proofreader, audit_fixer 等は urllib 直叩きなので
    # proofread_article をモック)
    try:
        import pipeline.llm_proofreader
        patches.append(
            patch.object(pipeline.llm_proofreader, 'proofread_article',
                         return_value=_fake_factcheck_result())
        )
    except ImportError:
        pass

    # 一気に patch.start() / stop()
    started = []
    try:
        for p in patches:
            started.append(p.start())
        yield
    finally:
        for p in patches:
            try:
                p.stop()
            except Exception:
                pass


def pytest_configure(config):
    """カスタム marker 登録"""
    config.addinivalue_line(
        'markers',
        'real_api: テストで実 Anthropic/OpenAI API を叩くことを許可 (デフォルトは mock)',
    )
