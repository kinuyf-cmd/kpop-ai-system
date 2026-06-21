"""x_pre_score の純粋スコアリングロジックの回帰テスト。

各セクション関数(hook/structure/target/alt)・完結チェック・類似度
(win_records を引数注入)・rewrite 補強・preflight 構造を、ソース実装
(lib/x_pre_score.py)どおりに固定する。

注意: similarity_score / load_win_records は logs/title_performance.jsonl に
依存するため、total/pass の「絶対値」は固定しない。スコア境界・上限・各
セクションの加減点ロジック・win_records 注入版のみを決定的にテストする。
"""
import lib.x_pre_score as ps


# ─── score_hook ──────────────────────────────────────────────────────────
class TestScoreHook:
    def test_within_max_and_min(self):
        for txt in ["", "速報🚨 aespa新曲 どう思う？", "皆さんこんにちは。お知らせです。"]:
            s, _ = ps.score_hook(txt)
            assert 0.0 <= s <= 35.0

    def test_weak_opening_penalized(self):
        weak, _ = ps.score_hook("皆さん、今日はaespaの話 どう思う？")
        strong, _ = ps.score_hook("速報 aespaの新曲が解禁 どう思う？")
        assert strong > weak

    def test_two_strong_words_beats_one(self):
        two, r2 = ps.score_hook("速報 解禁 どう思う？")
        one, r1 = ps.score_hook("速報のニュース どう思う？")
        assert two > one
        assert any("×2" in x or "強ワード" in x for x in r2)

    def test_unverified_assertion_penalized(self):
        with_assert, _ = ps.score_hook("速報 これは100%確実な話 どう思う？")
        clean, _ = ps.score_hook("速報 注目の話題 どう思う？")
        assert with_assert < clean

    def test_no_comment_trigger_penalized(self):
        # コメント誘導(疑問符・誘導語)が無いと -5
        no_trigger, reasons = ps.score_hook("速報 aespaの新曲が解禁。")
        assert any("コメント誘導なし" in x for x in reasons)


# ─── check_completeness ──────────────────────────────────────────────────
class TestCheckCompleteness:
    def test_question_is_incomplete_ok(self):
        ok, violations = ps.check_completeness("aespaの新曲、どう思う？")
        assert ok is True and violations == []

    def test_declarative_sentence_is_complete_ng(self):
        ok, violations = ps.check_completeness("aespaが新曲を発表した。")
        assert ok is False and violations

    def test_ellipsis_counts_as_incomplete(self):
        ok, _ = ps.check_completeness("aespaの新曲が気になる…")
        assert ok is True


# ─── score_structure ─────────────────────────────────────────────────────
class TestScoreStructure:
    def test_within_max(self):
        s, _ = ps.score_structure("a" * 500 + " http://x")
        assert 0.0 <= s <= 25.0

    def test_url_present_bonus(self):
        with_url, _ = ps.score_structure("aespaの新曲が話題 https://www.kpopjournal.tokyo/x/")
        without, _ = ps.score_structure("aespaの新曲が話題")
        # URLありは +8、なしは +4 → URLありが高い(長さ条件を揃えるため同程度の本文)
        assert with_url >= without

    def test_newline_bonus(self):
        multi, reasons = ps.score_structure("見出し\n本文がここに続く長めのテキストです")
        assert any("改行" in x for x in reasons)


# ─── score_target ────────────────────────────────────────────────────────
class TestScoreTarget:
    def test_within_max(self):
        s, _ = ps.score_target("BTS BLACKPINK aespa #KPOP #BTS #韓国 #Kpop")
        assert 0.0 <= s <= 15.0

    def test_known_artist_scored(self):
        s, reasons = ps.score_target("aespaの新曲")
        assert s > 0
        assert any("aespa" in x or "アーティスト" in x for x in reasons)

    def test_multiple_artists_beat_single(self):
        multi, _ = ps.score_target("BTSとaespaの対談")
        single, _ = ps.score_target("aespaの対談")
        assert multi >= single

    def test_hashtag_sweet_spot(self):
        good, _ = ps.score_target("aespa新曲 #KPOP #aespa #韓国")   # 2-4個
        none, _ = ps.score_target("aespa新曲")
        assert good > none

    def test_too_many_hashtags_penalized(self):
        s, reasons = ps.score_target("aespa #a #b #c #d #e #f")
        assert any("過多" in x for x in reasons)

    def test_kpop_word_fallback_when_no_artist(self):
        # アーティスト名なしでも K-POP 関連ワードで部分点
        s, reasons = ps.score_target("ガラス肌になれる韓国コスメ特集")
        assert s > 0
        assert any("K-POP関連" in x for x in reasons)


