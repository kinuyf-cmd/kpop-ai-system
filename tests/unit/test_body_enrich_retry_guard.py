#!/usr/bin/env python3
"""factcheck で弾かれ続ける記事を、毎週リトライしないためのガード。

2026-08-23 実測: body_enrich は同じ3記事を毎週処理し、毎回 factcheck_block。
factcheck は月4,212円で最大のコスト項目なので、成功しない対象への再試行は
そのまま無駄になる。3回連続で弾かれた記事は候補から外す。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from lib.body_enrich import blocked_too_often, MAX_FACTCHECK_BLOCKS

HIST = [
    {"slug": "a", "result": "factcheck_block"},
    {"slug": "a", "result": "factcheck_block"},
    {"slug": "a", "result": "factcheck_block"},
    {"slug": "b", "result": "factcheck_block"},
    {"slug": "c", "result": "updated"},
    {"slug": "c", "result": "factcheck_block"},
    {"slug": "d", "result": "skip"},
]


class TestBlockedTooOften:
    def test_three_blocks_is_excluded(self):
        assert blocked_too_often("a", HIST)

    def test_one_block_is_not_excluded(self):
        assert not blocked_too_often("b", HIST)

    def test_success_after_block_resets(self):
        """一度成功している記事は、その後の1回ブロックで切らない。"""
        assert not blocked_too_often("c", HIST)

    def test_unknown_slug_is_allowed(self):
        assert not blocked_too_often("zzz", HIST)

    def test_non_block_results_are_ignored(self):
        assert not blocked_too_often("d", HIST)

    def test_threshold_is_sane(self):
        assert 2 <= MAX_FACTCHECK_BLOCKS <= 5
