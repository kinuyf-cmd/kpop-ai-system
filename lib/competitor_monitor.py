#!/usr/bin/env python3
"""
competitor_monitor.py — 競合サイト自動監視→対抗記事キュー v1.0

【責務】
  1. kstyle.com・daebak.tokyo の新着記事をRSSフィードで30分ごとに監視
  2. トレンド記事（高関連度のK-POPニュース）を自動検出
  3. 自サイトに未カバーのトピックを対抗記事キューに登録
  4. キューに溜まった対抗記事をパイプラインの次回実行で自動生成

【安全制約】
  - 1日最大5件の対抗記事キュー（スパム防止）
  - 同一トピックの重複キューイングを防止
  - 既に類似記事がある場合はスキップ
  - gossip/炎上系は自動キューイングしない（安全制約）

【監視対象】
  - kstyle.com    : K-POP/韓流最大手。RSS取得。
  - daebak.tokyo  : 日本語K-POPメディア。RSS取得。
  - 追加サイトは config/competitor_feeds.json で管理。

Usage:
  python3 lib/competitor_monitor.py              # 監視実行
  python3 lib/competitor_monitor.py --dry-run    # 判定のみ
  python3 lib/competitor_monitor.py --queue      # キュー一覧
  python3 lib/competitor_monitor.py --stats      # 統計表示
"""
import argparse
import hashlib
import json
import re
import sys
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

COMPETITOR_QUEUE = LOGS / "competitor_article_queue.jsonl"
COMPETITOR_LOG = LOGS / "competitor_monitor.jsonl"
COMPETITOR_FEEDS_PATH = CONFIG / "competitor_feeds.json"
KPI_POSTS_PATH = LOGS / "kpi_posts.jsonl"
SEEN_ARTICLES_PATH = LOGS / "competitor_seen.json"

MAX_QUEUE_PER_DAY = 5
USER_AGENT = "KpopJournalMonitor/1.0 (kpop-ai-system)"

# ── デフォルトフィード ──
DEFAULT_FEEDS = [
    {
        "name": "kstyle",
        "url": "https://www.kstyle.com/",
        "type": "html",
        "priority": "high",
    },
    {
        "name": "daebak",
        "url": "https://daebak.tokyo/feed/",
        "type": "rss",
        "priority": "medium",
    },
]

# ── 自動キュー対象外キーワード（安全制約） ──
SKIP_KEYWORDS = [
    "炎上", "訴訟", "逮捕", "薬物", "暴行", "セクハラ",
    "パワハラ", "詐欺", "裁判", "脱退", "解散",
    "死去", "事故", "入院",
]

# ── 高関連度キーワード ──
KPOP_KEYWORDS = [
    "BTS", "BLACKPINK", "aespa", "TWICE", "SEVENTEEN", "Stray Kids",
    "NewJeans", "IVE", "LE SSERAFIM", "(G)I-DLE", "ENHYPEN", "TXT",
    "NCT", "EXO", "Red Velvet", "ITZY", "NMIXX", "ATEEZ",
    "BIGBANG", "2NE1", "TREASURE", "ZEROBASEONE",
    "カムバック", "comeback", "新曲", "MV", "コンサート",
    "ツアー", "来日", "日本公演", "ワールドツアー",
    "チャート", "ビルボード", "オリコン",
]


def _load_json(p: Path):
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    records = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def _append_jsonl(p: Path, entry: dict):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _article_hash(title: str) -> str:
    """タイトルからハッシュを生成（重複検出用）。"""
    normalized = re.sub(r'\s+', '', title.lower())
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


# ═══════════════════════════════════════════════════════════════
# RSS フィード取得
# ═══════════════════════════════════════════════════════════════

def fetch_rss(url: str, name: str) -> list[dict]:
    """RSSフィードを取得してパースする。"""
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", USER_AGENT)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [monitor] {name} 取得失敗: {e}", file=sys.stderr)
        return []

    articles = []
    try:
        root = ET.fromstring(data)
        # RSS 2.0
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            desc = (item.findtext("description") or "").strip()

            if title and link:
                articles.append({
                    "title": title,
                    "url": link,
                    "pub_date": pub_date,
                    "description": desc[:200],
                    "source": name,
                })

        # Atom形式のフォールバック
        if not articles:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall(".//atom:entry", ns):
                title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                if title and link:
                    articles.append({
                        "title": title,
                        "url": link,
                        "source": name,
                    })
    except ET.ParseError as e:
        print(f"  [monitor] {name} XMLパース失敗: {e}", file=sys.stderr)

    return articles


