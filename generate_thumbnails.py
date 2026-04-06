#!/usr/bin/env python3
"""
Generate 5 K-POP JOURNAL thumbnail background templates.
Each is 1200x630px, designed for YouTube thumbnail use.
Target audience: 10-30 year old female K-POP fans.
"""

import math
import random
from PIL import Image, ImageDraw, ImageFilter

W, H = 1200, 630

random.seed(42)  # Reproducible output


def draw_logo_pill(draw):
    """Draw a white rounded pill in the top-left for 'KPOP JOURNAL' logo area."""
    x0, y0, x1, y1 = 30, 25, 210, 58
    radius = (y1 - y0) // 2
    # Semi-transparent white pill
    pill = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pill_draw = ImageDraw.Draw(pill)
    pill_draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=(255, 255, 255, 200))
    return pill


def draw_category_badge(draw, color=(255, 255, 255, 180)):
    """Draw a category badge area in the top-right."""
    badge = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    badge_draw = ImageDraw.Draw(badge)
    x0, y0, x1, y1 = W - 220, 25, W - 30, 58
    radius = (y1 - y0) // 2
    badge_draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=color)
    return badge


def draw_bottom_accent(draw, color=(255, 255, 255, 100), y_offset=0):
    """Draw a thin decorative accent bar near the bottom."""
    accent = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    accent_draw = ImageDraw.Draw(accent)
    y = H - 45 + y_offset
    accent_draw.line([(40, y), (W - 40, y)], fill=color, width=2)
    # Small decorative dots at ends
    accent_draw.ellipse([(36, y - 4), (44, y + 4)], fill=color)
    accent_draw.ellipse([(W - 44, y - 4), (W - 36, y + 4)], fill=color)
    return accent


def make_gradient(colors_start, colors_end, direction="vertical"):
    """Create a smooth gradient image."""
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    r1, g1, b1 = colors_start
    r2, g2, b2 = colors_end
    if direction == "vertical":
        for y in range(H):
            t = y / H
            r = int(r1 + (r2 - r1) * t)
            g = int(g1 + (g2 - g1) * t)
            b = int(b1 + (b2 - b1) * t)
            draw.line([(0, y), (W, y)], fill=(r, g, b))
    elif direction == "horizontal":
        for x in range(W):
            t = x / W
            r = int(r1 + (r2 - r1) * t)
            g = int(g1 + (g2 - g1) * t)
            b = int(b1 + (b2 - b1) * t)
            draw.line([(x, 0), (x, H)], fill=(r, g, b))
    elif direction == "diagonal":
        for y in range(H):
            for x in range(W):
                t = (x / W * 0.5 + y / H * 0.5)
                r = int(r1 + (r2 - r1) * t)
                g = int(g1 + (g2 - g1) * t)
                b = int(b1 + (b2 - b1) * t)
                img.putpixel((x, y), (r, g, b))
    return img


def make_radial_gradient(center, radius, color_inner, color_outer, base_img):
    """Add a radial gradient overlay to an existing image."""
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cx, cy = center
    ri, gi, bi = color_inner
    ro, go, bo = color_outer
    for r in range(radius, 0, -2):
        t = r / radius
        red = int(ri + (ro - ri) * t)
        green = int(gi + (go - gi) * t)
        blue = int(bi + (bo - bi) * t)
        alpha = int(120 * (1 - t))
        draw.ellipse(
            [(cx - r, cy - r), (cx + r, cy + r)],
            fill=(red, green, blue, alpha)
        )
    base_img.paste(Image.alpha_composite(base_img.convert("RGBA"), overlay))
    return base_img


