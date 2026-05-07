#!/usr/bin/env python3
"""対象post_idのサムネをDALL-E 3で再生成し、WPのfeatured_mediaを差し替え"""
import sys
import os
import json
import base64
import urllib.request

sys.path.insert(0, "/home/aiuser/kpop-ai-system")
sys.path.insert(0, "/home/aiuser/kpop-ai-system/lib")
from lib.thumbnail_guard import safe_update_featured_media as _guard_update

from dalle_thumbnail_gen import generate_thumbnail
from make_thumbnail_v6 import _dalle_fallback

WP_USER = "kpop-bot"
WP_APP_PASS = "vl1H 1brV m4Pq Z1sm F8lZ 3nzh"
AUTH = base64.b64encode(f"{WP_USER}:{WP_APP_PASS}".encode()).decode()
WP_BASE = "https://www.kpopjournal.tokyo/wp-json/wp/v2"


def _wp_get(endpoint: str):
    req = urllib.request.Request(
        f"{WP_BASE}/{endpoint}",
        headers={"Authorization": f"Basic {AUTH}"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def _compress_to_jpg(png_path: str) -> str:
    """PNG→JPEG変換+圧縮 (WP 1MB制限対応)"""
    from PIL import Image
    jpg_path = png_path.rsplit(".", 1)[0] + ".jpg"
    img = Image.open(png_path).convert("RGB")
    # 1200px幅にリサイズ (サムネとして十分)
    if img.width > 1200:
        ratio = 1200 / img.width
        img = img.resize((1200, int(img.height * ratio)), Image.LANCZOS)
    img.save(jpg_path, "JPEG", quality=82, optimize=True)
    return jpg_path


def upload_media(image_path: str, post_id: int) -> int:
    # PNG→JPEG圧縮
    if image_path.endswith(".png"):
        image_path = _compress_to_jpg(image_path)

    with open(image_path, "rb") as f:
        data = f.read()
    ext = os.path.splitext(image_path)[1]
    content_type = "image/jpeg" if ext == ".jpg" else "image/png"
    filename = f"v6_dalle_post{post_id}{ext}"
    req = urllib.request.Request(
        f"{WP_BASE}/media",
        data=data,
        headers={
            "Authorization": f"Basic {AUTH}",
            "Content-Type": content_type,
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        res = json.loads(r.read())
    return res["id"]


def update_featured_media(post_id: int, media_id: int) -> bool:
    body = json.dumps({"featured_media": media_id}).encode()
    req = urllib.request.Request(
        f"{WP_BASE}/posts/{post_id}",
        data=body,
        headers={
            "Authorization": f"Basic {AUTH}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read())
        return res.get("featured_media") == media_id
    except Exception as e:
        print(f"  update error: {e}")
        return False


def process_post(post_id: int) -> bool:
    try:
        post = _wp_get(f"posts/{post_id}?_fields=title,content,excerpt")
    except Exception as e:
        print(f"[{post_id}] fetch error: {e}")
        return False

    import re
    title = re.sub(r"<[^>]+>", "", post["title"]["rendered"])
    body = (
        post.get("excerpt", {}).get("rendered", "")
        + " "
        + (post.get("content", {}).get("rendered", "") or "")[:2000]
    )

    print(f"\n[{post_id}] {title[:60]}")

    # v6パイプライン経由 (アーティスト写真最優先 → DALL-Eフォールバック)
    from make_thumbnail_v6 import make_thumbnail_v6
    result = make_thumbnail_v6(
        title=title, body=body, post_id=str(post_id),
        output_dir="/tmp/v6_regen", max_retries=2,
    )
    if result.get("verdict") not in ("PASS", "QUEUE_REVIEW") or not result.get("output_path"):
        print(f"  generation failed: {result.get('meta', {}).get('reason', '?')}")
        return False

    image_path = result["output_path"]
    source = result.get("source", "?")
    score = result.get("vision_score", 0)
    print(f"  v6 OK: source={source} score={score} {image_path}")

    try:
        media_id = upload_media(image_path, post_id)
        print(f"  WP upload: media_id={media_id}")
    except Exception as e:
        print(f"  upload failed: {e}")
        return False

    ok = update_featured_media(post_id, media_id)
    if ok:
        print(f"  featured_media updated")
        return True
    else:
        print(f"  featured_media update failed")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 regenerate_thumbnail_wp.py <post_id1> [post_id2] ...")
        sys.exit(1)

    ok, ng = 0, 0
    for arg in sys.argv[1:]:
        try:
            pid = int(arg)
            if process_post(pid):
                ok += 1
            else:
                ng += 1
        except ValueError:
            print(f"skip: {arg}")

    print(f"\n=== Done: {ok} ok / {ng} failed ===")
