"""固有名詞辞書の前置換と主役判定が、一般語をグループ名に化けさせないこと。

実例(2026-10-13): 「여자친구는 있지만」→「GFRIENDはITZYだけ」、「화사한 미소」→
「HWASAを思わせる微笑み」、「카라스코」(野球選手)→KARA、「우즈베크」→WOODZ。
"""
import pytest

from lib import korean_translator as kt
from lib.collectors.korean_base import clean_title, is_kpop_related


@pytest.mark.parametrize("src", [
    '물론 지금 사귀는 여자친구는 있지만 결혼 운운할 건 아니다',
    '이수빈, 화사한 미소',
    '어린 아이들이 뛰어논다',
    '가을 야구 승리',
    '엑스포츠뉴스 김유진 기자',
    '배우 한지민, 김수영과 호흡',
])
def test_translation_prereplace_leaves_common_words(src):
    out, _ = kt.apply_proper_noun_dict(src, context_aware=True)
    assert out == src


def test_translation_prereplace_still_replaces_clear_names():
    out, n = kt.apply_proper_noun_dict('방탄소년단 정국의 신곡, BTS 지민이 컴백한다', context_aware=True)
    assert out == 'BTS JUNGKOOK의 新曲, BTS JIMIN이 カムバック한다'
    assert n >= 5


def test_default_mode_keeps_plain_substring_replace():
    # 名寄せ・検索語の正規化(breaking_news_detector / pre_publish_gate)は従来どおり
    assert kt.apply_proper_noun_dict('있지 예지')[0] == 'ITZY YEJI'


def test_hints_only_for_standalone_ambiguous_words():
    assert '있지→ITZY' in kt.context_dependent_hints('있지 예지 출국')
    assert '화사→HWASA' in kt.context_dependent_hints('마마무 화사, 신곡')
    assert kt.context_dependent_hints('엑스포츠뉴스 김유진 기자') == ''
    assert kt.context_dependent_hints('블랙핑크 컴백') == ''


@pytest.mark.parametrize("title", [
    '하츠투하츠 이안, 화사한 발걸음 [포토엔HD]',
    '[공식발표] LG 손주영 빠졌다... 카라스코 vs 곽빈 선발',
    '손흥민, 우즈베크전 투톱 선발 출격',
    '이 슈트가 육상 경기의 방향 제시할 수도',
    '그럴 수 있지 않나 배우 A',
    '증거로 보아 유죄',
])
def test_detection_rejects_common_words(title):
    assert is_kpop_related(title) == []


@pytest.mark.parametrize("title,artist", [
    ('마마무 화사, 신곡 발매', '화사'),
    ('화사의 새 앨범', '화사'),
    ('카라 한승연 근황', '카라'),
    ('우즈, 전역 후 첫 콘서트', '우즈'),
    ('있지 예지 ‘꽃받침’', '있지'),
    ('보아, 데뷔 25주년 콘서트', '보아'),
    ('블랙핑크가 컴백한다', '블랙핑크'),
])
def test_detection_keeps_real_artists(title, artist):
    assert artist in is_kpop_related(title)


def test_clean_title_cuts_neighbor_headline():
    raw = "'결혼 발표' 박세미, 예비신랑 화제…과거 아이돌 도전까지          \n\n\n\n\n조세호에 발각 됐지만"
    assert clean_title(raw) == "'결혼 발표' 박세미, 예비신랑 화제…과거 아이돌 도전까지"
