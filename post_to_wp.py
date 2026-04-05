#!/usr/bin/env python3
"""
WordPress 投稿スクリプト（完全再実装）

【最重要ルール】
- 投稿対象は reports/final_post.md のみ
- 審査レポート（3_arceus.md等）を絶対に投稿しない
- post_guard による全チェックを通過しないと投稿しない
- post_log.json に全投稿を記録する
- 失敗時は指数バックオフで再試行する

配信本部（カビゴン）管轄
"""
import base64
import json
import os
import re
import sys
import time
import requests
from datetime import datetime

# パス設定
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from lib.post_guard import (
    full_pre_publish_check,
    validate_final_post,
    record_post,
    check_emergency_stop,
)
from lib.kpi_logger import log_post, log_error
from lib.retry_handler import exponential_backoff

# ── 設定読み込み ──

def load_env():
    """環境変数を .env から読み込み"""
    env_file = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())

load_env()

WP_URL = os.environ.get("SITE_URL", "https://www.kpopjournal.tokyo") + "/wp-json/wp/v2/posts"
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_PASS", "")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
FINAL_POST_PATH = os.path.join(REPORTS_DIR, "final_post.md")


def get_auth_headers():
    token = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    }


def post_to_wordpress(title, content, slug="", categories=None, tags=None,
                       featured_media=0, excerpt="", status="publish"):
    """
    WordPress REST API で記事を投稿
    指数バックオフ付きリトライ
    """
    headers = get_auth_headers()
    data = {
        "title": title,
        "content": content,
        "status": status,
        "slug": slug,
        "excerpt": excerpt,
    }
    if categories:
        data["categories"] = categories
    if tags:
        data["tags"] = tags
    if featured_media > 0:
        data["featured_media"] = featured_media

    max_retries = 3
    for attempt in range(max_retries):
        try:
            res = requests.post(WP_URL, headers=headers, json=data, timeout=30)

            if res.status_code == 201:
                result = res.json()
                return {
                    "success": True,
                    "status_code": 201,
                    "post_id": result.get("id"),
                    "url": result.get("link", ""),
                    "attempt": attempt + 1,
                }
            elif res.status_code == 429:
                delay = exponential_backoff(attempt, 30, 120)
                print(f"  Rate limited (429). Waiting {delay:.0f}s...")
                time.sleep(delay)
            elif 500 <= res.status_code < 600:
                delay = exponential_backoff(attempt, 5, 60)
                print(f"  Server error ({res.status_code}). Waiting {delay:.0f}s...")
                time.sleep(delay)
            else:
                return {
                    "success": False,
                    "status_code": res.status_code,
                    "error": res.text[:500],
                    "attempt": attempt + 1,
                }
        except requests.exceptions.Timeout:
            delay = exponential_backoff(attempt, 10, 60)
            print(f"  Timeout. Waiting {delay:.0f}s...")
            time.sleep(delay)
        except requests.exceptions.ConnectionError as e:
            delay = exponential_backoff(attempt, 10, 60)
            print(f"  Connection error. Waiting {delay:.0f}s...")
            time.sleep(delay)

    return {"success": False, "error": "Max retries exceeded", "attempt": max_retries}


