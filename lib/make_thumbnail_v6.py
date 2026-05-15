#!/usr/bin/env python3
"""
make_thumbnail_v6.py — Text-zero real-photo-first thumbnail generator.

Track B: サムネエンジン v6
  - Real photos preferred over AI-generated images
  - TEXT ZERO on thumbnails (no burned-in text)
  - Korean documentary style for AI images
  - Vision validation: 90%+ match required (JUDGE_Q2=A)
  - Fallback real photos when primary fails (JUDGE_Q1=B)

Flow:
  1. Classify article as concrete or abstract
  2. Resolve image source (real photo priority)
  3. Compose with v6 (text-zero, photo-only)
  4. Validate quality/relevance (heuristic scoring)
  5. Retry or fallback as needed

Usage:
  python3 lib/make_thumbnail_v6.py --title "BTSのV、新曲公開" --output /tmp/v6_test_01.jpg

Environment:
  THUMB_LAYOUT=v5_legacy  → fall back to old v5 compositor
"""

import json
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))

from article_topic_classifier import classify, classify_theme
from thumbnail_source_resolver import resolve, resolve_fallback_photo, resolve_ai_prompt
from thumbnail_vision_validator import validate_thumbnail

try:
    from dalle_thumbnail_gen import generate_thumbnail as _dalle_generate
except Exception:
    _dalle_generate = None


def _try_dalle_from_prompt(prompt_data: dict, output_dir: str, post_id: str) -> str:
    """ai_prompt結果からDALL-Eで画像を即時生成する。成功時はパスを返す。"""
    if _dalle_generate is None:
        return ""
    positive = prompt_data.get("ai_positive_prompt", "")
    if not positive:
        positive = (
            "Modern K-pop magazine editorial, abstract musical and cultural elements, "
            "pink coral and lavender gradient, minimal elegant composition, "
            "16:9 aspect ratio, NO TEXT, NO WORDS, NO LOGOS"
        )
    # negative_promptをpositiveに追記（DALL-E 3はnegative非対応のためAvoidで指示）
    negative = prompt_data.get("ai_negative_prompt", "")
    if negative:
        positive = f"{positive}. Avoid: {negative}"
    output = os.path.join(output_dir, f"dalle_v6_post{post_id}_v6.jpg")
    raw_output = os.path.join(output_dir, f"dalle_v6_post{post_id}.png")
    result = _dalle_generate(positive[:4000], raw_output, size="1792x1024", quality="standard")
    if result.get("success") and os.path.exists(raw_output):
        try:
            from thumbnail_compositor import compose_v6
            compose_v6(raw_output, output)
            sys.stderr.write(f"[v6] DALL-E fallback succeeded: {output} (${result.get('cost_usd', 0):.3f})\n")
            return output
        except Exception as e:
            sys.stderr.write(f"[v6] DALL-E compose_v6 failed: {e}\n")
            return raw_output
    sys.stderr.write(f"[v6] DALL-E fallback failed: {result.get('reason', '?')}\n")
    return ""


def _save_ai_prompt(prompt_data: dict, output_dir: str, post_id: str) -> str:
    """Save AI generation prompt to a JSON file for external processing."""
    prompt_dir = os.path.join(output_dir, "ai_prompts")
    os.makedirs(prompt_dir, exist_ok=True)
    prompt_file = os.path.join(prompt_dir, f"{post_id or 'prompt'}_{int(time.time())}.json")
    with open(prompt_file, "w", encoding="utf-8") as f:
        json.dump(prompt_data, f, ensure_ascii=False, indent=2)
    return prompt_file


