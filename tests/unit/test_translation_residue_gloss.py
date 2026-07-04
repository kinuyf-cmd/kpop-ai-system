"""翻訳残存ハングル判定の固有名詞gloss除外テスト(2026-07-04 速報skip率43%対策)

body_translate_fail×351の実測で、BLOCKされた本文のハングルは
「양평군（ヤンピョングン）」「경기사회복지공동모금회（京畿社会福祉共同募金会）」
のような意図的な固有名詞併記/glossだった(未翻訳文章ではない)。
gloss形式のハングルは残存判定から除外し、生の未翻訳文は従来通りBLOCKする。
"""
from lib.translation_residue_check import (
    count_hangul,
    _strip_quoted_proper_nouns,
    _strip_proper_noun_glosses,
    assess_residue,
)
from lib.korean_translator import _residue_verdict


BODY_PAD = "アイユが京畿道楊平郡に1000万ウォンを寄付したことが分かった。" * 4


class TestGlossStripping:
    def test_hangul_term_with_japanese_gloss(self):
        # ハングル語+（日本語gloss）は除外
        t = "韓国の京畿道にある양평군（ヤンピョングン）を訪れた"
        assert count_hangul(_strip_proper_noun_glosses(t)) == 0

    def test_long_org_name_with_kanji_gloss(self):
        t = "寄付金は경기사회복지공동모금회（京畿社会福祉共同募金会）に伝達された"
        assert count_hangul(_strip_proper_noun_glosses(t)) == 0

    def test_paren_hangul_annotation(self):
        # 日本語/英語語+（ハングル併記）も除外
        t = "BTS（방탄소년단）が新曲を発表した"
        assert count_hangul(_strip_proper_noun_glosses(t)) == 0

    def test_halfwidth_parens(self):
        t = "BTS (방탄소년단) のメンバーJINが除隊した"
        assert count_hangul(_strip_proper_noun_glosses(t)) == 0

    def test_raw_untranslated_sentence_kept(self):
        # 括弧に入っていない生の未翻訳文はそのまま残る(=BLOCK対象を維持)
        t = "아이유가 양평군에 또 기부했다고 소속사가 밝혔다"
        assert count_hangul(_strip_proper_noun_glosses(t)) == count_hangul(t)

    def test_japanese_parens_not_stripped(self):
        # ハングルを含まない括弧は触らない
        t = "アイユ（本名イ・ジウン）が寄付した"
        assert _strip_proper_noun_glosses(t) == t


class TestResidueVerdictBody:
    def test_gloss_heavy_body_passes(self):
        # 実測再現ケース: gloss由来32字は本文BLOCKしない
        body = (
            BODY_PAD
            + "韓国の京畿道にある양평군（ヤンピョングン）に寄付した。"
            + "寄付金は경기사회복지공동모금회（京畿社会福祉共同募金会）を通じて伝達された。"
            + "所属事務所EDAM엔터테인먼트（エンターテインメント）が明らかにした。"
        )
        assert count_hangul(body) >= 20  # 前提: 従来ロジックならBLOCKされる量
        assert _residue_verdict(body)["verdict"] == "PASS"

    def test_untranslated_body_still_blocked(self):
        body = BODY_PAD + "아이유가 양평군에 또 기부했다고 소속사 관계자가 이날 공식 발표했다."
        assert _residue_verdict(body)["verdict"] == "BLOCK"

    def test_short_title_still_strict(self):
        # タイトル想定(<=100字)は従来通り1字でもBLOCK
        assert _residue_verdict("아이유が寄付")["verdict"] == "BLOCK"


class TestAssessResidueBody:
    def test_gloss_heavy_body_passes_gate(self):
        body = (
            BODY_PAD
            + "양평군（ヤンピョングン）と경기사회복지공동모금회（京畿社会福祉共同募金会）に伝達。"
            + "EDAM엔터테인먼트（エンターテインメント）の発表による。"
        )
        r = assess_residue("アイユ、楊平郡にまた寄付", body)
        assert r["verdict"] != "BLOCK"

    def test_title_hangul_still_blocked(self):
        r = assess_residue("아이유、楊平郡にまた寄付", "本文は日本語のみ。")
        assert r["verdict"] == "BLOCK"
