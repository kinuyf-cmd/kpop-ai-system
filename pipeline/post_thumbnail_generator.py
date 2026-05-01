#!/usr/bin/env python3
"""サムネなし記事にv6方式(テキストゼロ+実写真優先)でサムネ自動生成

毎時25分・55分、最大3件/回。make_thumbnail_v6を必ず経由する。
PIL直描画禁止 — 教訓#50 (2026-04-27 ダササムネ事故)
"""
import base64
import io
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv("/home/aiuser/kpop-ai-system/.env")

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "lib"))

from make_thumbnail_v6 import make_thumbnail_v6
from lib.thumbnail_guard import safe_update_featured_media as _guard_update

WP_USER = os.getenv("WP_USER", "")
WP_PASS = os.getenv("WP_PASS", "")
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
MAX_PER_RUN = 3
V6_EXPECTED_SIZE = (1200, 675)
LOG_FILE = str(BASE_DIR / "logs" / "thumbnail_generator.jsonl")


def get_posts_without_thumbnail(per_page=20, post_types=None):
    if post_types is None:
        post_types = ["posts"]
    posts = []
    for endpoint in post_types:
        try:
            url = (
                f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}"
                f"?per_page={per_page}&_fields=id,title,featured_media,date,content"
                f"&orderby=date&order=desc"
            )
            req = urllib.request.Request(url, headers={"Authorization": f"Basic {AUTH}"})
            data = json.loads(urllib.request.urlopen(req, timeout=20).read())
            for p in data:
                if not p.get("featured_media") or p.get("featured_media") == 0:
                    p["_endpoint"] = endpoint
                    posts.append(p)
        except Exception as e:
            print(f"取得err {endpoint}: {e}")
    return posts


def _validate_v6_output(path: str) -> bool:
    """生成画像が1200x675であることを検証"""
    try:
        from PIL import Image

        img = Image.open(path)
        if img.size != V6_EXPECTED_SIZE:
            print(f"     v6検証NG: {img.size} != {V6_EXPECTED_SIZE}")
            return False
        return True
    except Exception as e:
        print(f"     v6検証err: {e}")
        return False


