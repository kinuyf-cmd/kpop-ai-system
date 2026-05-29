#!/usr/bin/env python3
"""速報dedup強化のリグレッションテスト (2026-05-30)。

背景: ILLITモカ事案が soompi/osen/Music Bank速報 の別ソースで5本生成された。
原因: dedup主キーが soompi記事ID専用で、別ソース・同一トピック別ソースをすり抜けた。
対策: 汎用source_id + アーティスト+トピックカテゴリ の補助dedupキーを追加。

実行: venv_kpi/bin/python3 -m pytest tests/test_breaking_dedup.py
      (pytest不在なら) venv_kpi/bin/python3 tests/test_breaking_dedup.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
import breaking_news_selector as b  # noqa: E402


def test_cross_source_same_event():
    """別ソース(osen)の同一事案を、既出トピックキーで重複検出する。"""
    pub_tk = {b._topic_key("ILLITのモカが「管理可能な範囲内」で活動再開")}
    sig = {"url": "https://www.osen.co.kr/article/G1112810589",
           "title": "ILLITのモカが本日29日活動復帰"}
    dup, _ = b.is_duplicate(sig, set(), set(), set(), pub_tk, set())
    assert dup is True


def test_same_batch_same_topic():
    """同一バッチ内の同トピック2本目を弾く。1本目は通す。"""
    seen_tk = set()
    s1 = {"url": "https://soompi.com/article/111wpp", "title": "ILLITのモカが活動再開"}
    d1, _ = b.is_duplicate(s1, set(), set(), set(), set(), seen_tk)
    seen_tk.add(b._topic_key(s1["title"]))
    s2 = {"url": "https://osen.co.kr/article/G222", "title": "ILLITのモカ、復帰へ"}
    d2, _ = b.is_duplicate(s2, set(), set(), set(), set(), seen_tk)
    assert d1 is False and d2 is True


def test_no_false_positive_other_artist():
    """別アーティスト・別トピックは重複でない(誤検知防止)。"""
    pub_tk = {b._topic_key("NCTのテヨンがソロ1位")}
    sig = {"url": "https://soompi.com/article/999wpp", "title": "aespaがカムバック"}
    dup, _ = b.is_duplicate(sig, set(), set(), set(), pub_tk, set())
    assert dup is False


def test_same_artist_different_topic():
    """同一アーティストでも別カテゴリ(除隊≠結婚)は別事案として通す。"""
    pub_tk = {b._topic_key("BTSジンが除隊")}
    sig = {"url": "https://soompi.com/article/888wpp", "title": "BTSジンが結婚を発表"}
    dup, _ = b.is_duplicate(sig, set(), set(), set(), pub_tk, set())
    assert dup is False


def test_topic_word_not_mistaken_for_artist():
    """トピック語(カムバック等カタカナ/英語)をアーティスト名と誤認しない。
    誤認すると別グループ(アイブ/エスパ)が同一キーになり誤排除される(code-review検出)。"""
    k_ive = b._topic_key("アイブがカムバック")
    k_aespa = b._topic_key("エスパがカムバック")
    assert k_ive and k_aespa and k_ive != k_aespa


def test_topic_only_no_artist_returns_empty():
    """アーティスト名が特定できない(トピック語のみ)ときは判定しない=空。"""
    assert b._topic_key("カムバック発表") == ""


def test_legacy_soompi_key_compat():
    """従来の soompi記事ID 主キーが引き続き効く(後方互換)。"""
    dup, _ = b.is_duplicate(
        {"url": "https://soompi.com/article/1844541wpp/x", "title": "X"},
        set(), {"1844541"}, set())
    assert dup is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
            passed += 1
        except AssertionError:
            print(f"  [FAIL] {fn.__name__}")
    print(f"\n{passed}/{len(fns)} passed")
    sys.exit(0 if passed == len(fns) else 1)
