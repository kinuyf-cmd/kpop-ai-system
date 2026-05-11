"""2026-05-11 korean_media collector の HTML/連結汚染 再発防止テスト

事故内容: 直近24h の trend_signals.jsonl で source=korean_media の title 列に
HTML タグ (koreaherald) や連続改行・隣接記事タイトル連結 (newsen/topstarnews) が
混入し、後段の artist 識別/breaking 判定精度を低下させていた。

修正: lib/collectors/korean_base.py に clean_title() を共通化、
newsen/koreaherald/topstarnews collector で使用。
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_clean_title_strips_html_tags():
    """HTML タグが除去されること"""
    from lib.collectors.korean_base import clean_title
    raw = '<div class="news_txt"><p class="news_title">BTS meets Mexican president as fans swarm palace</p></div>'
    cleaned = clean_title(raw)
    assert '<' not in cleaned, f'HTML tag still present: {cleaned!r}'
    assert 'BTS meets Mexican' in cleaned


def test_clean_title_splits_on_double_newline():
    """連続改行 (HTML strip 後の隣接記事タイトル境界) で先頭のみ採用"""
    from lib.collectors.korean_base import clean_title
    raw = '아일릿 원희, 자기객관화도 귀여움 폭발 [어제TV]\n\t\t\t\t\t\n\t\t\t\t\t\t\t\t\t\n\t\t\t\t\t\t \'봉주르빵집\' 사장님 김희애'
    cleaned = clean_title(raw)
    assert '봉주르빵집' not in cleaned, f'second title leaked: {cleaned!r}'
    assert '아일릿 원희' in cleaned


def test_clean_title_strips_journalist_signature():
    """記者署名 + 日付以降がカットされること"""
    from lib.collectors.korean_base import clean_title
    raw = '슬기, 동묘 골목에서 포즈…일상 속 남다른 존재감\n\t\t\t\t\n\t\t\t\t\n\t\t\t\t\t황선용 기자\n\t\t\t\t\t05.09 22:05'
    cleaned = clean_title(raw)
    assert '황선용' not in cleaned, f'journalist name leaked: {cleaned!r}'
    assert '05.09' not in cleaned, f'date leaked: {cleaned!r}'
    assert '슬기' in cleaned and '존재감' in cleaned


def test_clean_title_preserves_clean_titles():
    """既にクリーンな title は変更されないこと (false positive 回避)"""
    from lib.collectors.korean_base import clean_title
    raw = 'BTS 진、新曲「ARIRANG」Billboard 200で7週連続TOP10'
    cleaned = clean_title(raw)
    assert cleaned == raw, f'clean title was modified: {raw!r} → {cleaned!r}'


def test_clean_title_truncates_long_titles():
    """80字超は句読点で切断されること"""
    from lib.collectors.korean_base import clean_title
    raw = ('IU、初日売上1万枚を突破した新シングル「Love wins all」が話題になっており、' * 3)
    cleaned = clean_title(raw)
    assert len(cleaned) <= 81, f'title not truncated: len={len(cleaned)}'


def test_all_three_collectors_use_clean_title():
    """newsen/koreaherald/topstarnews すべてが共通 clean_title を経由していること"""
    for fname in ['newsen_collector.py', 'koreaherald_collector.py', 'topstarnews_collector.py']:
        path = f'/home/aiuser/kpop-ai-system/lib/collectors/{fname}'
        src = open(path).read()
        assert 'clean_title' in src, f'{fname} が clean_title を import/使用していない'
