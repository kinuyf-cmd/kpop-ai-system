#!/usr/bin/env python3
"""Task E: 既存4記事のCTAを最強CTA Phase 30版に置換"""
import json
import hashlib
import re
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cta.new_post_injector import (
    get_post_data, wp_update_content, classify_for_hybrid,
    get_programs_for_position, find_h2_positions,
    build_hybrid_html, load_banners, load_templates,
    CUTOFF_DATE
)

JST = timezone(timedelta(hours=9))
TARGET_IDS = [14991, 17060, 16993, 17054]


def strip_old_cta(content: str) -> str:
    """Remove all old hybrid CTA blocks from content."""
    # Remove kpj-hybrid-cta divs
    content = re.sub(
        r'<div\s+class="kpj-hybrid-cta[^"]*"[^>]*>.*?</div>\s*(?:</div>)*',
        '', content, flags=re.DOTALL
    )
    # Remove kpj-strongest-phase30 divs (in case of double-run)
    content = re.sub(
        r'<div\s+class="kpj-strongest-phase30[^"]*"[^>]*>.*?</div>\s*(?:</div>)*',
        '', content, flags=re.DOTALL
    )
    # More precise: remove blocks by data-cta-position marker
    content = re.sub(
        r'\n?<div[^>]*data-cta-position="[^"]*"[^>]*>.*?</div>\s*(?:</div>)*\s*(?:</div>)*\n?',
        '', content, flags=re.DOTALL
    )
    # Remove old PR disclosure
    content = re.sub(
        r'\n?<div\s+class="kpj-disclosure"[^>]*>.*?</div>\n?',
        '', content, flags=re.DOTALL
    )
    # Clean up multiple blank lines
    content = re.sub(r'\n{3,}', '\n\n', content)
    return content.strip()


def process_article(post_id: int, dry_run: bool = False) -> dict:
    """Replace CTA for a single article."""
    result = {
        "post_id": post_id,
        "status": "pending",
        "md5_before": "",
        "md5_after": "",
        "positions_injected": [],
    }

    # Fetch current content
    post = get_post_data(post_id)
    if not post:
        result["status"] = "error"
        result["reason"] = "fetch_failed"
        return result

    old_content = post["content"]
    result["md5_before"] = hashlib.md5(old_content.encode()).hexdigest()

    # Strip all old CTAs
    clean_content = strip_old_cta(old_content)

    # Re-classify and inject new CTA
    genre = classify_for_hybrid(post["title"], post["category_names"], post["tag_names"])
    result["genre"] = genre

    banners = load_banners()
    templates = load_templates()

    plain_text = re.sub(r'<[^>]+>', '', clean_content)
    content_length = len(plain_text)
    result["content_length"] = content_length

    programs_top = get_programs_for_position(genre, "position_top")
    programs_mid = get_programs_for_position(genre, "position_middle")
    programs_bot = get_programs_for_position(genre, "position_bottom")

    h2_positions = find_h2_positions(clean_content)
    new_content = clean_content
    injections = []

    # position_top
    if content_length >= 2500 and h2_positions:
        main_key = programs_top.get("main")
        if main_key and main_key in banners:
            prog = banners[main_key]
            if prog.get("size_limitation") == "only_300x250":
                main_key = programs_top.get("fallback")
            if main_key and main_key in banners:
                top_html = build_hybrid_html(main_key, "position_top", banners, templates)
                if top_html:
                    injections.append((h2_positions[0], top_html))
                    result["positions_injected"].append("top")

    # position_middle
    if content_length >= 2500 and len(h2_positions) >= 3:
        mid_idx = 3 if len(h2_positions) >= 4 else 2
        main_key = programs_mid.get("main")
        if main_key and main_key in banners:
            mid_html = build_hybrid_html(main_key, "position_middle", banners, templates)
            if mid_html:
                injections.append((h2_positions[mid_idx], mid_html))
                result["positions_injected"].append("middle")

    # position_bottom
    main_key = programs_bot.get("main")
    if main_key and main_key in banners:
        bot_html = build_hybrid_html(main_key, "position_bottom", banners, templates)
        if bot_html:
            injections.append((len(new_content), bot_html))
            result["positions_injected"].append("bottom")

    # Apply injections
    injections.sort(key=lambda x: x[0], reverse=True)
    for pos, html in injections:
        new_content = new_content[:pos] + "\n" + html + "\n" + new_content[pos:]

    # PR disclosure
    pr_disclosure = '\n<div class="kpj-disclosure" style="background:#fff5f7;border-radius:8px;padding:12px;margin:30px 0 20px;font-size:12px;color:#666;border-left:3px solid #FF4E6B">\n※当サイトはアフィリエイトプログラムに参加しており、リンク経由の商品購入により当サイトに収益が発生する場合があります。\n</div>'
    if "kpj-disclosure" not in new_content:
        new_content += pr_disclosure

    result["md5_after"] = hashlib.md5(new_content.encode()).hexdigest()

    if dry_run:
        result["status"] = "dry_run"
        print(f"[DRY-RUN] Post {post_id}: {result['positions_injected']}, genre={genre}")
        # Show a snippet of generated HTML
        for pos in result["positions_injected"]:
            marker = f'data-cta-position="{pos}"'
            if marker in new_content:
                idx = new_content.index(marker)
                print(f"  {pos}: ...{new_content[max(0,idx-30):idx+60]}...")
    else:
        if wp_update_content(post_id, new_content):
            result["status"] = "success"
            print(f"[OK] Post {post_id}: replaced with strongest CTA Phase 30 ({result['positions_injected']})")
        else:
            result["status"] = "error"
            result["reason"] = "update_failed"
            print(f"[ERROR] Post {post_id}: update failed")

    return result


def main():
    dry_run = "--dry-run" in sys.argv
    results = []

    for pid in TARGET_IDS:
        r = process_article(pid, dry_run=dry_run)
        results.append(r)

    # Summary
    print("\n=== SUMMARY ===")
    for r in results:
        print(f"  Post {r['post_id']}: {r['status']} | md5 {r['md5_before'][:8]}→{r['md5_after'][:8]} | positions: {r.get('positions_injected', [])}")

    # Save results
    outpath = "/home/aiuser/kpop-ai-system/cta/verification/replace_results_20260506.json"
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now(JST).isoformat(),
            "dry_run": dry_run,
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to {outpath}")


if __name__ == "__main__":
    main()
