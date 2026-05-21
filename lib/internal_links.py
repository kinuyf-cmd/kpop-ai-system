"""
内部リンク自動挿入モジュール

WordPress REST APIで既存記事のタイトル・URLリストを取得してキャッシュし、
新記事のHTML本文にアーティスト名・キーワードにマッチする既存記事へのリンクを
自動挿入する。記事末尾に「関連記事」セクションも追加する。

Usage:
  from lib.internal_links import insert_internal_links

  html_with_links = insert_internal_links(html_body, post_title="BTS新曲...")
"""

import json
import os
import re
import time
from datetime import datetime
from typing import Optional
import urllib.request
import urllib.error

# ── 設定 ──────────────────────────────────────────────────────────────────────
WP_URL = os.environ.get("WP_URL", "https://www.kpopjournal.tokyo")


def _wp_auth_header() -> str:
    """~/.wp_auth (curl config形式) から Authorization ヘッダ値を読む。
    フォールバック: WP_USER / WP_PASS 環境変数から生成。
    戻り値: 'Authorization: Basic xxxx' の文字列。
    """
    import re as _re
    wp_auth_path = os.path.expanduser("~/.wp_auth")
    if os.path.exists(wp_auth_path):
        with open(wp_auth_path) as f:
            for line in f:
                m = _re.match(r'header\s*=\s*"(Authorization:\s*Basic\s+[^"\\n]+)"?', line.strip())
                if m:
                    return m.group(1)
    # フォールバック: 環境変数
    import base64
    user = os.environ.get("WP_USER", "")
    passwd = os.environ.get("WP_PASS", "")
    token = base64.b64encode(f"{user}:{passwd}".encode()).decode()
    return f"Authorization: Basic {token}"

CACHE_FILE = "/home/aiuser/kpop-ai-system/logs/article_index.json"
CACHE_TTL_SECONDS = 3600  # 1時間キャッシュ

MAX_LINKS = 5  # 最大挿入リンク数
MIN_TITLE_LEN = 5  # タイトルが短すぎる記事は検索対象外

# ── アーティスト名・キーワード（検索用） ─────────────────────────────────────
ARTIST_NAMES = [
    "BTS", "TWICE", "BLACKPINK", "IVE", "ILLIT", "aespa", "NewJeans",
    "ENHYPEN", "TXT", "Stray Kids", "SEVENTEEN", "MAMAMOO", "EXO",
    "NCT", "RIIZE", "ZERO BASE ONE", "LE SSERAFIM", "Red Velvet",
    "GOT7", "MONSTA X", "ATEEZ", "THE BOYZ", "TOMORROW X TOGETHER",
]

GENRE_KEYWORDS = [
    "ガラス肌", "スキンケア", "カムバック", "ライブ", "チャート",
    "ビルボード", "訴訟", "ツアー", "ソウル", "旅行",
    "コスメ", "アイドル", "韓国", "Billboard", "comeback",
    "skincare", "concert", "tour", "chart",
]


# ── キャッシュ管理 ────────────────────────────────────────────────────────────

