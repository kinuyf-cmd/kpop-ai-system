"""2026-05-12 発見: pre_publish_gate の「タイトルにソースにない語句が追加」チェックが、
韓国語ソース見出しに対する正しい英字 alias 翻訳 (아일릿→ILLIT, 우주소녀→WJSN 等) を
「捏造」と誤検知し、OSEN/MyDaily 系の韓国一次ソース publish を 24h で 0 件まで落としていた。

gate 側でも korean_proper_nouns 辞書を共有してハングル→英字展開してから比較するよう
修正した。本 test は:
  - 主要 artist の하ngul → 英字 alias 展開が apply_proper_noun_dict で動く
  - pre_publish_gate.py のロジックが apply_proper_noun_dict を呼んでいる
を機械検証する。
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_apply_proper_noun_expands_korean_artist_names():
    """主要 7 アーティストのハングル→英字 alias 展開"""
    from lib.korean_translator import apply_proper_noun_dict
    cases = [
        ('아일릿', 'illit'),
        ('몬스타엑스', 'monsta'),
        ('우주소녀', 'wjsn'),
        ('보이넥스트도어', 'boynextdoor'),
        ('베이비몬스터', 'babymonster'),
        ('르세라핌', 'sserafim'),
        ('씨야', 'see'),  # See Ya
    ]
    failed = []
    for ko, en in cases:
        out, _ = apply_proper_noun_dict(ko + ' headline')
        if en.lower() not in out.lower():
            failed.append((ko, en, out))
    assert not failed, f'failed to expand: {failed}'


def test_gate_uses_apply_proper_noun_dict():
    """pre_publish_gate.py が tilte vs source 比較で apply_proper_noun_dict を呼んでいる"""
    src = open('/home/aiuser/kpop-ai-system/lib/pre_publish_gate.py',
               encoding='utf-8').read()
    # 該当 1h00 section に dict 展開ロジックがあること
    assert 'apply_proper_noun_dict' in src, \
        'pre_publish_gate must use apply_proper_noun_dict for hangul → alias expansion'
    # 説明コメントもチェック (2026-05-12 のリグレッション防止意図を明示)
    assert '아일릿' in src or 'OSEN' in src, \
        'gate fix should reference the 2026-05-12 OSEN root cause'


def test_korean_proper_nouns_has_wjsn():
    """우주소녀 → WJSN が登録されていること (OSEN 候補化された記事用)"""
    import json
    d = json.load(open('/home/aiuser/kpop-ai-system/config/korean_proper_nouns.json',
                       encoding='utf-8'))
    groups = d.get('groups', {})
    assert groups.get('우주소녀') == 'WJSN', \
        f'우주소녀 should map to WJSN, got {groups.get("우주소녀")}'


def test_gate_logic_simulated():
    """gate ロジック simulation: 아일릿 ソース + ILLIT タイトルで誤検知が出ないこと"""
    from lib.korean_translator import apply_proper_noun_dict
    import re

    source_title = "아일릿, '청순→발칙' 통했다..'도파민 테크노'로 증명한 한계 없는 변신"
    title = "ILLIT、清純→挑発「ドーパミンテクノ」で証明した限界なき変身"

    # gate の 1h00 ロジックを抜粋して再現
    normalized, _ = apply_proper_noun_dict(source_title)
    src_text = normalized.lower()
    title_proper = set(re.findall(r'[A-Z][A-Za-z]{2,}', title))
    title_proper -= {'速報', 'KPOP'}
    added = {p for p in title_proper if p.lower() not in src_text}
    added -= {'COUNTDOWN', 'JOURNAL'}
    suspicious = {w for w in added if len(w) >= 3 and
                  w not in {'BTS','YG','SM','JYP','HYBE','MBC','SBS','KBS','Mnet'}}

    assert not suspicious, \
        f'ILLIT should not be flagged after dict expansion, got suspicious={suspicious}'


def test_tavily_quota_exhausted_flag_exists():
    """breaking_news_detector に Tavily quota exhausted flag が定義されていること

    quota exceed 時に同一 process 内で Tavily skip して DuckDuckGo に固定 fallback
    することで、毎回の Tavily API call 失敗とログ汚染を防ぐ。
    """
    src = open('/home/aiuser/kpop-ai-system/pipeline/breaking_news_detector.py',
               encoding='utf-8').read()
    assert '_TAVILY_QUOTA_EXHAUSTED' in src, \
        'process-local flag _TAVILY_QUOTA_EXHAUSTED must exist for quota guard'
    assert 'usage limit' in src.lower() or 'quota' in src.lower(), \
        'quota detection keyword must be referenced'
