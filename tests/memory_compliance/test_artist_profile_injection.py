"""2026-05-11 factcheck CRITICAL 事故の再発防止テスト

事故内容: 5/11 の breaking 5記事 (CORTIS/KATSEYE/BABYMONSTER 等) が
factcheck CRITICAL で draft 化。真因は artist_profiles.json の不適切注入:
  - members=[] (CORTIS 等の group with empty member list) を「0人組」と注入
  - is_solo=true (IU/LISA 等の solo artist) を「0人組」と注入
  - 注入文言「矛盾していればcriticalで報告」が LLM に「記載なし=矛盾」と誤読され
    記事が言及していないだけで critical 報告される (KATSEYE「6人組注記が抜け」事例)

修正後:
  - solo artist は「ソロアーティスト, YYYY年デビュー」として注入
  - members=[] かつ is_solo=False の group は注入スキップ
  - 注入文言は「明確に異なる数値のみ critical」と緩和
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_breaking_news_detector_solo_injection():
    """is_solo=true の artist は「ソロアーティスト」として注入され「0人組」を含まない

    artist_profiles.json は pipeline auto-update で変動するため、データ独立 test として
    一時的に solo entry を mock してロジックを検証する。
    """
    import json
    from pathlib import Path
    profile_path = Path('/home/aiuser/kpop-ai-system/config/artist_profiles.json')
    backup = profile_path.read_text()
    try:
        d = json.loads(backup)
        d.setdefault('profiles', {})['_test_solo_iu'] = {
            'display_name': 'IU',
            'name_en': 'IU',
            'agency': 'EDAM Entertainment',
            'debut_year': 2008,
            'is_solo': True,
            'members': [],
        }
        profile_path.write_text(json.dumps(d, ensure_ascii=False, indent=2))
        from pipeline.breaking_news_detector import _get_artist_profile_context
        ctx = _get_artist_profile_context('IU', [{'title': 'IUが新曲リリース'}])
        assert '0人組' not in ctx, f'solo artist injection contains 0人組: {ctx!r}'
        assert 'ソロアーティスト' in ctx, f'solo marker missing: {ctx!r}'
    finally:
        profile_path.write_text(backup)


def test_breaking_news_detector_solo_logic_without_data():
    """データに solo artist がいなくても、コード分岐に「ソロアーティスト」記述があること
    (将来 solo artist が追加された時の logic 正常性を保証する static test)"""
    src = open('/home/aiuser/kpop-ai-system/pipeline/breaking_news_detector.py').read()
    assert 'ソロアーティスト' in src, 'solo branch missing in code'
    assert "prof.get('is_solo'" in src, 'is_solo check missing'


def test_breaking_news_detector_empty_group_skipped():
    """members=[] の group は注入されない (誤情報源化防止)"""
    from pipeline.breaking_news_detector import _get_artist_profile_context
    # CORTIS は group だが artist_profiles.json で members=[] (実データ不完全)
    ctx = _get_artist_profile_context('CORTIS', [{'title': 'CORTIS「GREENGREEN」リリース'}])
    assert '0人組' not in ctx, f'empty-members group still injected 0人組: {ctx!r}'
    # CORTIS が injection 自体に出てこない (skip された) ことを確認
    assert 'CORTIS' not in ctx, f'empty-members group not skipped: {ctx!r}'


def test_breaking_news_detector_group_with_members():
    """members 入りの group は従来通り正しく注入される (regression防止)"""
    from pipeline.breaking_news_detector import _get_artist_profile_context
    ctx = _get_artist_profile_context('KATSEYE', [{'title': 'KATSEYEメンバー脱退報道'}])
    assert '6人組' in ctx, f'KATSEYE 6人組 not injected: {ctx!r}'
    assert '2024年' in ctx, f'KATSEYE debut year missing: {ctx!r}'


def test_llm_proofreader_injection_text_softened():
    """proofreader の injection 文言から「矛盾していればcritical」を撤去し
    「明確に異なる数値のみ critical」に緩和されていること
    """
    src = open('/home/aiuser/kpop-ai-system/pipeline/llm_proofreader.py').read()
    # 旧文言は撤去されていること
    assert '矛盾していればcriticalで報告' not in src, (
        'overdefense文言「矛盾していればcriticalで報告」が残っている。'
        'LLMが「記載なし=矛盾」と誤読する原因なので緩和すること'
    )
    # 新文言が入っていること
    assert '明確に異なる数値' in src or '記載がないこと自体は問題ではない' in src, (
        'softened文言が見当たらない'
    )
