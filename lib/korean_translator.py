#!/usr/bin/env python3
"""Korean → Japanese 翻訳 (GPT-4o-mini)"""
import os, json, urllib.request, datetime
from dotenv import load_dotenv
load_dotenv()

API = "https://api.openai.com/v1/chat/completions"
LOG = '/home/aiuser/kpop-ai-system/logs/translation.jsonl'
DAILY_LIMIT = 100


def _count_today():
    if not os.path.exists(LOG):
        return 0
    today = datetime.date.today().isoformat()
    return sum(1 for line in open(LOG, encoding='utf-8')
               if line.strip() and json.loads(line).get('date') == today)


def translate_ko_to_ja(text, context='K-POP entertainment news'):
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        return {'success': False, 'translated': text, 'reason': 'OPENAI_API_KEY未設定'}
    if _count_today() >= DAILY_LIMIT:
        return {'success': False, 'translated': text, 'reason': f'1日上限{DAILY_LIMIT}到達'}

    system = ("あなたはK-POP専門の韓国語→日本語翻訳者。"
              "1. 自然な日本語に翻訳 2. アーティスト名は英語表記優先(방탄소년단→BTS) "
              "3. 推測や創作禁止、原文にない情報書かない 4. 出力はプレーンテキストのみ")

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f"Context: {context}\n\n韓国語原文:\n{text[:3000]}\n\n日本語訳:"}
        ],
        'temperature': 0.3,
        'max_tokens': 2000,
    }).encode()

    req = urllib.request.Request(API, data=body, headers={
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
    })

    try:
        r = urllib.request.urlopen(req, timeout=60)
        res = json.loads(r.read())
    except Exception as e:
        return {'success': False, 'translated': text, 'reason': str(e)[:200]}

    translated = res['choices'][0]['message']['content']
    usage = res.get('usage', {})
    cost = usage.get('prompt_tokens', 0) * 0.15 / 1e6 + usage.get('completion_tokens', 0) * 0.60 / 1e6

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'date': datetime.date.today().isoformat(),
            'ts': datetime.datetime.now().isoformat(),
            'cost_usd': cost,
            'tokens': usage,
        }) + '\n')
    return {'success': True, 'translated': translated, 'cost_usd': cost}


if __name__ == '__main__':
    import sys
    text = sys.argv[1] if len(sys.argv) > 1 else "방탄소년단이 새 앨범을 발표했다."
    print(json.dumps(translate_ko_to_ja(text), ensure_ascii=False, indent=2))
