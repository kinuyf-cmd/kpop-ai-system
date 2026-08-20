"""X投稿のエンゲージ率算出と型A適合率の集計を検査する。

背景:
  既存メモリ「Phase3ゲートはimpでなくエンゲージ率」の通り、判定の主指標は
  エンゲージ率。しかし x_phase2_report は impression しか見ていなかった。
  2026-08-20 に型A(感想→起で止め、結はリプ)を導入したため、
  「型Aになっている投稿の割合」と「エンゲージ率」を並べて追えるようにする。

  ゼロ除算(imp=0)で落ちないこと、metrics が欠けた投稿を勝手に0扱いして
  母数を汚さないことを保証する。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib.x_engagement import engagement_rate, summarize_engagement


def test_engagement_rate_counts_all_reactions():
    """いいね・リプ・RT・引用を合算して imp で割る。"""
    m = {"impression_count": 100, "like_count": 3, "reply_count": 1,
         "retweet_count": 1, "quote_count": 1}
    assert engagement_rate(m) == 6.0


def test_zero_impression_returns_none_not_zero():
    """imp=0 は「率が定義できない」。0.0 にすると平均を不当に下げる。"""
    assert engagement_rate({"impression_count": 0, "like_count": 0}) is None


def test_missing_keys_are_treated_as_zero_reactions():
    m = {"impression_count": 50}
    assert engagement_rate(m) == 0.0


def test_summarize_skips_undefined_rates():
    """imp=0 の投稿は母数から除く(0%として混ぜない)。"""
    data = {
        "1": {"impression_count": 100, "like_count": 5},
        "2": {"impression_count": 0, "like_count": 0},
        "3": {"impression_count": 100, "like_count": 1},
    }
    s = summarize_engagement(data)
    assert s["n"] == 2
    assert s["avg_engagement_rate"] == 3.0


def test_summarize_handles_empty_input():
    s = summarize_engagement({})
    assert s["n"] == 0
    assert s["avg_engagement_rate"] is None
