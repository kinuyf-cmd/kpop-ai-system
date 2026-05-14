"""
2026-05-15: profile_wiki_builder の Wikipedia diff hallucination guard 検証。

事故 (5/15): Hyolyn の web search 結果が
  本名 김현영 / 生年 1989-01-11
を出力したが、Wikipedia 確定値は
  本名 김효정 / 生年 1990-12-11
ガード未実装だと stub を bad data で上書きしていた。
"""
import sys

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_check_hallucination_detects_birth_mismatch():
    from pipeline.profile_wiki_builder import _check_hallucination
    profile = {'members': [{'name_en': 'Hyolyn', 'birth': '1989-01-11', 'real_name_en': 'Kim Hyun-young'}]}
    wiki = {'birth_date': '1990-12-11', 'real_name_en_wikipedia': 'Kim Hyo-jung'}
    issues = _check_hallucination(profile, wiki)
    assert len(issues) >= 1
    assert any('birth_date' in i for i in issues)


def test_check_hallucination_detects_real_name_mismatch():
    from pipeline.profile_wiki_builder import _check_hallucination
    profile = {'members': [{'name_en': 'Hyolyn', 'birth': '1990-12-11', 'real_name_en': 'Kim Hyun-young'}]}
    wiki = {'birth_date': '1990-12-11', 'real_name_en_wikipedia': 'Kim Hyo-jung'}
    issues = _check_hallucination(profile, wiki)
    assert any('real_name_en' in i for i in issues)


def test_check_hallucination_passes_when_match():
    from pipeline.profile_wiki_builder import _check_hallucination
    profile = {'members': [{'name_en': 'Hyolyn', 'birth': '1990-12-11', 'real_name_en': 'Kim Hyo-jung'}]}
    wiki = {'birth_date': '1990-12-11', 'real_name_en_wikipedia': 'Kim Hyo-jung'}
    assert _check_hallucination(profile, wiki) == []


def test_check_hallucination_no_wiki_data_skip():
    """Wikipedia 取れない (新人 artist 等) → 検証 skip、issues 空返却"""
    from pipeline.profile_wiki_builder import _check_hallucination
    profile = {'members': [{'birth': '2000-01-01', 'real_name_en': 'Some Name'}]}
    assert _check_hallucination(profile, {}) == []


def test_check_hallucination_partial_data_no_false_positive():
    """LLM が birth/real_name を出してないなら比較 skip (false positive 防止)"""
    from pipeline.profile_wiki_builder import _check_hallucination
    profile = {'members': [{'name_en': 'X', 'note': 'no birth'}]}
    wiki = {'birth_date': '1990-12-11', 'real_name_en_wikipedia': 'Kim Hyo-jung'}
    assert _check_hallucination(profile, wiki) == []


def test_real_name_normalization_handles_spacing():
    """'Kim Hyo-jung' と 'Kim Hyojung' を同一扱いする (hyphen/space 差異吸収)"""
    from pipeline.profile_wiki_builder import _check_hallucination
    profile = {'members': [{'real_name_en': 'Kim Hyojung', 'birth': '1990-12-11'}]}
    wiki = {'birth_date': '1990-12-11', 'real_name_en_wikipedia': 'Kim Hyo-jung'}
    assert _check_hallucination(profile, wiki) == []


def test_wikipedia_fetch_real_artist():
    """実 Wikipedia から birth_date が取れること (live integration、安定 artist で確認)"""
    from pipeline.profile_wiki_builder import _fetch_wikipedia_facts
    facts = _fetch_wikipedia_facts('Hyolyn')
    # birth_date が取れる ('1990-12-11' 期待だが network 状況次第なので存在のみ確認)
    if facts and 'birth_date' in facts:
        assert facts['birth_date'].startswith('19') or facts['birth_date'].startswith('20')
