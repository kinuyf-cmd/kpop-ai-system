"""人数・デビュー年のルール照合が、別グループの数字や古い知識で記事を止めないこと。

直近30日(〜2026-10-13)のBLOCK 19件中およそ17件が誤検知だった実例を固定する。
"""
import pytest

from lib.factcheck_corpus import build_corpus
from pipeline.llm_proofreader import _check_artist_profile as check

FALSE_POSITIVES = [
    ("NCT WISH「I Spy」で4作連続ミリオン達成", "NCT WISHは2024年にデビューした6人組グループで、NCTの日本チームとして活動している。"),
    ("NiziU、韓国初ミニアルバム", "BOYNEXTDOORやILLITも出演する。NiziUは9人組ガールズグループで、2020年にデビューした。"),
    ("BTSのJung Kook「GOLDEN」", "ILLITも同チャートに入った。BTSは2013年にデビューした7人組だ。"),
    ("Fin.K.L、21年ぶり完全体", "Red Velvetのカバーでも知られる。Fin.K.Lは1998年にデビューした4人組。"),
    ("SEVENTEEN新ユニットJxJ", "SEVENTEENの新ユニットJxJは2025年にデビューした。"),
    ("EXO SUHO", "EXOはデビュー当時12人組だった。"),
    ("T.O.P、BIGBANG20周年活動に言及", "BIGBANGは現在3人組として活動している。"),
    ("fromis_9ノ・ジソン", "fromis_9は現在5人組で活動している。"),
    ("IVE LIVE", "alive tourが始まる。別のグループは5人組だ。"),
]

REAL_ERRORS = [
    ("Stray Kids メキシコ公演", "Stray Kidsは7人組ボーイズグループだ。", "Stray Kids"),
    ("TWICE新曲", "9人組ガールズグループTWICEは2016年にデビューした。", "TWICE"),
    ("aespa", "5人組ガールズグループaespaが新曲を出す。", "aespa"),
    ("BLACKPINK", "BLACKPINKは、2017年デビューの4人組。", "BLACKPINK"),
]


@pytest.mark.parametrize("title,body", FALSE_POSITIVES)
def test_no_block_on_other_groups_numbers(title, body):
    assert check(title, body) == []


@pytest.mark.parametrize("title,body,name", REAL_ERRORS)
def test_real_mismatch_still_detected(title, body, name):
    issues = check(title, body)
    assert len(issues) == 1 and issues[0].startswith(name)


def test_corpus_does_not_state_partial_roster_as_headcount():
    corpus = build_corpus()
    nct = corpus[corpus.index('## NCT'):].split('\n## ')[0]
    assert 'メンバー人数' not in nct
    assert '一部のみ' in nct and 'NCT WISH' in nct
    baby = corpus[corpus.index('## BABYMONSTER'):].split('\n## ')[0]
    assert 'RORA' in baby and 'HARAM' not in baby
    big = corpus[corpus.index('## BIGBANG'):].split('\n## ')[0]
    assert 'メンバー人数: 3人' in big and 'T.O.P' in big.split('脱退メンバー')[1]
