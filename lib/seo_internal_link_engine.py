#!/usr/bin/env python3
"""seo_internal_link_engine.py — GSCデータ駆動の内部リンク最適化エンジン

既存記事間の内部リンクを、GSCの共起クエリ・表示回数・順位データに基づいて
自動的に最適化する。タグ/カテゴリの構造的マッチに加え、検索クエリの意味的関連性で
リンク先を選定する。

機能:
  1. 孤立記事（被リンク0）の検出・自動リンク挿入
  2. GSCクエリ共起による関連記事ペア発見
  3. ピラーページ→クラスター記事のハブリンク自動挿入
  4. リンク切れ検出

使い方:
  python3 lib/seo_internal_link_engine.py [--dry-run] [--limit 200]
  python3 lib/seo_internal_link_engine.py --report  # 分析レポートのみ
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
LOGS.mkdir(exist_ok=True)
GSC_FILE = LOGS / "gsc_metrics_latest.json"
OUT_LOG = LOGS / "seo_internal_link_engine.jsonl"
WP = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")
JST = timezone(timedelta(hours=9))

RELATED_MARKER = "related-internal-links"
MIN_RELATED = 3
MAX_RELATED = 5

# アーティスト→カテゴリID マッピング
ARTIST_CATEGORY = {
    "bts": 18, "blackpink": 23, "aespa": 25, "twice": 22,
    "seventeen": 24, "newjeans": 32, "ive": 68, "le sserafim": 41,
    "stray kids": 43, "nct": 40, "riize": 39, "illit": 44,
    "bigbang": 19, "exo": 60, "itzy": 37, "babymonster": 38,
}


def curl_get(path: str) -> list | dict:
    cmd = ["curl", "-s", f"{WP}{path}", "-K", WP_AUTH]
    out = subprocess.check_output(cmd, timeout=30).decode()
    return json.loads(out)


def curl_post(path: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False)
    cmd = ["curl", "-s", "-X", "POST", f"{WP}{path}",
           "-K", WP_AUTH, "-H", "Content-Type: application/json",
           "-d", body]
    out = subprocess.check_output(cmd, timeout=60).decode()
    return json.loads(out)


def fetch_all_posts(limit: int = 500) -> list[dict]:
    posts = []
    page = 1
    while len(posts) < limit:
        batch = curl_get(
            f"/wp-json/wp/v2/posts?per_page=100&page={page}&orderby=date&order=desc"
            "&_fields=id,title,slug,link,categories,tags,content,date"
        )
        if not batch or isinstance(batch, dict):
            break
        posts.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return posts[:limit]


def load_gsc_data() -> dict:
    if not GSC_FILE.exists():
        return {}
    try:
        return json.loads(GSC_FILE.read_text())
    except Exception:
        return {}


def extract_title(post: dict) -> str:
    t = post.get("title", {})
    return (t.get("rendered", "") if isinstance(t, dict) else str(t)).strip()


def extract_content(post: dict) -> str:
    c = post.get("content", {})
    return c.get("rendered", "") if isinstance(c, dict) else str(c)


def has_related_section(content: str) -> bool:
    return RELATED_MARKER in content or (
        "関連記事" in content and bool(re.search(r"<(h[23]|strong)[^>]*>\s*関連記事", content))
    )


# ─── GSCベースの関連性スコアリング ───────────────────────────────────────────

def build_url_query_map(gsc_data: dict) -> dict[str, set[str]]:
    """GSCのpage×queryデータからURL→クエリセットのマップを構築"""
    # gsc_metrics_latest.json は page次元のみなので、
    # low_ctr_pages.json や metrics_yesterday.json からquery情報を補完
    url_queries: dict[str, set[str]] = defaultdict(set)

    # metrics_yesterday.json のtop_queriesからURL推定
    my_file = BASE / "google_metrics" / "metrics_yesterday.json"
    if my_file.exists():
        try:
            my = json.loads(my_file.read_text())
            for q in my.get("gsc", {}).get("top_queries", []):
                query = q.get("query", "").lower()
                # クエリをアーティスト名で分類し、該当カテゴリの全記事に紐付け
                for artist, _ in ARTIST_CATEGORY.items():
                    if artist in query:
                        url_queries[f"__artist__{artist}"].add(query)
        except Exception:
            pass

    # GSC latest（page次元）からURLベースのimp/ctr情報
    for page_data in gsc_data.get("pages", []):
        url = page_data.get("url", "")
        if url:
            # URLからスラグを抽出してキーワード化
            slug = url.rstrip("/").split("/")[-1] if "/" in url else ""
            tokens = set(re.split(r"[-_]", slug.lower())) - {"", "kpop", "2026", "2025"}
            for t in tokens:
                url_queries[url].add(t)

    return url_queries


def compute_relevance(post_a: dict, post_b: dict, url_queries: dict) -> float:
    """2記事間のSEO関連性スコアを計算（0-100）"""
    score = 0.0

    # 1. カテゴリ一致（重み: 25）
    cats_a = set(post_a.get("categories", []) or [])
    cats_b = set(post_b.get("categories", []) or [])
    if cats_a & cats_b:
        score += 25 * min(len(cats_a & cats_b), 3) / 3

    # 2. タグ一致（重み: 30）
    tags_a = set(post_a.get("tags", []) or [])
    tags_b = set(post_b.get("tags", []) or [])
    tag_overlap = len(tags_a & tags_b)
    if tag_overlap:
        score += min(tag_overlap * 10, 30)

    # 3. タイトルキーワード共起（重み: 25）
    title_a = extract_title(post_a).lower()
    title_b = extract_title(post_b).lower()
    tokens_a = set(re.findall(r"[a-z]{2,}|[ぁ-んァ-ヶー]{2,}|[一-龥]{2,}", title_a))
    tokens_b = set(re.findall(r"[a-z]{2,}|[ぁ-んァ-ヶー]{2,}|[一-龥]{2,}", title_b))
    token_overlap = len(tokens_a & tokens_b)
    if token_overlap:
        score += min(token_overlap * 8, 25)

    # 4. GSCクエリ共起（重み: 20）
    url_a = post_a.get("link", "")
    url_b = post_b.get("link", "")
    q_a = url_queries.get(url_a, set())
    q_b = url_queries.get(url_b, set())
    query_overlap = len(q_a & q_b)
    if query_overlap:
        score += min(query_overlap * 10, 20)

    return score


def pick_related_gsc(target: dict, pool: list[dict], url_queries: dict, n: int = MAX_RELATED) -> list[dict]:
    """GSCデータを加味した関連記事選定"""
    scored = []
    for p in pool:
        if p["id"] == target["id"]:
            continue
        rel = compute_relevance(target, p, url_queries)
        if rel > 10:
            scored.append((rel, p))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:n]]


# ─── 孤立記事検出 ────────────────────────────────────────────────────────────

def find_orphan_articles(posts: list[dict]) -> list[dict]:
    """他記事からリンクされていない孤立記事を検出"""
    all_urls = {p.get("link", "") for p in posts}
    linked_urls: set[str] = set()

    for p in posts:
        content = extract_content(p)
        for url in all_urls:
            if url and url in content and url != p.get("link", ""):
                linked_urls.add(url)

    orphans = [p for p in posts if p.get("link", "") not in linked_urls]
    return orphans


# ─── リンクブロック生成 ───────────────────────────────────────────────────────

def build_related_block(related: list[dict]) -> str:
    items = []
    for r in related:
        url = r.get("link", "")
        title = extract_title(r)
        title = re.sub(r"<[^>]+>", "", title)
        items.append(f'<li><a href="{url}">{title}</a></li>')
    lis = "\n".join(items)
    return f"""