# ============================================================
# 1. NEWS - Bold red-black gradient with diagonal stripes
# ============================================================
def generate_news():
    img = make_gradient((30, 0, 0), (10, 10, 10), direction="diagonal")
    img = img.convert("RGBA")

    # Red glow from top-left
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    for r in range(500, 0, -3):
        t = r / 500
        alpha = int(80 * (1 - t))
        draw_ov.ellipse(
            [(100 - r, 50 - r), (100 + r, 50 + r)],
            fill=(200, 20, 20, alpha)
        )
    img = Image.alpha_composite(img, overlay)

    # Secondary red glow from bottom-right
    overlay2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_ov2 = ImageDraw.Draw(overlay2)
    for r in range(400, 0, -3):
        t = r / 400
        alpha = int(50 * (1 - t))
        draw_ov2.ellipse(
            [(W - 200 - r, H - 100 - r), (W - 200 + r, H - 100 + r)],
            fill=(180, 0, 0, alpha)
        )
    img = Image.alpha_composite(img, overlay2)

    # Diagonal stripe pattern
    stripes = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    stripe_draw = ImageDraw.Draw(stripes)
    for i in range(-H, W + H, 40):
        stripe_draw.line(
            [(i, 0), (i + H, H)],
            fill=(255, 30, 30, 18), width=12
        )
    img = Image.alpha_composite(img, stripes)

    # Geometric accent lines
    accents = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    acc_draw = ImageDraw.Draw(accents)
    # Thin red accent lines
    acc_draw.line([(0, 80), (350, 80)], fill=(255, 50, 50, 120), width=2)
    acc_draw.line([(0, 85), (280, 85)], fill=(255, 50, 50, 80), width=1)
    acc_draw.line([(W - 350, H - 80), (W, H - 80)], fill=(255, 50, 50, 120), width=2)
    acc_draw.line([(W - 280, H - 75), (W, H - 75)], fill=(255, 50, 50, 80), width=1)
    # Corner geometric triangles
    acc_draw.polygon([(0, 0), (60, 0), (0, 60)], fill=(255, 40, 40, 40))
    acc_draw.polygon([(W, H), (W - 60, H), (W, H - 60)], fill=(255, 40, 40, 40))
    img = Image.alpha_composite(img, accents)

    # Subtle noise/grain via small dots
    grain = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    grain_draw = ImageDraw.Draw(grain)
    for _ in range(800):
        x = random.randint(0, W - 1)
        y = random.randint(0, H - 1)
        a = random.randint(5, 20)
        grain_draw.point((x, y), fill=(255, 255, 255, a))
    img = Image.alpha_composite(img, grain)

    # Logo pill, badge, bottom accent
    img = Image.alpha_composite(img, draw_logo_pill(None))
    img = Image.alpha_composite(img, draw_category_badge(None, color=(220, 40, 40, 200)))
    img = Image.alpha_composite(img, draw_bottom_accent(None, color=(255, 60, 60, 120)))

    img.convert("RGB").save("/home/aiuser/kpop-ai-system/assets/thumbnails/news.png")
    print("  news.png generated")


