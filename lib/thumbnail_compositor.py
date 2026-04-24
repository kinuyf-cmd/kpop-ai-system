#!/usr/bin/env python3
"""
Thumbnail Compositor v1.0 — Yuta-approved design for K-POP Journal.

Design spec:
  - 1200x630 output (OG image standard)
  - Photo background with left-side black gradient (40-60% opacity)
  - NotoSansJP-Black font
  - 12 chars max per line, auto line break, line spacing 1.1x
  - White text #FFFFFF
  - 【】and emphasis words in gold #FFD700
  - Control char sanitization (n/, 見切れ etc.)

Usage:
  python3 thumbnail_compositor.py --artist "BTS" --copy "衝撃の復活発表" --bg image.jpg
  python3 thumbnail_compositor.py --artist "BLACKPINK" --copy "新曲MV解禁" --genre comeback
"""

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import json
import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
W, H = 1200, 630

# ── Font paths ──
FONT_DIR = "/home/aiuser/.local/share/fonts"
FONT_JP_BLACK = None
FONT_LATIN = None

# Load Japanese Black weight font
_BLACK_CANDIDATES = [
    f"{FONT_DIR}/NotoSansJP-Black.otf",
    f"{FONT_DIR}/NotoSansJP-Black.ttf",
    f"{FONT_DIR}/ZenKakuGothicNew-Black.ttf",
]
for _p in _BLACK_CANDIDATES:
    if os.path.exists(_p):
        try:
            _f = ImageFont.truetype(_p, 40)
            _name = _f.getname()
            if _name and len(_name) > 1 and any(
                w in (_name[1] or "") for w in ("Black", "ExtraBold", "Heavy")
            ):
                FONT_JP_BLACK = _p
                break
        except Exception:
            continue

# Load Latin font (Bebas Neue)
_LATIN_PATH = f"{FONT_DIR}/BebasNeue-Regular.ttf"
if os.path.exists(_LATIN_PATH):
    FONT_LATIN = _LATIN_PATH

if FONT_JP_BLACK is None:
    sys.stderr.write("[compositor] FATAL: Black weight Japanese font not found\n")
    sys.exit(1)

# ── Constants ──
MAX_CHARS = 12
GOLD = (255, 215, 0)        # #FFD700
WHITE = (255, 255, 255)     # #FFFFFF
SHADOW_COLOR = (0, 0, 0)

# Strong words that get gold highlight
STRONG_WORDS = [
    "衝撃", "速報", "判明", "神", "炎上", "ついに", "電撃",
    "復活", "決定", "解禁", "初公開", "大反響", "騒然",
    "覚醒", "急変", "崩壊", "暴露", "激変", "独占", "注目",
    "緊急", "確定", "発覚", "完全", "即完売", "真相",
]


def _jp_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_JP_BLACK, size)


def _latin_font(size: int) -> ImageFont.FreeTypeFont:
    path = FONT_LATIN or FONT_JP_BLACK
    return ImageFont.truetype(path, size)


def _sanitize(text: str) -> str:
    """Remove control chars and artifacts from thumbnail text."""
    text = text.replace("\\n", "").replace("\n", "")
    text = re.sub(r"n/\s*", "", text)
    text = re.sub(r"見切れ.*", "", text)
    text = re.sub(r"\{[^}]*\}", "", text)  # JSON artifacts
    text = re.sub(r"<[^>]+>", "", text)    # HTML tags
    text = text.strip()
    return text