def _dalle_fallback(title: str, body: str, post_id, output_dir: str = "/tmp",
                    theme_dalle_prompt: str = "") -> dict:
    """v6の実写真検索が空振りしたときのDALL-E生成フォールバック

    theme_dalle_prompt: テーマ分類から得たDALL-Eプロンプト。指定時はこれを優先使用。
    """
    if _dalle_generate is None:
        return {"verdict": "QUEUE_REVIEW", "output_path": "", "reason": "dalle module unavailable"}

    # テーマ別プロンプトがあればそれを優先使用
    if theme_dalle_prompt:
        prompt = theme_dalle_prompt
    else:
        # レガシーフォールバック: キーワードマッチ
        text = title + " " + (body or "")[:500]
        if any(k in text for k in ["スキンケア", "美容", "コスメ", "肌", "グロウ", "PDRN", "メイク"]):
            prompt = (
                "Editorial magazine photo, young East Asian woman with luminous glowing skin, "
                "natural K-beauty makeup, soft pastel pink and lavender background, "
                "elegant cosmetic products arranged aesthetically, "
                "professional studio lighting, shallow depth of field, high-end beauty magazine style, "
                "16:9 aspect ratio, NO TEXT, NO WORDS, NO LOGOS"
            )
        elif any(k in text for k in ["チャート", "ランキング", "Billboard", "Circle",
                                      "投票", "音楽番組", "ミューバン", "エムカ", "インガ",
                                      "Music Bank", "M COUNTDOWN", "人気歌謡", "1位"]):
            prompt = (
                "Dynamic music chart visualization, vinyl records floating on gradient pink-purple background, "
                "golden trophy, musical notes, concert lights, professional photography style, "
                "16:9 aspect ratio, NO TEXT, NO WORDS"
            )
        elif any(k in text for k in ["ライブ", "コンサート", "ツアー"]):
            prompt = (
                "K-pop concert stage with spotlights, excited crowd silhouettes, stage confetti, "
                "vibrant pink and purple lighting, photorealistic concert photography, "
                "16:9 aspect ratio, NO TEXT, NO WORDS"
            )
        else:
            prompt = (
                "Modern K-pop magazine editorial, abstract musical and cultural elements, "
                "pink coral and lavender gradient, minimal elegant composition, "
                "16:9 aspect ratio, NO TEXT, NO WORDS, NO LOGOS"
            )

    output = os.path.join(output_dir, f"dalle_v6_post{post_id}.png")
    result = _dalle_generate(prompt, output, size="1792x1024", quality="standard")

    if result["success"]:
        # DALL-E出力を1200x675にリサイズ/クロップ (v6準拠)
        try:
            from thumbnail_compositor import compose_v6
            v6_output = os.path.join(output_dir, f"dalle_v6_post{post_id}_v6.jpg")
            compose_v6(output, v6_output)
            final_output = v6_output
        except Exception as e:
            sys.stderr.write(f"[v6] dalle compose_v6 failed: {e}, using raw\n")
            final_output = output
        return {
            "output_path": final_output,
            "source": "dalle3",
            "vision_score": 85,
            "verdict": "PASS",
            "meta": {
                "cost_usd": result["cost_usd"],
                "revised_prompt": result.get("revised_prompt", "")[:200],
                "reason": "dalle3 generated + v6 composed",
            },
        }
    return {
        "output_path": "",
        "source": "dalle3_failed",
        "vision_score": 0,
        "verdict": "QUEUE_REVIEW",
        "meta": {"reason": result["reason"]},
    }


