"""factcheck v2 — Claude Sonnet 4.6 + Web search + Prompt caching + Structured outputs

llm_proofreader.proofread_post() の Claude版。OpenAI gpt-4o-mini代替。

機能:
- Web search tool (server-side) で外部ファクトチェック (Tavily不要)
- Prompt caching で K-pop知識prefix を90%コスト削減
- Structured outputs でJSON parse失敗ゼロ
- メンバー人数/所属事務所/デビュー年の誤りを web search で実証

Usage:
    from lib.factcheck_v2 import proofread_post_v2
    result = proofread_post_v2(post)  # post: {'id', 'title', 'content'}
    # → {'score': 0-100, 'critical': [...], 'high': [...], 'medium': [...]}

統合方法:
    proofread_post() で env flag FACTCHECK_V2=1 のとき呼び出し
"""
from __future__ import annotations
import os
import json
import re
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

LOG_PATH = Path('/home/aiuser/kpop-ai-system/logs/factcheck_v2.jsonl')
CACHE_PATH = Path('/home/aiuser/kpop-ai-system/data/factcheck_v2_cache.json')
CACHE_TTL_SEC = 6 * 3600  # 同一 title+content の連続呼び出し (pre_publish_gate → post_publish_hook → comprehensive_audit) を 1回に折り畳む

# Prompt caching用 K-pop審査基準 (1500+ tokens, 5分TTL)
KPOP_FACTCHECK_PREFIX = """あなたはK-POP専門メディアの校閲AIです。以下のK-pop知識基盤と判定ルールに従って記事を校閲してください。

## 主要K-popグループ覚え書き
- BLACKPINK (YG, 2016年デビュー, 4人, 女性): Jisoo/Jennie/Rosé/Lisa
- aespa (SM, 2020年, 4人, 女性): Karina/Giselle/Winter/Ningning
- BTS (HYBE/Bighit, 2013年, 7人, 男性): RM/Jin/Suga/J-Hope/Jimin/V/Jungkook
- TWICE (JYP, 2015年, 9人, 女性): Nayeon/Jeongyeon/Momo/Sana/Jihyo/Mina/Dahyun/Chaeyoung/Tzuyu
- NewJeans (ADOR/HYBE, 2022年, 5人, 女性): Minji/Hanni/Danielle/Haerin/Hyein
- IVE (Starship, 2021年, 6人, 女性): Yujin/Gaeul/Rei/Wonyoung/Liz/Leeseo
- LE SSERAFIM (Source/HYBE, 2022年, 5人, 女性): Sakura/Chaewon/Yunjin/Kazuha/Eunchae
- ITZY (JYP, 2019年, 5人, 女性): Yeji/Lia/Ryujin/Chaeryeong/Yuna
- SEVENTEEN (Pledis/HYBE, 2015年, 13人, 男性)
- Stray Kids (JYP, 2018年, 8人, 男性)
- ENHYPEN (Belift/HYBE, 2020年, 7人, 男性)
- TXT/TOMORROW X TOGETHER (Bighit, 2019年, 5人, 男性)
- ATEEZ (KQ, 2018年, 8人, 男性)
- TREASURE (YG, 2020年, 10人 → 現在7人, 男性)
- NMIXX (JYP, 2022年, 6人, 女性)
- ILLIT (Belift/HYBE, 2024年, 5人, 女性)
- BABYMONSTER (YG, 2023年, 7人, 女性): Ahyeon/Pharita/Asa/Rami/Ruka/Rora/Chiquita
- BOYNEXTDOOR (KOZ/HYBE, 2023年, 6人, 男性)
- RIIZE (SM, 2023年, 7人, 男性)
- TWS (Pledis/HYBE, 2024年, 6人, 男性)
- KISS OF LIFE (S2, 2023年, 4人, 女性)

## 判定基準
- **critical**: 人名/グループ名間違い, 数値矛盾, 存在しない人物, ソース記事にない事実の追加(捏造), タイトル本文不一致(妹/姉間違い等), バラエティ番組を新曲と誤記
- **high**: 不自然な日本語, タイトルと本文の不整合, 重要事実の省略, リリース日の誤り
- **medium**: 表現の改善余地, 軽微な表記揺れ

## 絶対に問題として報告してはいけないもの (LLM proofreader 誤検知 memory rule)
- 2026年以降の日付は正常 (現在は2026年)
- 曜日と日付の整合性チェック (暦計算は不正確)
- K-POPアーティスト名の英語/韓国語/日本語表記揺れ
- カムバック/ファンミ/アンコール等のK-POPファン用語
- 「TWICE・ITZY・Stray Kids」のようなグループ列挙は「TWICEはX人」と主張していないので、メンバー数誤りとして報告してはならない
- 「JYP所属のTWICE」のような所属関係の記述は事実関係でメンバー数とは無関係
- slug/URL/メタ情報は本文の事実とは無関係

## スコア基準
- 95-100: 問題なし
- 80-94: medium問題のみ
- 60-79: high問題あり
- 60未満: critical問題あり

## 検証手順
1. タイトルと本文の整合性チェック (主語/数字/日付の一致)
2. 上記K-pop覚え書きと矛盾しないか
3. 必要なら web_search ツールで信頼メディア (soompi/allkpop/billboard/naver/newsen/starnewskorea等) で裏取り
4. 結果をJSON schemaに従って返却
"""

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


