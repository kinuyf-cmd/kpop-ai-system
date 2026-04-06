"""
K-POP JOURNAL サムネイル生成スクリプト v3

Usage:
  python3 make_thumbnail.py "テキスト"
  python3 make_thumbnail.py "テキスト" --genre breaking
  python3 make_thumbnail.py "テキスト" --genre breaking --title "元タイトル"

仕様: 1200x630, NotoSansJP-Black (メイン)
      テンプレート背景画像, 2行制限 (14文字/行), 固定レイアウト
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import sys
import os
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

# ── Safe area ──
SAFE_LEFT = 80
SAFE_RIGHT = 1120
SAFE_TOP = 80
SAFE_BOTTOM = 550
MAX_CHARS_PER_LINE = 14
MAX_LINES = 2
LINE_GAP = 16

# ── フォント ──
FONT_DIR = "/home/aiuser/.local/share/fonts"
ASSETS_DIR = "/home/aiuser/kpop-ai-system/assets/thumbnails"

FONT_MAIN = None
FONT_SUB = None

# メインフォント: NotoSansJP-Black (太く、インパクト重視)
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

# サブフォント: Noto Sans JP Bold (ロゴ・バッジ用)
for p in [
    f"{FONT_DIR}/NotoSansJP-Bold.ttf",
    f"{FONT_DIR}/NotoSansJP.ttf",
]:
    try:
        ImageFont.truetype(p, 40)
        FONT_SUB = p
        break
    except Exception:
        pass

if FONT_MAIN is None:
    FONT_MAIN = FONT_SUB


def get_font_main(size):
    if FONT_MAIN:
        return ImageFont.truetype(FONT_MAIN, size)
    return ImageFont.load_default()


def get_font_sub(size):
    if FONT_SUB:
        return ImageFont.truetype(FONT_SUB, size)
    return ImageFont.load_default()


# ── ジャンル → 背景ファイル マッピング ──
GENRE_BG_MAP = {
    "breaking": "news.png",
    "controversy": "news.png",
    "comeback": "comeback.png",
    "debut": "comeback.png",
    "analysis": "analysis.png",
    "special": "analysis.png",
    "chart": "analysis.png",
    "ranking": "analysis.png",
    "comparison": "analysis.png",
    "live": "live.png",
    "streaming": "live.png",
    "beauty": "beauty.png",
}
DEFAULT_BG = "news.png"

# ── ジャンル → バッジラベル ──
GENRE_LABELS = {
    "breaking": "BREAKING",
    "controversy": "ISSUE",
    "comeback": "COMEBACK",
    "debut": "DEBUT",
    "analysis": "ANALYSIS",
    "special": "SPECIAL",
    "chart": "CHART",
    "ranking": "RANKING",
    "comparison": "COMPARE",
    "live": "LIVE",
    "streaming": "STREAMING",
    "beauty": "BEAUTY",
    "travel": "TRAVEL",
    "fashion": "FASHION",
}

# ── ジャンル別配色 (バッジ用 + フォールバックグラデーション用) ──
GENRE_STYLES = {
    "breaking": {
        "grad_top": (255, 107, 129),
        "grad_bottom": (255, 154, 139),
        "label_bg": (255, 107, 129, 200),
        "label_fg": (255, 255, 255),
    },
    "controversy": {
        "grad_top": (108, 117, 137),
        "grad_bottom": (148, 157, 177),
        "label_bg": (255, 107, 129, 200),
        "label_fg": (255, 255, 255),
    },
    "comeback": {
        "grad_top": (102, 126, 234),
        "grad_bottom": (139, 172, 255),
        "label_bg": (102, 126, 234, 200),
        "label_fg": (255, 255, 255),
    },
    "debut": {
        "grad_top": (255, 134, 179),
        "grad_bottom": (255, 177, 209),
        "label_bg": (255, 134, 179, 200),
        "label_fg": (255, 255, 255),
    },
    "analysis": {
        "grad_top": (167, 119, 227),
        "grad_bottom": (192, 155, 247),
        "label_bg": (167, 119, 227, 200),
        "label_fg": (255, 255, 255),
    },
    "special": {
        "grad_top": (102, 126, 234),
        "grad_bottom": (167, 119, 227),
        "label_bg": (120, 120, 230, 200),
        "label_fg": (255, 255, 255),
    },
    "chart": {
        "grad_top": (30, 30, 50),
        "grad_bottom": (60, 50, 90),
        "label_bg": (100, 220, 255, 200),
        "label_fg": (30, 30, 50),
    },
    "ranking": {
        "grad_top": (255, 185, 56),
        "grad_bottom": (255, 210, 110),
        "label_bg": (60, 40, 10, 180),
        "label_fg": (255, 210, 110),
    },
    "comparison": {
        "grad_top": (255, 159, 67),
        "grad_bottom": (255, 190, 120),
        "label_bg": (255, 159, 67, 200),
        "label_fg": (255, 255, 255),
    },
    "live": {
        "grad_top": (255, 154, 86),
        "grad_bottom": (255, 183, 122),
        "label_bg": (255, 154, 86, 200),
        "label_fg": (255, 255, 255),
    },
    "streaming": {
        "grad_top": (72, 199, 154),
        "grad_bottom": (120, 224, 180),
        "label_bg": (72, 199, 154, 200),
        "label_fg": (255, 255, 255),
    },
    "beauty": {
        "grad_top": (255, 182, 193),
        "grad_bottom": (255, 218, 224),
        "label_bg": (255, 130, 170, 200),
        "label_fg": (255, 255, 255),
    },
    "travel": {
        "grad_top": (255, 154, 86),
        "grad_bottom": (255, 183, 122),
        "label_bg": (255, 154, 86, 200),
        "label_fg": (255, 255, 255),
    },
    "fashion": {
        "grad_top": (102, 126, 234),
        "grad_bottom": (139, 172, 255),
        "label_bg": (102, 126, 234, 200),
        "label_fg": (255, 255, 255),
    },
}

DEFAULT_STYLE = GENRE_STYLES["breaking"]


def detect_genre(text, title=""):
    """テキストからジャンルを自動判定"""
    combined = (text + " " + title).lower()
    # beauty (美容系)
    if any(w in combined for w in ["美容", "コスメ", "スキンケア", "メイク", "ガラス肌", "化粧", "韓国コスメ"]):
        return "beauty"
    # travel (旅行系) → live背景を流用
    if any(w in combined for w in ["旅行", "ソウル", "カフェ"]):
        return "travel"
    # fashion → comeback背景を流用
    if any(w in combined for w in ["ファッション", "着用", "ブランド"]):
        return "fashion"
    if any(w in combined for w in ["速報", "緊急", "判明", "発表", "解禁", "衝撃", "電撃"]):
        return "breaking"
    if any(w in combined for w in ["カムバック", "comeback", "新曲", "アルバム", "mv", "復帰", "復活"]):
        return "comeback"
    if any(w in combined for w in ["チャート", "ランキング", "1位", "chart", "順位"]):
        return "chart"
    if any(w in combined for w in ["ライブ", "ツアー", "コンサート", "公演", "ファンミ", "フェス"]):
        return "live"
    if any(w in combined for w in ["炎上", "騒動", "脱退", "訴訟", "逮捕", "事件"]):
        return "controversy"
    if any(w in combined for w in ["top", "best"]):
        return "ranking"
    if any(w in combined for w in ["視聴", "配信", "見る方法", "無料", "見逃し"]):
        return "streaming"
    if any(w in combined for w in ["比較", "おすすめ", "vs", "どっち"]):
        return "comparison"
    if any(w in combined for w in ["特集", "完全ガイド"]):
        return "special"
    if any(w in combined for w in ["デビュー", "debut", "新人", "練習生"]):
        return "debut"
    if any(w in combined for w in ["解説", "考察", "分析", "なぜ", "理由"]):
        return "analysis"
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


def load_background(genre_key):
    """テンプレート背景を読み込む。なければフォールバックグラデーション"""
    # travel/fashion は別ジャンルだがBGマップで対応
    bg_map_key = genre_key
    if genre_key == "travel":
        bg_map_key = "live"
    elif genre_key == "fashion":
        bg_map_key = "comeback"

    bg_file = GENRE_BG_MAP.get(bg_map_key, DEFAULT_BG)
    bg_path = os.path.join(ASSETS_DIR, bg_file)

    if os.path.exists(bg_path):
        img = Image.open(bg_path).convert("RGB")
        img = img.resize((W, H), Image.LANCZOS)
        return img

    # フォールバック: グラデーション生成
    style = GENRE_STYLES.get(genre_key, DEFAULT_STYLE)
    return create_gradient(W, H, style["grad_top"], style["grad_bottom"])


def truncate_line(text, max_chars=MAX_CHARS_PER_LINE):
    """1行を最大文字数で切り詰め"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1] + "…"