def _load_cache() -> Optional[list[dict]]:
    """キャッシュファイルを読み込む。TTL切れ・未存在の場合はNoneを返す。"""
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_at = data.get("cached_at", 0)
        if time.time() - cached_at > CACHE_TTL_SECONDS:
            return None
        return data.get("articles", [])
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def _save_cache(articles: list[dict]) -> None:
    """記事リストをキャッシュファイルに保存する。"""
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    payload = {
        "cached_at": time.time(),
        "cached_date": datetime.now().isoformat(),
        "articles": articles,
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


# ── WordPress REST API フェッチ ───────────────────────────────────────────────

def _fetch_wp_articles(per_page: int = 100, max_pages: int = 20) -> list[dict]:
    """
    WordPress REST APIから公開済み記事のタイトル・URLを全件取得する。

    Returns
    -------
    [{"title": str, "url": str, "id": int}, ...]
    """
    articles: list[dict] = []
    base = WP_URL.rstrip("/")
    api_base = f"{base}/wp-json/wp/v2/posts"

    headers: dict[str, str] = {"Accept": "application/json"}
    _auth = _wp_auth_header()
    _auth_value = _auth.split(": ", 1)[1] if ": " in _auth else _auth
    if _auth_value:
        headers["Authorization"] = _auth_value

    for page in range(1, max_pages + 1):
        url = f"{api_base}?per_page={per_page}&page={page}&_fields=id,title,link&status=publish"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    break
                body = json.loads(resp.read().decode("utf-8"))
                if not body:
                    break
                for post in body:
                    title_raw = post.get("title", {})
                    title = (
                        title_raw.get("rendered", "")
                        if isinstance(title_raw, dict)
                        else str(title_raw)
                    )
                    # HTMLエンティティを簡易デコード
                    title = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), title)
                    title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                    articles.append({
                        "id": post.get("id"),
                        "title": title,
                        "url": post.get("link", ""),
                    })
                # 総ページ数をチェック
                total_pages = int(resp.headers.get("X-WP-TotalPages", page))
                if page >= total_pages:
                    break
        except urllib.error.HTTPError as e:
            if e.code == 400:  # ページ超過
                break
            raise
        except Exception as e:
            print(f"[internal_links] WP API fetch error (page {page}): {e}")
            break

    return articles


def get_article_index(force_refresh: bool = False) -> list[dict]:
    """
    キャッシュまたはWordPress APIから記事インデックスを取得する。

    Parameters
    ----------
    force_refresh : Trueの場合キャッシュを無視してAPIから再取得

    Returns
    -------
    [{"title": str, "url": str, "id": int}, ...]
    """
    if not force_refresh:
        cached = _load_cache()
        if cached is not None:
            return cached

    articles = _fetch_wp_articles()
    if articles:
        _save_cache(articles)
    return articles


# ── キーワードマッチング ──────────────────────────────────────────────────────

def _extract_keywords_from_text(text: str) -> list[str]:
    """テキストからアーティスト名・ジャンルキーワードを抽出する。"""
    found: list[str] = []
    for name in ARTIST_NAMES:
        if re.search(re.escape(name), text, re.IGNORECASE):
            found.append(name)
    for kw in GENRE_KEYWORDS:
        if kw in text:
            found.append(kw)
    return found


def _title_matches_keywords(article_title: str, keywords: list[str]) -> bool:
    """記事タイトルがキーワードリストのいずれかにマッチするか確認する。"""
    if len(article_title) < MIN_TITLE_LEN:
        return False
    for kw in keywords:
        if re.search(re.escape(kw), article_title, re.IGNORECASE):
            return True
    return False


def _find_related_articles(
    html_body: str,
    post_title: str,
    article_index: list[dict],
    current_url: Optional[str] = None,
) -> list[dict]:
    """
    本文・タイトルのキーワードにマッチする関連記事を最大MAX_LINKS件返す。

    Parameters
    ----------
    html_body     : 新記事のHTML本文
    post_title    : 新記事タイトル
    article_index : 既存記事インデックス
    current_url   : 自記事URL（自己リンクを除外するため）

    Returns
    -------
    [{"title": str, "url": str}, ...]  最大MAX_LINKS件
    """
    # 本文とタイトルを合わせてキーワード抽出
    plain_text = re.sub(r"<[^>]+>", " ", html_body)
    search_text = f"{post_title} {plain_text}"
    keywords = _extract_keywords_from_text(search_text)

    if not keywords:
        return []

    seen_urls: set[str] = {current_url} if current_url else set()
    results: list[dict] = []

    for article in article_index:
        url = article.get("url", "")
        title = article.get("title", "")

        if url in seen_urls:
            continue
        if not url or not title:
            continue

        if _title_matches_keywords(title, keywords):
            seen_urls.add(url)
            results.append({"title": title, "url": url})
            if len(results) >= MAX_LINKS:
                break

    return results


# ── HTMLへのリンク挿入 ────────────────────────────────────────────────────────

