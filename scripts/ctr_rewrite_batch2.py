#!/usr/bin/env python3
"""CTR改善タイトルリライト - バッチ2 (index 10-29)"""
import json
import os
import sys
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv("/home/aiuser/kpop-ai-system/.env")

WP_USER = os.environ["WP_USER"]
WP_PASS = os.environ["WP_PASS"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
SITE_URL = "https://www.kpopjournal.tokyo"

SKIP_SLUGS = {"about-editor", "www.kpopjournal.tokyo", "advertise", "about"}

with open("/home/aiuser/kpop-ai-system/data/low_ctr_targets.json") as f:
    targets = json.load(f)

# Load existing rewrites
rewrites_path = "/home/aiuser/kpop-ai-system/data/ctr_rewrites.json"
with open(rewrites_path) as f:
    rewrites = json.load(f)

log_path = "/home/aiuser/kpop-ai-system/logs/ctr_rewrite_batch2.log"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(log_path, "a") as f:
        f.write(line + "\n")

def get_post_by_slug(slug):
    """WP REST APIでslugから記事を取得"""
    url = f"{SITE_URL}/wp-json/wp/v2/posts"
    resp = requests.get(url, params={"slug": slug}, auth=(WP_USER, WP_PASS), timeout=30)
    if resp.status_code == 200:
        posts = resp.json()
        if posts:
            return posts[0]
    return None

def get_post_by_url(page_url):
    """URLからslugを抽出して記事を取得。URL-encoded slugにも対応"""
    # URLからslugを抽出
    slug = page_url.rstrip("/").split("/")[-1]
    # URL-encodedの場合もそのまま試す
    post = get_post_by_slug(slug)
    if post:
        return post
    # デコードして試す
    from urllib.parse import unquote
    decoded = unquote(slug)
    if decoded != slug:
        post = get_post_by_slug(decoded)
        if post:
            return post
    return None

def generate_new_title(old_title, slug, ctr, impressions):
    """GPT-4o-miniで1件ずつタイトル生成"""
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    prompt = f"""あなたはK-POPメディアのSEOタイトル改善の専門家です。
以下の記事タイトルのCTRが低いため、改善してください。

現在のタイトル: {old_title}
記事slug: {slug}
現在のCTR: {ctr}%
表示回数: {impressions}

ルール:
- 40文字以内（日本語で）
- 「完全」「徹底」「衝撃」は使わない
- 疑問形や数字を使って注目を集める
- 記事の内容がわかるタイトルにする
- K-POPファンが思わずクリックしたくなるタイトル
- 元のタイトルの主題（アーティスト名・テーマ）は保持する

改善後のタイトルのみを1行で出力してください。余計な説明は不要です。"""

    data = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 100
    }

    resp = requests.post("https://api.openai.com/v1/chat/completions",
                         headers=headers, json=data, timeout=30)
    if resp.status_code != 200:
        log(f"  GPT API error: {resp.status_code} {resp.text[:200]}")
        return None

    result = resp.json()
    new_title = result["choices"][0]["message"]["content"].strip()
    # 余計な引用符を除去
    new_title = new_title.strip('"').strip("「").strip("」").strip("'")
    return new_title

def update_wp_title(post_id, new_title):
    """WPのタイトルを更新"""
    url = f"{SITE_URL}/wp-json/wp/v2/posts/{post_id}"
    resp = requests.post(url, auth=(WP_USER, WP_PASS),
                         headers={"Content-Type": "application/json"},
                         json={"title": new_title}, timeout=30)
    return resp.status_code == 200, resp.status_code

def main():
    # Index 10-29 を処理
    batch = targets[10:30]
    processed = 0
    skipped = 0
    errors = 0

    log("=== CTR Rewrite Batch 2 開始 ===")

    for i, entry in enumerate(batch):
        slug = entry.get("slug", "")
        url = entry.get("url", "")

        # スキップ判定
        if slug in SKIP_SLUGS or slug.startswith("#rtoc"):
            log(f"[{i+11}] SKIP: {slug}")
            skipped += 1
            continue

        log(f"[{i+11}] Processing: {slug} (CTR={entry['ctr']}%, imp={entry['impressions']})")

        # WPから記事取得
        post = get_post_by_url(url)
        if not post:
            log(f"  ERROR: 記事が見つかりません slug={slug}")
            errors += 1
            continue

        post_id = post["id"]
        old_title = post["title"]["rendered"]
        log(f"  ID={post_id}, 旧タイトル: {old_title}")

        # GPTで新タイトル生成（1件ずつ）
        new_title = generate_new_title(old_title, slug, entry["ctr"], entry["impressions"])
        if not new_title:
            log(f"  ERROR: タイトル生成失敗")
            errors += 1
            continue

        log(f"  新タイトル: {new_title}")

        # WPに適用
        ok, status = update_wp_title(post_id, new_title)
        if ok:
            log(f"  OK: WP更新成功")
            rewrites.append({
                "id": post_id,
                "old": old_title,
                "new": new_title,
                "impressions": entry["impressions"],
                "ctr": entry["ctr"]
            })
            processed += 1
        else:
            log(f"  ERROR: WP更新失敗 status={status}")
            errors += 1

        # API rate limit対策
        time.sleep(1)

    # rewrites保存
    with open(rewrites_path, "w") as f:
        json.dump(rewrites, f, ensure_ascii=False, indent=2)

    log(f"=== 完了: 処理={processed}, スキップ={skipped}, エラー={errors} ===")

if __name__ == "__main__":
    main()