def auto_split_text(text):
    """テキストを自動的に2行に分割する。
    助詞や句読点などの自然な区切りで分割を試みる。
    """
    text = text.strip()

    # 既に改行があればそのまま分割
    if "\n" in text:
        parts = text.split("\n", 1)
        line1 = truncate_line(parts[0].strip())
        line2 = truncate_line(parts[1].strip()) if len(parts) > 1 else ""
        lines = [line1]
        if line2:
            lines.append(line2)
        return lines

    # 1行に収まるならそのまま
    if len(text) <= MAX_CHARS_PER_LINE:
        return [text]

    # 自然な分割点を探す (助詞・句読点)
    # 分割候補: 助詞・記号の直後
    particles = ["から", "まで", "の", "は", "が", "を", "に", "で", "と", "も"]
    punctuation = ["、", "。", "！", "？", "…", "!", "?", " ", "　"]

    best_pos = -1
    best_score = -1
    target = len(text) / 2  # 中央付近が理想

    # 助詞での分割を試みる
    for particle in particles:
        start = 0
        while True:
            pos = text.find(particle, start)
            if pos == -1:
                break
            split_at = pos + len(particle)
            # 分割後の両方が14文字以内か確認
            if split_at <= MAX_CHARS_PER_LINE and len(text) - split_at <= MAX_CHARS_PER_LINE:
                score = 100 - abs(split_at - target)
                if score > best_score:
                    best_score = score
                    best_pos = split_at
            start = pos + 1

    # 句読点での分割
    for punct in punctuation:
        start = 0
        while True:
            pos = text.find(punct, start)
            if pos == -1:
                break
            split_at = pos + len(punct)
            if split_at <= MAX_CHARS_PER_LINE and len(text) - split_at <= MAX_CHARS_PER_LINE:
                score = 200 - abs(split_at - target)  # 句読点優先
                if score > best_score:
                    best_score = score
                    best_pos = split_at
            start = pos + 1

    if best_pos > 0:
        line1 = text[:best_pos].strip()
        line2 = text[best_pos:].strip()
        return [truncate_line(line1), truncate_line(line2)]

    # 自然な区切りが見つからない場合、中央付近で強制分割
    mid = min(MAX_CHARS_PER_LINE, len(text) // 2)
    line1 = text[:mid]
    line2 = text[mid:]
    return [truncate_line(line1), truncate_line(line2)]


def draw_text_with_stroke(draw, position, text, font, fill, stroke_width=2, stroke_fill=(0, 0, 0)):
    """テキストをストローク (アウトライン) 付きで描画"""
    x, y = position
    # 8方向にオフセットしてストロークを描画
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=stroke_fill)
    # 本体テキスト
    draw.text((x, y), text, font=font, fill=fill)