def _upload_to_wp(img_path: str, post_id: int, title: str, endpoint: str) -> bool:
    """WPにアップロードしてfeatured_mediaに設定"""
    try:
        with open(img_path, "rb") as f:
            img_bytes = f.read()
    except Exception as e:
        print(f"     読込err: {e}")
        return False

    # ファイル名にv6マーカーを含める
    ts = int(time.time())
    filename = f"v6_kpop_thumb_{post_id}_{ts}.jpg"

    try:
        boundary = f"kpjV6Boundary{post_id}{ts}"
        parts = [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode(),
            b"Content-Type: image/jpeg",
            b"",
            img_bytes,
            f"--{boundary}--".encode(),
            b"",
        ]
        upload_body = b"\r\n".join(parts)
        req = urllib.request.Request(
            "https://www.kpopjournal.tokyo/wp-json/wp/v2/media",
            data=upload_body,
            method="POST",
            headers={
                "Authorization": f"Basic {AUTH}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        r = json.loads(urllib.request.urlopen(req, timeout=60).read())
        media_id = r.get("id")
    except Exception as e:
        print(f"     WP media err: {e}")
        return False

    # alt_text設定
    import re
    alt_text = re.sub(r"[【】「」『』|｜]", " ", title).strip()
    alt_text = re.sub(r"\s+", " ", alt_text)[:100]
    try:
        body = json.dumps({"alt_text": alt_text}).encode()
        req = urllib.request.Request(
            f"https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{media_id}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Basic {AUTH}",
                "Content-Type": "application/json",
            },
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception:
        pass

    # featured_media設定 (thumbnail_guard経由)
    try:
        result = _guard_update(post_id, media_id, source='post_thumbnail_generator')
        if result.get('blocked'):
            print(f"     🛡️ MV画像保護: 上書き拒否")
            return False
        if result.get('success'):
            print(f"     OK media_id={media_id} file={filename}")
            return True
        return False
    except Exception as e:
        print(f"     update err: {e}")
        return False


def _dalle_fallback(post_id: int, title: str, body: str) -> str:
    """教訓#59: v6 score<90時のDALL-Eフォールバック
    記事タイトル+本文からテーマに合った画像を生成"""
    try:
        from lib.dalle_thumbnail_gen import generate_thumbnail
        from PIL import Image

        # タイトルから英語プロンプト生成
        prompt = (
            f"A professional editorial thumbnail image for a K-pop/Korean culture article titled '{title}'. "
            f"Modern, vibrant, magazine-quality photo composition, 1200x675 aspect ratio. "
            f"No text overlay, no faces of real people. Korean pop culture aesthetic."
        )

        out_dir = f"/tmp/dalle_fallback_{post_id}"
        os.makedirs(out_dir, exist_ok=True)
        raw_path = f"{out_dir}/dalle_raw.jpg"

        result = generate_thumbnail(prompt=prompt, output_path=raw_path, size="1792x1024", quality="standard")
        if not result.get("success"):
            print(f"     DALL-E err: {result.get('reason', '?')}")
            return ""

        # リサイズ 1200x675
        resized_path = f"{out_dir}/dalle_resized.jpg"
        img = Image.open(raw_path)
        img = img.resize((1200, 675), Image.LANCZOS)
        img.save(resized_path, "JPEG", quality=85, optimize=True)
        print(f"     DALL-E OK: {os.path.getsize(resized_path)} bytes")
        return resized_path
    except Exception as e:
        print(f"     DALL-E fallback err: {e}")
        return ""


def generate_and_attach(post):
    """v6方式でサムネ生成 → WPアップロード"""
    pid = post["id"]
    
    # 保護: 既にfeatured_mediaが設定済みで、MV画像(v6_mv_ or v6_kpop_thumb)なら生成しない
    existing_fm = post.get("featured_media", 0)
    if existing_fm and existing_fm > 0:
        try:
            _check_url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{existing_fm}?_fields=media_details"
            _check_req = urllib.request.Request(_check_url, headers={"Authorization": f"Basic {AUTH}"})
            _check_data = json.loads(urllib.request.urlopen(_check_req, timeout=10).read())
            _check_file = _check_data.get("media_details", {}).get("file", "")
            if ("v6_mv_" in _check_file or "v6_kpop_thumb" in _check_file) and "dalle" not in _check_file.lower():
                print(f"  id={pid} SKIP: 既存MV画像を保持 ({_check_file})")
                return True
        except:
            pass
    title_obj = post.get("title", {})
    title = title_obj.get("rendered", "") if isinstance(title_obj, dict) else str(title_obj)
    body = ""
    if isinstance(post.get("content"), dict):
        body = post["content"].get("rendered", "")[:1000]
    endpoint = post.get("_endpoint", "posts")

    print(f"  id={pid} {title[:50]}")

    # v6生成 (make_thumbnail_v6 を必ず経由)
    output_dir = f"/tmp/v6_thumb_{pid}"
    os.makedirs(output_dir, exist_ok=True)

    result = make_thumbnail_v6(
        title=title,
        body=body,
        post_id=str(pid),
        output_dir=output_dir,
        max_retries=3,
    )

    verdict = result.get("verdict", "")
    score = result.get("score", 0)
    output_path = result.get("output_path", "")

    print(f"     v6 verdict={verdict} score={score} source={result.get('source', '?')}")

    # 教訓#59: QUEUE_REVIEW (score<90) はテーマ無関係の可能性が高い → DALL-Eフォールバック
    if verdict == "QUEUE_REVIEW" or score < 90:
        print(f"     ⚠️ v6 score<90 ({score}) → DALL-Eフォールバック試行")
        dalle_path = _dalle_fallback(pid, title, body)
        if dalle_path:
            output_path = dalle_path
            verdict = "DALLE_FALLBACK"
        else:
            print(f"     DALL-Eも失敗、v6出力を使用 (要手動確認)")

    if not output_path or not os.path.exists(output_path):
        print(f"     出力なし (verdict={verdict})")
        return False

    # v6出力検証
    if not _validate_v6_output(output_path):
        print(f"     出力サイズ不正、スキップ")
        return False

    return _upload_to_wp(output_path, pid, title, endpoint)


def regenerate_for_post(post_id: int, force: bool = False) -> dict:
    """既存記事のサムネをv6で再生成 (外部呼び出し用)"""
    # 保護: 既にYouTube MV画像が設定済みなら再生成しない (DALL-E上書き防止)
    if not force:
        existing_fm = post.get("featured_media", 0)
        if existing_fm:
            try:
                _m_url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{existing_fm}"
                _m_req = urllib.request.Request(_m_url, headers={"Authorization": f"Basic {AUTH}"})
                _m_data = json.loads(urllib.request.urlopen(_m_req, timeout=10).read())
                _m_file = _m_data.get("media_details", {}).get("file", "")
                if "v6_kpop_thumb" in _m_file and "dalle" not in _m_file.lower():
                    print(f"  skip_if_youtube: 既存v6 MV画像を保持 ({_m_file})")
                    return {"success": True, "verdict": "SKIP", "reason": "existing_v6_mv_preserved"}
            except: pass

    try:
        url = (
            f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}"
            f"?_fields=id,title,content,featured_media"
        )
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {AUTH}"})
        post = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception as e:
        return {"success": False, "error": f"WP fetch: {e}"}

    title_obj = post.get("title", {})
    title = title_obj.get("rendered", "") if isinstance(title_obj, dict) else str(title_obj)
    body = ""
    if isinstance(post.get("content"), dict):
        body = post["content"].get("rendered", "")[:1000]

    output_dir = f"/tmp/v6_regen_{post_id}"
    os.makedirs(output_dir, exist_ok=True)

    result = make_thumbnail_v6(
        title=title,
        body=body,
        post_id=str(post_id),
        output_dir=output_dir,
        max_retries=3,
    )

    output_path = result.get("output_path", "")
    if not output_path or not os.path.exists(output_path):
        return {"success": False, "verdict": result.get("verdict"), "error": "no output"}

    if not _validate_v6_output(output_path):
        return {"success": False, "error": "size validation failed"}

    ok = _upload_to_wp(output_path, post_id, title, "posts")
    return {
        "success": ok,
        "verdict": result.get("verdict"),
        "source": result.get("source"),
        "output_path": output_path,
    }


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--post-type", default=None, help="posts or popup")
    parser.add_argument("--limit", type=int, default=MAX_PER_RUN)
    parser.add_argument("--regen", type=int, nargs="+", help="再生成対象のpost ID")
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).isoformat()

    # 再生成モード
    if args.regen:
        print(f"=== v6 regen mode {ts} ids={args.regen} ===")
        for pid in args.regen:
            r = regenerate_for_post(pid, force=True)
            print(f"  {pid}: {r}")
        return

    # 通常モード: サムネなし記事の自動補完
    post_types = [args.post_type] if args.post_type else ["posts"]
    limit = args.limit

    print(f"=== post_thumbnail_generator (v6) {ts} types={post_types} limit={limit} ===")
    posts = get_posts_without_thumbnail(per_page=50, post_types=post_types)
    targets = posts[:limit]

    if not targets:
        print("  対象なし")
        return

    print(f"  対象: {len(targets)}件 (全{len(posts)}件から)")
    success = 0
    for post in targets:
        if generate_and_attach(post):
            success += 1
        time.sleep(2)

    print(f"\n{success}/{len(targets)}件 v6サムネ生成完了")

    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "ts": ts,
                    "engine": "v6",
                    "attempted": len(targets),
                    "success": success,
                    "pending": len(posts) - success,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


if __name__ == "__main__":
    main()
