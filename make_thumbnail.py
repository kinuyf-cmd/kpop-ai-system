"""
K-POP JOURNAL サムネイル生成スクリプト

Usage:
  python3 make_thumbnail.py "テキスト"                       # 自動判定
  python3 make_thumbnail.py "テキスト" --genre breaking      # ジャンル指定
  python3 make_thumbnail.py "テキスト" --genre chart --title "元タイトル"

仕様: 1200x630, Noto Sans JP Bold, ジャンル別配色
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import sys
import re

# ── 引数 ──
thumb_text = sys.argv[1] if len(sys.argv) > 1 else "K-POP NEWS"
genre = None
full_title = ""

for i, arg in enumerate(sys.argv):
    if arg == "--genre" and i + 1 < len(sys.argv):
        genre = sys.argv[i + 1]
    if arg == "--title" and i + 1 < len(sys.argv):
        full_title = sys.argv[i + 1]

W, H = 1200, 630

# ── フォント ──
FONT_PATH = None
font_candidates = [
    "/home/aiuser/.local/share/fonts/NotoSansJP.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansCJKjp-Bold.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
]
for p in font_candidates:
    try:
        ImageFont.truetype(p, 40)
        FONT_PATH = p
        break
    except Exception:
        pass

if FONT_PATH is None:
    print("WARNING: 日本語フォントが見つかりません。デフォルトフォントを使用します。")
    FONT_PATH = None


def get_font(size):
    if FONT_PATH:
        return ImageFont.truetype(FONT_PATH, size)
    return ImageFont.load_default()


# ── ジャンル別配色 ──
GENRE_STYLES = {
    "breaking":   {"bg": (229, 62, 62),   "text": (255, 255, 255), "accent": (255, 200, 200), "label": "BREAKING"},
    "comeback":   {"bg": (49, 130, 206),  "text": (255, 255, 255), "accent": (190, 220, 255), "label": "COMEBACK"},
    "analysis":   {"bg": (128, 90, 213),  "text": (255, 255, 255), "accent": (200, 180, 255), "label": "ANALYSIS"},
    "live":       {"bg": (26, 32, 44),    "text": (214, 158, 46),  "accent": (255, 220, 100), "label": "LIVE"},
    "controversy":{"bg": (113, 128, 150), "text": (229, 62, 62),   "accent": (255, 150, 150), "label": "ISSUE"},
    "ranking":    {"bg": (42, 67, 101),   "text": (236, 201, 75),  "accent": (255, 230, 120), "label": "RANKING"},
    "streaming":  {"bg": (56, 161, 105),  "text": (255, 255, 255), "accent": (180, 255, 220), "label": "STREAMING"},
    "comparison": {"bg": (221, 107, 32),  "text": (255, 255, 255), "accent": (255, 210, 170), "label": "COMPARE"},
    "special":    {"bg": (26, 54, 93),    "text": (255, 255, 255), "accent": (180, 200, 255), "label": "SPECIAL"},
    "debut":      {"bg": (237, 100, 166), "text": (255, 255, 255), "accent": (255, 200, 230), "label": "DEBUT"},
    "chart":      {"bg": (0, 0, 0),       "text": (0, 181, 216),   "accent": (100, 220, 240), "label": "CHART"},
}

DEFAULT_STYLE = {"bg": (229, 62, 62), "text": (255, 255, 255), "accent": (255, 200, 200), "label": "NEWS"}


def detect_genre(text, title=""):
    """テキストとタイトルからジャンルを自動判定"""
    combined = (text + " " + title).lower()

    if any(w in combined for w in ["速報", "緊急", "判明", "発表", "解禁"]):
        return "breaking"
    if any(w in combined for w in ["カムバック", "comeback", "新曲", "アルバム", "mv"]):
        return "comeback"
    if any(w in combined for w in ["チャート", "ランキング", "1位", "chart", "順位"]):
        return "chart"
    if any(w in combined for w in ["ライブ", "ツアー", "コンサート", "公演", "ファンミ", "フェス"]):
        return "live"
    if any(w in combined for w in ["炎上", "騒動", "脱退", "訴訟", "逮捕", "事件"]):
        return "controversy"
    if any(w in combined for w in ["ランキング", "top", "best", "順位"]):
        return "ranking"
    if any(w in combined for w in ["視聴", "配信", "見る方法", "無料", "見逃し"]):
        return "streaming"
    if any(w in combined for w in ["比較", "おすすめ", "vs", "どっち"]):
        return "comparison"
    if any(w in combined for w in ["特集", "まとめ", "完全ガイド"]):
        return "special"
    if any(w in combined for w in ["デビュー", "debut", "新人", "練習生"]):
        return "debut"
    if any(w in combined for w in ["解説", "考察", "分析", "なぜ", "理由"]):
        return "analysis"
    return "breaking"


def hex_to_rgb(hex_str):
    hex_str = hex_str.lstrip('#')
    return tuple(int(hex_str[i:i+2], 16) for i in (0, 2, 4))


def draw_thumbnail(text, genre_key, full_title=""):
    style = GENRE_STYLES.get(genre_key, DEFAULT_STYLE)
    bg_color = style["bg"]
    text_color = style["text"]
    accent_color = style["accent"]
    label = style["label"]

    img = Image.new("RGB", (W, H), bg_color)
    draw = ImageDraw.Draw(img)

    # ── 背景パターン（対角線のグラデーション効果）──
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    # 大きな円形グラデーション（右下）
    glow_color = (*accent_color, 60)
    odraw.ellipse((W-400, H-300, W+200, H+200), fill=glow_color)
    # 小さな円形グラデーション（左上）
    glow_color2 = (*accent_color, 35)
    odraw.ellipse((-150, -100, 350, 250), fill=glow_color2)
    overlay = overlay.filter(ImageFilter.GaussianBlur(80))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── 上部：K-POP JOURNAL ロゴ + ジャンルバッジ ──
    font_logo = get_font(22)
    font_badge = get_font(20)

    # ロゴ（左上）
    brightness = sum(bg_color)
    if brightness < 200:
        logo_bg = (255, 255, 255, 200)
        logo_color = (30, 30, 30)
    elif brightness < 400:
        logo_bg = (0, 0, 0, 160)
        logo_color = (255, 255, 255)
    else:
        logo_bg = (0, 0, 0, 180)
        logo_color = (255, 255, 255)
    # RGBA背景をRGBに変換して描画
    logo_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    logo_draw = ImageDraw.Draw(logo_overlay)
    logo_draw.rounded_rectangle((30, 25, 220, 60), radius=8, fill=logo_bg)
    img = Image.alpha_composite(img.convert("RGBA"), logo_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    draw.text((42, 30), "K-POP JOURNAL", fill=logo_color, font=font_logo)

    # ジャンルバッジ（右上）
    badge_w = len(label) * 16 + 30
    badge_x = W - badge_w - 30
    badge_bg = text_color  # テキスト色をバッジ背景に
    badge_fg = bg_color    # 背景色をバッジテキストに（コントラスト）
    draw.rounded_rectangle((badge_x, 25, badge_x + badge_w, 60), radius=8, fill=badge_bg)
    draw.text((badge_x + 15, 30), label, fill=badge_fg, font=font_badge)

    # ── メインテキスト（中央配置、大きく）──
    # テキスト長に応じてフォントサイズを動的調整
    text_len = len(text)
    if text_len <= 4:
        main_size = 140
    elif text_len <= 6:
        main_size = 120
    elif text_len <= 8:
        main_size = 100
    elif text_len <= 10:
        main_size = 85
    else:
        main_size = 70

    font_main = get_font(main_size)

    # テキストサイズ計測
    bbox = draw.textbbox((0, 0), text, font=font_main)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    # 画面幅に収まらない場合はフォント縮小
    while tw > W - 120 and main_size > 40:
        main_size -= 10
        font_main = get_font(main_size)
        bbox = draw.textbbox((0, 0), text, font=font_main)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

    tx = (W - tw) // 2
    ty = (H - th) // 2 - 20

    # グロー効果
    glow_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_img)
    glow_fill = (*text_color, 80)
    for dx in range(-4, 5, 2):
        for dy in range(-4, 5, 2):
            glow_draw.text((tx + dx, ty + dy), text, font=font_main, fill=glow_fill)
    glow_img = glow_img.filter(ImageFilter.GaussianBlur(12))
    img = Image.alpha_composite(img.convert("RGBA"), glow_img).convert("RGB")
    draw = ImageDraw.Draw(img)

    # メインテキスト描画
    draw.text((tx, ty), text, fill=text_color, font=font_main)

    # ── 下部アクセントライン ──
    line_color = text_color
    line_y = H - 35
    line_w = min(tw + 60, W - 100)
    line_x = (W - line_w) // 2
    draw.rounded_rectangle((line_x, line_y, line_x + line_w, line_y + 6), radius=3, fill=line_color)

    # ── 下部にサブテキスト（元タイトルから抽出）──
    if full_title and full_title != text:
        font_sub = get_font(24)
        sub = full_title.replace(text, "").strip("｜|- 　・")
        if len(sub) > 35:
            sub = sub[:35] + "..."
        if sub:
            sub_bbox = draw.textbbox((0, 0), sub, font=font_sub)
            sub_w = sub_bbox[2] - sub_bbox[0]
            sub_x = (W - sub_w) // 2
            sub_color = (*text_color[:3],) if len(text_color) == 3 else text_color
            # 半透明背景
            sub_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            sub_od = ImageDraw.Draw(sub_overlay)
            sub_alpha = 100 if brightness > 300 else 140
            sub_od.rounded_rectangle(
                (sub_x - 15, H - 80, sub_x + sub_w + 15, H - 50),
                radius=6, fill=(0, 0, 0, sub_alpha)
            )
            img = Image.alpha_composite(img.convert("RGBA"), sub_overlay).convert("RGB")
            draw = ImageDraw.Draw(img)
            draw.text((sub_x, H - 77), sub, fill=sub_color, font=font_sub)

    return img


# ── メイン実行 ──
if genre is None:
    genre = detect_genre(thumb_text, full_title)

img = draw_thumbnail(thumb_text, genre, full_title)
img.save("thumbnail.jpg", quality=95)
print(f"thumbnail.jpg を作成しました (genre={genre}, text='{thumb_text}')")