def fetch_html_articles(url: str, name: str) -> list[dict]:
    """HTMLページから記事リンクをスクレイピングする（RSS非公開サイト向け）。"""
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0 (compatible; KpopJournalBot/1.0)")
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [monitor] {name} HTML取得失敗: {e}", file=sys.stderr)
        return []

    articles = []
    # <a href="...">タイトル</a> パターンで記事リンクを抽出
    # kstyle: /article/NNNN/ 形式
    # 汎用: 記事っぽいリンクを抽出
    link_patterns = [
        re.compile(r'<a[^>]+href="(https?://[^"]*(?:/article[./]|/news/|/post/)[^"]*)"[^>]*>([^<]{10,})</a>', re.I),
        re.compile(r'<a[^>]+href="(/(?:article[./]|news/|post/)[^"]*)"[^>]*>([^<]{10,})</a>', re.I),
        # kstyle: /article.ksn?articleNo=NNNN
        re.compile(r'<a[^>]+href="(/article\.ksn\?articleNo=\d+)"[^>]*>([^<]{10,})</a>', re.I),
    ]

    base_url = re.match(r'(https?://[^/]+)', url)
    base_domain = base_url.group(1) if base_url else ""

    seen_urls = set()
    for pattern in link_patterns:
        for m in pattern.finditer(html):
            link = m.group(1)
            title = m.group(2).strip()
            if not title or len(title) < 5:
                continue
            # 相対URL→絶対URL
            if link.startswith("/"):
                link = base_domain + link
            if link in seen_urls:
                continue
            seen_urls.add(link)
            articles.append({
                "title": title,
                "url": link,
                "source": name,
            })

    # タイトルが重複するものを除去
    unique = {}
    for a in articles:
        key = a["title"][:30]
        if key not in unique:
            unique[key] = a
    return list(unique.values())[:30]


# ═══════════════════════════════════════════════════════════════
# 記事フィルタリング
# ═══════════════════════════════════════════════════════════════

def load_seen_articles() -> set:
    """既に確認済みの記事ハッシュを読み込む。"""
    data = _load_json(SEEN_ARTICLES_PATH)
    return set(data.get("seen", []))


def save_seen_articles(seen: set):
    """確認済み記事ハッシュを保存する。最大2000件保持。"""
    seen_list = list(seen)[-2000:]
    SEEN_ARTICLES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_ARTICLES_PATH.write_text(
        json.dumps({"seen": seen_list, "updated_at": NOW.isoformat()}, ensure_ascii=False),
        encoding="utf-8",
    )


def is_kpop_relevant(title: str, description: str = "") -> float:
    """K-POP関連度スコアを返す（0-1）。"""
    text = (title + " " + description).upper()
    hits = sum(1 for kw in KPOP_KEYWORDS if kw.upper() in text)
    return min(hits / 3.0, 1.0)  # 3キーワードヒットで1.0


def should_skip(title: str) -> bool:
    """安全制約に基づいてスキップすべきかチェック。"""
    for kw in SKIP_KEYWORDS:
        if kw in title:
            return True
    return False


def has_similar_article(title: str) -> bool:
    """自サイトに類似記事があるかチェック。"""
    posts = _load_jsonl(KPI_POSTS_PATH)
    # 直近14日の記事とタイトル類似度を比較
    cutoff = (date.today() - timedelta(days=14)).isoformat()
    for post in posts:
        if post.get("date", "") < cutoff:
            continue
        post_title = post.get("title", "")
        if not post_title:
            continue
        # 簡易類似度: 共通文字数 / 最大文字数
        common = len(set(title) & set(post_title))
        max_len = max(len(set(title)), len(set(post_title)), 1)
        if common / max_len > 0.6:
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# キュー管理
# ═══════════════════════════════════════════════════════════════

def today_queue_count() -> int:
    today = date.today().isoformat()
    return sum(1 for r in _load_jsonl(COMPETITOR_QUEUE)
               if r.get("queued_at", "").startswith(today))


def queue_article(article: dict, relevance: float, dry_run: bool = False) -> bool:
    """対抗記事をキューに追加する。"""
    if today_queue_count() >= MAX_QUEUE_PER_DAY:
        return False

    entry = {
        "queued_at": NOW.isoformat(),
        "source": article["source"],
        "competitor_title": article["title"],
        "competitor_url": article.get("url", ""),
        "relevance_score": round(relevance, 2),
        "status": "pending",
        "article_hash": _article_hash(article["title"]),
        "suggested_angle": f"競合「{article['source']}」が報じた「{article['title'][:40]}」に対し、"
                           f"独自視点・ファン目線の深掘り記事を作成。",
    }

    if dry_run:
        print(f"  [DRY-RUN] キュー追加: {article['title'][:50]}")
        return True

    _append_jsonl(COMPETITOR_QUEUE, entry)
    return True


