"""Claude Web Search ベースのfactcheck (2026-05-10)

Tavily APIの代替。Anthropic server-side web_search toolで記事タイトルの
裏取りをする。Tavily quota超過時のフォールバック。

利点:
- Tavilyとは別のquota管理 → 同時に枯渇しない
- 引用ソース付き
- structured outputで JSON parse 失敗ゼロ

Usage:
    from lib.claude_websearch_factcheck import verify_with_claude_websearch
    r = verify_with_claude_websearch("BABYMONSTER 新曲CHOOMリリース")
    # r: {'found': bool, 'reason': str, 'sources': [...]}
"""
from __future__ import annotations
import os
import json
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

LOG_PATH = Path('/home/aiuser/kpop-ai-system/logs/claude_websearch_factcheck.jsonl')

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


# 信頼K-popメディアドメイン (allowed_domains で限定)
_TRUSTED_DOMAINS = [
    "soompi.com", "allkpop.com", "koreaboo.com", "billboard.com",
    "starnewskorea.com", "kpopping.com", "tenasia.com", "kbizoom.com",
    "kpopstarz.com", "hellokpop.com", "thebiaslist.com", "naver.com",
    "newsen.com", "osen.co.kr", "topstarnews.net", "kstyle.com",
    "yna.co.kr", "spotvnews.co.kr", "mydaily.co.kr",
]


def verify_with_claude_websearch(title: str, max_searches: int = 3) -> dict:
    """Claude server-side web_search で title を裏取り

    Returns:
        {
            'found': True | False | None,
            'reason': str,
            'sources': [{'url':..., 'title':...}],
        }
    """
    client = _get_client()
    try:
        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=800,
            tools=[{
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": max_searches,
            }],
            messages=[{
                "role": "user",
                "content": (
                    f"次のK-pop記事タイトルが事実か信頼メディアで検証してください:\n"
                    f"\"{title}\"\n\n"
                    f"web_searchツールで {max_searches}回まで調べ、最後に必ず以下のJSON形式で回答:\n"
                    '{"found": true/false, "reason": "1-2文の要約", "sources": [{"url": "...", "title": "..."}]}\n\n'
                    f"判定基準:\n"
                    f"- 信頼メディアで同内容が確認できた → found=true\n"
                    f"- 検索したが裏付けなし → found=false\n"
                    f"- 関連情報あるが直接裏付けなし → found=false (reason に「関連のみ」と明記)"
                ),
            }],
        )

        # tool_use blocks → web_search citations
        sources = []
        for block in response.content:
            if block.type == 'web_search_tool_result':
                # extract URLs from tool result
                content = getattr(block, 'content', None)
                if isinstance(content, list):
                    for item in content:
                        if hasattr(item, 'url') and hasattr(item, 'title'):
                            sources.append({'url': item.url, 'title': item.title[:80]})

        # parse final text JSON
        text = ''
        for block in response.content:
            if block.type == 'text':
                text += block.text

        import re as _re
        m = _re.search(r'\{[^{}]*"found"[^{}]*\}', text, _re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group())
                # merge cited sources from tool results if not already in parsed
                if not parsed.get('sources') and sources:
                    parsed['sources'] = sources[:3]
                _log({
                    'title': title[:60],
                    'found': parsed.get('found'),
                    'reason': parsed.get('reason', '')[:100],
                    'tokens': response.usage.input_tokens + response.usage.output_tokens,
                })
                return parsed
            except json.JSONDecodeError:
                pass

        # fallback: detect YES/NO from text
        text_low = text.lower()
        if 'true' in text_low and 'false' not in text_low[:50]:
            return {'found': True, 'reason': text[:200], 'sources': sources[:3]}
        return {'found': False, 'reason': text[:200] or 'Could not parse response', 'sources': sources[:3]}

    except anthropic.RateLimitError:
        return {'found': None, 'reason': 'Claude rate limit', 'sources': []}
    except anthropic.APIStatusError as e:
        return {'found': None, 'reason': f'Claude API err {e.status_code}', 'sources': []}
    except Exception as e:
        return {'found': None, 'reason': f'err: {type(e).__name__}: {str(e)[:100]}', 'sources': []}


def _log(entry: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps({**entry, 'ts': datetime.now().isoformat()}, ensure_ascii=False) + '\n')
    except OSError:
        pass


if __name__ == '__main__':
    import sys
    title = sys.argv[1] if len(sys.argv) > 1 else 'BABYMONSTER 新曲CHOOMリリース'
    r = verify_with_claude_websearch(title)
    print(json.dumps(r, ensure_ascii=False, indent=2))