def draw_thumbnail(text, genre_key, full_title=""):
    style = GENRE_STYLES.get(genre_key, DEFAULT_STYLE)

    # ── 背景読み込み ──
    img = load_background(genre_key)

    draw = ImageDraw.Draw(img)

    # ── 左上ロゴ (K-POP JOURNAL pill) ──
    font_logo = get_font_sub(19)
    logo_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    logo_draw = ImageDraw.Draw(logo_overlay)
    logo_draw.rounded_rectangle(
        (30, 25, 210, 58), radius=14,
        fill=(255, 255, 255, 180)
    )
    img = Image.alpha_composite(img.convert("RGBA"), logo_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    draw.text((45, 30), "K-POP JOURNAL", fill=(80, 80, 80), font=font_logo)

    # ── 右上ジャンルバッジ (角丸ピル型) ──
    label = GENRE_LABELS.get(genre_key, "NEWS")
    font_badge = get_font_sub(17)
    badge_bbox = draw.textbbox((0, 0), label, font=font_badge)
    badge_tw = badge_bbox[2] - badge_bbox[0]
    badge_w = badge_tw + 32
    badge_x = W - badge_w - 30

    badge_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    badge_draw = ImageDraw.Draw(badge_overlay)
    badge_draw.rounded_rectangle(
        (badge_x, 25, badge_x + badge_w, 58), radius=14,
        fill=tuple(style["label_bg"])
    )
    img = Image.alpha_composite(img.convert("RGBA"), badge_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    draw.text(
        (badge_x + 16, 30), label,
        fill=style["label_fg"], font=font_badge
    )

    # ── テキスト処理（2レイヤー構造: 煽り＋メイン） ──
    lines = auto_split_text(text)

    # 2行の場合: line1=煽り(小), line2=メイン(大)
    # 1行の場合: 煽りなし、メインのみ
    if len(lines) >= 2:
        sub_line = lines[0]   # 煽り（上・小さめ）
        main_line = lines[1]  # メイン（下・大きめ）
    else:
        sub_line = ""
        main_line = lines[0]

    # フォントサイズ決定
    main_len = len(main_line)
    if main_len <= 7:
        main_size = 100
    elif main_len <= 10:
        main_size = 82
    else:
        main_size = 68

    sub_size = 34  # 煽りは固定小サイズ

    font_main_text = get_font_main(main_size)  # 太字 (NotoSansJP-Black)
    font_sub_text = get_font_sub(sub_size)      # 通常 (NotoSansJP-Bold)

    # 明るい背景（beauty等）ではストロークを白に
    light_bg = genre_key in ["beauty"]
    stroke_color = (255, 255, 255) if light_bg else (0, 0, 0)
    stroke_w = 4  # 3-6px のストローク
    shadow_alpha = 50 if light_bg else 110

    # 強ワード・数字のハイライト色
    HIGHLIGHT_COLOR = (255, 230, 50)   # 黄色
    HIGHLIGHT_RED = (255, 80, 80)      # 赤
    STRONG_WORDS = ["衝撃", "速報", "判明", "神", "炎上", "ついに", "電撃",
                    "復活", "決定", "解禁", "初公開", "大反響", "騒然", "ヤバい"]

    def has_highlight(word):
        """強ワードか数字を含むかチェック"""
        if any(ch.isdigit() for ch in word):
            return HIGHLIGHT_COLOR
        if any(sw in word for sw in STRONG_WORDS):
            return HIGHLIGHT_RED
        return None

    def split_for_highlight(line_text):
        """テキストをハイライト区間と通常区間に分割"""
        segments = []
        buf = ""
        i = 0
        while i < len(line_text):
            # 数字列をチェック
            if line_text[i].isdigit() or (line_text[i] in "０１２３４５６７８９"):
                if buf:
                    segments.append((buf, None))
                    buf = ""
                num_buf = line_text[i]
                i += 1
                # 数字の後に続く単位も含める（冠、年、選、曲、位 etc）
                while i < len(line_text) and (line_text[i].isdigit() or line_text[i] in "万億千百兆冠年月日位選曲本人回組枚ぶり"):
                    num_buf += line_text[i]
                    i += 1
                segments.append((num_buf, HIGHLIGHT_COLOR))
                continue
            # 強ワードをチェック
            matched_sw = None
            for sw in sorted(STRONG_WORDS, key=len, reverse=True):
                if line_text[i:i+len(sw)] == sw:
                    matched_sw = sw
                    break
            if matched_sw:
                if buf:
                    segments.append((buf, None))
                    buf = ""
                segments.append((matched_sw, HIGHLIGHT_RED))
                i += len(matched_sw)
                continue
            buf += line_text[i]
            i += 1
        if buf:
            segments.append((buf, None))
        return segments

    # ── レイアウト計算（左寄せ・上寄せ）──
    TEXT_LEFT = SAFE_LEFT + 20  # 左寄せ x=100

    # メインテキストのサイズ
    main_bbox = draw.textbbox((0, 0), main_line, font=font_main_text)
    main_w = main_bbox[2] - main_bbox[0]
    main_h = main_bbox[3] - main_bbox[1]

    # 煽りテキストのサイズ
    if sub_line:
        sub_bbox = draw.textbbox((0, 0), sub_line, font=font_sub_text)
        sub_w = sub_bbox[2] - sub_bbox[0]
        sub_h = sub_bbox[3] - sub_bbox[1]
    else:
        sub_w, sub_h = 0, 0

    # 全体高さ
    gap_between = 20 if sub_line else 0
    total_h = sub_h + gap_between + main_h

    # 上寄せ配置（垂直は中央やや上）
    block_y = (H - total_h) // 2 - 30
    block_y = max(SAFE_TOP + 10, block_y)

    sub_y = block_y
    main_y = block_y + sub_h + gap_between if sub_line else block_y

    # ── 帯（半透明黒背景）──
    band_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    band_draw = ImageDraw.Draw(band_overlay)
    band_pad_x = 30
    band_pad_y = 18
    band_top = block_y - band_pad_y
    band_bottom = main_y + main_h + band_pad_y
    band_right = TEXT_LEFT + max(main_w, sub_w) + band_pad_x * 2
    band_right = min(band_right, W - 40)
    band_draw.rounded_rectangle(
        (TEXT_LEFT - band_pad_x, band_top, band_right, band_bottom),
        radius=12, fill=(0, 0, 0, 140)
    )
    img = Image.alpha_composite(img.convert("RGBA"), band_overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # ── 煽りテキスト描画（上・小・通常フォント）──
    if sub_line:
        draw_text_with_stroke(
            draw, (TEXT_LEFT, sub_y), sub_line, font_sub_text,
            fill=(255, 255, 255), stroke_width=3, stroke_fill=stroke_color
        )

    # ── メインテキスト描画（下・大・太字・色分け）──
    segments = split_for_highlight(main_line)
    cx = TEXT_LEFT
    for seg_text, seg_color in segments:
        fill = seg_color if seg_color else (255, 255, 255)
        draw_text_with_stroke(
            draw, (cx, main_y), seg_text, font_main_text,
            fill=fill, stroke_width=stroke_w, stroke_fill=stroke_color
        )
        seg_bbox = draw.textbbox((0, 0), seg_text, font=font_main_text)
        cx += seg_bbox[2] - seg_bbox[0]

    # ── 下部アクセントライン ──
    bar_overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bar_draw = ImageDraw.Draw(bar_overlay)
    bar_w = min(main_w + 60, W - 160)
    bar_x = TEXT_LEFT
    bar_y = H - 35
    bar_draw.rounded_rectangle(
        (bar_x, bar_y, bar_x + bar_w, bar_y + 4),
        radius=2, fill=(255, 255, 255, 120)
    )
    img = Image.alpha_composite(img.convert("RGBA"), bar_overlay).convert("RGB")

    return img


# ── メイン実行 ──
if genre is None:
    genre = detect_genre(thumb_text, full_title)

# travel/fashion は背景マップ用に変換
_bg_genre = genre
if genre == "travel":
    _bg_genre = "live"
elif genre == "fashion":
    _bg_genre = "comeback"

img = draw_thumbnail(thumb_text, genre, full_title)
img.save("thumbnail.webp", format="WEBP", quality=85)
img.save("thumbnail.jpg", format="JPEG", quality=95)
print(f"thumbnail.webp / thumbnail.jpg を作成しました (genre={genre}, text='{thumb_text}')")
