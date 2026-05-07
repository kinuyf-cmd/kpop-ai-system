#!/usr/bin/env python3
"""
thumbnail_vision_validator.py — Heuristic thumbnail quality/relevance validator.

Scoring (0-100):
  - Image dimensions closeness to 1200x630 ideal: up to +20
  - File size quality (larger = better detail): up to +20
  - Artist/keyword match in filename: up to +30
  - Source type bonus (real_photo > ai_generated > gradient_fallback): up to +30

Verdict:
  90+     → PASS    (JUDGE_Q2=A)
  80-89   → RETRY   (try different source)
  <80     → HARD_FAIL (fallback to real photo, JUDGE_Q1=B)

Note: Real Vision API call (GPT-4o) is expensive, so this version uses
heuristic scoring. A future version can add actual vision validation.

Usage:
  python3 lib/thumbnail_vision_validator.py --image /path/to/img.jpg --title "BTS新曲"
"""

import json
import os
import re
import sys
from pathlib import Path


def _score_dimensions(width: int, height: int) -> int:
    """Score based on closeness to ideal dimensions. Max 20.

    Accepts both 1200x630 (OG standard) and 1200x675 (16:9 v6) as ideal.
    """
    # 縦長画像は即NG (height > width)
    if height == 0:
        return 0
    if height > width:
        return 0  # portrait image → score 0 → HARD_FAIL
    actual_ratio = width / height
    # 2つの理想比率のうち近い方を使う
    ratio_og = 1200 / 630    # 1.905 (OG image standard)
    ratio_16_9 = 1200 / 675  # 1.778 (16:9 v6)
    ideal_ratio = ratio_og if abs(actual_ratio - ratio_og) < abs(actual_ratio - ratio_16_9) else ratio_16_9
    ratio_diff = abs(actual_ratio - ideal_ratio) / ideal_ratio

    # Size match (minimum: 1200x630 or equivalent)
    size_score = 0
    if width >= 1200 and height >= 630:
        size_score = 10  # Full marks for meeting minimum
    elif width >= 800 and height >= 420:
        size_score = 6
    elif width >= 600 and height >= 300:
        size_score = 3
    else:
        size_score = 0

    # Ratio match
    ratio_score = 0
    if ratio_diff < 0.05:
        ratio_score = 10
    elif ratio_diff < 0.15:
        ratio_score = 7
    elif ratio_diff < 0.30:
        ratio_score = 4
    else:
        ratio_score = 1

    return size_score + ratio_score


def _score_file_size(file_size_bytes: int) -> int:
    """Score based on file size (proxy for image quality). Max 20."""
    kb = file_size_bytes / 1024
    if kb >= 200:
        return 20
    elif kb >= 100:
        return 15
    elif kb >= 50:
        return 10
    elif kb >= 10:
        return 5
    else:
        return 0


def _score_filename_match(image_path: str, title: str) -> int:
    """Score based on artist/keyword presence in filename. Max 30."""
    filename = os.path.basename(image_path).lower()
    title_lower = title.lower()

    score = 0

    # Extract potential artist names from title (ASCII words 2+ chars)
    ascii_words = re.findall(r'[A-Za-z]{2,}', title)
    for word in ascii_words:
        if word.lower() in filename:
            score += 15
            break

    # Also check slug-style overlap (artist_cache filenames like riize_e56e66f4.jpg)
    slug_parts = re.findall(r'[a-z]{3,}', filename)
    title_ascii_lower = set(w.lower() for w in re.findall(r'[A-Za-z]{3,}', title))
    for slug in slug_parts:
        if slug in title_ascii_lower or any(slug in t for t in title_ascii_lower):
            if score < 15:
                score += 15
            break

    # Check for common source prefixes indicating real photos
    if any(prefix in filename for prefix in ['wiki', 'yt_', 'unsplash', 'pexels']):
        score += 10
    elif 'ai_' in filename or 'generated' in filename:
        score += 3

    # Artist cache directory = real photo source
    if 'artist_cache' in str(image_path).lower():
        score += 5

    return min(30, score)


