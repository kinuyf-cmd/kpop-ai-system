"""
K-POP JOURNAL サムネイル生成スクリプト v4

Usage:
  python3 make_thumbnail.py "テキスト"
  python3 make_thumbnail.py "テキスト" --genre breaking
  python3 make_thumbnail.py "テキスト" --genre breaking --title "元タイトル"

v4変更点:
  - 10文字/行 制限（旧14文字）
  - 左寄せ固定（中央配置禁止）
  - 4px ストローク固定
  - ドロップシャドウ blur 10px
  - 帯 opacity 0.75-0.85
  - 煽りフォントも Black 統一
  - 10パターン戦略対応
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import sys
import os

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

# ── Safe area ──
SAFE_LEFT = 80
SAFE_RIGHT = 1120
SAFE_TOP = 80
SAFE_BOTTOM = 550
MAX_CHARS_PER_LINE = 10
MAX_LINES = 2

# ── フォント ──
FONT_DIR = "/home/aiuser/.local/share/fonts"
ASSETS_DIR = "/home/aiuser/kpop-ai-system/assets/thumbnails"

FONT_MAIN = None

# メインフォント: NotoSansJP-Black のみ (全テキスト統一)
for p in [
    f"{FONT_DIR}/NotoSansJP-Black.ttf",
    f"{FONT_DIR}/NotoSansJP-ExtraBold.ttf",
    f"{FONT_DIR}/NotoSansJP-Bold.ttf",
    f"{FONT_DIR}/NotoSansJP.ttf",
]:
    try:
        ImageFont.truetype(p, 40)
        FONT_MAIN = p
        break
    except Exception:
        pass


def get_font(size):
    if FONT_MAIN:
        return ImageFont.truetype(FONT_MAIN, size)
    return ImageFont.load_default()


# ── 10パターン定義 ──
# パターン名 → (背景ファイル, バッジ, 帯色, テキスト色, ストローク色)
PATTERNS = {
    "breaking": {
        "bg": "news.png",
        "badge": "BREAKING",
        "badge_bg": (220, 40, 40, 220),
        "badge_fg": (255, 255, 255),
        "band_color": (0, 0, 0),
        "band_opacity": 200,  # 0.78
        "text_color": (255, 255, 255),
        "stroke_color": (0, 0, 0),
        "highlight_color": (255, 230, 50),
    },
    "comeback": {
        "bg": "comeback.png",
        "badge": "COMEBACK",
        "badge_bg": (102, 50, 200, 220),
        "badge_fg": (255, 255, 255),
        "band_color": (20, 10, 40),
        "band_opacity": 195,
        "text_color": (255, 255, 255),
        "stroke_color": (0, 0, 0),
        "highlight_color": (180, 140, 255),
    },
    "ranking": {
        "bg": "analysis.png",
        "badge": "RANKING",
        "badge_bg": (255, 200, 50, 220),
        "badge_fg": (30, 30, 30),
        "band_color": (0, 0, 0),
        "band_opacity": 200,
        "text_color": (255, 255, 255),
        "stroke_color": (0, 0, 0),
        "highlight_color": (255, 210, 60),
    },
    "expose": {
        "bg": "news.png",
        "badge": "EXCLUSIVE",
        "badge_bg": (60, 60, 80, 220),
        "badge_fg": (255, 255, 255),
        "band_color": (10, 10, 20),
        "band_opacity": 210,
        "text_color": (255, 255, 255),
        "stroke_color": (0, 0, 0),
        "highlight_color": (255, 100, 100),
    },
    "oshikatsu": {
        "bg": "comeback.png",
        "badge": "LOVE",
        "badge_bg": (255, 120, 170, 220),
        "badge_fg": (255, 255, 255),
        "band_color": (40, 10, 30),
        "band_opacity": 190,
        "text_color": (255, 255, 255),
        "stroke_color": (0, 0, 0),
        "highlight_color": (255, 180, 220),
    },
    "beauty": {
        "bg": "beauty.png",
        "badge": "BEAUTY",
        "badge_bg": (180, 100, 140, 200),
        "badge_fg": (255, 255, 255),
        "band_color": (255, 245, 240),
        "band_opacity": 210,
        "text_color": (40, 30, 35),
        "stroke_color": (255, 255, 255),
        "highlight_color": (200, 50, 100),
    },
    "live": {
        "bg": "live.png",
        "badge": "LIVE",
        "badge_bg": (255, 100, 50, 220),
        "badge_fg": (255, 255, 255),
        "band_color": (0, 0, 0),
        "band_opacity": 200,
        "text_color": (255, 255, 255),
        "stroke_color": (0, 0, 0),
        "highlight_color": (0, 255, 200),
    },
    "analysis": {
        "bg": "analysis.png",
        "badge": "ANALYSIS",
        "badge_bg": (80, 80, 100, 220),
        "badge_fg": (255, 255, 255),
        "band_color": (0, 0, 0),
        "band_opacity": 200,
        "text_color": (255, 255, 255),
        "stroke_color": (0, 0, 0),
        "highlight_color": (100, 200, 255),
    },
    "beginner": {
        "bg": "live.png",
        "badge": "GUIDE",
        "badge_bg": (50, 180, 120, 220),
        "badge_fg": (255, 255, 255),
        "band_color": (0, 0, 0),
        "band_opacity": 195,
        "text_color": (255, 255, 255),
        "stroke_color": (0, 0, 0),
        "highlight_color": (100, 255, 180),
    },
    "buzz": {
        "bg": "news.png",
        "badge": "BUZZ",
        "badge_bg": (255, 50, 100, 230),
        "badge_fg": (255, 255, 255),
        "band_color": (0, 0, 0),
        "band_opacity": 195,
        "text_color": (255, 255, 255),
        "stroke_color": (0, 0, 0),
        "highlight_color": (255, 255, 0),
    },
}

DEFAULT_PATTERN = "breaking"


def detect_genre(text, title=""):
    """テキストからジャンルを自動判定（10パターン）"""
    combined = (text + " " + title).lower()

    # beauty
    if any(w in combined for w in ["美容", "コスメ", "スキンケア", "メイク", "ガラス肌", "韓国コスメ", "真似したい"]):
        return "beauty"
    # expose (裏側・暴露)
    if any(w in combined for w in ["暴露", "裏側", "真相", "告白", "独占", "内部", "闇"]):
        return "expose"
    # breaking (速報・衝撃)
    if any(w in combined for w in ["速報", "緊急", "判明", "発表", "解禁", "衝撃", "電撃", "まさか"]):
        return "breaking"
    # comeback
    if any(w in combined for w in ["カムバック", "comeback", "新曲", "アルバム", "復帰", "復活", "新章"]):
        return "comeback"
    # ranking
    if any(w in combined for w in ["チャート", "ランキング", "1位", "chart", "順位", "比較", "どっち"]):
        return "ranking"
    # live
    if any(w in combined for w in ["ライブ", "ツアー", "コンサート", "公演", "ファンミ", "フェス", "来日", "日本上陸"]):
        return "live"
    # oshikatsu
    if any(w in combined for w in ["推し", "尊い", "神", "沼", "ファン", "感動", "号泣"]):
        return "oshikatsu"
    # analysis
    if any(w in combined for w in ["解説", "考察", "分析", "なぜ", "理由", "結論"]):
        return "analysis"
    # beginner
    if any(w in combined for w in ["初心者", "入門", "5分で", "無料", "簡単", "ハウツー", "ガイド"]):
        return "beginner"
    # controversy → expose
    if any(w in combined for w in ["炎上", "騒動", "脱退", "訴訟", "逮捕", "事件"]):
        return "expose"
    # buzz
    if any(w in combined for w in ["バズ", "レベチ", "バグ", "やばい", "ヤバい", "話題"]):
        return "buzz"
    # fashion → comeback
    if any(w in combined for w in ["ファッション", "着用", "ブランド", "即完売", "コーデ"]):
        return "comeback"
    # travel → live
    if any(w in combined for w in ["旅行", "ソウル", "カフェ", "聖地巡礼"]):
        return "live"
    return "breaking"


def create_gradient(w, h, color_top, color_bottom):
    """フォールバック用: 滑らかな縦グラデーション画像を生成"""
    img = Image.new("RGB", (w, h))
    for y in range(h):
        ratio = y / h
        ratio = ratio * ratio * (3 - 2 * ratio)
        r = int(color_top[0] + (color_bottom[0] - color_top[0]) * ratio)
        g = int(color_top[1] + (color_bottom[1] - color_top[1]) * ratio)
        b = int(color_top[2] + (color_bottom[2] - color_top[2]) * ratio)
        ImageDraw.Draw(img).line([(0, y), (w, y)], fill=(r, g, b))
    return img


# フォールバックグラデーション色
GRAD_FALLBACK = {
    "breaking":  ((180, 30, 30), (60, 10, 10)),
    "comeback":  ((60, 30, 120), (30, 15, 80)),
    "ranking":   ((30, 30, 50), (60, 50, 90)),
    "expose":    ((40, 40, 50), (20, 20, 30)),
    "oshikatsu": ((120, 40, 80), (60, 20, 50)),
    "beauty":    ((255, 230, 220), (255, 200, 210)),
    "live":      ((30, 30, 30), (50, 30, 20)),
    "analysis":  ((50, 50, 60), (30, 30, 40)),
    "beginner":  ((20, 80, 60), (10, 50, 40)),
    "buzz":      ((180, 20, 60), (100, 10, 30)),
}


def load_background(pattern):
    """テンプレート背景を読み込む。なければフォールバックグラデーション"""
    bg_file = pattern.get("bg", "news.png")
    bg_path = os.path.join(ASSETS_DIR, bg_file)

    if os.path.exists(bg_path):
        img = Image.open(bg_path).convert("RGB")
        img = img.resize((W, H), Image.LANCZOS)
        return img

    # フォールバック
    genre_key = DEFAULT_PATTERN
    for k, p in PATTERNS.items():
        if p is pattern:
            genre_key = k
            break
    colors = GRAD_FALLBACK.get(genre_key, ((30, 30, 30), (10, 10, 10)))
    return create_gradient(W, H, colors[0], colors[1])


def truncate_line(text, max_chars=MAX_CHARS_PER_LINE):
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1] + "…"


def auto_split_text(text):
    """テキストを自動的に2行に分割（各行最大10文字）"""
    text = text.strip()

    if "\n" in text:
        parts = text.split("\n", 1)
        line1 = truncate_line(parts[0].strip())
        line2 = truncate_line(parts[1].strip()) if len(parts) > 1 else ""
        lines = [line1]
        if line2:
            lines.append(line2)
        return lines

    if len(text) <= MAX_CHARS_PER_LINE:
        return [text]

    # 自然な分割点を探す
    particles = ["の", "は", "が", "を", "に", "で", "と", "も"]
    punctuation = ["、", "！", "？", " ", "　"]

    best_pos = -1
    best_score = -1
    target = len(text) / 2

    for particle in particles:
        start = 0
        while True:
            pos = text.find(particle, start)
            if pos == -1:
                break
            split_at = pos + len(particle)
            if split_at <= MAX_CHARS_PER_LINE and len(text) - split_at <= MAX_CHARS_PER_LINE:
                score = 100 - abs(split_at - target)
                if score > best_score:
                    best_score = score
                    best_pos = split_at
            start = pos + 1

    for punct in punctuation:
        start = 0
        while True:
            pos = text.find(punct, start)
            if pos == -1:
                break
            split_at = pos + len(punct)
            if split_at <= MAX_CHARS_PER_LINE and len(text) - split_at <= MAX_CHARS_PER_LINE:
                score = 200 - abs(split_at - target)
                if score > best_score:
                    best_score = score
                    best_pos = split_at
            start = pos + 1

    if best_pos > 0:
        line1 = text[:best_pos].strip()
        line2 = text[best_pos:].strip()
        return [truncate_line(line1), truncate_line(line2)]

    mid = min(MAX_CHARS_PER_LINE, len(text) // 2)
    return [truncate_line(text[:mid]), truncate_line(text[mid:])]


# ── 強ワード ──
STRONG_WORDS = ["衝撃", "速報", "判明", "神", "炎上", "ついに", "電撃",
                "復活", "決定", "解禁", "初公開", "大反響", "騒然",
                "レベチ", "バグ", "尊い", "まさか", "完全", "即完売"]


def split_for_highlight(line_text, highlight_color):
    """テキストをハイライト区間と通常区間に分割"""
    segments = []
    buf = ""
    i = 0
    while i < len(line_text):
        # 数字列
        if line_text[i].isdigit() or line_text[i] in "０１２３４５６７８９":
            if buf:
                segments.append((buf, None))
                buf = ""
            num_buf = line_text[i]
            i += 1
            while i < len(line_text) and (line_text[i].isdigit() or line_text[i] in "万億千百冠年月日位選曲本人回組枚ぶり"):
                num_buf += line_text[i]
                i += 1
            segments.append((num_buf, highlight_color))
            continue
        # 強ワード
        matched_sw = None
        for sw in sorted(STRONG_WORDS, key=len, reverse=True):
            if line_text[i:i+len(sw)] == sw:
                matched_sw = sw
                break
        if matched_sw:
            if buf:
                segments.append((buf, None))
                buf = ""
            segments.append((matched_sw, highlight_color))
            i += len(matched_sw)
            continue
        buf += line_text[i]
        i += 1
    if buf:
        segments.append((buf, None))
    return segments


def draw_text_with_stroke(draw, position, text, font, fill,
                          stroke_width=4, stroke_fill=(0, 0, 0)):
    """テキストをストローク付きで描画（4px固定）"""
    x, y = position
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=stroke_fill)
    draw.text((x, y), text, font=font, fill=fill)


def draw_shadow_layer(img, text, position, font, blur_radius=10, shadow_alpha=120):
    """ドロップシャドウを blur で生成"""
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    x, y = position
    sd.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0, shadow_alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    return Image.alpha_composite(img.convert("RGBA"), shadow)


def draw_thumbnail(text, genre_key, full_title=""):
    pat = PATTERNS.get(genre_key, PATTERNS[DEFAULT_PATTERN])

    # ── 背景 ──
    img = load_background(pat)

    draw = ImageDraw.Draw(img)

    # ── 左上ロゴ ──
    font_logo = get_font(18)
    logo_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    logo_draw = ImageDraw.Draw(logo_overlay)
    logo_draw.rounded_rectangle(
        (30, 22, 200, 52), radius=14,
        fill=(255, 255, 255, 190)
    )
    img = Image.alpha_composite(img.convert("RGBA"), logo_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    draw.text((44, 26), "K-POP JOURNAL", fill=(60, 60, 60), font=font_logo)

    # ── 右上バッジ ──
    label = pat["badge"]
    font_badge = get_font(17)
    badge_bbox = draw.textbbox((0, 0), label, font=font_badge)
    badge_tw = badge_bbox[2] - badge_bbox[0]
    badge_w = badge_tw + 30
    badge_x = W - badge_w - 30

    badge_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    badge_draw = ImageDraw.Draw(badge_overlay)
    badge_draw.rounded_rectangle(
        (badge_x, 22, badge_x + badge_w, 52), radius=14,
        fill=tuple(pat["badge_bg"])
    )
    img = Image.alpha_composite(img.convert("RGBA"), badge_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    draw.text(
        (badge_x + 15, 26), label,
        fill=pat["badge_fg"], font=font_badge
    )

    # ── テキスト処理 ──
    lines = auto_split_text(text)

    if len(lines) >= 2:
        sub_line = lines[0]
        main_line = lines[1]
    else:
        sub_line = ""
        main_line = lines[0]

    # フォントサイズ（10文字制限に最適化）
    main_len = len(main_line)
    if main_len <= 5:
        main_size = 110
    elif main_len <= 7:
        main_size = 95
    elif main_len <= 10:
        main_size = 78
    else:
        main_size = 64

    sub_size = 38  # 煽りも Black フォント

    font_main_text = get_font(main_size)
    font_sub_text = get_font(sub_size)  # Black 統一

    stroke_color = pat["stroke_color"]
    text_color = pat["text_color"]
    highlight_color = pat["highlight_color"]

    # ── レイアウト計算（左寄せ）──
    TEXT_LEFT = SAFE_LEFT + 20

    main_bbox = draw.textbbox((0, 0), main_line, font=font_main_text)
    main_w = main_bbox[2] - main_bbox[0]
    main_h = main_bbox[3] - main_bbox[1]

    if sub_line:
        sub_bbox = draw.textbbox((0, 0), sub_line, font=font_sub_text)
        sub_w = sub_bbox[2] - sub_bbox[0]
        sub_h = sub_bbox[3] - sub_bbox[1]
    else:
        sub_w, sub_h = 0, 0

    gap_between = 16 if sub_line else 0
    total_h = sub_h + gap_between + main_h

    # 垂直配置: やや上寄せ
    block_y = (H - total_h) // 2 - 20
    block_y = max(SAFE_TOP + 10, block_y)

    sub_y = block_y
    main_y = block_y + sub_h + gap_between if sub_line else block_y

    # ── 帯（半透明背景 opacity 0.75-0.85） ──
    band_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    band_draw = ImageDraw.Draw(band_overlay)
    band_pad_x = 36
    band_pad_y = 22
    band_top = block_y - band_pad_y
    band_bottom = main_y + main_h + band_pad_y
    band_right = TEXT_LEFT + max(main_w, sub_w) + band_pad_x * 2
    band_right = min(band_right, W - 50)
    bc = pat["band_color"]
    bo = pat["band_opacity"]
    band_draw.rounded_rectangle(
        (TEXT_LEFT - band_pad_x, band_top, band_right, band_bottom),
        radius=10, fill=(bc[0], bc[1], bc[2], bo)
    )
    img = Image.alpha_composite(img.convert("RGBA"), band_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── ドロップシャドウ (blur 10px) ──
    is_light = genre_key == "beauty"
    shadow_alpha = 60 if is_light else 140

    if sub_line:
        img = draw_shadow_layer(
            img, sub_line, (TEXT_LEFT, sub_y), font_sub_text,
            blur_radius=10, shadow_alpha=shadow_alpha
        )
        img = img.convert("RGB")
        draw = ImageDraw.Draw(img)

    # メインテキストのシャドウ
    img = draw_shadow_layer(
        img, main_line, (TEXT_LEFT, main_y), font_main_text,
        blur_radius=10, shadow_alpha=shadow_alpha
    )
    img = img.convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── 煽りテキスト描画（Black フォント統一）──
    if sub_line:
        draw_text_with_stroke(
            draw, (TEXT_LEFT, sub_y), sub_line, font_sub_text,
            fill=text_color, stroke_width=4, stroke_fill=stroke_color
        )

    # ── メインテキスト描画（色分け）──
    segments = split_for_highlight(main_line, highlight_color)
    cx = TEXT_LEFT
    for seg_text, seg_color in segments:
        fill = seg_color if seg_color else text_color
        draw_text_with_stroke(
            draw, (cx, main_y), seg_text, font_main_text,
            fill=fill, stroke_width=4, stroke_fill=stroke_color
        )
        seg_bbox = draw.textbbox((0, 0), seg_text, font=font_main_text)
        cx += seg_bbox[2] - seg_bbox[0]

    # ── 下部アクセントライン ──
    bar_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bar_draw = ImageDraw.Draw(bar_overlay)
    bar_w = min(main_w + 60, W - 160)
    bar_x = TEXT_LEFT
    bar_y = H - 32
    bar_draw.rounded_rectangle(
        (bar_x, bar_y, bar_x + bar_w, bar_y + 4),
        radius=2, fill=(255, 255, 255, 130)
    )
    img = Image.alpha_composite(img.convert("RGBA"), bar_overlay).convert("RGB")

    return img


# ── メイン実行 ──
if genre is None:
    genre = detect_genre(thumb_text, full_title)

# パターンに無いジャンルはフォールバック
if genre not in PATTERNS:
    genre = DEFAULT_PATTERN

img = draw_thumbnail(thumb_text, genre, full_title)
img.save("thumbnail.webp", format="WEBP", quality=85)
img.save("thumbnail.jpg", format="JPEG", quality=95)
print(f"thumbnail.webp / thumbnail.jpg を作成しました (genre={genre}, text='{thumb_text}')")
