"""2026-05-12 post 22195 事故: NCT TAEYONG (태용) 記事を翻訳して TAEYEON (태연,
少女時代) として publish した。title/slug/サムネ全部の取り違えで、本文だけ NCT のテヨン
と書かれている矛盾状態だった。

translator_v2 が TAEYONG↔TAEYEON 取り違え検出を post-check として持つことを機械検証する。
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def _src_in_out_swap_check(src: str, out: str) -> tuple[bool, str]:
    """translator_v2 の post-check と同じロジックを抽出して再現テスト。
    Returns: (is_block, reason)
    """
    src_lower = (src or '').lower()
    src_taeyong = ('taeyong' in src_lower) or ('태용' in (src or ''))
    src_taeyeon = ('taeyeon' in src_lower) or ('태연' in (src or ''))
    out_lower = (out or '').lower()
    out_taeyong = 'taeyong' in out_lower
    out_taeyeon = 'taeyeon' in out_lower
    if src_taeyong and out_taeyeon and not src_taeyeon:
        return True, 'taeyong_taeyeon_swap: source=Taeyong but output contains TAEYEON'
    if src_taeyeon and out_taeyong and not src_taeyong:
        return True, 'taeyong_taeyeon_swap: source=Taeyeon but output contains TAEYONG'
    return False, ''


def test_post_check_in_source_present_in_translator_v2():
    """translator_v2.py 本体に検出ロジックが置かれていること"""
    src = open('/home/aiuser/kpop-ai-system/lib/translator_v2.py', encoding='utf-8').read()
    assert 'taeyong_taeyeon_swap' in src, 'post-check rule must mention taeyong_taeyeon_swap'


def test_source_taeyong_output_taeyeon_blocks():
    """src に Taeyong あるのに 出力が TAEYEON → BLOCK"""
    block, reason = _src_in_out_swap_check(
        src="NCT's Taeyong ignites comeback anticipation with 'STORM' performance video",
        out='NCTのTAEYEONが「STORM」のパフォーマンスビデオを公開した。',
    )
    assert block is True, f'expected BLOCK, got pass'
    assert 'taeyong_taeyeon_swap' in reason


def test_source_taeyeon_output_taeyong_blocks():
    """src に Taeyeon あるのに 出力が TAEYONG → BLOCK"""
    block, _ = _src_in_out_swap_check(
        src="Girls' Generation's Taeyeon announces solo album",
        out='少女時代のTAEYONGがソロアルバム発表',
    )
    assert block is True


def test_both_present_in_source_passes():
    """両方が src に含まれているケース (NCT TAEYONG vs SNSD TAEYEON 比較記事等) は PASS"""
    block, _ = _src_in_out_swap_check(
        src='NCT Taeyong and SNSD Taeyeon, both leaders, share birthdays',
        out='NCTのTAEYONGと少女時代のTAEYEONはどちらもリーダー',
    )
    assert block is False


def test_neither_present_passes():
    """両方とも無関係な記事は PASS"""
    block, _ = _src_in_out_swap_check(
        src='BLACKPINK Lisa releases solo album',
        out='BLACKPINKのLISAがソロアルバムをリリース',
    )
    assert block is False


def test_korean_proper_nouns_has_taeyong_entry():
    """config/korean_proper_nouns.json の members に 태용 -> TAEYONG が登録されていること"""
    import json
    d = json.load(open('/home/aiuser/kpop-ai-system/config/korean_proper_nouns.json',
                       encoding='utf-8'))
    members = d.get('members', {})
    assert '태용' in members, '태용 (TAEYONG) must be in korean_proper_nouns.json members'
    assert members['태용'] == 'TAEYONG'
    assert members.get('태연') == 'TAEYEON', '태연 entry should remain intact'