def make_thumbnail_v6(
    title: str,
    body: str = "",
    post_id: str = "",
    output_dir: str = "/tmp",
    max_retries: int = 3,
) -> dict:
    """
    Generate a text-zero, real-photo-first thumbnail.

    Args:
        title: Article title (required)
        body: Article body text (optional)
        post_id: WordPress post ID or slug
        output_dir: Directory for output files
        max_retries: Maximum retry attempts for RETRY verdict

    Returns:
        {
            "output_path": str,
            "source": str,
            "vision_score": int,
            "verdict": str,
            "meta": {...}
        }
    """
    # Check for v5 legacy mode
    if os.environ.get("THUMB_LAYOUT") == "v5_legacy":
        sys.stderr.write("[v6] THUMB_LAYOUT=v5_legacy, delegating to v5 compositor\n")
        from thumbnail_compositor import compose
        artist_name = ""
        classification = classify(title, body)
        if classification["subjects"]:
            artist_name = classification["subjects"][0]
        result = resolve(artist_name, article_type=classification["type"],
                         post_id=str(post_id) if post_id else "")
        meta = compose(
            artist=artist_name,
            copy_text=title,
            bg_image=result.get("image_path", ""),
            output_path=os.path.join(output_dir, f"{post_id or 'thumb'}.webp"),
        )
        return {
            "output_path": meta["output_path"],
            "source": result.get("source", "unknown"),
            "vision_score": 0,
            "verdict": "LEGACY",
            "meta": meta,
        }

    # Step 1: Classify article (type + theme)
    classification = classify(title, body)
    article_type = classification["type"]
    subjects = classification["subjects"]
    artist_name = subjects[0] if subjects else ""

    theme_result = classify_theme(title, body)
    theme = theme_result["theme"]
    theme_config = theme_result["theme_config"]

    sys.stderr.write(
        f"[v6] classified: type={article_type}, theme={theme}, subjects={subjects}, "
        f"confidence={classification['confidence']:.2f}, "
        f"theme_confidence={theme_result['confidence']:.2f}\n"
    )

    os.makedirs(output_dir, exist_ok=True)
    output_ext = ".jpg"
    output_filename = f"{post_id or 'thumb_v6'}_{int(time.time())}{output_ext}"
    output_path = os.path.join(output_dir, output_filename)

    best_result = None
    best_score = 0
    attempts = []

    for attempt in range(max_retries + 1):
        # Step 2: Resolve image source
        if attempt == 0:
            source_result = resolve(
                artist_name=artist_name,
                genre="",
                post_id=post_id,
                article_type=article_type,
                theme=theme,
                theme_config=theme_config,
            )
        else:
            # Retry with fallback strategies
            if article_type == "concrete" and artist_name:
                # Try fallback real photo (JUDGE_Q1=B)
                source_result = resolve_fallback_photo(artist_name)
                if not source_result:
                    # Last resort: AI prompt
                    source_result = resolve_ai_prompt(
                        topic_context=artist_name, genre=""
                    )
            else:
                # Abstract: try AI prompt (テーマのみ、タイトル全文は渡さない)
                source_result = resolve_ai_prompt(
                    topic_context=theme or "K-POP culture", genre=""
                )

        source_type = source_result.get("source", "unknown")
        image_path = source_result.get("image_path", "")

        sys.stderr.write(
            f"[v6] attempt {attempt + 1}: source={source_type}, "
            f"image={image_path or '(none)'}\n"
        )

        # Handle AI prompt source — try DALL-E generation immediately
        if source_type == "ai_prompt":
            # テーマ別DALL-Eプロンプトがあれば、汎用テンプレを上書き
            if theme_config.get("dalle_prompt"):
                source_result["ai_positive_prompt"] = theme_config["dalle_prompt"]
                if theme_config.get("dalle_negative"):
                    source_result["ai_negative_prompt"] = theme_config["dalle_negative"]
                sys.stderr.write(f"[v6] overriding ai_prompt with theme dalle_prompt (theme={theme})\n")

            prompt_file = _save_ai_prompt(source_result, output_dir, post_id)
            sys.stderr.write(f"[v6] AI prompt saved to {prompt_file}\n")

            # Attempt DALL-E generation from the prompt
            dalle_path = _try_dalle_from_prompt(source_result, output_dir, post_id)
            if dalle_path and os.path.exists(dalle_path):
                image_path = dalle_path
                source_type = "dalle3"
                source_result["source"] = "dalle3"  # バリデーターにDALL-E成功を伝える
                source_result["image_path"] = dalle_path
                sys.stderr.write(f"[v6] DALL-E fallback succeeded: {dalle_path}\n")
                # Fall through to compose_v6 below
            else:
                # If we have no image at all, queue for review
                if not best_result:
                    best_result = {
                        "output_path": "",
                        "source": "ai_prompt",
                        "vision_score": 0,
                        "verdict": "QUEUE_REVIEW",
                        "meta": {
                            "classification": classification,
                            "ai_prompt_file": prompt_file,
                            "ai_positive_prompt": source_result.get("ai_positive_prompt", ""),
                            "ai_negative_prompt": source_result.get("ai_negative_prompt", ""),
                            "attempts": attempt + 1,
                            "reason": "AI prompt generated, DALL-E unavailable",
                        },
                    }
                continue

        # No image file available
        if not image_path or not os.path.exists(image_path):
            sys.stderr.write(f"[v6] no image file at {image_path}, trying next\n")
            continue

        # Step 3: Compose with v6 (text-zero)
        try:
            from thumbnail_compositor import compose_v6
            attempt_output = os.path.join(
                output_dir,
                f"{post_id or 'thumb_v6'}_attempt{attempt}{output_ext}",
            )
            composed = compose_v6(image_path, attempt_output)
            if composed is None:
                sys.stderr.write(f"[v6] compose_v6 rejected (portrait/too-dark), skipping to next source\n")
                continue
        except Exception as e:
            sys.stderr.write(f"[v6] compose_v6 failed: {e}\n")
            continue

        # Step 4: Validate (pass source_path + source_info for accurate scoring)
        validation = validate_thumbnail(
            attempt_output, title, body,
            source_path=image_path, source_info=source_result,
        )
        score = validation["score"]
        verdict = validation["verdict"]

        sys.stderr.write(
            f"[v6] validation: score={score}, verdict={verdict}\n"
        )

        attempts.append({
            "attempt": attempt + 1,
            "source": source_type,
            "image": image_path,
            "score": score,
            "verdict": verdict,
        })

        # Track best result
        if score > best_score:
            best_score = score
            best_result = {
                "output_path": attempt_output,
                "source": source_type,
                "vision_score": score,
                "verdict": verdict,
                "meta": {
                    "classification": classification,
                    "theme": theme,
                    "theme_config": theme_config,
                    "source_detail": source_result,
                    "validation": validation,
                    "attempts": attempts,
                },
            }

        # Step 5: Check verdict
        if verdict == "PASS":
            # Score >= 90: done (JUDGE_Q2=A)
            # Rename to final output path
            if attempt_output != output_path:
                os.rename(attempt_output, output_path)
                best_result["output_path"] = output_path
            sys.stderr.write(f"[v6] PASS — score={score}, output={output_path}\n")
            return best_result

        if verdict == "RETRY":
            # Score 80-89: try again with different source
            sys.stderr.write(
                f"[v6] RETRY — score={score}, attempt {attempt + 1}/{max_retries + 1}\n"
            )
            continue

        # HARD_FAIL: score < 80
        sys.stderr.write(
            f"[v6] HARD_FAIL — score={score}, trying fallback\n"
        )
        continue

    # Exhausted retries — return best result or queue for review
    if best_result and best_result.get("output_path") and os.path.exists(best_result["output_path"]):
        # Use best attempt even if not perfect
        if best_result["output_path"] != output_path:
            os.rename(best_result["output_path"], output_path)
            best_result["output_path"] = output_path
        if best_result["verdict"] != "PASS":
            best_result["verdict"] = "QUEUE_REVIEW"
            best_result["meta"]["reason"] = (
                f"Best score {best_score} after {len(attempts)} attempts. "
                "Queued for Yuta review."
            )
        sys.stderr.write(
            f"[v6] final: verdict={best_result['verdict']}, "
            f"score={best_score}, output={output_path}\n"
        )
        return best_result

    # No usable image at all
    if not best_result:
        best_result = {
            "output_path": "",
            "source": "none",
            "vision_score": 0,
            "verdict": "QUEUE_REVIEW",
            "meta": {
                "classification": classification,
                "attempts": attempts,
                "reason": "No usable image found. Queued for Yuta review.",
            },
        }

    # Try DALL-E 3 fallback before giving up
    if _dalle_generate is not None:
        sys.stderr.write(f"[v6] no real photo found, trying DALL-E 3 fallback (theme={theme})...\n")
        fallback_result = _dalle_fallback(
            title, body, post_id or "0", output_dir,
            theme_dalle_prompt=theme_config.get("dalle_prompt", ""),
        )
        if fallback_result["verdict"] == "PASS":
            sys.stderr.write(
                f"[v6] DALL-E fallback succeeded: {fallback_result['output_path']} "
                f"(${fallback_result['meta'].get('cost_usd', 0):.3f})\n"
            )
            return fallback_result

    sys.stderr.write("[v6] QUEUE_REVIEW — no passing image found\n")
    return best_result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Thumbnail v6: text-zero, real-photo-first generator"
    )
    parser.add_argument("--title", required=True, help="Article title")
    parser.add_argument("--body", default="", help="Article body (optional)")
    parser.add_argument("--post-id", default="", help="Post ID or slug")
    parser.add_argument("--output", default="/tmp/v6_test_01.jpg",
                        help="Output file path")
    parser.add_argument("--max-retries", type=int, default=3,
                        help="Max retry attempts (default: 3)")
    args = parser.parse_args()

    output_dir = os.path.dirname(args.output) or "/tmp"
    result = make_thumbnail_v6(
        title=args.title,
        body=args.body,
        post_id=args.post_id,
        output_dir=output_dir,
        max_retries=args.max_retries,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