# ─── score_alt ───────────────────────────────────────────────────────────
class TestScoreAlt:
    def test_within_max(self):
        s, _ = ps.score_alt("テキスト🎵", alt_text="x" * 50)
        assert 0.0 <= s <= 10.0

    def test_full_alt_beats_none(self):
        full, _ = ps.score_alt("text", alt_text="十分な長さの説明テキストです")
        none, _ = ps.score_alt("text", alt_text="")
        assert full > none

    def test_emoji_bonus(self):
        s, reasons = ps.score_alt("aespa新曲🎵🔥")
        assert any("絵文字" in x for x in reasons)


# ─── similarity_score(win_records 注入で決定的) ──────────────────────────
class TestSimilarityScore:
    def test_empty_records_returns_baseline(self):
        score, reasons = ps.similarity_score("aespaの新曲", [])
        assert score == 8.0
        assert any("ベースライン" in x for x in reasons)

    def test_score_capped_at_15(self):
        wins = [{"title": "aespa 新曲 速報", "result": "win"}]
        score, _ = ps.similarity_score("aespa 新曲 速報", wins)
        assert 8.0 <= score <= 15.0

    def test_overlap_increases_score(self):
        wins = [{"title": "aespa 新曲 速報 解禁", "result": "win"}]
        related, _ = ps.similarity_score("aespa 新曲 速報 解禁 だね", wins)
        unrelated, _ = ps.similarity_score("天気がいいですね 散歩", wins)
        assert related > unrelated


# ─── extract_keywords ────────────────────────────────────────────────────
class TestExtractKeywords:
    def test_uppercases_and_extracts(self):
        kws = ps.extract_keywords("aespa の新曲 BTS")
        assert "AESPA" in kws and "BTS" in kws


# ─── preflight_score 構造 + rewrite ──────────────────────────────────────
class TestPreflightAndRewrite:
    def test_breakdown_structure_and_caps(self):
        r = ps.preflight_score("速報 aespaの新曲が解禁 どう思う？ #KPOP #aespa")
        assert set(r["breakdown"]) == {"hook", "structure", "target", "alt", "history"}
        bd = r["breakdown"]
        assert bd["hook"]["max"] == 35 and bd["hook"]["score"] <= 35
        assert bd["structure"]["max"] == 25 and bd["structure"]["score"] <= 25
        assert bd["target"]["max"] == 15 and bd["target"]["score"] <= 15
        assert bd["alt"]["max"] == 10 and bd["alt"]["score"] <= 10
        assert bd["history"]["max"] == 15 and bd["history"]["score"] <= 15
        # total は各セクション合計と一致
        expected = round(sum(bd[k]["score"] for k in bd), 1)
        assert r["total"] == expected
        assert r["pass"] == (r["total"] >= ps.PASS_THRESHOLD)
        assert r["threshold"] == ps.PASS_THRESHOLD == 80

    def test_rewrite_adds_hook_and_hashtags(self):
        weak = "aespaの新曲がリリースされた"
        out = ps.rewrite(weak)
        # アーティスト名ありなら「速報」フックが付く
        assert out.startswith("速報")
        # ハッシュタグが補強される
        assert "#KPOP" in out

    def test_rewrite_improves_score(self):
        weak = "aespaの新曲がリリースされた"
        before = ps.preflight_score(weak)["total"]
        after = ps.preflight_score(ps.rewrite(weak))["total"]
        assert after > before

    def test_rewrite_non_artist_uses_generic_hook(self):
        out = ps.rewrite("韓国コスメの新作が登場")
        assert out.startswith("注目") or out.startswith("速報")
        assert "#" in out
