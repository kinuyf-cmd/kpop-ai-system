#!/usr/bin/env python3
"""web_factcheck.py — 投稿前のWeb検索ファクトチェック

LLM生成記事の主要クレームをWeb検索で裏取りする。
裏付けソースが見つからなければ BLOCK を返す。

使い方:
    from lib.web_factcheck import verify_article
    result = verify_article(title, body_text, kind='news')
    # result: {'verified': bool, 'confidence': float, 'sources': [...], 'issues': [...]}
"""

import os
import re
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

_JST = timezone(timedelta(hours=9))
_LOG_PATH = '/home/aiuser/kpop-ai-system/logs/web_factcheck.jsonl'

# 一次情報源（チケット販売／公式番組／公式イベント等）。
# これらに該当するシグナルが当たればWeb検索が空でもPASS同等の確信度を与える。
_AUTHORITATIVE_SIGNAL_SOURCES = {
    'ticket_guide',     # tickebo / pia 等のチケット販売サイト
    'kcon_monitor',     # KCON公式日程
    'music_show',       # 音楽番組
    'music_show_monitor',
    'music_show_weekly',
    'youtube_show',     # 公式YouTube番組
    'youtube_show_monitor',
}


def _extract_claims(title: str, body_text: str) -> list[dict]:
    """タイトルと本文から検証すべきクレーム（固有名詞×イベント）を抽出"""
    claims = []

    # タイトルから主要クレームを抽出
    # パターン: アーティスト名 + 動詞/イベント
    title_clean = re.sub(r'【[^】]+】', '', title).strip()
    claims.append({'type': 'title', 'text': title_clean, 'query': title_clean})

    # 本文から具体的な数字・日付・固有名詞を抽出
    # 新曲名・アルバム名の抽出
    song_matches = re.findall(r'[「『]([^」』]{2,30})[」』]', title + ' ' + body_text[:500])
    for song in song_matches[:3]:
        # アーティスト名も合わせて検索
        artist = re.findall(r'(BTS|BLACKPINK|TWICE|aespa|NewJeans|IVE|LE SSERAFIM|SEVENTEEN|'
                           r'Stray Kids|TXT|ENHYPEN|ITZY|NMIXX|NCT|EXO|Red Velvet|'
                           r'BABYMONSTER|ILLIT|KATSEYE|RIIZE|G-Dragon|LISA|JENNIE|Jisoo|'
                           r'MONSTA X|GOT7|DAY6|ATEEZ|TREASURE|fromis_9|MAMAMOO|'
                           r'Hearts2Hearts|xikers|PLAVE|iKON|KARA|2PM|SUPER JUNIOR|SHINee)',
                           title, re.IGNORECASE)
        if artist:
            claims.append({'type': 'song', 'text': song, 'query': f'{artist[0]} "{song}" 2026'})

    return claims


def _search_tavily(query: str, num_results: int = 5) -> list[dict]:
    """Tavily API でWeb検索（AI特化の検索エンジン）"""
    tavily_key = os.environ.get('TAVILY_API_KEY', '')
    if not tavily_key:
        return []

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=tavily_key)
        response = client.search(query, max_results=num_results, search_depth="basic")
        results = []
        for r in response.get('results', []):
            results.append({
                'url': r.get('url', ''),
                'title': r.get('title', ''),
                'content': r.get('content', '')[:200],
                'score': r.get('score', 0),
            })
        return results
    except Exception as e:
        return []