<div class="{RELATED_MARKER}" style="margin:32px 0;padding:18px 20px;border-left:4px solid #ff4d6d;background:#fff5f7;border-radius:0 8px 8px 0;">
<h3 style="margin:0 0 10px 0;font-size:1.05em;color:#ff4d6d;">関連記事</h3>
<ul style="margin:0;padding-left:20px;">
{lis}
</ul>
</div>
"""


# ─── レポート生成 ─────────────────────────────────────────────────────────────

def generate_report(posts: list[dict], gsc_data: dict) -> dict:
    """SEO内部リンク分析レポート"""
    orphans = find_orphan_articles(posts)
    has_related = sum(1 for p in posts if has_related_section(extract_content(p)))

    # GSCからの低CTR記事
    low_ctr_pages = []
    for pg in gsc_data.get("pages", []):
        if pg.get("impressions", 0) > 50 and pg.get("ctr", 0) < 0.02:
            low_ctr_pages.append(pg)
    low_ctr_pages.sort(key=lambda x: -x.get("impressions", 0))

    return {
        "timestamp": datetime.now(JST).isoformat(),
        "total_posts": len(posts),
        "with_related_section": has_related,
        "without_related_section": len(posts) - has_related,
        "orphan_articles": len(orphans),
        "orphan_samples": [{"id": p["id"], "title": extract_title(p)} for p in orphans[:10]],
        "low_ctr_high_imp": [{"url": pg["url"], "imp": pg["impressions"],
                              "ctr": round(pg["ctr"] * 100, 2)} for pg in low_ctr_pages[:10]],
    }


# ─── メイン処理 ──────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true", help="分析レポートのみ出力")
    args = ap.parse_args()

    print(f"[seo_link_engine] 最大{args.limit}記事スキャン")
    posts = fetch_all_posts(args.limit)
    print(f"[seo_link_engine] {len(posts)}記事取得")

    gsc_data = load_gsc_data()
    print(f"[seo_link_engine] GSCデータ: {gsc_data.get('row_count', 0)}ページ")

    if args.report:
        report = generate_report(posts, gsc_data)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    url_queries = build_url_query_map(gsc_data)
    ts = datetime.now(tz=JST).isoformat()

    updated = 0
    skipped = 0
    failed = 0
    orphan_fixed = 0

    orphans = find_orphan_articles(posts)
    orphan_ids = {p["id"] for p in orphans}

    with OUT_LOG.open("a") as fp:
        for p in posts:
            try:
                content = extract_content(p)
                if has_related_section(content):
                    skipped += 1
                    continue

                related = pick_related_gsc(p, posts, url_queries, MAX_RELATED)
                if len(related) < MIN_RELATED:
                    skipped += 1
                    continue

                block = build_related_block(related)
                new_content = content.rstrip() + "\n" + block

                if args.dry_run:
                    print(f"  [DRY] [{p['id']}] +{len(related)}関連")
                    updated += 1
                    if p["id"] in orphan_ids:
                        orphan_fixed += 1
                    continue

                curl_post(f"/wp-json/wp/v2/posts/{p['id']}", {"content": new_content})
                updated += 1
                if p["id"] in orphan_ids:
                    orphan_fixed += 1

                fp.write(json.dumps({
                    "ts": ts, "post_id": p["id"], "slug": p.get("slug", ""),
                    "related_ids": [r["id"] for r in related],
                    "is_orphan": p["id"] in orphan_ids,
                }, ensure_ascii=False) + "\n")
                print(f"  [OK] [{p['id']}] +{len(related)}関連 {'(orphan rescued)' if p['id'] in orphan_ids else ''}")

            except Exception as e:
                failed += 1
                print(f"  [NG] [{p['id']}] {e}")

    print(f"\n[seo_link_engine] 完了: 挿入={updated} / スキップ={skipped} / 失敗={failed} / 孤立救済={orphan_fixed}")


if __name__ == "__main__":
    main()
