#!/bin/bash

TITLE="$1"

TEXT=$(bash ~/google_metrics/generate_thumbnail_text.sh "$TITLE")
STYLE=$(bash ~/google_metrics/get_thumbnail_style.sh "$TITLE")

python3 - << PY
from PIL import Image, ImageDraw, ImageFont

img = Image.new("RGB", (1200, 675))

style = "$STYLE"

if style == "NEON":
    bg = (255, 20, 80)
elif style == "GOLD":
    bg = (180, 150, 60)
elif style == "LIGHT":
    bg = (240, 240, 240)
elif style == "PASTEL":
    bg = (255, 220, 230)
elif style == "RED_ALERT":
    bg = (200, 0, 0)
else:
    bg = (30, 30, 30)

img.paste(bg, [0,0,1200,675])

draw = ImageDraw.Draw(img)

try:
    font = ImageFont.truetype("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 90)
except:
    font = ImageFont.load_default()

text = "$TEXT"

bbox = draw.textbbox((0,0), text, font=font)
w = bbox[2] - bbox[0]
h = bbox[3] - bbox[1]

x = (1200 - w) // 2
y = (675 - h) // 2

draw.text((x,y), text, fill=(255,255,255), font=font)

img.save("/tmp/thumb.jpg")
print("/tmp/thumb.jpg")
PY