# ═══════════════════════════════════════════════════════════════
# メイン監視ループ
# ═══════════════════════════════════════════════════════════════

def run_monitor(dry_run: bool = False) -> dict:
    """競合サイトを監視し、対抗記事をキューに追加する。"""
    print(f"[competitor_monitor] {NOW.isoformat()} 開始", file=sys.stderr)

    # フィード設定を読み込む
    custom_feeds = _load_json(COMPETITOR_FEEDS_PATH)
    feeds = custom_feeds.get("feeds", DEFAULT_FEEDS) if custom_feeds else DEFAULT_FEEDS

    seen = load_seen_articles()
    results = {
        "feeds_checked": 0,
        "articles_found": 0,
        "new_articles": 0,
        "queued": 0,
        "skipped_safety": 0,
        "skipped_similar": 0,
        "skipped_low_relevance": 0,
    }

    all_new = []

    for feed in feeds:
        name = feed["name"]
        url = feed["url"]
        results["feeds_checked"] += 1

        feed_type = feed.get("type", "rss")
        if feed_type == "html":
            articles = fetch_html_articles(url, name)
        else:
            articles = fetch_rss(url, name)
        results["articles_found"] += len(articles)
        print(f"  {name}: {len(articles)}記事取得", file=sys.stderr)

        for article in articles:
            ahash = _article_hash(article["title"])
            if ahash in seen:
                continue

            seen.add(ahash)
            results["new_articles"] += 1

            # 安全制約チェック
            if should_skip(article["title"]):
                results["skipped_safety"] += 1
                continue

            # 関連度チェック
            relevance = is_kpop_relevant(article["title"], article.get("description", ""))
            if relevance < 0.3:
                results["skipped_low_relevance"] += 1
                continue

            # 類似記事チェック
            if has_similar_article(article["title"]):
                results["skipped_similar"] += 1
                continue

            all_new.append((article, relevance))

    # 関連度順でソートしてキューに追加
    all_new.sort(key=lambda x: -x[1])
    for article, relevance in all_new:
        if queue_article(article, relevance, dry_run):
            results["queued"] += 1
            print(f"  📰 キュー追加: [{article['source']}] {article['title'][:50]} "
                  f"(関連度={relevance:.1f})", file=sys.stderr)

    # seen を保存
    if not dry_run:
        save_seen_articles(seen)

    # ログ記録
    _append_jsonl(COMPETITOR_LOG, {
        "timestamp": NOW.isoformat(),
        **results,
    })

    print(f"[competitor_monitor] 完了: new={results['new_articles']} "
          f"queued={results['queued']}", file=sys.stderr)

    return results


def get_pending_queue() -> list[dict]:
    """pending状態の対抗記事キューを返す。"""
    return [r for r in _load_jsonl(COMPETITOR_QUEUE) if r.get("status") == "pending"]


def print_queue():
    pending = get_pending_queue()
    if not pending:
        print("対抗記事キューは空です。")
        return

    print(f"\n=== 対抗記事キュー ({len(pending)}件) ===\n")
    for i, item in enumerate(pending, 1):
        print(f"  {i}. [{item['source']}] {item['competitor_title'][:60]}")
        print(f"     関連度: {item['relevance_score']}  キュー日時: {item['queued_at'][:16]}")
        print(f"     提案: {item['suggested_angle'][:80]}")
        print()


def print_stats():
    records = _load_jsonl(COMPETITOR_LOG)
    if not records:
        print("競合監視ログなし")
        return

    total_found = sum(r.get("articles_found", 0) for r in records)
    total_queued = sum(r.get("queued", 0) for r in records)

    print(f"\n=== 競合監視統計 ===")
    print(f"  実行回数: {len(records)}")
    print(f"  記事検出累計: {total_found}")
    print(f"  キュー追加累計: {total_queued}")
    if records:
        latest = records[-1]
        print(f"  最終実行: {latest.get('timestamp', '-')}")
        print(f"  最新: found={latest.get('articles_found', 0)} "
              f"new={latest.get('new_articles', 0)} "
              f"queued={latest.get('queued', 0)}")


def main():
    parser = argparse.ArgumentParser(description="競合サイト自動監視 v1.0")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--queue", action="store_true", help="キュー一覧")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    if args.queue:
        print_queue()
    elif args.stats:
        print_stats()
    else:
        result = run_monitor(dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
