"""
memory: feedback_popup_article_cta.md
規定: 「popup記事に「開催中の全ポップアップ情報はこちら」CTA必須」
"""
import os


def test_popup_cta_helper_exists():
    """popup CTA挿入ロジックが存在 (lib/ pipeline/ いずれか)"""
    import glob
    found = False
    keywords = ('popup-list', 'pop-up一覧', 'ポップアップ一覧', '開催中の全ポップアップ',
                'popup_cta', 'popup-cta', '/category/popup', 'popup_roundup')
    for base in ('/home/aiuser/kpop-ai-system/lib', '/home/aiuser/kpop-ai-system/pipeline'):
        for p in glob.glob(f'{base}/**/*.py', recursive=True):
            try:
                text = open(p, encoding='utf-8', errors='ignore').read()
            except Exception:
                continue
            if any(k in text for k in keywords):
                found = True
                break
        if found:
            break
    assert found, "popup CTA関連ロジックが lib/ pipeline/ に見つからない"
