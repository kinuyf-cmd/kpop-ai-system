from PIL import Image, ImageDraw, ImageFont, ImageFilter
import sys
import textwrap

title = sys.argv[1] if len(sys.argv) > 1 else "K-POP NEWS"

W, H = 1280, 720
img = Image.new("RGB", (W, H), (12, 12, 18))
draw = ImageDraw.Draw(img)

# ========= フォント =========
font_candidates = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]

font_big = None
font_mid = None
font_small = None

for path in font_candidates:
    try:
        font_big = ImageFont.truetype(path, 110)
        font_mid = ImageFont.truetype(path, 56)
        font_small = ImageFont.truetype(path, 30)
        break
    except Exception:
        pass

if font_big is None:
    font_big = ImageFont.load_default()
    font_mid = ImageFont.load_default()
    font_small = ImageFont.load_default()

# ========= 背景グラデ =========
for y in range(H):
    r = int(18 + (y / H) * 20)
    g = int(18 + (y / H) * 10)
    b = int(28 + (y / H) * 35)
    draw.line((0, y, W, y), fill=(r, g, b))

# ========= ネオン風の丸ぼかし =========
overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
odraw = ImageDraw.Draw(overlay)
odraw.ellipse((760, 80, 1220, 540), fill=(255, 50, 100, 90))
odraw.ellipse((820, 180, 1250, 680), fill=(90, 40, 255, 80))
odraw.ellipse((650, 260, 1050, 700), fill=(0, 180, 255, 55))
overlay = overlay.filter(ImageFilter.GaussianBlur(55))
img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
draw = ImageDraw.Draw(img)

# ========= 上部帯 =========
draw.rounded_rectangle((40, 36, 360, 100), radius=18, fill=(255, 48, 92))
draw.text((62, 50), "K-POP JOURNAL", fill="white", font=font_small)

# ========= 左下の黒パネル =========
panel_x1, panel_y1, panel_x2, panel_y2 = 40, 150, 980, 650
draw.rounded_rectangle((panel_x1, panel_y1, panel_x2, panel_y2), radius=34, fill=(8, 8, 12))

# ========= 下部アクセント =========
draw.rectangle((0, H - 18, W, H), fill=(255, 48, 92))

# ========= キーワード抽出 =========
strong_keywords = [
    "BTS", "BLACKPINK", "BIGBANG", "SEVENTEEN", "TWICE", "Stray Kids",
    "NewJeans", "ILLIT", "IVE", "aespa", "XG",
    "カムバック", "1位", "速報", "新曲", "ツアー", "ライブ", "コーチェラ", "Coachella"
]

main_word = None
for kw in strong_keywords:
    if kw.lower() in title.lower():
        main_word = kw
        break

if not main_word:
    main_word = title[:10]

sub_text = title.replace(main_word, "").strip("｜|- 　")
if not sub_text:
    sub_text = title

# ========= メインワード描画 =========
def draw_glow_text(base_draw, x, y, text, font, main_fill, glow_fill):
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    for dx in range(-6, 7, 2):
        for dy in range(-6, 7, 2):
            gdraw.text((x + dx, y + dy), text, font=font, fill=glow_fill)
    glow = glow.filter(ImageFilter.GaussianBlur(8))
    merged = Image.alpha_composite(img.convert("RGBA"), glow)
    merged_draw = ImageDraw.Draw(merged)
    merged_draw.text((x, y), text, font=font, fill=main_fill)
    return merged.convert("RGB")

img = draw_glow_text(draw, 72, 215, main_word, font_big, (255, 70, 90), (255, 70, 120, 130))
draw = ImageDraw.Draw(img)

# ========= サブコピー =========
wrapped = textwrap.wrap(sub_text, width=18)
wrapped = wrapped[:3]

y = 380
for line in wrapped:
    draw.text((72, y), line, fill="white", font=font_mid)
    y += 78

# ========= 右上バッジ =========
badge_text = "最新"
badge_w, badge_h = 160, 72
bx1, by1 = 1060, 54
bx2, by2 = bx1 + badge_w, by1 + badge_h
draw.rounded_rectangle((bx1, by1, bx2, by2), radius=22, fill=(255, 210, 0))
tw = draw.textlength(badge_text, font=font_small)
draw.text((bx1 + (badge_w - tw) / 2, by1 + 17), badge_text, fill=(18, 18, 18), font=font_small)

# ========= 速報ライン =========
draw.rounded_rectangle((72, 575, 400, 628), radius=14, fill=(255, 48, 92))
draw.text((95, 587), "CLICKされる速報デザイン", fill="white", font=font_small)

img.save("thumbnail.jpg", quality=95)
print("thumbnail.jpg を作成しました")