def _insert_inline_links(html_body: str, related: list[dict]) -> str:
    """
    段落末の適切な位置（</p>の直前ではなく文末の文字の後）にインラインリンクを挿入する。
    各記事のアーティスト名・キーワードが本文中に出現する最初の段落末に挿入する。
    同一URLは1回のみ。
    """
    if not related:
        return html_body

    inserted_urls: set[str] = set()
    paragraphs = re.split(r"(<p[^>]*>.*?</p>)", html_body, flags=re.DOTALL | re.IGNORECASE)

    result_parts: list[str] = []
    remaining_links = list(related)

    for part in paragraphs:
        if not re.match(r"<p", part, re.IGNORECASE):
            result_parts.append(part)
            continue

        # この段落のプレーンテキスト
        plain = re.sub(r"<[^>]+>", "", part)
        matched_link = None

        for link in remaining_links:
            if link["url"] in inserted_urls:
                continue
            # リンク先記事のキーワードが段落に含まれるかチェック
            link_keywords = _extract_keywords_from_text(link["title"])
            if any(
                kw.lower() in plain.lower() or re.search(re.escape(kw), plain, re.IGNORECASE)
                for kw in link_keywords
                if kw
            ):
                matched_link = link
                break

        if matched_link and matched_link["url"] not in inserted_urls:
            inserted_urls.add(matched_link["url"])
            remaining_links = [l for l in remaining_links if l["url"] != matched_link["url"]]
            # </p>の直前にリンクを挿入（文末・段落末の文字の後）
            anchor = (
                f' <a href="{matched_link["url"]}" '
                f'rel="noopener">{matched_link["title"]}</a>'
            )
            # </p>タグの直前（文末とタグの間）に挿入
            part = re.sub(r"(</p>)", anchor + r"\1", part, count=1, flags=re.IGNORECASE)

        result_parts.append(part)

    return "".join(result_parts)


def _build_related_section(related: list[dict]) -> str:
    """「関連記事」HTMLセクションを生成する。"""
    if not related:
        return ""

    items = "\n".join(
        f'    <li><a href="{a["url"]}" rel="noopener">{a["title"]}</a></li>'
        for a in related
    )
    return (
        '\n<section class="related-articles" aria-label="関連記事">\n'
        "  <h2>関連記事</h2>\n"
        "  <ul>\n"
        f"{items}\n"
        "  </ul>\n"
        "</section>\n"
    )


# ── パブリックAPI ─────────────────────────────────────────────────────────────

def insert_internal_links(
    html_body: str,
    post_title: str = "",
    current_url: Optional[str] = None,
    force_refresh: bool = False,
) -> str:
    """
    新記事のHTML本文に内部リンクを挿入し、末尾に「関連記事」セクションを追加する。

    Parameters
    ----------
    html_body     : 新記事のHTML本文
    post_title    : 新記事のタイトル（キーワード抽出に使用）
    current_url   : 自記事のURL（自己リンク除外用、省略可）
    force_refresh : Trueにするとキャッシュを無視してAPIから再取得

    Returns
    -------
    内部リンク挿入済みのHTML文字列
    """
    if not html_body:
        return html_body

    try:
        article_index = get_article_index(force_refresh=force_refresh)
    except Exception as e:
        print(f"[internal_links] Failed to get article index: {e}")
        return html_body

    if not article_index:
        return html_body

    related = _find_related_articles(html_body, post_title, article_index, current_url)

    if not related:
        return html_body

    # インラインリンク挿入
    result = _insert_inline_links(html_body, related)

    # 末尾に「関連記事」セクション追加
    result = result + _build_related_section(related)

    return result


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 internal_links.py <html_file> [post_title]")
        print("  または: python3 internal_links.py --refresh-cache")
        sys.exit(1)

    if sys.argv[1] == "--refresh-cache":
        print("Refreshing article index cache...")
        arts = get_article_index(force_refresh=True)
        print(f"Fetched {len(arts)} articles → {CACHE_FILE}")
        sys.exit(0)

    html_path = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) >= 3 else ""

    with open(html_path, "r", encoding="utf-8") as f:
        body = f.read()

    result = insert_internal_links(body, post_title=title)
    print(result)
