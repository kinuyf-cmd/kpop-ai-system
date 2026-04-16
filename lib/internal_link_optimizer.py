#!/usr/bin/env python3
"""internal_link_optimizer.py — 既存記事に関連記事3本＋カテゴリ導線を挿入

スキャン対象: WP REST API で全公開記事を取得
判定: 本文末尾に「関連記事」セクションが存在しなければ挿入
類似判定: タグ一致 + カテゴリ一致 + タイトルキーワード一致

使い方:
  python3 lib/internal_link_optimizer.py [--limit 100] [--dry-run]
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
LOGS.mkdir(exist_ok=True)
OUT_LOG = LOGS / "internal_link_updates.jsonl"
WP = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")
JST = timezone(timedelta(hours=9))

RELATED_SECTION_MARKER = "related-internal-links"


def curl_get(path: str) -> dict | list:
    cmd = ["curl", "-s", f"{WP}{path}", "-K", WP_AUTH]
    out = subprocess.check_output(cmd, timeout=30).decode()
    return json.loads(out)


def curl_post(path: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode()
    cmd = ["curl", "-s", "-X", "POST", f"{WP}{path}",
           "-K", WP_AUTH, "-H", "Content-Type: application/json",
           "--data-binary", body.decode()]
    out = subprocess.check_output(cmd, timeout=60).decode()
    return json.loads(out)


def fetch_all_posts(limit: int) -> list[dict]:
    posts = []
    page = 1
    while len(posts) < limit:
        batch = curl_get(
            f"/wp-json/wp/v2/posts?per_page=50&page={page}&orderby=date&order=desc"
            "&_fields=id,title,slug,link,categories,tags,content,date"
        )
        if not batch or isinstance(batch, dict):
            break
        posts.extend(batch)
        if len(batch) < 50:
            break
        page += 1
    return posts[:limit]


def has_related_section(content: str) -> bool:
    if RELATED_SECTION_MARKER in content:
        return True
    if "関連記事" in content and re.search(r"<(h[23]|strong)[^>]*>\s*関連記事", content):
        return True
    return False


def pick_related(target: dict, pool: list[dict], n: int = 4) -> list[dict]:
    t_cats = set(target.get("categories", []) or [])
    t_tags = set(target.get("tags", []) or [])
    t_title = target["title"]["rendered"].lower() if isinstance(target["title"], dict) else target["title"].lower()
    t_tokens = set(re.findall(r"[a-z0-9]+|[ぁ-んァ-ヶ一-龥]+", t_title))

    scored = []
    for p in pool:
        if p["id"] == target["id"]:
            continue
        p_cats = set(p.get("categories", []) or [])
        p_tags = set(p.get("tags", []) or [])
        p_title = p["title"]["rendered"].lower() if isinstance(p["title"], dict) else p["title"].lower()
        p_tokens = set(re.findall(r"[a-z0-9]+|[ぁ-んァ-ヶ一-龥]+", p_title))
        score = 0
        score += len(t_tags & p_tags) * 30
        score += len(t_cats & p_cats) * 20
        score += min(len(t_tokens & p_tokens), 5) * 8
        if score <= 0:
            continue
        scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], -int(p_cats and max(p_cats) or 0)))
    return [p for _, p in scored[:n]]


def build_related_block(related: list[dict], target_cats: list[int], cat_names: dict[int, str]) -> str:
    items = []
    for r in related:
        url = r["link"]
        title = r["title"]["rendered"] if isinstance(r["title"], dict) else r["title"]
        title = re.sub(r"<[^>]+>", "", title)
        items.append(f'<li><a href="{url}">{title}</a></li>')
    lis = "\n".join(items)
    # カテゴリ導線
    cat_links = []
    for cid in target_cats[:3]:
        name = cat_names.get(cid)
        if name:
            cat_links.append(f'<a href="{WP}/?cat={cid}">{name}</a>')
    cat_nav = " / ".join(cat_links) if cat_links else ""
    cat_html = f'<p class="related-cat-nav"><strong>カテゴリ:</strong> {cat_nav}</p>' if cat_nav else ""
    return f"""
<div class="{RELATED_SECTION_MARKER}" style="margin:32px 0;padding:18px 20px;border-left:4px solid #ff4d6d;background:#fff5f7;border-radius:0 8px 8px 0;">
<h3 style="margin:0 0 10px 0;font-size:1.05em;color:#ff4d6d;">📚 関連記事</h3>
<ul style="margin:0;padding-left:20px;">
{lis}
</ul>
{cat_html}
</div>
"""


def fetch_categories() -> dict[int, str]:
    try:
        cats = curl_get("/wp-json/wp/v2/categories?per_page=100&_fields=id,name")
        return {c["id"]: c["name"] for c in cats}
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"[internal_link_optimizer] 最大{args.limit}記事をスキャン")
    posts = fetch_all_posts(args.limit)
    print(f"[internal_link_optimizer] {len(posts)}記事取得")
    cat_names = fetch_categories()

    ts = datetime.now(tz=JST).isoformat()
    updated = 0
    skipped_has = 0
    failed = 0
    no_related = 0

    with OUT_LOG.open("a") as fp:
        for p in posts:
            try:
                content = p.get("content", {}).get("rendered", "") if isinstance(p.get("content"), dict) else p.get("content", "")
                if has_related_section(content):
                    skipped_has += 1
                    continue
                related = pick_related(p, posts, n=4)
                if len(related) < 3:
                    no_related += 1
                    continue
                block = build_related_block(related, p.get("categories", []), cat_names)
                new_content = content.rstrip() + "\n" + block
                if args.dry_run:
                    updated += 1
                    continue
                curl_post(f"/wp-json/wp/v2/posts/{p['id']}", {"content": new_content})
                updated += 1
                fp.write(json.dumps({
                    "ts": ts, "post_id": p["id"], "slug": p["slug"],
                    "related_ids": [r["id"] for r in related],
                    "action": "inserted",
                }, ensure_ascii=False) + "\n")
                print(f"  ✅ [{p['id']}] +{len(related)}関連 inserted")
            except Exception as e:
                failed += 1
                print(f"  ❌ [{p['id']}] {e}")

    print()
    print(f"[internal_link_optimizer] 完了: 挿入={updated} / 既存={skipped_has} / 関連不足={no_related} / 失敗={failed}")
    print(f"  ログ: {OUT_LOG}")


if __name__ == "__main__":
    main()
