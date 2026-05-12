"""2026-05-12 発見: 翻訳出力に hangul が残存しても translator は success=True を
返していたため、gate でしか BLOCK されず breaking/event/comeback の `if not success:
continue` 経路で skip できなかった。

translator 層で post-check して呼び出し側に skip させる規定を機械検証する。
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_residue_verdict_title_one_char_blocks():
    """短文 (タイトル想定 <=100字) はハングル1字でも BLOCK"""
    from lib.korean_translator import _residue_verdict
    v = _residue_verdict('변우석、新曲リリース')  # 3字 hangul
    assert v['verdict'] == 'BLOCK', f'expected BLOCK, got {v}'


def test_residue_verdict_body_short_passes():
    """本文想定 (>100字) で hangul 5字未満は PASS (gate WARN相当だが translator は通す)"""
    from lib.korean_translator import _residue_verdict
    long_text = '日本語本文。' * 30 + 'コラボ。'  # >100字、hangul 0
    v = _residue_verdict(long_text)
    assert v['verdict'] == 'PASS'


def test_residue_verdict_body_20chars_blocks():
    """本文想定で hangul 20字以上は BLOCK"""
    from lib.korean_translator import _residue_verdict
    long_text = '日本語本文。' * 30 + ' 韓国語: 변우석이 새 앨범을 발매하면서 팬들의 환영을 받았다 (24字)'
    v = _residue_verdict(long_text)
    assert v['verdict'] == 'BLOCK', f'expected BLOCK, got {v}'


def test_residue_verdict_strips_quoted_proper_nouns():
    """「」内の hangul は引用符内固有名詞として除外 (楽曲名等)"""
    from lib.korean_translator import _residue_verdict
    v = _residue_verdict('BABYMONSTERが「춤」をリリース')
    assert v['verdict'] == 'PASS', f'quoted hangul should be stripped: {v}'


def test_dictionary_has_new_2026_05_12_entries():
    """2026-05-12 に追加した固有名詞が辞書に存在することを保証"""
    import json
    d = json.load(open('/home/aiuser/kpop-ai-system/config/korean_proper_nouns.json',
                       encoding='utf-8'))
    assert d['personalities'].get('변우석') == 'ピョン・ウソク'
    assert d['personalities'].get('차주완') == 'チャ・ジュワン'
    assert d['personalities'].get('진해성') == 'ジン・ヘソン'
    assert d['groups'].get('씨야') == 'See Ya'
    assert d['members'].get('유주') == 'Yuju'


def test_apply_proper_noun_dict_replaces_new_entries():
    """前置換が新規エントリで動くこと (lru_cache の影響を避けるためclear)"""
    from lib.korean_translator import _load_proper_nouns, apply_proper_noun_dict
    _load_proper_nouns.cache_clear()
    out, n = apply_proper_noun_dict('변우석이 21세기 대군부인 OST를 발표')
    assert '변우석' not in out, f'변우석 should be replaced: {out}'
    assert 'ピョン・ウソク' in out, f'expected katakana: {out}'
