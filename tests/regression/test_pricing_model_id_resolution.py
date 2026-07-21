"""PRICING の解決が日付サフィックス付きモデルIDでも正しく効くことの回帰テスト。

背景 (2026-07-21):
  PRICING のキーは 'claude-haiku-4-5' だが、lib/thumbnail_relevance_audit.py が渡す
  モデルIDは 'claude-haiku-4-5-20251001' (日付サフィックス付き)。
  _calc_cost は dict.get の完全一致で引くため未ヒットとなり、default の
  claude-sonnet-4-6 単価 ($3/$15) にフォールバックしていた。
  Haiku の実単価は $1/$5 なので、計上額が実費の約3倍に膨らむ。
"""
import sys

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

from lib.anthropic_cost_guard import _calc_cost, PRICING  # noqa: E402


USAGE = {'input': 1_000_000, 'output': 0, 'cache_create': 0, 'cache_read': 0}


def test_dated_haiku_id_resolves_to_haiku_pricing():
    """日付サフィックス付き Haiku ID が Haiku 単価で計算されること。"""
    dated = _calc_cost('claude-haiku-4-5-20251001', USAGE)
    plain = _calc_cost('claude-haiku-4-5', USAGE)
    assert dated == plain, (
        f'日付サフィックス付きIDが別単価で計算されている: '
        f'{dated} != {plain} (Sonnet単価にフォールバックしている疑い)'
    )
    assert dated == PRICING['claude-haiku-4-5']['input'], (
        f'Haiku 入力単価 $1/MTok で計算されていない: {dated}'
    )


def test_dated_sonnet_id_resolves_to_sonnet_pricing():
    """Sonnet 側も同様に日付サフィックスを吸収すること。"""
    assert _calc_cost('claude-sonnet-5-20250101', USAGE) == _calc_cost('claude-sonnet-5', USAGE)


def test_unknown_model_falls_back_conservatively():
    """未知モデルは高め (保守側) の単価で計上しアラートが早く鳴ること。"""
    got = _calc_cost('claude-something-unknown', USAGE)
    assert got >= PRICING['claude-haiku-4-5']['input'], (
        '未知モデルが Haiku より安く見積もられると予算アラートが鳴り遅れる'
    )
