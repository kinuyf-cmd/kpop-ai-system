"""ソース記事本文取得 — 全パイプライン共通

記事を書く前に必ずソースを読む。これは絶対ルール。
ソースURLがあるのにソース本文なしでGPTに記事を書かせてはならない。

Usage:
    from lib.source_reader import read_source, read_sources

    # 単一URL
    text = read_source('https://www.koreaboo.com/news/...')

    # 複数シグナルから最良のソース本文を取得
    text = read_sources([{'url': '...', 'title': '...'}, ...])
"""
import re
import urllib.request
import urllib.error

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 KPOPJournal-Bot/1.0',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'en-US,en;q=0.9,ko;q=0.8,ja;q=0.7',
}

# フェッチしても意味のないドメイン
_SKIP_DOMAINS = [
    'youtube.com', 'youtu.be', 'instagram.com', 'tiktok.com',
    'twitter.com', 'x.com', 'facebook.com', 'reddit.com',
]


def read_source(url: str, max_chars: int = 2000) -> str:
    """URLから記事本文をフェッチしてプレーンテキストで返す。

    Args:
        url: ソース記事のURL
        max_chars: 取得する最大文字数

    Returns:
        プレーンテキスト (失敗時は空文字列)
    """
    if not url or not url.startswith('http'):
        return ''

    # スキップドメイン
    if any(d in url for d in _SKIP_DOMAINS):
        return ''

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8', errors='ignore')

        # HTML→プレーンテキスト
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        # ナビゲーション/フッター除去: 本文部分を推定抽出
        if len(text) > 500:
            text = text[300:300 + max_chars]

        return text.strip()

    except urllib.error.HTTPError as e:
        print(f"  [source_reader] HTTP {e.code}: {url[:50]}")
        return ''
    except Exception as e:
        print(f"  [source_reader] err: {url[:50]} — {e}")
        return ''


def read_sources(signals: list, max_chars: int = 2000) -> str:
    """複数シグナルから最良のソース本文を取得。

    最初に200字以上取得できたソースを返す。
    """
    for sig in signals[:5]:
        url = sig.get('url', '')
        text = read_source(url, max_chars=max_chars)
        if text and len(text) > 200:
            print(f"  [source_reader] OK: {url[:50]} ({len(text)}字)")
            return text

    print(f"  [source_reader] WARN: 全{len(signals[:5])}件のソースから本文取得失敗")
    return ''
