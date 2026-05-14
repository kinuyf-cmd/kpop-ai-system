"""
2026-05-14: llm_proofreader が style 提案を high として返した場合に
post-process で medium に downgrade することの機械検証。

事故 (5/14 監査): 23125/23162/23194/23224/23237 が score 80-85 だが
high issues はすべて「冗長」「より自然」「改善余地」「あいまい」等の
スタイル提案 → factcheck=fail 誤判定で 5 件が draft 化対象になりかけた。

memory: feedback_llm_proofreader_false_positive
"""
import inspect
import sys

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_prompt_no_longer_allows_general_unnatural_japanese_as_high():
    """prompt の high 判定基準から「不自然な日本語」一般指摘が削除されていること"""
    from pipeline import llm_proofreader
    src = inspect.getsource(llm_proofreader.proofread_post)
    # high 行に「不自然な日本語」単独定義が無いこと
    assert 'high: 不自然な日本語、' not in src, \
        'prompt が「不自然な日本語」を high として認めている (style 誤検知の温床)'


def test_prompt_excludes_style_suggestions_explicitly():
    """prompt に style 提案を high として報告するなとの明示禁止があること"""
    from pipeline import llm_proofreader
    src = inspect.getsource(llm_proofreader.proofread_post)
    assert '冗長' in src and 'より自然な表現' in src and '改善余地' in src, \
        'prompt の禁止リストに style suggestion キーワードが入っていない'


def test_post_process_demotes_style_high_to_medium():
    """post-process filter が style 提案 high を medium に downgrade すること"""
    src = open('/home/aiuser/kpop-ai-system/pipeline/llm_proofreader.py',
               encoding='utf-8').read()
    # style_kw タプルの存在 + downgrade logic
    assert 'style_kw' in src or 'demoted' in src, \
        'post-process style downgrade logic が無い'
    assert "'冗長'" in src and "'より自然'" in src and "'改善余地'" in src, \
        'style_kw に主要 false-positive キーワードが無い'


def test_post_process_filter_actually_runs(monkeypatch):
    """proofread_post の実行で実際に style high → medium downgrade されること
    (LLM 呼出を mock して filter のみ検証)"""
    import urllib.request
    from pipeline import llm_proofreader

    fake_llm_response = {
        'score': 80,
        'critical': [],
        'high': [
            '「魅力披露」という表現が不自然な日本語であり、改善できる',
            '「興奮を示しています」が冗長な表現',
            'メンバー名「TWICE」の表記が間違っており、正しくは「TWICE」ではなく別の名前',
        ],
        'medium': [],
    }

    class FakeResp:
        def __init__(self, payload):
            self.payload = payload
        def read(self):
            import json
            return json.dumps({
                'choices': [{'message': {'content': json.dumps(self.payload)}}]
            }).encode()

    def fake_urlopen(req, timeout=60):
        return FakeResp(fake_llm_response)

    monkeypatch.setattr(urllib.request, 'urlopen', fake_urlopen)
    monkeypatch.setenv('OPENAI_API_KEY', 'fake-key')
    monkeypatch.setattr(llm_proofreader, 'OPENAI_KEY', 'fake-key')

    fake_post = {
        'title': {'rendered': 'テストタイトル'},
        'content': {'rendered': '<p>テスト本文です。</p>' * 50},
        'id': 99999,
        'type': 'post',
    }
    result = llm_proofreader.proofread_post(fake_post)

    # 1番目と2番目は style 系 → demoted to medium
    # 3番目はメンバー名の問題 → high に残るはず
    high_text = ' '.join(str(x) for x in result.get('high', []))
    medium_text = ' '.join(str(x) for x in result.get('medium', []))

    assert '魅力披露' not in high_text, '魅力披露 (style) が high に残っている'
    assert '冗長' not in high_text, '冗長 (style) が high に残っている'
    assert '魅力披露' in medium_text or '冗長' in medium_text, \
        'style 提案が medium に降格されていない'