# Claude structured outputs はnumerical constraints (minimum/maximum)非サポート
# verified_facts は呼び出し側で参照されておらず output token を圧迫していたため削除 (2026-05-12)
_FACTCHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "critical": {"type": "array", "items": {"type": "string"}},
        "high": {"type": "array", "items": {"type": "string"}},
        "medium": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "critical", "high", "medium"],
    "additionalProperties": False,
}


def _cache_key(title: str, plain: str) -> str:
    h = hashlib.sha256()
    h.update(title.encode('utf-8', errors='ignore'))
    h.update(b'\x1f')
    h.update(plain[:3000].encode('utf-8', errors='ignore'))
    return h.hexdigest()[:24]


def _cache_load() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _cache_get(key: str) -> dict | None:
    cache = _cache_load()
    entry = cache.get(key)
    if not entry:
        return None
    if time.time() - entry.get('ts', 0) > CACHE_TTL_SEC:
        return None
    return entry.get('result')


def _cache_put(key: str, result: dict) -> None:
    try:
        cache = _cache_load()
        now = time.time()
        cache = {k: v for k, v in cache.items() if now - v.get('ts', 0) <= CACHE_TTL_SEC}
        cache[key] = {'ts': now, 'result': result}
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def proofread_post_v2(post: dict, use_web_search: bool = True) -> dict:
    """Claude Sonnet 4.6で記事校閲

    Args:
        post: {'id', 'title', 'content'}
        use_web_search: True ならweb_searchツール有効化 (3回まで)

    Returns:
        {'score', 'critical', 'high', 'medium'}
    """
    title = post['title']['rendered'] if isinstance(post.get('title'), dict) else post.get('title', '')
    content = post['content']['rendered'] if isinstance(post.get('content'), dict) else post.get('content', '')
    plain = re.sub(r'<[^>]+>', ' ', content)
    plain = re.sub(r'\s+', ' ', plain).strip()[:2500]

    ck = _cache_key(title, plain)
    cached = _cache_get(ck)
    if cached is not None:
        _log({
            'pid': post.get('id'),
            'title': title[:60],
            'score': cached.get('score'),
            'critical_count': len(cached.get('critical', [])),
            'high_count': len(cached.get('high', [])),
            'medium_count': len(cached.get('medium', [])),
            'usage': {'cache_hit': True},
        })
        return cached

    today = datetime.now(timezone.utc).strftime('%Y年%m月%d日')

    # 過去の検出事例 (lessons learned) を prompt に注入 — 自己学習
    try:
        from lib.factcheck_lessons import get_recent_lessons, format_lessons_for_prompt
        lessons = get_recent_lessons(days=30, max_count=12)
        lessons_section = format_lessons_for_prompt(lessons)
    except Exception:
        lessons_section = ''

    user_prompt = f"""今日の日付: {today}

## 校閲対象記事
【タイトル】{title}
【本文抜粋】{plain}
{('\n' + lessons_section + '\n') if lessons_section else ''}
上記K-pop知識基盤と判定ルールに従って校閲し、JSONで返却してください。
不明な事実 (新曲名/最新リリース日等) があれば web_search ツールで信頼メディアで裏取りしてからJSON結果を返してください。
"""

    tools = []
    if use_web_search:
        tools = [{
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": 3,
        }]

    try:
        client = _get_client()
        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=1500,
            system=[{
                "type": "text",
                "text": KPOP_FACTCHECK_PREFIX,
                "cache_control": {"type": "ephemeral"},
            }],
            tools=tools,
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": _FACTCHECK_SCHEMA,
                },
            },
            messages=[{"role": "user", "content": user_prompt}],
        )
        # 最初のtext blockがschema-validated JSON
        text = next((b.text for b in response.content if b.type == 'text'), '{}')
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            return {'score': 50, 'critical': [], 'high': [f'schema parse err: {text[:100]}'], 'medium': []}

        # ログ
        _log({
            'pid': post.get('id'),
            'title': title[:60],
            'score': result.get('score'),
            'critical_count': len(result.get('critical', [])),
            'high_count': len(result.get('high', [])),
            'medium_count': len(result.get('medium', [])),
            'usage': {
                'input': response.usage.input_tokens,
                'output': response.usage.output_tokens,
                'cache_create': getattr(response.usage, 'cache_creation_input_tokens', 0),
                'cache_read': getattr(response.usage, 'cache_read_input_tokens', 0),
            },
        })

        # 同一 title+content の連続呼び出しを 1回に折り畳むため結果をキャッシュ
        _cache_put(ck, result)

        # 自己学習: critical/high issue を lessons.jsonl に追加
        try:
            from lib.factcheck_lessons import append_lessons
            append_lessons(post.get('id', 0), title, result)
        except Exception:
            pass

        return result

    except anthropic.RateLimitError:
        return {'score': 50, 'critical': [], 'high': ['Claude rate limit'], 'medium': []}
    except anthropic.APIStatusError as e:
        return {'score': 50, 'critical': [], 'high': [f'API err {e.status_code}'], 'medium': []}
    except Exception as e:
        return {'score': 50, 'critical': [], 'high': [f'err: {type(e).__name__}'], 'medium': []}


def _log(entry: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps({**entry, 'ts': datetime.now().isoformat()}, ensure_ascii=False) + '\n')
    except OSError:
        pass


if __name__ == '__main__':
    import sys
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 19623
    import urllib.request
    d = json.load(urllib.request.urlopen(f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{pid}?_fields=id,title,content', timeout=15))
    r = proofread_post_v2(d)
    print(json.dumps(r, ensure_ascii=False, indent=2))
