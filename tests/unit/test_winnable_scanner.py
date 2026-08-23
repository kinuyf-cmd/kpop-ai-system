#!/usr/bin/env python3
"""「3位以内を取れる」領域だけを狙うための候補抽出。

2026-08-23 実測の背景:
  page_one_tracker は5週連続で pos<3 進入がゼロ。CTRは pos1-3 で 6.96%、
  pos4-10 では 2% 前後しかないため、4-10位で頑張っても回収できない。
  一方、実際に pos<=3 を取れているクエリを見ると:
    複合語(2語以上) CTR 21.4% / 単独名詞 CTR 14.2%
  つまり「勝てる場所」には特徴がある。そこだけを狙う。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from lib.winnable_scanner import is_winnable, score_candidate, BRAND_RE


def q(query, imp, clicks, position):
    return {"keys": [query], "impressions": imp, "clicks": clicks, "position": position}


class TestBrandExclusion:
    """ブランド名は既に1位で、伸ばす余地も意味もない(意図不一致)。"""

    def test_brand_queries_excluded(self):
        for s in ("kジャーナル", "k-journal", "ケージャーナル", "kpopj"):
            assert BRAND_RE.search(s), s

    def test_brand_is_not_winnable(self):
        assert not is_winnable(q("kジャーナル", 2859, 52, 2.8))


class TestWinnableRange:
    """pos4-10 は「あと少しで3位以内」= 狙う価値がある。"""

    def test_position_4_to_10_is_target(self):
        assert is_winnable(q("鉄槌教師 声優 一覧", 300, 5, 6.5))

    def test_already_top3_is_not_target(self):
        """既に3位以内なら伸ばす余地が小さい。"""
        assert not is_winnable(q("デーモンハンターズ 相関図", 542, 197, 1.3))

    def test_far_position_is_not_target(self):
        """20位以遠は現実的に3位以内へ届かない。"""
        assert not is_winnable(q("なにか 遠いクエリ", 300, 0, 25.0))

    def test_low_impression_is_not_target(self):
        """imp が小さすぎるものは上げても回収できない。"""
        assert not is_winnable(q("誰も検索しない語 詳細", 5, 0, 6.0))


class TestScoring:
    def test_more_impressions_scores_higher(self):
        a = score_candidate(q("aaa bbb", 1000, 10, 6.0))
        b = score_candidate(q("ccc ddd", 100, 1, 6.0))
        assert a > b

    def test_closer_position_scores_higher(self):
        near = score_candidate(q("aaa bbb", 500, 5, 4.2))
        far = score_candidate(q("ccc ddd", 500, 5, 9.8))
        assert near > far

    def test_multiword_scores_higher_than_single(self):
        """複合語は実測CTR 21.4% vs 単独 14.2%。"""
        multi = score_candidate(q("ive ユジン 怪我", 200, 5, 6.0))
        single = score_candidate(q("リサ", 200, 5, 6.0))
        assert multi > single


class TestNotationMismatch:
    """検索語がタイトル先頭に無いとCTRが落ちる(実測3.4倍差)。

    2026-08-23: 「恋は雨模様 相関図」imp6,379/CTR0.74% に対し
    「恋は飴模様」CTR2.52%。記事タイトルは『恋は飴模様』(恋は雨模様)の順で、
    最多検索語の「雨模様」がタイトル先頭に無かった。
    """

    def test_detects_leading_term_absent(self):
        from lib.winnable_scanner import leading_term_missing
        assert leading_term_missing("恋は雨模様 相関図",
                                    "『恋は飴模様』(恋は雨模様)相関図|キャスト関係")

    def test_ok_when_leading_term_present(self):
        from lib.winnable_scanner import leading_term_missing
        assert not leading_term_missing("恋は雨模様 相関図",
                                        "恋は雨模様(飴模様)相関図|キャスト関係")

    def test_ignores_case_and_spaces(self):
        from lib.winnable_scanner import leading_term_missing
        assert not leading_term_missing("BTS 相関図", "bts 相関図まとめ")

    def test_empty_inputs_are_safe(self):
        from lib.winnable_scanner import leading_term_missing
        assert not leading_term_missing("", "なにか")
        assert not leading_term_missing("なにか", "")


class TestNotationNormalization:
    """中黒・記号の表記差で誤検出しないこと(実データで判明)。

    「ユジン怪我」× 題「IVEアン・ユジン、負傷で…」は CTR38% の成功例。
    中黒や読点の有無で「先頭に無い」と誤判定してはいけない。
    """

    def test_nakaguro_difference_is_not_missing(self):
        from lib.winnable_scanner import leading_term_missing
        # 「ユジン」はタイトル先頭側にある(アン・ユジン)
        assert not leading_term_missing("ユジン怪我", "IVEアン・ユジン、負傷で本日の公演出演を制限")

    def test_real_mismatch_still_detected(self):
        from lib.winnable_scanner import leading_term_missing
        assert leading_term_missing("恋は雨模様 相関図",
                                    "『恋は飴模様』(恋は雨模様)相関図|キャスト関係")