def _verify_with_tavily(title: str, body_text: str) -> dict:
    """Tavily QnA検索で記事の事実検証"""
    tavily_key = os.environ.get('TAVILY_API_KEY', '')
    if not tavily_key:
        return {'found': None, 'reason': 'TAVILY_API_KEY未設定', 'sources': []}

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=tavily_key)

        # タイトルの主要クレームを検索クエリに変換
        query = f'{title} K-POP 2026'
        response = client.search(
            query, max_results=5, search_depth="basic",
            exclude_domains=["kpopjournal.tokyo"],  # 自サイト除外（自己参照防止）
        )
        results = response.get('results', [])

        # 結果の分析：信頼できるK-POPメディアからのソースがあるか
        trusted_domains = [
            'soompi.com', 'allkpop.com', 'koreaboo.com', 'billboard.com',
            'kpopstarz.com', 'hellokpop.com', 'nme.com', 'rollingstone.com',
            'starnewskorea.com', 'pannchoa.com', 'kbizoom.com',
            'thebiaslist.com', 'kpopping.com', 'tenasia.com',
            'hollywoodreporter.com', 'variety.com', 'youtube.com',
            'gmanetwork.com', 'yahoo.com', 'reuters.com', 'apnews.com',
            'bbc.com', 'cnn.com', 'pitchfork.com', 'prtimes.jp',
        ]

        trusted_hits = []
        all_hits = []
        for r in results:
            url = r.get('url', '')
            content = r.get('content', '')
            score = r.get('score', 0)
            hit = {'url': url, 'title': r.get('title', ''), 'score': score}
            all_hits.append(hit)
            if any(d in url for d in trusted_domains) and score > 0.5:
                trusted_hits.append(hit)

        if trusted_hits:
            return {
                'found': True,
                'reason': f'信頼メディア{len(trusted_hits)}件で確認: {trusted_hits[0]["title"][:60]}',
                'sources': trusted_hits,
            }
        elif all_hits and all_hits[0].get('score', 0) > 0.85:
            # スコア0.85以上の高精度マッチのみ信頼
            return {
                'found': True,
                'reason': f'Web検索で高精度一致(score={all_hits[0]["score"]:.2f}): {all_hits[0]["title"][:60]}',
                'sources': all_hits[:3],
            }
        elif all_hits:
            # 関連情報はあるが直接裏付けではない → 裏付けなしと判定
            return {
                'found': False,
                'reason': f'直接裏付けなし（関連情報のみ: {all_hits[0]["title"][:50]}）',
                'sources': all_hits[:3],
            }
        else:
            return {
                'found': False,
                'reason': '裏付けソースがWeb上に見つかりません',
                'sources': [],
            }
    except Exception as e:
        return {'found': None, 'reason': f'Tavily error: {str(e)[:60]}', 'sources': []}


def _check_against_signals(title: str) -> dict:
    """trend_signals.jsonlに元ネタがあるか照合"""
    signals_path = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'
    if not os.path.exists(signals_path):
        return {'matched': False}

    title_lower = title.lower()
    # タイトルから固有名詞（アーティスト名+イベント/曲名）を抽出
    # アーティスト名単体の一致では不十分。イベント/曲名も一致する必要がある
    artists = re.findall(
        r'BTS|BLACKPINK|TWICE|aespa|NewJeans|IVE|LE SSERAFIM|SEVENTEEN|'
        r'Stray Kids|TXT|ENHYPEN|ITZY|NMIXX|NCT|EXO|Red Velvet|'
        r'BABYMONSTER|ILLIT|KATSEYE|RIIZE|G-Dragon|LISA|JENNIE|Jisoo|'
        r'KARINA|MONSTA X|GOT7|DAY6|ATEEZ|TREASURE|fromis_9',
        title, re.IGNORECASE)

    # 曲名・イベント名を抽出（括弧内）
    specifics = re.findall(r'[「『"](.*?)[」』"]', title)
    # 数字を含む固有情報
    specifics += re.findall(r'\d+[万億兆回位日月]', title)

    if not artists or not specifics:
        return {'matched': False}

    matches = []
    try:
        with open(signals_path, encoding='utf-8') as f:
            for line in f:
                try:
                    sig = json.loads(line)
                    sig_text = (sig.get('title', '') + ' ' + sig.get('summary', '')).lower()
                    # アーティスト名が一致 AND 固有情報（曲名等）も一致
                    artist_match = any(a.lower() in sig_text for a in artists)
                    specific_match = any(s.lower() in sig_text for s in specifics if len(s) >= 2)
                    if artist_match and specific_match:
                        matches.append({
                            'source': sig.get('source', ''),
                            'url': sig.get('url', ''),
                            'title': sig.get('title', '')[:60],
                        })
                except:
                    pass
    except:
        pass

    if matches:
        # 一次情報源を優先
        matches.sort(key=lambda m: 0 if m.get('source') in _AUTHORITATIVE_SIGNAL_SOURCES else 1)
        return {
            'matched': True,
            'source': matches[0],
            'authoritative': matches[0].get('source') in _AUTHORITATIVE_SIGNAL_SOURCES,
        }
    return {'matched': False, 'authoritative': False}


