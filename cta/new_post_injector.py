#!/usr/bin/env python3
"""new_post_injector.py — Phase 30.1: 最強CTA Phase 30版 自動配置

対象: 2026-05-04以降の新規投稿のみ (既存631記事は不変)
フロー:
  1. WP REST APIで投稿のcategory/tag/title/content取得
  2. 文字数カウント
  3. hybrid_banner_matrixでメイン/サブ案件決定
  4. 2500字以上ならH2位置検出 (第1, 第3-4)
  5. 最強CTA Phase 30版 8ブロックHTML生成 (A8素材改変禁止)
  6. WP REST APIでpost.content更新

8ブロック構造:
  1. ヒーロー枠 (A8バナー)
  2. 見出し+サブテキスト
  3. 緊急性バー
  4. ベネフィット4項目
  5. 社会的証明バー
  6. A8公式バナー枠 (300x250)
  7. メインボタン
  8. 保証バッジ4つ

使い方:
  python3 cta/new_post_injector.py <post_id>
  python3 cta/new_post_injector.py --batch  # 5/4以降の未処理記事一括
  python3 cta/new_post_injector.py --dry-run <post_id>
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = Path(__file__).resolve().parent.parent
CTA_DIR = BASE / "cta"
CONFIG_DIR = BASE / "config" / "affiliate"
LOGS = BASE / "logs"
LOG_FILE = LOGS / "hybrid_cta_inject.jsonl"
REVIEW_QUEUE = BASE / "data" / "cta_review_queue.jsonl"
JST = timezone(timedelta(hours=9))

# WP Auth
from dotenv import dotenv_values
ENV = dotenv_values(str(BASE / ".env"))
WP_USER = ENV.get("WP_USER", "")
WP_PASS = ENV.get("WP_PASS", "")
SITE_URL = ENV.get("SITE_URL", "https://www.kpopjournal.tokyo")
WP_API = f"{SITE_URL}/wp-json/wp/v2"
AUTH_HEADER = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()

# Phase 30 cutoff date
CUTOFF_DATE = "2026-05-04T00:00:00"

# Markers to avoid double-injection (detect both old and new CTA)
HYBRID_MARKER = 'data-cta-position="'
STRONGEST_MARKER = 'kpj-strongest-phase30'


def load_banners() -> dict:
    with open(CTA_DIR / "a8_banners.json") as f:
        return json.load(f)["programs"]


def load_templates() -> dict:
    """Load the strongest Phase 30 templates (8-block version)."""
    with open(CTA_DIR / "cta_strongest_phase30_templates.json") as f:
        return json.load(f)


def load_strongest_data() -> dict:
    """Load the strongest Phase 30 program data (verified claims only)."""
    with open(CTA_DIR / "cta_strongest_phase30_data.json") as f:
        return json.load(f)


def load_genre_map() -> dict:
    with open(CONFIG_DIR / "cta_genre_map.json") as f:
        data = json.load(f)
    return data.get("hybrid_banner_matrix", {}), data.get("hybrid_defaults", {})


def wp_get(endpoint: str) -> dict | None:
    """WP REST API GET request."""
    import urllib.request
    url = f"{WP_API}/{endpoint}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Basic {AUTH_HEADER}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"[ERROR] WP GET {url}: {e}", file=sys.stderr)
        return None


def wp_update_content(post_id: int, content: str) -> bool:
    """WP REST API POST to update content."""
    import urllib.request
    url = f"{WP_API}/posts/{post_id}"
    data = json.dumps({"content": content}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Basic {AUTH_HEADER}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[ERROR] WP UPDATE {post_id}: {e}", file=sys.stderr)
        return False


def get_post_data(post_id: int) -> dict | None:
    """Fetch post with categories, tags, title, content."""
    data = wp_get(f"posts/{post_id}?context=edit&_fields=id,title,content,categories,tags,date,status")
    if not data:
        return None
    # Resolve category/tag names
    cat_names = []
    for cat_id in data.get("categories", []):
        cat_data = wp_get(f"categories/{cat_id}?_fields=name,slug")
        if cat_data:
            cat_names.append(cat_data.get("name", ""))
    tag_names = []
    for tag_id in data.get("tags", []):
        tag_data = wp_get(f"tags/{tag_id}?_fields=name,slug")
        if tag_data:
            tag_names.append(tag_data.get("name", ""))
    return {
        "id": data["id"],
        "title": data["title"]["raw"] if isinstance(data["title"], dict) else data["title"],
        "content": data["content"]["raw"] if isinstance(data["content"], dict) else data["content"],
        "categories": data.get("categories", []),
        "category_names": cat_names,
        "tags": data.get("tags", []),
        "tag_names": tag_names,
        "date": data.get("date", ""),
        "status": data.get("status", ""),
    }


def classify_for_hybrid(title: str, category_names: list, tag_names: list) -> str:
    """Classify article into hybrid_banner_matrix category."""
    matrix, _ = load_genre_map()
    text = title + " " + " ".join(category_names) + " " + " ".join(tag_names)

    best_match = None
    best_score = 0
    for genre_key, rule in matrix.items():
        if not isinstance(rule, dict):
            continue
        regex = rule.get("title_regex", "")
        if not regex:
            continue
        matches = re.findall(regex, text, re.IGNORECASE)
        score = len(matches)
        # Boost if WP tag matches
        for tag in tag_names:
            if tag in rule.get("wp_tags", []):
                score += 2
        if score > best_score:
            best_score = score
            best_match = genre_key

    return best_match if best_match else "default"


def get_programs_for_position(genre: str, position: str) -> dict:
    """Get main/sub program keys for a given genre and position."""
    matrix, defaults = load_genre_map()
    if genre in matrix:
        pos_data = matrix[genre].get(position, {})
    else:
        pos_data = defaults.get(position, {})
    return pos_data


def find_h2_positions(content: str) -> list[int]:
    """Find character positions of all <h2> tags in content."""
    positions = []
    for m in re.finditer(r'<h2[^>]*>', content, re.IGNORECASE):
        positions.append(m.start())
    return positions


def _build_benefits_html(benefits: list) -> str:
    """Build 4 benefit items HTML."""
    icons = ["✨", "🎯", "💡", "🎁"]
    items = []
    for i, b in enumerate(benefits[:4]):
        icon = icons[i % len(icons)]
        items.append(f'<div class="kpj-benefit-item"><span class="kpj-benefit-icon">{icon}</span>{b}</div>')
    return "\n".join(items)


def build_hybrid_html(program_key: str, position: str, banners: dict,
                      templates: dict, sub_key: str = None) -> str:
    """Build the 最強CTA Phase 30版 8-block HTML for a given position."""
    program = banners.get(program_key)
    if not program:
        return ""

    pos_template = templates["positions"].get(position)
    if not pos_template:
        return ""

    # Load strongest data for this program
    strongest = load_strongest_data()
    prog_data = strongest.get("programs", {}).get(program_key, {})
    if not prog_data:
        return ""

    trust_badges = templates.get("trust_badges_html", "")

    if position == "position_top":
        sizes = program["sizes"]
        has_728 = "728x90" in sizes
        has_320 = "320x50" in sizes

        if has_728 and has_320:
            html = pos_template["template"]
            html = html.replace("{{a8mat_pc}}", sizes["728x90"]["a8mat"])
            html = html.replace("{{banner_html_728x90}}", sizes["728x90"]["html"])
            html = html.replace("{{tracking_pixel_728x90}}", sizes["728x90"]["tracking_pixel"])
            html = html.replace("{{banner_html_320x50}}", sizes["320x50"]["html"])
            html = html.replace("{{tracking_pixel_320x50}}", sizes["320x50"]["tracking_pixel"])
            click_a8mat = sizes["728x90"]["a8mat"]
        elif has_320:
            html = pos_template.get("fallback_no_728", pos_template["template"])
            html = html.replace("{{a8mat_sp}}", sizes["320x50"]["a8mat"])
            html = html.replace("{{banner_html_320x50}}", sizes["320x50"]["html"])
            html = html.replace("{{tracking_pixel_320x50}}", sizes["320x50"]["tracking_pixel"])
            click_a8mat = sizes["320x50"]["a8mat"]
        else:
            return ""

        html = html.replace("{{program_key}}", program_key)
        html = html.replace("{{headline}}", prog_data.get("headline", ""))
        html = html.replace("{{subtext}}", prog_data.get("subtext", ""))
        html = html.replace("{{button_text}}", prog_data.get("button_text", program["button_text"]))
        html = html.replace("{{click_url}}", f"https://px.a8.net/svt/ejp?a8mat={click_a8mat}")
        html = html.replace("{{trust_badges}}", trust_badges)
        return html

    elif position == "position_middle":
        sizes = program["sizes"]
        if "300x250" not in sizes:
            return ""
        size_data = sizes["300x250"]

        html = pos_template["template"]
        html = html.replace("{{a8mat}}", size_data["a8mat"])
        html = html.replace("{{program_key}}", program_key)
        html = html.replace("{{headline}}", prog_data.get("headline", ""))
        html = html.replace("{{subtext}}", prog_data.get("subtext", ""))
        html = html.replace("{{urgency_text}}", prog_data.get("urgency_text", ""))
        html = html.replace("{{benefits_html}}", _build_benefits_html(prog_data.get("benefits", [])))
        html = html.replace("{{social_proof}}", prog_data.get("social_proof", ""))
        html = html.replace("{{banner_html_300x250}}", size_data["html"])
        html = html.replace("{{tracking_pixel_300x250}}", size_data["tracking_pixel"])
        html = html.replace("{{click_url}}", f"https://px.a8.net/svt/ejp?a8mat={size_data['a8mat']}")
        html = html.replace("{{button_text}}", prog_data.get("button_text", program["button_text"]))
        return html

    elif position == "position_bottom":
        sizes_main = program["sizes"]
        if "300x250" not in sizes_main:
            return ""
        main_300 = sizes_main["300x250"]

        html = pos_template["template"]
        html = html.replace("{{a8mat}}", main_300["a8mat"])
        html = html.replace("{{program_key}}", program_key)
        html = html.replace("{{headline}}", prog_data.get("headline", ""))
        html = html.replace("{{subtext}}", prog_data.get("subtext", ""))
        html = html.replace("{{urgency_text}}", prog_data.get("urgency_text", ""))
        html = html.replace("{{benefits_html}}", _build_benefits_html(prog_data.get("benefits", [])))
        html = html.replace("{{social_proof}}", prog_data.get("social_proof", ""))
        html = html.replace("{{banner_html_300x250}}", main_300["html"])
        html = html.replace("{{tracking_pixel_300x250}}", main_300["tracking_pixel"])
        html = html.replace("{{click_url}}", f"https://px.a8.net/svt/ejp?a8mat={main_300['a8mat']}")
        html = html.replace("{{button_text}}", prog_data.get("button_text", program["button_text"]))
        html = html.replace("{{trust_badges}}", trust_badges)
        return html

    return ""


def inject_hybrid_cta(post_id: int, dry_run: bool = False) -> dict:
    """Main injection logic for a single post."""
    result = {
        "post_id": post_id,
        "status": "skipped",
        "reason": "",
        "injected_positions": [],
        "timestamp": datetime.now(JST).isoformat(),
    }

    # 1. Fetch post
    post = get_post_data(post_id)
    if not post:
        result["status"] = "error"
        result["reason"] = "fetch_failed"
        return result

    # 2. Check cutoff date (only new posts after 2026-05-04)
    if post["date"] < CUTOFF_DATE:
        result["reason"] = "before_cutoff"
        return result

    # 3. Check if already injected (old or new CTA)
    content = post["content"]
    if HYBRID_MARKER in content or STRONGEST_MARKER in content:
        result["reason"] = "already_injected"
        return result

    # 4. Check status
    if post["status"] != "publish":
        result["reason"] = f"status_{post['status']}"
        return result

    # 5. Classify genre
    genre = classify_for_hybrid(post["title"], post["category_names"], post["tag_names"])
    result["genre"] = genre

    # 6. Load resources
    banners = load_banners()
    templates = load_templates()

    # 7. Content length check
    plain_text = re.sub(r'<[^>]+>', '', content)
    content_length = len(plain_text)
    result["content_length"] = content_length

    # 8. Get programs per position
    programs_top = get_programs_for_position(genre, "position_top")
    programs_mid = get_programs_for_position(genre, "position_middle")
    programs_bot = get_programs_for_position(genre, "position_bottom")

    # 9. Determine injection points via H2 positions
    h2_positions = find_h2_positions(content)
    new_content = content

    # Shared CSS (inject once at top)
    css_block = templates.get("shared_css", "")

    injections = []  # (position_in_content, html_to_insert)

    # position_top: before 1st H2 (if 2500+ chars)
    if content_length >= 2500 and h2_positions:
        main_key = programs_top.get("main")
        if main_key and main_key in banners:
            # Check size_limitation
            prog = banners[main_key]
            if prog.get("size_limitation") == "only_300x250":
                # Fall back
                main_key = programs_top.get("fallback")
            if main_key and main_key in banners:
                top_html = build_hybrid_html(main_key, "position_top", banners, templates)
                if top_html:
                    injections.append((h2_positions[0], top_html))
                    result["injected_positions"].append("top")

    # position_middle: before 3rd or 4th H2 (if 2500+ chars)
    if content_length >= 2500 and len(h2_positions) >= 3:
        mid_idx = 3 if len(h2_positions) >= 4 else 2  # 0-indexed: 3rd=idx2, 4th=idx3
        main_key = programs_mid.get("main")
        if main_key and main_key in banners:
            mid_html = build_hybrid_html(main_key, "position_middle", banners, templates)
            if mid_html:
                injections.append((h2_positions[mid_idx], mid_html))
                result["injected_positions"].append("middle")

    # position_bottom: always (end of content)
    main_key = programs_bot.get("main")
    sub_key = programs_bot.get("sub")
    if main_key and main_key in banners:
        bot_html = build_hybrid_html(main_key, "position_bottom", banners, templates, sub_key)
        if bot_html:
            injections.append((len(content), bot_html))
            result["injected_positions"].append("bottom")

    if not injections:
        result["reason"] = "no_applicable_programs"
        return result

    # 10. Apply injections (reverse order to preserve positions)
    injections.sort(key=lambda x: x[0], reverse=True)
    for pos, html in injections:
        new_content = new_content[:pos] + "\n" + html + "\n" + new_content[pos:]

    # Prepend CSS if any injections
    # shared_css は WP REST API が <style> タグを除去するため本文に注入しない
    # CSSはフロントエンド(Next.js)のグローバルCSSで適用する
    # new_content = css_block + "\n" + new_content  # DISABLED: WP strips <style>

    # Add PR disclosure at end
    pr_disclosure = '\n<div class="kpj-disclosure" style="background:#fff5f7;border-radius:8px;padding:12px;margin:30px 0 20px;font-size:12px;color:#666;border-left:3px solid #FF4E6B">\n※当サイトはアフィリエイトプログラムに参加しており、リンク経由の商品購入により当サイトに収益が発生する場合があります。\n</div>'
    if "kpj-disclosure" not in new_content:
        new_content += pr_disclosure

    result["status"] = "success"
    result["reason"] = "injected"

    # 11. Update post (or dry-run)
    if dry_run:
        result["status"] = "dry_run"
        print(f"[DRY-RUN] Post {post_id}: would inject {result['injected_positions']}")
    else:
        if wp_update_content(post_id, new_content):
            result["status"] = "success"
            log_result(result)
        else:
            result["status"] = "error"
            result["reason"] = "update_failed"
            queue_for_review(result)

    return result


def log_result(result: dict):
    """Append result to JSONL log."""
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def queue_for_review(result: dict):
    """Add failed injection to review queue."""
    with open(REVIEW_QUEUE, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def batch_inject(dry_run: bool = False, limit: int = 50):
    """Inject CTA into all new posts since cutoff date."""
    # Fetch recent posts after cutoff
    endpoint = f"posts?after={CUTOFF_DATE}&per_page={limit}&orderby=date&order=desc&status=publish&_fields=id,date"
    posts = wp_get(endpoint)
    if not posts:
        print("[INFO] No new posts found or API error")
        return

    print(f"[INFO] Found {len(posts)} posts after {CUTOFF_DATE}")
    results = {"success": 0, "skipped": 0, "error": 0}
    for post in posts:
        pid = post["id"]
        r = inject_hybrid_cta(pid, dry_run=dry_run)
        print(f"  Post {pid}: {r['status']} ({r.get('reason', '')})")
        if r["status"] in ("success", "dry_run"):
            results["success"] += 1
        elif r["status"] == "skipped":
            results["skipped"] += 1
        else:
            results["error"] += 1

    print(f"\n[SUMMARY] success={results['success']} skipped={results['skipped']} error={results['error']}")


def main():
    parser = argparse.ArgumentParser(description="Phase 30: Hybrid CTA Injector for new posts")
    parser.add_argument("post_id", nargs="?", type=int, help="Single post ID to inject")
    parser.add_argument("--batch", action="store_true", help="Process all new posts since 2026-05-04")
    parser.add_argument("--dry-run", action="store_true", help="Preview without updating")
    parser.add_argument("--limit", type=int, default=50, help="Batch limit")
    args = parser.parse_args()

    if args.batch:
        batch_inject(dry_run=args.dry_run, limit=args.limit)
    elif args.post_id:
        result = inject_hybrid_cta(args.post_id, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
