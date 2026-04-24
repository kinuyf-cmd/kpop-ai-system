#!/usr/bin/env python3
"""
post_publish_enricher.py — 記事公開後の構造自動補完

公開直後の記事に対して以下を自動挿入する:
  1. 3行まとめ (kpj-summary)  — article_summarizer.py
  2. アーティストプロフィール (kpj-artist-profile) — artist_profile_inserter.py
  3. サムネサイズ検証（GRADIENT_FAIL検出時はログ警告）

Usage:
  # 単一記事
  python3 pipeline/post_publish_enricher.py --post-id 3952

  # 直近N時間以内の全記事
  python3 pipeline/post_publish_enricher.py --recent-hours 6

  # パイプラインから呼び出し
  from pipeline.post_publish_enricher import enrich_post
  result = enrich_post(post_id=3952)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "lib"))

from article_summarizer import generate_summary, insert_summary_into_html
from artist_profile_inserter import detect_artist_in_text, generate_profile_html

LOGS = BASE / "logs"
JST = timezone(timedelta(hours=9))

# WP API helpers
WP_DOMAIN = "https://www.kpopjournal.tokyo"
WP_AUTH_FILE = Path.home() / ".wp_auth"


def _wp_headers() -> dict:
    """Load WP auth header from ~/.wp_auth curl config."""
    if WP_AUTH_FILE.exists():
        for line in WP_AUTH_FILE.read_text().splitlines():
            if line.strip().startswith("header"):
                # header = "Authorization: Basic xxx"
                val = line.split("=", 1)[1].strip().strip('"')
                return {"Authorization": val.split(": ", 1)[1] if ": " in val else val,
                        "Content-Type": "application/json"}
    return {}


def _log(msg: str):
    ts = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [enricher] {msg}"
    print(line)
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOGS / "post_publish_enricher.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _fetch_post(post_id: int) -> dict | None:
    import requests
    try:
        resp = requests.get(
            f"{WP_DOMAIN}/wp-json/wp/v2/posts/{post_id}",
            params={"_fields": "id,title,content,featured_media"},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        _log(f"WARN: fetch post {post_id} failed: {e}")
    return None


def _update_post_content(post_id: int, content: str) -> bool:
    import requests
    headers = _wp_headers()
    if not headers:
        _log("ERROR: WP auth not available")
        return False
    try:
        resp = requests.post(
            f"{WP_DOMAIN}/wp-json/wp/v2/posts/{post_id}",
            headers=headers,
            json={"content": content},
            timeout=30,
        )
        return resp.status_code == 200
    except Exception as e:
        _log(f"ERROR: update post {post_id} failed: {e}")
        return False


def _check_thumbnail_size(featured_media: int) -> tuple[str, int]:
    """Check thumbnail file size. Returns (verdict, size_bytes)."""
    if not featured_media:
        return "NO_THUMB", 0
    import requests
    try:
        m = requests.get(f"{WP_DOMAIN}/wp-json/wp/v2/media/{featured_media}", timeout=10).json()
        url = m.get("source_url", "")
        if not url:
            return "NO_URL", 0
        head = requests.head(url, timeout=5)
        size = int(head.headers.get("content-length", 0))
        if size >= 50000:
            return "PASS", size
        elif size >= 10000:
            return "NEEDS_V6_REPLACE", size
        else:
            return "GRADIENT_FAIL", size
    except Exception:
        return "CHECK_FAILED", 0


def _check_thumbnail_quality(image_url: str) -> tuple[bool, str]:
    """Download thumbnail and check for v6 violations (dark bg / text burn-in).
    Returns (is_violation, reason).
    """
    try:
        from PIL import Image
        import numpy as np
        import io
        import requests as _req
    except ImportError:
        return False, "PIL/numpy not installed"

    try:
        resp = _req.get(image_url, timeout=10)
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        arr = np.array(img)
    except Exception as e:
        return False, f"image load failed: {e}"

    mean_brightness = float(arr.mean())
    if mean_brightness < 55:
        return True, f"dark_bg(brightness={mean_brightness:.0f})"

    h = arr.shape[0]
    bottom = arr[int(h * 0.66):, :, :]
    bottom_mean = float(bottom.mean())
    if abs(bottom_mean - mean_brightness) > 80:
        return True, f"text_band(bottom={bottom_mean:.0f},full={mean_brightness:.0f})"

    std_val = float(arr.std())
    if std_val < 20:
        return True, f"flat_color(std={std_val:.0f})"

    return False, "ok"


def enrich_post(post_id: int) -> dict:
    """Enrich a single post with summary + profile if missing."""
    result = {"post_id": post_id, "changes": [], "status": "ok"}

    post = _fetch_post(post_id)
    if not post:
        result["status"] = "fetch_failed"
        return result

    title = post.get("title", {}).get("rendered", "")
    content = post.get("content", {}).get("rendered", "")
    featured_media = post.get("featured_media", 0)

    modified = content
    changes = []

    # 1. Summary
    if "kpj-summary" not in content:
        summary_html = generate_summary(content)
        modified = insert_summary_into_html(modified, summary_html)
        changes.append("summary_added")

    # 2. Profile — タイトルに含まれるアーティストのみ（本文の言及で別グループ混入を防止）
    if "kpj-artist-profile" not in content:
        artists = detect_artist_in_text(title)
        if artists:
            profile_html = generate_profile_html(artists[0])
            if profile_html:
                modified = modified + "\n" + profile_html
                changes.append(f"profile_added({artists[0]})")

    # 3. Thumbnail check
    thumb_verdict, thumb_size = _check_thumbnail_size(featured_media)
    if thumb_verdict not in ("PASS", "NO_THUMB"):
        changes.append(f"thumb_warn({thumb_verdict},{thumb_size}B)")
        _log(f"WARN: post {post_id} thumbnail {thumb_verdict} ({thumb_size}B)")

    # Apply changes
    if any(c.startswith(("summary_", "profile_")) for c in changes):
        ok = _update_post_content(post_id, modified)
        if ok:
            _log(f"OK: post {post_id} enriched: {', '.join(changes)}")
        else:
            result["status"] = "update_failed"
            _log(f"FAIL: post {post_id} update failed")
    else:
        _log(f"SKIP: post {post_id} already complete (thumb={thumb_verdict})")

    # 4. Lead structure validation (Phase 10)
    lead_ok, lead_issues = _validate_lead_structure(content)
    if not lead_ok:
        changes.append(f"lead_warn({'; '.join(lead_issues[:2])})")

    result["changes"] = changes
    return result


def _validate_lead_structure(content_html: str) -> tuple:
    """記事冒頭3段落がリード文構造 (5W1H→背景→重要性) かを検証。"""
    pre_h2 = content_html.split("<h2", 1)[0] if "<h2" in content_html else content_html
    paras = re.findall(r"<p[^>]*>(.*?)</p>", pre_h2, re.DOTALL)
    paras_text = [re.sub(r"<[^>]+>", "", p).strip() for p in paras]
    paras_text = [p for p in paras_text if len(p) > 20]

    issues: list[str] = []
    if len(paras_text) < 3:
        issues.append(f"リード文{len(paras_text)}段落(3段落必須)")
        return False, issues

    p1 = paras_text[0]
    has_who = bool(re.search(r"[A-Z][A-Z]+|[ぁ-んァ-ヶ一-龠]{2,}(?:は|が|、)", p1))
    has_when = bool(re.search(r"\d+月|\d+日|\d+年|本日|今週|先週", p1))
    if not (has_who and has_when):
        issues.append("第1段落の5W1H要素不足")

    if len(paras_text[1]) < 40:
        issues.append("第2段落が短い(背景不足)")

    if not re.search(r"重要|初|史上|記録|最大|注目|意味|背景", paras_text[2]):
        issues.append("第3段落に重要性表現不足")

    return len(issues) == 0, issues


def enrich_recent(hours: int = 6) -> list[dict]:
    """Enrich all posts published within the last N hours."""
    import requests
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        resp = requests.get(
            f"{WP_DOMAIN}/wp-json/wp/v2/posts",
            params={"after": cutoff, "per_page": 50, "_fields": "id"},
            timeout=15,
        )
        posts = resp.json() if resp.status_code == 200 else []
    except Exception:
        posts = []

    results = []
    for p in posts:
        r = enrich_post(p["id"])
        results.append(r)
    return results


def main():
    parser = argparse.ArgumentParser(description="記事公開後の構造自動補完")
    parser.add_argument("--post-id", type=int, help="特定の記事IDを処理")
    parser.add_argument("--recent-hours", type=int, default=0, help="直近N時間以内の記事を一括処理")
    args = parser.parse_args()

    if args.post_id:
        result = enrich_post(args.post_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.recent_hours:
        results = enrich_recent(args.recent_hours)
        for r in results:
            print(json.dumps(r, ensure_ascii=False))
        print(f"\nTotal: {len(results)} posts processed")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
