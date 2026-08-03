#!/usr/bin/env python3
"""new_post_injector.py — J-4 最強CTA(Phase 30版)自動配置 [stg移植版]

origin/main から rebuild ブランチへ移植。主な変更点:
  - 投稿先URL/認証は lib/revenue/settings 経由(env SITE_URL 優先、既定は stg)。
    ハードコードの本番URL既定を撤去。
  - cutoff_date / min_length / max_cta は config/revenue/revenue_settings.json から。
  - WP認証(WP_USER/WP_PASS)は .env 参照のまま(平文ハードコードなし)。
  - 配信は本番化Phase C-7開始。それまでは stg で --dry-run 確認に使う。

フロー:
  1. WP REST APIで投稿のcategory/tag/title/content取得
  2. 文字数カウント
  3. hybrid_banner_matrixでメイン/サブ案件決定(lib.revenue.genre_classifier)
  4. min_length以上ならH2位置検出
  5. 最強CTA 8ブロックHTML生成 (A8素材改変禁止)
  6. WP REST APIでpost.content更新(--dry-run で更新せず確認)

使い方:
  python3 cta/new_post_injector.py <post_id>
  python3 cta/new_post_injector.py --batch
  python3 cta/new_post_injector.py --dry-run <post_id>
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from lib.revenue import settings  # noqa: E402

CTA_DIR = BASE / "cta"
CONFIG_DIR = BASE / "config" / "affiliate"
LOGS = BASE / "logs"
LOG_FILE = LOGS / "hybrid_cta_inject.jsonl"
REVIEW_QUEUE = BASE / "data" / "cta_review_queue.jsonl"
JST = timezone(timedelta(hours=9))

# WP Auth — env 参照(.env)。ハードコードの本番URL既定は撤去し、settings 経由(既定 stg)。
try:
    from dotenv import dotenv_values
    ENV = dotenv_values(str(BASE / ".env"))
except Exception:
    ENV = {}
WP_USER = ENV.get("WP_USER", "")
WP_PASS = ENV.get("WP_PASS", "")
SITE_URL = settings.site_url()  # env SITE_URL > config(既定 stg)
WP_API = f"{SITE_URL}/wp-json/wp/v2"
AUTH_HEADER = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()

# config 由来(ハードコード回避)
CUTOFF_DATE = settings.cta_cutoff_date()
MIN_LENGTH = settings.cta_min_length()

# Markers to avoid double-injection
HYBRID_MARKER = 'data-cta-position="'
STRONGEST_MARKER = 'kpj-strongest-phase30'


def load_banners() -> dict:
    """バナー素材。提携終了した案件は除外して返す。

    終了案件を貼り続けると A8 で無効クリック扱いになり収益ゼロ + 死んだ導線に
    なる(2026-08-03 DHOLIC 他で発生)。判定は genre_classifier に一本化。
    """
    from lib.revenue.genre_classifier import is_active_program
    with open(settings.a8_banners_path()) as f:
        programs = json.load(f)["programs"]
    return {k: v for k, v in programs.items() if is_active_program(v)}


def load_templates() -> dict:
    with open(CTA_DIR / "cta_strongest_phase30_templates.json") as f:
        return json.load(f)


def load_strongest_data() -> dict:
    with open(CTA_DIR / "cta_strongest_phase30_data.json") as f:
        return json.load(f)


def load_genre_map() -> tuple[dict, dict]:
    with open(settings.a8_genre_map_path()) as f:
        data = json.load(f)
    return data.get("hybrid_banner_matrix", {}), data.get("hybrid_defaults", {})


def wp_get(endpoint: str) -> dict | None:
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
    data = wp_get(f"posts/{post_id}?context=edit&_fields=id,title,content,categories,tags,date,status")
    if not data:
        return None
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
    """ジャンル判定は lib.revenue.genre_classifier に委譲(二重実装回避)。"""
    from lib.revenue.genre_classifier import classify_genre
    return classify_genre(title, category_names, tag_names)


def get_programs_for_position(genre: str, position: str) -> dict:
    matrix, defaults = load_genre_map()
    if genre in matrix:
        pos_data = matrix[genre].get(position, {})
    else:
        pos_data = defaults.get(position, {})
    return pos_data


def find_h2_positions(content: str) -> list[int]:
    return [m.start() for m in re.finditer(r'<h2[^>]*>', content, re.IGNORECASE)]


def _build_benefits_html(benefits: list) -> str:
    icons = ["✨", "🎯", "💡", "🎁"]
    items = []
    for i, b in enumerate(benefits[:4]):
        icon = icons[i % len(icons)]
        items.append(f'<div class="kpj-benefit-item"><span class="kpj-benefit-icon">{icon}</span>{b}</div>')
    return "\n".join(items)


def build_hybrid_html(program_key: str, position: str, banners: dict,
                      templates: dict, sub_key: str = None) -> str:
    program = banners.get(program_key)
    if not program:
        return ""
    pos_template = templates["positions"].get(position)
    if not pos_template:
        return ""
    strongest = load_strongest_data()
    prog_data = strongest.get("programs", {}).get(program_key, {})
    if not prog_data:
        return ""
    trust_badges = templates.get("trust_badges_html", "")
    click_base = settings.a8_click_base_url()

    if position == "position_top":
        sizes = program.get("sizes") or {}
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
        html = html.replace("{{click_url}}", f"{click_base}?a8mat={click_a8mat}")
        html = html.replace("{{trust_badges}}", trust_badges)
        return html

    elif position == "position_middle":
        sizes = program.get("sizes") or {}
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
        html = html.replace("{{click_url}}", f"{click_base}?a8mat={size_data['a8mat']}")
        html = html.replace("{{button_text}}", prog_data.get("button_text", program["button_text"]))
        return html

    elif position == "position_bottom":
        sizes_main = program.get("sizes") or {}
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
        html = html.replace("{{click_url}}", f"{click_base}?a8mat={main_300['a8mat']}")
        html = html.replace("{{button_text}}", prog_data.get("button_text", program["button_text"]))
        html = html.replace("{{trust_badges}}", trust_badges)
        return html

    return ""


def inject_hybrid_cta(post_id: int, dry_run: bool = False) -> dict:
    result = {
        "post_id": post_id,
        "status": "skipped",
        "reason": "",
        "injected_positions": [],
        "site_url": SITE_URL,
        "timestamp": datetime.now(JST).isoformat(),
    }

    post = get_post_data(post_id)
    if not post:
        result["status"] = "error"
        result["reason"] = "fetch_failed"
        return result

    if post["date"] < CUTOFF_DATE:
        result["reason"] = "before_cutoff"
        return result

    content = post["content"]
    if HYBRID_MARKER in content or STRONGEST_MARKER in content:
        result["reason"] = "already_injected"
        return result

    if post["status"] != "publish":
        result["reason"] = f"status_{post['status']}"
        return result

    genre = classify_for_hybrid(post["title"], post["category_names"], post["tag_names"])
    result["genre"] = genre

    banners = load_banners()
    templates = load_templates()

    plain_text = re.sub(r'<[^>]+>', '', content)
    content_length = len(plain_text)
    result["content_length"] = content_length

    programs_top = get_programs_for_position(genre, "position_top")
    programs_mid = get_programs_for_position(genre, "position_middle")
    programs_bot = get_programs_for_position(genre, "position_bottom")

    h2_positions = find_h2_positions(content)
    new_content = content
    injections = []

    if content_length >= MIN_LENGTH and h2_positions:
        main_key = programs_top.get("main")
        if main_key and main_key in banners:
            prog = banners[main_key]
            if prog.get("size_limitation") == "only_300x250":
                main_key = programs_top.get("fallback")
            if main_key and main_key in banners:
                top_html = build_hybrid_html(main_key, "position_top", banners, templates)
                if top_html:
                    injections.append((h2_positions[0], top_html))
                    result["injected_positions"].append("top")

    if content_length >= MIN_LENGTH and len(h2_positions) >= 3:
        mid_idx = 3 if len(h2_positions) >= 4 else 2
        main_key = programs_mid.get("main")
        if main_key and main_key in banners:
            mid_html = build_hybrid_html(main_key, "position_middle", banners, templates)
            if mid_html:
                injections.append((h2_positions[mid_idx], mid_html))
                result["injected_positions"].append("middle")

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

    injections.sort(key=lambda x: x[0], reverse=True)
    for pos, html in injections:
        new_content = new_content[:pos] + "\n" + html + "\n" + new_content[pos:]

    # PR表記(景表法/ステマ規制対応)
    pr_disclosure = (
        '\n<div class="kpj-disclosure" style="background:#fff5f7;border-radius:8px;padding:12px;'
        'margin:30px 0 20px;font-size:12px;color:#666;border-left:3px solid #FF4E6B">\n'
        '※当サイトはアフィリエイトプログラムに参加しており、リンク経由の商品購入により当サイトに収益が発生する場合があります。\n</div>'
    )
    if "kpj-disclosure" not in new_content:
        new_content += pr_disclosure

    result["status"] = "success"
    result["reason"] = "injected"

    if dry_run:
        result["status"] = "dry_run"
        print(f"[DRY-RUN] Post {post_id} @ {SITE_URL}: would inject {result['injected_positions']}")
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
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def queue_for_review(result: dict):
    REVIEW_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    with open(REVIEW_QUEUE, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def batch_inject(dry_run: bool = False, limit: int = 50):
    endpoint = f"posts?after={CUTOFF_DATE}&per_page={limit}&orderby=date&order=desc&status=publish&_fields=id,date"
    posts = wp_get(endpoint)
    if not posts:
        print("[INFO] No new posts found or API error")
        return
    print(f"[INFO] {SITE_URL}: {len(posts)} posts after {CUTOFF_DATE}")
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
    parser = argparse.ArgumentParser(description="J-4 Hybrid CTA Injector (stg移植版)")
    parser.add_argument("post_id", nargs="?", type=int, help="Single post ID to inject")
    parser.add_argument("--batch", action="store_true", help="Process all new posts since cutoff")
    parser.add_argument("--dry-run", action="store_true", help="Preview without updating")
    parser.add_argument("--limit", type=int, default=50, help="Batch limit")
    args = parser.parse_args()

    print(f"[CONFIG] target={SITE_URL} cutoff={CUTOFF_DATE} min_len={MIN_LENGTH} "
          f"auth={'set' if (WP_USER and WP_PASS) else 'MISSING(.env)'}", file=sys.stderr)

    if args.batch:
        batch_inject(dry_run=args.dry_run, limit=args.limit)
    elif args.post_id:
        result = inject_hybrid_cta(args.post_id, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