def main():
    """
    メインフロー:
    1. 強制停止チェック
    2. final_post.md 読み込み
    3. post_guard 全チェック
    4. WordPress投稿
    5. post_log 記録
    6. KPIログ記録
    """
    start_time = time.time()

    # ── 引数パース ──
    slug = ""
    categories = []
    tags = []
    media_id = 0
    article_type = "flow"
    status = "publish"

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--slug" and i + 1 < len(sys.argv):
            slug = sys.argv[i + 1]; i += 2
        elif arg == "--categories" and i + 1 < len(sys.argv):
            categories = [int(x) for x in sys.argv[i + 1].split(",") if x.strip()]
            i += 2
        elif arg == "--tags" and i + 1 < len(sys.argv):
            tags = [int(x) for x in sys.argv[i + 1].split(",") if x.strip()]
            i += 2
        elif arg == "--media" and i + 1 < len(sys.argv):
            media_id = int(sys.argv[i + 1]); i += 2
        elif arg == "--type" and i + 1 < len(sys.argv):
            article_type = sys.argv[i + 1]; i += 2
        elif arg == "--status" and i + 1 < len(sys.argv):
            status = sys.argv[i + 1]; i += 2
        elif arg == "--file" and i + 1 < len(sys.argv):
            global FINAL_POST_PATH
            FINAL_POST_PATH = sys.argv[i + 1]; i += 2
        else:
            i += 1

    print("=" * 50)
    print(" WordPress投稿 (post_to_wp.py)")
    print(f" 対象: {os.path.basename(FINAL_POST_PATH)}")
    print("=" * 50)

    # ── 1. 強制停止チェック ──
    stop = check_emergency_stop()
    if stop["stop"]:
        print(f"🚨 EMERGENCY STOP: {stop['reason']}")
        log_error({"pipeline": "post_to_wp", "step": "emergency_check", "error_type": "emergency_stop",
                    "message": stop["reason"], "recoverable": False})
        sys.exit(1)

    # ── 2. final_post.md 読み込み ──
    if not os.path.exists(FINAL_POST_PATH):
        print(f"❌ {FINAL_POST_PATH} が存在しません")
        log_error({"pipeline": "post_to_wp", "step": "file_read", "error_type": "file_not_found",
                    "message": f"{FINAL_POST_PATH} not found"})
        sys.exit(1)

    # ファイル名チェック（最重要ガード）
    basename = os.path.basename(FINAL_POST_PATH)
    if basename != "final_post.md":
        print(f"🚨 BLOCK: {basename} は投稿対象外です。final_post.md のみ投稿可能。")
        log_error({"pipeline": "post_to_wp", "step": "file_check", "error_type": "wrong_file",
                    "message": f"Attempted to post {basename}", "recoverable": False})
        sys.exit(1)

    with open(FINAL_POST_PATH, encoding="utf-8") as f:
        content_raw = f.read()

    lines = content_raw.strip().split("\n")
    title = lines[0].strip()
    body = "\n".join(lines[1:]).strip()

    print(f"  タイトル: {title[:50]}...")
    plain = re.sub(r'<[^>]+>', '', body)
    print(f"  本文: {len(plain)}文字")

    # ── 3. post_guard 全チェック ──
    print("\n--- Pre-publish Check ---")
    check = full_pre_publish_check(title, slug, article_type, FINAL_POST_PATH)
    print(json.dumps(check, ensure_ascii=False, indent=2))

    if not check["allowed"]:
        print(f"\n🚨 BLOCK: {check['reason']}")
        log_error({"pipeline": "post_to_wp", "step": "pre_publish_check", "error_type": check["reason"],
                    "message": json.dumps(check.get("details", {}), ensure_ascii=False)})
        sys.exit(1)

    if check.get("needs_approval"):
        print("\n⚠️  手動承認が必要です。承認後に再実行してください。")
        from lib.human_gate import request_approval
        request_approval({"title": title, "article_type": article_type, "file_path": FINAL_POST_PATH},
                          check["details"].get("manual_approval", {}).get("reasons", []))
        sys.exit(2)

    for w in check.get("warnings", []):
        print(f"  ⚠️  {w}")

    # ── 4. WordPress投稿 ──
    print("\n--- Publishing ---")
    # メタディスクリプション生成（110-130字、§9準拠）
    plain = re.sub(r'<[^>]+>', '', body).strip()
    # 最初の文（。で区切り）を収集して110-130字に収める
    sentences = re.split(r'(?<=[。！？])', plain)
    excerpt = ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(excerpt) + len(s) <= 130:
            excerpt += s
        else:
            break
    # 110字未満なら本文先頭から取得
    if len(excerpt) < 110:
        excerpt = plain[:125]
    # 130字超なら切り詰め
    if len(excerpt) > 130:
        excerpt = excerpt[:127] + "..."

    result = post_to_wordpress(
        title=title,
        content=body,
        slug=slug,
        categories=categories if categories else None,
        tags=tags if tags else None,
        featured_media=media_id,
        excerpt=excerpt,
        status=status,
    )

    elapsed = time.time() - start_time

    if result["success"]:
        post_id = result["post_id"]
        post_url = result["url"]
        print(f"\n✅ 投稿成功")
        print(f"  ID : {post_id}")
        print(f"  URL: {post_url}")
        print(f"  試行: {result['attempt']}回")

        # ── 5. post_log 記録 ──
        record_post(
            post_id=post_id,
            title=title,
            slug=slug,
            url=post_url,
            article_type=article_type,
            categories=categories,
        )

        # ── 6. KPIログ ──
        log_post({
            "post_id": post_id,
            "title": title,
            "url": post_url,
            "slug": slug,
            "article_type": article_type,
            "categories": categories,
            "char_count": len(plain),
            "h2_count": len(re.findall(r'<h2', body, re.IGNORECASE)),
            "pipeline": "post_to_wp",
            "has_cta": "revenue-cta" in body,
            "has_thumbnail": media_id > 0,
            "token_count": int(os.environ.get("PIPELINE_TOKEN_COUNT", 0)),
            "processing_time_sec": round(elapsed, 1),
        })

        # 出力（パイプライン連携用）
        output = {
            "post_id": post_id,
            "url": post_url,
            "title": title,
            "status": "published",
        }
        print(json.dumps(output, ensure_ascii=False))

    else:
        print(f"\n❌ 投稿失敗: {result.get('error', 'Unknown')}")
        print(f"  試行: {result['attempt']}回")
        log_error({
            "pipeline": "post_to_wp",
            "step": "wp_api_post",
            "error_type": f"http_{result.get('status_code', 'unknown')}",
            "message": result.get("error", ""),
            "recoverable": True,
        })
        sys.exit(1)


if __name__ == "__main__":
    main()
