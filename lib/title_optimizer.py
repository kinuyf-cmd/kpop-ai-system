#!/usr/bin/env python3
"""タイトル最適化: 日本語42文字厳守、SEO/CTR最適"""
import os, json, re, urllib.request
from dotenv import load_dotenv
from lib.agent_learning_loop import inject_lessons_to_prompt
load_dotenv()

API = "https://api.openai.com/v1/chat/completions"
MAX_TITLE = 42


def optimize_title(raw_title: str, body: str = '') -> str:
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        return raw_title[:MAX_TITLE]

    system = (
        "あなたはK-POP専門Webメディアの見出し編集者。ルール厳守:\n"
        f"1. 日本語{MAX_TITLE}文字以内 (絶対厳守)\n"
        "2. アーティスト/グループ名を前半に\n"
        "3. 数字・固有名詞・日付は保持\n"
        "4. 助詞最小限、体言止め推奨\n"
        "5. 【】は原題にある場合のみ保持\n"
        "6. 誇張禁止、事実のみ\n"
        "7. 出力はタイトル1行のみ"
    )
    user = f"原題: {raw_title}"
    if body:
        user += f"\n本文冒頭: {body[:300]}"
    user += f"\n\n最適化タイトル({MAX_TITLE}文字以内):"

    body_req = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [
            {'role': 'system', 'content': inject_lessons_to_prompt('feature_article_writer', system)},
            {'role': 'user', 'content': user},
        ],
        'temperature': 0.3,
        'max_tokens': 100,
    }).encode()

    req = urllib.request.Request(API, data=body_req, headers={
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
    })

    try:
        r = urllib.request.urlopen(req, timeout=30)
        res = json.loads(r.read())
        title = res['choices'][0]['message']['content'].strip().strip('「」""').split('\n')[0].strip()
        if len(title) > MAX_TITLE:
            title = title[:MAX_TITLE]
        return title if len(title) >= 10 else raw_title[:MAX_TITLE]
    except Exception as e:
        print(f"  title_optimizer error: {e}")
        return raw_title[:MAX_TITLE]


def _fallback_slug(title: str) -> str:
    """GPT不使用のフォールバックスラッグ生成。英語部分を抽出+タイムスタンプ"""
    parts = re.findall(r'[a-zA-Z0-9]+', title)
    base = '-'.join(p.lower() for p in parts if len(p) > 1)[:40]
    if len(base) < 20:
        from datetime import datetime
        base = f"kpop-article-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    return re.sub(r'-+', '-', base).strip('-')


def validate_slug(slug: str) -> str:
    """スラッグがASCII/適切長であることを検証。不合格なら空文字を返す"""
    if not slug:
        return ''
    slug = slug.lower().strip()
    slug = re.sub(r'[^a-z0-9-]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    # 不正パターンの検出
    if '%' in slug:
        return ''  # エンコード文字が残っている
    if re.match(r'^post-\d+$', slug) or re.match(r'^popup-\d+$', slug):
        return ''  # 自動生成スラッグ
    if '__trashed' in slug:
        return ''
    if len(slug) < 15:
        return ''  # 短すぎる（監査基準に合わせ最低15文字）
    return slug[:60]


def generate_slug(title: str) -> str:
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        return _fallback_slug(title)

    body_req = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [
            {'role': 'system', 'content': (
                "記事タイトルからURLスラッグ生成:\n"
                "1. 英小文字+数字+ハイフンのみ（日本語禁止）\n"
                "2. 20-50文字\n"
                "3. アーティスト名+キーワード2-3語\n"
                "4. 出力はスラッグ1行のみ"
            )},
            {'role': 'user', 'content': f"タイトル: {title}\nスラッグ:"},
        ],
        'temperature': 0.1,
        'max_tokens': 50,
    }).encode()

    req = urllib.request.Request(API, data=body_req, headers={
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
    })

    try:
        r = urllib.request.urlopen(req, timeout=20)
        res = json.loads(r.read())
        slug = res['choices'][0]['message']['content'].strip().lower().split('\n')[0].strip()
        slug = validate_slug(slug)
        if slug:
            return slug
    except Exception:
        pass
    # GPT失敗時のフォールバック
    return _fallback_slug(title)


def generate_meta_description(title: str, body: str) -> str:
    key = os.getenv('OPENAI_API_KEY')
    if not key or not body:
        return body[:150] if body else ''

    body_req = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [
            {'role': 'system', 'content': '記事のタイトルと本文から、SEO最適なメタディスクリプション(120-155文字)を生成。事実のみ。出力は1行のみ。'},
            {'role': 'user', 'content': f"タイトル: {title}\n本文: {body[:500]}\nメタディスクリプション:"},
        ],
        'temperature': 0.3,
        'max_tokens': 200,
    }).encode()

    req = urllib.request.Request(API, data=body_req, headers={
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
    })

    try:
        r = urllib.request.urlopen(req, timeout=20)
        res = json.loads(r.read())
        return res['choices'][0]['message']['content'].strip().split('\n')[0][:160]
    except Exception:
        return body[:150] if body else ''


if __name__ == '__main__':
    import sys
    raw = sys.argv[1] if len(sys.argv) > 1 else 'TWICEのダヒョン、東京公演から限定的にパフォーマンスに復帰することが発表された'
    print(f"原題({len(raw)}文字): {raw}")
    opt = optimize_title(raw)
    print(f"最適化({len(opt)}文字): {opt}")
    print(f"スラッグ: {generate_slug(opt)}")