def verify_article(title: str, body_text: str, kind: str = 'news',
                   source_url: str = None) -> dict:
    """記事の事実検証

    Returns:
        {
            'verified': True/False/None,
            'confidence': 0.0-1.0,
            'sources': [...],
            'issues': [...],
            'verdict': 'PASS' | 'WARN' | 'BLOCK'
        }
    """
    issues = []
    sources = []

    # 1. ソースURLがある場合はそれを信頼
    if source_url and source_url.startswith('http'):
        return {
            'verified': True,
            'confidence': 0.9,
            'sources': [{'type': 'source_url', 'url': source_url}],
            'issues': [],
            'verdict': 'PASS',
        }

    # 2. Web検索による裏取り (Tavily → 失敗時 Claude web_search にフォールバック)
    tavily_result = _verify_with_tavily(title, body_text)
    tavily_found = tavily_result.get('found')
    # Tavilyがquota超過/未設定/エラーの場合 Claude web_search に切り替え
    if tavily_found is None and ('quota' in tavily_result.get('reason', '').lower()
                                  or '未設定' in tavily_result.get('reason', '')
                                  or 'error' in tavily_result.get('reason', '').lower()):
        try:
            from lib.claude_websearch_factcheck import verify_with_claude_websearch
            cw = verify_with_claude_websearch(title)
            if cw.get('found') is not None:
                tavily_result = cw
                tavily_found = cw.get('found')
                tavily_result['reason'] = f"[Claude WS fallback] {cw.get('reason','')[:150]}"
        except Exception:
            pass

    if tavily_result.get('sources'):
        for s in tavily_result['sources'][:3]:
            sources.append({'type': 'web_search', 'url': s.get('url', ''), 'title': s.get('title', '')})

    if tavily_found is False:
        issues.append({
            'type': 'no_web_source',
            'detail': tavily_result.get('reason', '裏付けソースなし'),
        })

    # 3. シグナルDBとの照合（補助）
    sig_result = _check_against_signals(title)
    has_signal = sig_result.get('matched', False)
    authoritative_signal = sig_result.get('authoritative', False)
    if has_signal:
        sources.append({
            'type': 'signal_authoritative' if authoritative_signal else 'signal',
            'detail': sig_result['source'],
        })

    # 4. 判定（Tavily結果を最優先、シグナルは補助 / 一次情報源シグナルは Tavily 並みに信頼）
    if tavily_found is True:
        verdict = 'PASS'
        confidence = 0.9
        verified = True
    elif tavily_found is False and authoritative_signal:
        # Web未掲載でも一次情報源（チケット/KCON/音楽番組）に裏付け → PASS
        verdict = 'PASS'
        confidence = 0.8
        verified = True
    elif tavily_found is False and not has_signal:
        # Web検索で見つからず、シグナルもない → BLOCK
        verdict = 'BLOCK'
        confidence = 0.8
        verified = False
    elif tavily_found is False and has_signal:
        # Web検索で見つからないがシグナルはある（非権威） → WARN
        verdict = 'WARN'
        confidence = 0.4
        verified = None
    elif tavily_found is None and authoritative_signal:
        # Tavily不明でも一次情報源シグナルで確認可 → PASS
        verdict = 'PASS'
        confidence = 0.75
        verified = True
    elif tavily_found is None and has_signal:
        # Tavily不明だがシグナルあり（非権威） → WARN
        verdict = 'WARN'
        confidence = 0.5
        verified = None
    else:
        # Tavily不明、シグナルなし
        if kind == 'feature':
            verdict = 'BLOCK'
            confidence = 0.3
            verified = False
        else:
            verdict = 'WARN'
            confidence = 0.3
            verified = None

    result = {
        'verified': verified,
        'confidence': confidence,
        'sources': sources,
        'issues': issues,
        'verdict': verdict,
    }

    # ログ記録
    try:
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        with open(_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'ts': datetime.now(_JST).isoformat(),
                'title': title[:60],
                'kind': kind,
                'verdict': verdict,
                'confidence': confidence,
                'has_signal': has_signal,
                'tavily_found': tavily_found,
            }, ensure_ascii=False) + '\n')
    except:
        pass

    return result


if __name__ == '__main__':
    import sys
    from dotenv import load_dotenv
    load_dotenv('/home/aiuser/kpop-ai-system/.env')

    title = sys.argv[1] if len(sys.argv) > 1 else 'SEVENTEEN新曲「ソノゴン」の魅力とは'
    result = verify_article(title, '', kind='feature')
    print(json.dumps(result, ensure_ascii=False, indent=2))