def _score_source_type(image_path: str) -> int:
    """Score based on detected source type. Max 30."""
    filename = os.path.basename(image_path).lower()

    path_str = str(image_path).lower()

    # Real photo sources (filename or path indicators)
    if any(s in filename for s in ['wiki', 'yt_', 'youtube', 'unsplash', 'pexels', 'real']):
        return 30  # real_photo
    # Artist cache = curated real photos
    if 'artist_cache' in path_str:
        return 30  # real_photo from cache

    # AI generated
    if any(s in filename for s in ['ai_', 'generated', 'sdxl', 'dalle', 'midjourney']):
        return 20  # ai_generated

    # Gradient fallback
    if any(s in filename for s in ['gradient', 'fallback', 'placeholder']):
        return 0  # gradient_fallback

    # Unknown source — assume moderate quality
    return 20


def _score_filename_match_from_info(source_info: dict, title: str) -> int:
    """source_info から直接スコアリング。Max 25.

    ファイル名パターン推測ではなく、resolverが返した実際のソース情報を使う。
    テーマ雰囲気画像(DALL-E/Unsplash)はアーティスト名不要でも高スコア。
    """
    source = source_info.get("source", "")
    attribution = (source_info.get("attribution", "") or "").lower()
    theme = source_info.get("theme", "")

    score = 0

    # テーマ雰囲気画像(DALL-E/Unsplash) → アーティスト名マッチ不要、テーマ指定自体が品質保証
    if source in ("dalle3", "unsplash") and theme:
        score += 18  # テーマ別プロンプト/クエリで生成 → 内容は適切
    else:
        # アーティスト写真系ソース → アーティスト名がattributionに含まれているかチェック
        title_words = re.findall(r'[A-Za-z]{2,}', title)
        for word in title_words:
            if word.lower() in attribution:
                score += 15
                break

    # ソースの信頼性ボーナス
    if source in ("youtube_official", "wikimedia", "unsplash"):
        score += 7
    elif source in ("dalle3",):
        score += 7
    elif source == "ai_prompt":
        score += 3  # 未生成
    elif source == "fallback_cache":
        score += 5

    return min(25, score)


def _score_source_type_from_info(source_info: dict) -> int:
    """source_info から直接ソースタイプスコア。Max 25."""
    source = source_info.get("source", "")

    source_scores = {
        "youtube_official": 25,  # 公式チャンネルの画像
        "wikimedia": 25,         # CC-BY ライセンス写真
        "unsplash": 25,          # ストック写真
        "dalle3": 22,            # テーマ別AI生成
        "ai_prompt": 15,         # 未生成プロンプト
        "fallback_cache": 20,    # キャッシュ画像
    }
    return source_scores.get(source, 15)


def _score_theme_relevance(image_path: str, source_info: dict) -> int:
    """Score based on theme-source alignment. Max 10.

    テーマに合ったソースから取得された画像は高スコア。
    例: concert記事でYouTubeライブ映像 → +10
        chart記事でアーティスト通常写真 → +3
    """
    theme = source_info.get("theme", "")
    source = source_info.get("source", "")
    fetch_mode = source_info.get("fetch_mode", "")

    if not theme or theme == "general":
        return 5  # テーマ不明は中立スコア

    # YouTube公式ソース: テーマに応じたfetch_modeかチェック
    if source in ("youtube_official",):
        # chart記事でviewCount順取得 = 最適
        if theme == "chart" and fetch_mode == "viewCount":
            return 10
        # comeback記事で最新動画 = 最適
        if theme == "comeback" and fetch_mode in ("date", "latest"):
            return 10
        # それ以外のYouTube = やや適合
        return 7

    # Wikimedia: アーティスト本人写真 = テーマ問わず中程度の適合
    if source == "wikimedia":
        return 6

    # Unsplash: テーマ別クエリで取得された場合は高スコア
    if source == "unsplash":
        return 8  # テーマクエリで取得済みの前提

    # DALL-E: テーマプロンプトで生成 = 高適合
    if source in ("dalle3", "ai_prompt"):
        return 8

    # fallback_cache: テーマ適合は低い（同じアーティストだが内容無関係）
    if source == "fallback_cache":
        return 3

    return 5


