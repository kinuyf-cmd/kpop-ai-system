"""薬機法チェッカー — 化粧品記事の禁止表現検出"""
import json, re
from pathlib import Path

BLACKLIST_PATH = Path('/home/aiuser/kpop-ai-system/config/yakkihou_blacklist.json')

def load_blacklist():
    return json.load(open(BLACKLIST_PATH)) if BLACKLIST_PATH.exists() else {'categories': {}}

def check(text):
    bl = load_blacklist()
    issues = []
    for cat_name, cat_data in bl.get('categories', {}).items():
        for pat in cat_data.get('patterns', []):
            for m in re.finditer(re.escape(pat), text):
                issues.append({
                    'category': cat_name, 'pattern': pat,
                    'severity': cat_data.get('severity', 'medium'),
                    'pos': m.start(),
                    'suggested': cat_data.get('suggested', ''),
                    'context': text[max(0, m.start()-20):m.end()+20],
                })
    return issues

def is_cosmetic_article(title, categories=None):
    keywords = ['コスメ', '美容', 'スキンケア', '化粧', 'ヘアケア', '美肌', 'メイク', 'ファンデ', 'リップ', 'カラコン']
    return any(k in title for k in keywords)
