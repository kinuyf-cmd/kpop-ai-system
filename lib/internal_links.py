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
    """WP REST 認証ヘッダを返す。
    2026-05-23: 認証順序を「env 優先 → ~/.wp_auth フォールバック」に変更。
    旧実装は ~/.wp_auth(curl config形式)を先に読んでいたが、移植後の本番では
    このファイルが旧サーバの stale 認証(4/10)で 401 を返し、内部リンク enrich が
    全失敗していた。env(WP_USER/WP_PASS)は publisher bot の有効な app password で
    REST 通過実績があるため env を優先する(unified_publisher 1eac288 と同方針)。
    戻り値: 'Authorization: Basic xxxx'。
    """
    import re as _re
    import base64
    try:
        from dotenv import load_dotenv
        load_dotenv("/home/aiuser/kpop-ai-system/.env")
    except Exception:
        pass
    # 1) env を優先(有効な app password)
    user = os.environ.get("WP_USER", "")
    passwd = os.environ.get("WP_APP_PASS") or os.environ.get("WP_PASS", "")
    if user and passwd:
        token = base64.b64encode(f"{user}:{passwd}".encode()).decode()
        return f"Authorization: Basic {token}"
    # 2) フォールバック: ~/.wp_auth(env 未設定時のみ)
    wp_auth_path = os.path.expanduser("~/.wp_auth")
    if os.path.exists(wp_auth_path):
        with open(wp_auth_path) as f:
            for line in f:
                m = _re.match(r'header\s*=\s*"(Authorization:\s*Basic\s+[^"\\n]+)"?', line.strip())
                if m:
                    return m.group(1)
    return "Authorization: Basic "

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
    # 2026-05-12: 22075 NMIXX / 21989 CORTIS / 22123 fromis_9 で artist 一致
    # スコアが付かず Gummy/MOMOLAND 等の無関係 GENRE_KEYWORDS マッチ記事へ
    # リンクが流れていた事故への対応。最近活動の主要グループを追加。
    "NMIXX", "CORTIS", "fromis_9", "ITZY", "(G)I-DLE", "G)I-DLE", "GIDLE",
    "Kep1er", "ZEROBASEONE", "TWS", "BOYNEXTDOOR", "EVNNE",
    "NCT WISH", "NCT DREAM", "NCT 127", "WayV",
    "TAEYONG", "TAEYEON", "JISOO", "JENNIE", "ROSE", "LISA",
    "STAYC", "VIVIZ", "Billlie", "tripleS", "QWER",
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


def _tokenize_title(title: str) -> set[str]:
    """タイトルからスコアリング用トークンを抽出する。"""
    return set(re.findall(
        r"[a-zA-Z]{2,}|[ぁ-んァ-ヶー]{2,}|[一-龥]{2,}", title.lower()
    ))


def _score_relevance(
    new_title_tokens: set[str],
    new_keywords: list[str],
    candidate_title: str,
) -> float:
    """
    新記事と候補記事のSEO関連性スコアを計算（0-100）。

    スコア構成:
      - タイトルキーワード共起: 最大40点 (8pt × トークン重複数, cap=5)
      - アーティスト/ジャンルキーワード一致: 最大40点 (13pt × 一致数, cap=3)
      - タイトル長バランス: 最大20点 (短すぎ/長すぎにペナルティ)
    """
    score = 0.0

    # 1. タイトルキーワード共起（重み: 40）
    cand_tokens = _tokenize_title(candidate_title)
    token_overlap = len(new_title_tokens & cand_tokens)
    score += min(token_overlap * 8, 40)

    # 2. アーティスト/ジャンルキーワード一致（重み: 40）
    kw_matches = sum(
        1 for kw in new_keywords
        if re.search(re.escape(kw), candidate_title, re.IGNORECASE)
    )
    score += min(kw_matches * 13, 40)

    # 3. タイトル長バランス（重み: 20）— 適度な長さの記事を優先
    title_len = len(candidate_title)
    if 15 <= title_len <= 60:
        score += 20
    elif 10 <= title_len < 15 or 60 < title_len <= 80:
        score += 10

    return score


def _find_related_articles(
    html_body: str,
    post_title: str,
    article_index: list[dict],
    current_url: Optional[str] = None,
) -> list[dict]:
    """
    本文・タイトルのキーワードにマッチする関連記事を、関連度スコア順に最大MAX_LINKS件返す。

    Parameters
    ----------
    html_body     : 新記事のHTML本文
    post_title    : 新記事タイトル
    article_index : 既存記事インデックス
    current_url   : 自記事URL（自己リンクを除外するため）

    Returns
    -------
    [{"title": str, "url": str, "score": float}, ...]  最大MAX_LINKS件（スコア降順）
    """
    # 本文とタイトルを合わせてキーワード抽出
    plain_text = re.sub(r"<[^>]+>", " ", html_body)
    search_text = f"{post_title} {plain_text}"
    keywords = _extract_keywords_from_text(search_text)

    if not keywords:
        return []

    seen_urls: set[str] = {current_url} if current_url else set()
    new_title_tokens = _tokenize_title(post_title)

    # 全候補をスコアリング
    scored: list[tuple[float, dict]] = []
    for article in article_index:
        url = article.get("url", "")
        title = article.get("title", "")

        if url in seen_urls:
            continue
        if not url or not title or len(title) < MIN_TITLE_LEN:
            continue

        score = _score_relevance(new_title_tokens, keywords, title)
        if score > 15:  # 最低関連度閾値
            scored.append((score, {"title": title, "url": url, "score": score}))

    # スコア降順でソートし上位MAX_LINKS件を返す
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:MAX_LINKS]]


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