# ============================================================
# 2. COMEBACK - Purple-to-blue neon gradient with sparkles
# ============================================================
def generate_comeback():
    img = make_gradient((100, 20, 160), (20, 60, 180), direction="diagonal")
    img = img.convert("RGBA")

    # Neon glow center
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for r in range(450, 0, -3):
        t = r / 450
        alpha = int(60 * (1 - t))
        glow_draw.ellipse(
            [(W // 2 - r, H // 2 - r), (W // 2 + r, H // 2 + r)],
            fill=(180, 100, 255, alpha)
        )
    img = Image.alpha_composite(img, glow)

    # Secondary blue glow top-right
    glow2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow2_draw = ImageDraw.Draw(glow2)
    for r in range(300, 0, -3):
        t = r / 300
        alpha = int(40 * (1 - t))
        glow2_draw.ellipse(
            [(W - 150 - r, -50 - r), (W - 150 + r, -50 + r)],
            fill=(80, 120, 255, alpha)
        )
    img = Image.alpha_composite(img, glow2)

    # Star / sparkle dots
    sparkles = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sp_draw = ImageDraw.Draw(sparkles)
    for _ in range(120):
        x = random.randint(0, W)
        y = random.randint(0, H)
        size = random.randint(1, 4)
        alpha = random.randint(80, 220)
        sp_draw.ellipse(
            [(x - size, y - size), (x + size, y + size)],
            fill=(255, 255, 255, alpha)
        )
    # Larger sparkle accents (cross-shaped)
    for _ in range(15):
        x = random.randint(50, W - 50)
        y = random.randint(50, H - 50)
        length = random.randint(6, 14)
        alpha = random.randint(120, 200)
        sp_draw.line([(x - length, y), (x + length, y)], fill=(255, 255, 255, alpha), width=1)
        sp_draw.line([(x, y - length), (x, y + length)], fill=(255, 255, 255, alpha), width=1)
        sp_draw.ellipse([(x - 2, y - 2), (x + 2, y + 2)], fill=(255, 255, 255, alpha))
    img = Image.alpha_composite(img, sparkles)

    # Subtle light rays from center
    rays = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rays_draw = ImageDraw.Draw(rays)
    cx, cy = W // 2, H // 2 - 50
    for angle_deg in range(0, 360, 15):
        angle = math.radians(angle_deg)
        ex = cx + int(700 * math.cos(angle))
        ey = cy + int(700 * math.sin(angle))
        rays_draw.line([(cx, cy), (ex, ey)], fill=(200, 180, 255, 8), width=3)
    img = Image.alpha_composite(img, rays)

    # Logo pill, badge, bottom accent
    img = Image.alpha_composite(img, draw_logo_pill(None))
    img = Image.alpha_composite(img, draw_category_badge(None, color=(160, 80, 255, 200)))
    img = Image.alpha_composite(img, draw_bottom_accent(None, color=(200, 160, 255, 130)))

    img.convert("RGB").save("/home/aiuser/kpop-ai-system/assets/thumbnails/comeback.png")
    print("  comeback.png generated")


# ============================================================
# 3. ANALYSIS - Dark navy with gold accent lines
# ============================================================
def generate_analysis():
    img = make_gradient((12, 15, 30), (8, 10, 22), direction="vertical")
    img = img.convert("RGBA")

    # Subtle navy-blue radial glow
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for r in range(500, 0, -3):
        t = r / 500
        alpha = int(30 * (1 - t))
        glow_draw.ellipse(
            [(W // 2 - r, H // 2 - r), (W // 2 + r, H // 2 + r)],
            fill=(20, 30, 60, alpha)
        )
    img = Image.alpha_composite(img, glow)

    # Gold accent lines - horizontal thin lines
    gold_lines = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gl_draw = ImageDraw.Draw(gold_lines)

    gold = (212, 175, 55)
    gold_dim = (180, 150, 40)

    # Top decorative gold lines
    gl_draw.line([(40, 75), (400, 75)], fill=(*gold, 140), width=2)
    gl_draw.line([(40, 80), (300, 80)], fill=(*gold_dim, 80), width=1)
    gl_draw.line([(40, 90), (200, 90)], fill=(*gold_dim, 50), width=1)

    # Bottom decorative gold lines
    gl_draw.line([(W - 400, H - 75), (W - 40, H - 75)], fill=(*gold, 140), width=2)
    gl_draw.line([(W - 300, H - 80), (W - 40, H - 80)], fill=(*gold_dim, 80), width=1)
    gl_draw.line([(W - 200, H - 90), (W - 40, H - 90)], fill=(*gold_dim, 50), width=1)

    # Subtle horizontal rules across full width (very faint)
    for y_pos in [150, 200, 430, 480]:
        gl_draw.line([(60, y_pos), (W - 60, y_pos)], fill=(*gold_dim, 20), width=1)

    # Gold corner accents
    corner_size = 40
    gl_draw.line([(30, 20), (30, 20 + corner_size)], fill=(*gold, 100), width=2)
    gl_draw.line([(30, 20), (30 + corner_size, 20)], fill=(*gold, 100), width=2)
    gl_draw.line([(W - 30, H - 20), (W - 30, H - 20 - corner_size)], fill=(*gold, 100), width=2)
    gl_draw.line([(W - 30, H - 20), (W - 30 - corner_size, H - 20)], fill=(*gold, 100), width=2)
    # Other two corners
    gl_draw.line([(W - 30, 20), (W - 30, 20 + corner_size)], fill=(*gold, 60), width=1)
    gl_draw.line([(W - 30, 20), (W - 30 - corner_size, 20)], fill=(*gold, 60), width=1)
    gl_draw.line([(30, H - 20), (30, H - 20 - corner_size)], fill=(*gold, 60), width=1)
    gl_draw.line([(30, H - 20), (30 + corner_size, H - 20)], fill=(*gold, 60), width=1)

    img = Image.alpha_composite(img, gold_lines)

    # Subtle diamond pattern overlay
    pattern = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pat_draw = ImageDraw.Draw(pattern)
    for x in range(0, W, 60):
        for y in range(0, H, 60):
            pat_draw.polygon(
                [(x, y - 3), (x + 3, y), (x, y + 3), (x - 3, y)],
                fill=(*gold_dim, 10)
            )
    img = Image.alpha_composite(img, pattern)

    # Logo pill, badge, bottom accent
    img = Image.alpha_composite(img, draw_logo_pill(None))
    img = Image.alpha_composite(img, draw_category_badge(None, color=(*gold, 200)))
    img = Image.alpha_composite(img, draw_bottom_accent(None, color=(*gold, 120)))

    img.convert("RGB").save("/home/aiuser/kpop-ai-system/assets/thumbnails/analysis.png")
    print("  analysis.png generated")


# ============================================================
# 4. LIVE - Warm orange-to-pink with bokeh flares
# ============================================================
def generate_live():
    img = make_gradient((230, 120, 30), (220, 60, 120), direction="diagonal")
    img = img.convert("RGBA")

    # Center warm glow
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for r in range(400, 0, -3):
        t = r / 400
        alpha = int(50 * (1 - t))
        glow_draw.ellipse(
            [(W // 2 - r, H // 2 - r), (W // 2 + r, H // 2 + r)],
            fill=(255, 200, 100, alpha)
        )
    img = Image.alpha_composite(img, glow)

    # Circular bokeh light flares
    bokeh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bk_draw = ImageDraw.Draw(bokeh)
    for _ in range(30):
        x = random.randint(-50, W + 50)
        y = random.randint(-50, H + 50)
        size = random.randint(20, 80)
        alpha = random.randint(15, 50)
        color_choice = random.choice([
            (255, 230, 180, alpha),
            (255, 180, 140, alpha),
            (255, 200, 200, alpha),
            (255, 255, 220, alpha),
        ])
        # Draw bokeh as concentric rings for realism
        bk_draw.ellipse(
            [(x - size, y - size), (x + size, y + size)],
            fill=color_choice
        )
        # Brighter edge ring
        bk_draw.ellipse(
            [(x - size, y - size), (x + size, y + size)],
            outline=(*color_choice[:3], min(255, alpha + 20)), width=2
        )
    # Apply blur for soft bokeh
    bokeh = bokeh.filter(ImageFilter.GaussianBlur(radius=6))
    img = Image.alpha_composite(img, bokeh)

    # Smaller sharp bokeh dots
    dots = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dots_draw = ImageDraw.Draw(dots)
    for _ in range(50):
        x = random.randint(0, W)
        y = random.randint(0, H)
        size = random.randint(2, 6)
        alpha = random.randint(80, 180)
        dots_draw.ellipse(
            [(x - size, y - size), (x + size, y + size)],
            fill=(255, 255, 255, alpha)
        )
    dots = dots.filter(ImageFilter.GaussianBlur(radius=1))
    img = Image.alpha_composite(img, dots)

    # Light streak from top
    streak = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    st_draw = ImageDraw.Draw(streak)
    for i in range(200):
        alpha = max(0, 30 - i // 7)
        st_draw.line(
            [(W // 3 + i, 0), (W // 3 - 100 + i, H)],
            fill=(255, 255, 200, alpha), width=2
        )
    img = Image.alpha_composite(img, streak)

    # Logo pill, badge, bottom accent
    img = Image.alpha_composite(img, draw_logo_pill(None))
    img = Image.alpha_composite(img, draw_category_badge(None, color=(255, 100, 80, 200)))
    img = Image.alpha_composite(img, draw_bottom_accent(None, color=(255, 220, 180, 140)))

    img.convert("RGB").save("/home/aiuser/kpop-ai-system/assets/thumbnails/live.png")
    print("  live.png generated")


# ============================================================
# 5. BEAUTY - Soft white-to-pink with pastel bokeh
# ============================================================
def generate_beauty():
    img = make_gradient((255, 245, 248), (255, 200, 220), direction="vertical")
    img = img.convert("RGBA")

    # Subtle warm glow center
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for r in range(450, 0, -3):
        t = r / 450
        alpha = int(35 * (1 - t))
        glow_draw.ellipse(
            [(W // 2 - r, H // 2 - r - 50), (W // 2 + r, H // 2 + r - 50)],
            fill=(255, 255, 255, alpha)
        )
    img = Image.alpha_composite(img, glow)

    # Soft circle bokeh in pastel pink
    bokeh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bk_draw = ImageDraw.Draw(bokeh)
    for _ in range(25):
        x = random.randint(-30, W + 30)
        y = random.randint(-30, H + 30)
        size = random.randint(30, 100)
        alpha = random.randint(10, 35)
        color_choice = random.choice([
            (255, 180, 200, alpha),
            (255, 200, 210, alpha),
            (255, 190, 220, alpha),
            (255, 220, 230, alpha),
        ])
        bk_draw.ellipse(
            [(x - size, y - size), (x + size, y + size)],
            fill=color_choice
        )
    bokeh = bokeh.filter(ImageFilter.GaussianBlur(radius=12))
    img = Image.alpha_composite(img, bokeh)

    # Tiny sparkle dots
    sparkles = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sp_draw = ImageDraw.Draw(sparkles)
    for _ in range(40):
        x = random.randint(0, W)
        y = random.randint(0, H)
        size = random.randint(1, 3)
        alpha = random.randint(60, 140)
        sp_draw.ellipse(
            [(x - size, y - size), (x + size, y + size)],
            fill=(255, 255, 255, alpha)
        )
    img = Image.alpha_composite(img, sparkles)

    # Subtle petal-like shapes at edges
    petals = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pet_draw = ImageDraw.Draw(petals)
    for _ in range(8):
        x = random.choice([random.randint(0, 150), random.randint(W - 150, W)])
        y = random.randint(0, H)
        size = random.randint(15, 35)
        pet_draw.ellipse(
            [(x - size, y - size // 2), (x + size, y + size // 2)],
            fill=(255, 190, 210, 20)
        )
    petals = petals.filter(ImageFilter.GaussianBlur(radius=5))
    img = Image.alpha_composite(img, petals)

    # Logo pill (slightly darker for visibility on light bg)
    pill = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pill_draw = ImageDraw.Draw(pill)
    pill_draw.rounded_rectangle(
        [30, 25, 210, 58], radius=16,
        fill=(255, 255, 255, 220), outline=(240, 180, 200, 100), width=1
    )
    img = Image.alpha_composite(img, pill)

    # Category badge (pink toned)
    img = Image.alpha_composite(img, draw_category_badge(None, color=(255, 160, 190, 180)))

    # Bottom accent (soft pink)
    img = Image.alpha_composite(img, draw_bottom_accent(None, color=(240, 160, 180, 100)))

    img.convert("RGB").save("/home/aiuser/kpop-ai-system/assets/thumbnails/beauty.png")
    print("  beauty.png generated")


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    print("Generating K-POP JOURNAL thumbnail backgrounds...")
    generate_news()
    generate_comeback()
    generate_analysis()
    generate_live()
    generate_beauty()
    print("Done! All 5 templates saved to assets/thumbnails/")