def validate_thumbnail(image_path: str, title: str, body: str = "", source_path: str = "",
                       source_info: dict | None = None) -> dict:
    """
    Validate a thumbnail image using heuristic scoring.

    Args:
        image_path: Path to the thumbnail image file
        title: Article title for relevance checking
        body: Article body (optional, reserved for future use)

    Returns:
        {
            "score": 0-100,
            "verdict": "PASS" | "RETRY" | "HARD_FAIL",
            "details": {
                "dimensions_score": int,
                "filesize_score": int,
                "filename_match_score": int,
                "source_type_score": int,
                "width": int,
                "height": int,
                "file_size_kb": float,
                "checks_passed": [...],
                "checks_failed": [...]
            }
        }
    """
    checks_passed = []
    checks_failed = []

    # Basic file checks
    if not os.path.exists(image_path):
        return {
            "score": 0,
            "verdict": "HARD_FAIL",
            "details": {
                "error": f"File not found: {image_path}",
                "checks_passed": [],
                "checks_failed": ["file_exists"],
            },
        }

    file_size = os.path.getsize(image_path)
    if file_size < 10 * 1024:  # < 10KB
        checks_failed.append("min_file_size (< 10KB)")
    else:
        checks_passed.append("min_file_size")

    # Try to get image dimensions
    width, height = 0, 0
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            width, height = img.size
    except ImportError:
        # PIL not available — estimate from file size
        sys.stderr.write("[validator] PIL not available, using file-size-only scoring\n")
        width, height = 1200, 630  # Assume correct if we can't check
    except Exception as e:
        checks_failed.append(f"image_open ({e})")
        return {
            "score": 0,
            "verdict": "HARD_FAIL",
            "details": {
                "error": f"Cannot open image: {e}",
                "checks_passed": checks_passed,
                "checks_failed": checks_failed,
            },
        }

    # Minimum dimensions check
    if width >= 600 and height >= 300:
        checks_passed.append("min_dimensions (600x300)")
    else:
        checks_failed.append(f"min_dimensions ({width}x{height} < 600x300)")

    # Use source_path for filename/source scoring if provided (compose_v6 creates temp files)
    scoring_path = source_path if source_path else image_path

    # --- 明るさチェック ---
    brightness_score = 0
    mean_brightness = -1
    dark_ratio = -1
    try:
        from PIL import Image as _PILImage
        import numpy as np
        with _PILImage.open(image_path) as _img:
            gray = _img.convert("L")
            arr = np.array(gray)
            mean_brightness = float(arr.mean())
            dark_ratio = float((arr < 50).sum() / arr.size)

        if dark_ratio > 0.60:
            checks_failed.append(f"brightness_critical (dark_ratio={dark_ratio:.0%})")
            brightness_score = -20  # 重いペナルティ
        elif mean_brightness < 60:
            checks_failed.append(f"brightness_low (mean={mean_brightness:.0f})")
            brightness_score = -15
        elif mean_brightness < 90:
            brightness_score = 0  # やや暗いが許容
        else:
            checks_passed.append("brightness_ok")
            brightness_score = 5  # 明るい画像にボーナス
    except Exception:
        pass  # PILやnumpyが無い場合はスキップ

    # Compute individual scores (max 20 + 20 + 25 + 25 + 10 + 5 = 105, capped at 100)
    dim_score = _score_dimensions(width, height)
    fs_score = _score_file_size(file_size)

    si = source_info or {}
    if si.get("source"):
        fn_score = _score_filename_match_from_info(si, title)
        src_score = _score_source_type_from_info(si)
    else:
        fn_score = min(25, _score_filename_match(scoring_path, title))
        src_score = min(25, _score_source_type(scoring_path))

    theme_score = _score_theme_relevance(scoring_path, si)

    total_score = min(100, dim_score + fs_score + fn_score + src_score + theme_score + brightness_score)
    total_score = max(0, total_score)

    # Determine verdict
    if total_score >= 90:
        verdict = "PASS"
    elif total_score >= 80:
        verdict = "RETRY"
    else:
        verdict = "HARD_FAIL"

    return {
        "score": total_score,
        "verdict": verdict,
        "details": {
            "dimensions_score": dim_score,
            "filesize_score": fs_score,
            "filename_match_score": fn_score,
            "source_type_score": src_score,
            "theme_relevance_score": theme_score,
            "brightness_score": brightness_score,
            "mean_brightness": round(mean_brightness, 1) if mean_brightness >= 0 else None,
            "dark_ratio": round(dark_ratio, 3) if dark_ratio >= 0 else None,
            "width": width,
            "height": height,
            "file_size_kb": round(file_size / 1024, 1),
            "checks_passed": checks_passed,
            "checks_failed": checks_failed,
        },
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Thumbnail Vision Validator")
    parser.add_argument("--image", required=True, help="Path to thumbnail image")
    parser.add_argument("--title", required=True, help="Article title")
    parser.add_argument("--body", default="", help="Article body (optional)")
    args = parser.parse_args()

    result = validate_thumbnail(args.image, args.title, args.body)
    print(json.dumps(result, ensure_ascii=False, indent=2))
