"""2026-05-12 ユーザー指摘で発覚: X 投稿の AI 臭抽象表現を撲滅する規定の機械検証。

検証対象は lib/x_post_templates.py の HOOKS / EMOTION_LINES / fragment_patterns
等のテンプレ文字列。
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_hooks_no_abstract_verbs():
    """HOOKS から「動いた」「動向」「注目が集まっている」を排除"""
    from lib.x_post_templates import HOOKS
    banned = ['動いた', '動向', '動きがあった', '注目が集まっている',
              '話題になっている', '事態']
    for genre, templates in HOOKS.items():
        for tpl in templates:
            for b in banned:
                assert b not in tpl, f'HOOKS[{genre}] に禁止語 "{b}": {tpl}'


def test_emotion_lines_no_dead_fillers():
    """EMOTION_LINES から「あらまし」「ポイント」「まとめている」を排除"""
    from lib.x_post_templates import EMOTION_LINES
    banned = ['あらまし', 'ポイント', 'まとめている', '整理した',
              '事態は今も動いている', '現時点で分かっていること']
    for genre, lines in EMOTION_LINES.items():
        for line in lines:
            for b in banned:
                assert b not in line, f'EMOTION_LINES[{genre}] に禁止語 "{b}": {line}'


def test_extract_number_returns_empty_on_failure():
    """extract_number は数値抽出失敗時に空文字 (旧 "新" は廃止)"""
    from lib.x_post_templates import extract_number
    assert extract_number('IVE、Starshipが悪質投稿に法的措置発表') == ''
    assert extract_number('NewJeans著作権訴訟') == ''
    # 数値があれば抽出
    assert extract_number('SHINee、13年ぶりミニアルバム') == '13'


def test_extract_event_returns_empty_on_failure():
    """extract_event は event_words に該当しない時に空文字 (旧 "動向" fallback は廃止)"""
    from lib.x_post_templates import extract_event
    # event_words に含まれないタイトル
    assert extract_event('適当な意味のないテキスト 12345') == ''
    # event_words が含まれる
    assert extract_event('BTS、ツアー発表') in ('ツアー', '発表')


def test_select_hook_skips_unfillable_placeholders():
    """event/number 抽出失敗時、{event}/{number} 必須テンプレを skip して plain を採用"""
    from lib.x_post_templates import select_hook
    title = 'IVE、Starshipが悪質投稿に法的措置発表'  # event/number 共に空
    # 30回試行: {event}/{number} のリテラルが結果に含まれてはいけない
    for _ in range(30):
        hook = select_hook('news', title, 'IVE')
        assert '{event}' not in hook
        assert '{number}' not in hook
        # 空 fallback で「冠」「都市で公演決定」だけ残るバグ防止
        assert hook not in ('IVEが冠', 'IVE、都市で公演決定', 'IVEが', 'IVE、で公演決定')


def test_fragment_patterns_no_suffix():
    """extract_title_fragment は「のあらまし」「のポイント」suffix を付けない"""
    src = open('/home/aiuser/kpop-ai-system/lib/x_post_templates.py').read()
    # fragment_patterns 領域に「のあらまし」「のポイント」「を簡単に」が含まれない
    # (全 source code 検索で禁止)
    assert "'\"{kw}\"のあらまし'" not in src, 'fragment_patterns に「のあらまし」suffix 残存'
    assert "'「{kw}」のポイント'" not in src, 'fragment_patterns に「のポイント」suffix 残存'
    assert "'\"{kw}\"を簡単に'" not in src, 'fragment_patterns に「を簡単に」suffix 残存'