def _auto_break(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Split text into lines of max_chars, preferring natural break points."""
    text = _sanitize(text)
    if len(text) <= max_chars:
        return [text]

    # Try natural split points
    particles = ["の", "は", "が", "を", "に", "で", "と", "も"]
    punctuation = ["】", "、", "！", "？", "・"]

    best_pos = -1
    best_score = -1
    target = len(text) / 2

    for group in [punctuation, particles]:
        for p in group:
            idx = 0
            while True:
                pos = text.find(p, idx)
                if pos == -1:
                    break
                split_at = pos + len(p)
                if split_at <= max_chars and len(text) - split_at <= max_chars:
                    score = 100 - abs(split_at - target)
                    if score > best_score:
                        best_score = score
                        best_pos = split_at
                idx = pos + 1

    if best_pos > 0:
        return [text[:best_pos].strip(), text[best_pos:].strip()[:max_chars]]

    # Force split at midpoint
    mid = min(max_chars, len(text) // 2)
    return [text[:mid], text[mid:mid + max_chars]]


def _segment_for_highlight(text: str) -> list[tuple[str, tuple]]:
    """Split text into (text, color) segments. Gold for 【】 brackets and strong words."""
    segments = []
    buf = ""
    i = 0
    while i < len(text):
        # 【...】 brackets → gold
        if text[i] == "【":
            if buf:
                segments.append((buf, WHITE))
                buf = ""
            end = text.find("】", i)
            if end != -1:
                segments.append((text[i:end + 1], GOLD))
                i = end + 1
                continue
        # Numbers → gold
        if text[i].isdigit() or text[i] in "０１２３４５６７８９":
            if buf:
                segments.append((buf, WHITE))
                buf = ""
            num_buf = text[i]
            i += 1
            while i < len(text) and (text[i].isdigit() or text[i] in "万億千百年月日位選曲本人回組枚ぶり"):
                num_buf += text[i]
                i += 1
            segments.append((num_buf, GOLD))
            continue
        # Strong words → gold
        matched = None
        for sw in sorted(STRONG_WORDS, key=len, reverse=True):
            if text[i:i + len(sw)] == sw:
                matched = sw
                break
        if matched:
            if buf:
                segments.append((buf, WHITE))
                buf = ""
            segments.append((matched, GOLD))
            i += len(matched)
            continue
        buf += text[i]
        i += 1
    if buf:
        segments.append((buf, WHITE))
    return segments


def _load_photo_bg(path: str) -> Image.Image:
    """Load and crop a photo to 1200x630 maintaining aspect ratio."""
    img = Image.open(path).convert("RGB")
    iw, ih = img.size
    scale = max(W / iw, H / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - W) // 2
    top = (nh - H) // 2
    return img.crop((left, top, left + W, top + H))


def _create_gradient_bg(accent: tuple = (80, 20, 60)) -> Image.Image:
    """Create a dark gradient background with accent color."""
    img = Image.new("RGB", (W, H))
    dark_top = tuple(max(0, int(c * 0.35)) for c in accent)
    dark_bot = tuple(max(0, int(c * 0.12)) for c in accent)
    for y in range(H):
        ratio = y / H
        ratio = ratio * ratio * (3 - 2 * ratio)
        r = int(dark_top[0] + (dark_bot[0] - dark_top[0]) * ratio)
        g = int(dark_top[1] + (dark_bot[1] - dark_top[1]) * ratio)
        b = int(dark_top[2] + (dark_bot[2] - dark_top[2]) * ratio)
        ImageDraw.Draw(img).line([(0, y), (W, y)], fill=(r, g, b))
    return img


def compose(
    artist: str = "",
    copy_text: str = "",
    bg_image: str = "",
    genre: str = "breaking",
    output_path: str = "thumbnail.webp",
) -> dict:
    """
    Generate a thumbnail image.

    Returns metadata dict with: output_path, artist, copy_text, source_used, etc.
    """
    copy_text = _sanitize(copy_text)
    artist = (artist or "").strip().upper()

    # ── Background ──
    has_photo = False
    if bg_image and os.path.exists(bg_image):
        img = _load_photo_bg(bg_image)
        has_photo = True
    else:
        img = _create_gradient_bg()

    # ── Dark overlay (whole image) ──
    if has_photo:
        dark = Image.new("RGBA", (W, H), (0, 0, 0, 70))
        img = Image.alpha_composite(img.convert("RGBA"), dark).convert("RGB")

    # ── Left-side black gradient (40-60% opacity for text readability) ──
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    # Gradient from left (strong) to right (transparent), covering ~65% of width
    for x in range(0, 780):
        # Alpha: 160 at x=0 → 0 at x=780 (smooth curve)
        alpha = int(160 * (1 - x / 780) ** 1.4)
        odraw.line([(x, 0), (x, H)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── Logo badge (top-left) ──
    font_logo = _jp_font(13)
    logo_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ldraw = ImageDraw.Draw(logo_overlay)
    ldraw.rounded_rectangle((28, 24, 168, 50), radius=12, fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img.convert("RGBA"), logo_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    draw.text((40, 29), "K-POP JOURNAL", fill=WHITE, font=font_logo)

    # ── Bottom band (semi-transparent) ──
    BAND_H = 180
    BAND_TOP = H - BAND_H
    band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(band)
    bdraw.rectangle((0, BAND_TOP, W, H), fill=(0, 0, 0, 140))
    # Accent line at top of band
    accent_color = GOLD + (255,)
    bdraw.rectangle((0, BAND_TOP, W, BAND_TOP + 3), fill=accent_color)
    img = Image.alpha_composite(img.convert("RGBA"), band).convert("RGB")
    draw = ImageDraw.Draw(img)

    PAD_X = 60

    # ── Line 1: Artist name (Bebas Neue / Latin, gray) ──
    has_artist = bool(artist)
    if has_artist:
        font_artist = _latin_font(32)
        draw.text((PAD_X, BAND_TOP + 22), artist, fill=(220, 220, 220), font=font_artist)

    # ── Line 2: Copy text (NotoSansJP-Black, white + gold highlights) ──
    if copy_text:
        lines = _auto_break(copy_text)
        line_spacing = 1.1

        # Determine font size based on longest line
        max_len = max(len(line) for line in lines)
        if max_len <= 6:
            base_size = 72
        elif max_len <= 9:
            base_size = 62
        elif max_len <= 12:
            base_size = 52
        else:
            base_size = 44

        font_copy = _jp_font(base_size)

        # Starting Y position
        if has_artist:
            y_start = BAND_TOP + 64
        else:
            # Center in band
            total_h = base_size * len(lines) * line_spacing
            y_start = BAND_TOP + (BAND_H - total_h) // 2

        for line_idx, line in enumerate(lines):
            y = int(y_start + line_idx * base_size * line_spacing)

            # Drop shadow
            shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            sdraw = ImageDraw.Draw(shadow_layer)
            sdraw.text((PAD_X + 2, y + 3), line, font=font_copy, fill=(0, 0, 0, 160))
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=5))
            img = Image.alpha_composite(img.convert("RGBA"), shadow_layer).convert("RGB")
            draw = ImageDraw.Draw(img)

            # Render segments with gold highlights
            segments = _segment_for_highlight(line)
            x_cursor = PAD_X
            for seg_text, seg_color in segments:
                draw.text((x_cursor, y), seg_text, font=font_copy,
                          fill=seg_color, stroke_width=2, stroke_fill=SHADOW_COLOR)
                bbox = draw.textbbox((0, 0), seg_text, font=font_copy)
                x_cursor += bbox[2] - bbox[0]

    # ── No-photo hero text (centered, large) ──
    if not has_photo and artist:
        display = artist
        hero_size = 230 if len(display) <= 6 else (180 if len(display) <= 10 else 140)
        font_hero = _latin_font(hero_size)
        bbox = draw.textbbox((0, 0), display, font=font_hero)
        hw = bbox[2] - bbox[0]
        while hw > W - 100 and hero_size > 60:
            hero_size -= 10
            font_hero = _latin_font(hero_size)
            bbox = draw.textbbox((0, 0), display, font=font_hero)
            hw = bbox[2] - bbox[0]
        hx = (W - hw) // 2
        hy = 100 + (H - 280 - (bbox[3] - bbox[1])) // 2
        if hy < 80:
            hy = 80
        # Shadow
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        shdraw = ImageDraw.Draw(sh)
        shdraw.text((hx + 3, hy + 5), display, font=font_hero, fill=(0, 0, 0, 140))
        sh = sh.filter(ImageFilter.GaussianBlur(radius=9))
        img = Image.alpha_composite(img.convert("RGBA"), sh).convert("RGB")
        draw = ImageDraw.Draw(img)
        draw.text((hx, hy), display, font=font_hero, fill=WHITE)

    # ── Save ──
    img.save(output_path, format="WEBP", quality=85)
    jpg_path = output_path.replace(".webp", ".jpg")
    img.save(jpg_path, format="JPEG", quality=95)

    meta = {
        "output_path": output_path,
        "jpg_path": jpg_path,
        "artist": artist,
        "copy_text": copy_text,
        "has_photo": has_photo,
        "bg_image": bg_image,
        "genre": genre,
        "size": f"{W}x{H}",
    }
    sys.stderr.write("COMPOSITOR_META: " + json.dumps(meta, ensure_ascii=False) + "\n")
    return meta


def compose_v6(image_path: str, output_path: str) -> str:
    """v6 compositor: text-zero, photo-only processing.

    No text overlay, no gradient band, no logo badge.
    Just clean photo processing: resize/crop to 1200x630 with subtle enhancement.
    """
    img = Image.open(image_path).convert("RGB")
    # Resize/crop to 1200x630
    target_ratio = W / H  # 1200/630
    img_ratio = img.width / img.height
    if img_ratio > target_ratio:
        new_h = H
        new_w = int(H * img_ratio)
    else:
        new_w = W
        new_h = int(W / img_ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    # Center crop
    left = (new_w - W) // 2
    top = (new_h - H) // 2
    img = img.crop((left, top, left + W, top + H))
    # Subtle enhancement
    from PIL import ImageEnhance
    img = ImageEnhance.Contrast(img).enhance(1.05)
    img = ImageEnhance.Brightness(img).enhance(1.02)
    # Save
    if output_path.endswith('.webp'):
        img.save(output_path, 'WEBP', quality=92)
    else:
        img.save(output_path, 'JPEG', quality=95)
    return output_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Thumbnail Compositor")
    parser.add_argument("--artist", default="", help="Artist name (ASCII)")
    parser.add_argument("--copy", default="", help="Copy text (Japanese, ≤15 chars)")
    parser.add_argument("--bg", default="", help="Background image path")
    parser.add_argument("--genre", default="breaking", help="Genre key")
    parser.add_argument("--output", default="thumbnail.webp", help="Output path")
    args = parser.parse_args()

    result = compose(
        artist=args.artist,
        copy_text=args.copy,
        bg_image=args.bg,
        genre=args.genre,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
