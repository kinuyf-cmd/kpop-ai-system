#!/usr/bin/env python3
"""月次集約ページ用サムネ生成 (Pillow ベース, 1200x675)"""
import os
from datetime import datetime

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


def _get_font(size):
    """利用可能なフォントを探す"""
    font_paths = [
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                pass
    return ImageFont.load_default()


def generate_roundup_thumbnail(year, month, jp_count, kr_count, gl_count, output_path):
    """月次集約サムネを生成 (1200x675, グラデーション背景)"""
    if not HAS_PILLOW:
        print("  Pillow未インストール、サムネ生成skip")
        return False

    W, H = 1200, 675
    img = Image.new('RGB', (W, H))
    draw = ImageDraw.Draw(img)

    # グラデーション背景 (ピンク→紫→青)
    for y in range(H):
        r = int(255 - (255 - 59) * y / H)
        g = int(20 + (51 - 20) * y / H * 0.5)
        b = int(147 + (246 - 147) * y / H)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    font_huge = _get_font(140)
    font_big = _get_font(42)
    font_med = _get_font(28)
    font_sm = _get_font(20)

    # 年
    text_year = f"{year}"
    draw.text((W // 2, 50), text_year, font=font_big, fill='white', anchor='mt')

    # 月 (巨大)
    text_month = f"{month}"
    draw.text((W // 2, 120), text_month, font=font_huge, fill='white', anchor='mt')

    # タイトル
    draw.text((W // 2, 310), "K-POP", font=font_big, fill='white', anchor='mt')
    draw.text((W // 2, 370), "POPUP COMPLETE MAP", font=font_med, fill=(255, 255, 255, 200), anchor='mt')

    # 件数バー
    stats_y = 450
    bar_w = 200
    gap = 40
    start_x = (W - bar_w * 3 - gap * 2) // 2

    for i, (emoji, count, label) in enumerate([
        ('JP', jp_count, 'JAPAN'),
        ('KR', kr_count, 'KOREA'),
        ('GL', gl_count, 'GLOBAL'),
    ]):
        x = start_x + i * (bar_w + gap)
        # 半透明バー
        for dy in range(70):
            alpha_r = min(255, 255)
            draw.rectangle(
                [(x, stats_y + dy), (x + bar_w, stats_y + dy + 1)],
                fill=(255, 255, 255, 30),
            )
        draw.rounded_rectangle(
            [(x, stats_y), (x + bar_w, stats_y + 70)],
            radius=12, outline=(255, 255, 255, 100), width=1,
        )
        draw.text((x + bar_w // 2, stats_y + 10), f"{count}", font=font_big, fill='white', anchor='mt')
        draw.text((x + bar_w // 2, stats_y + 50), label, font=font_sm, fill=(255, 255, 255, 200), anchor='mt')

    # ブランド
    draw.text((W // 2, H - 40), "KPOP JOURNAL", font=font_sm, fill=(255, 255, 255, 180), anchor='mt')

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    img.save(output_path, 'PNG')
    return os.path.exists(output_path)
