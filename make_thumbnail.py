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

# ── Phase 1止血: 編集系プレフィックス除去 ──
# 【戦略】【速報】等のパイプライン内部マーカーはサムネに不要。
# 10文字制限を圧迫して本文が切れる原因になる。
PREFIXES_TO_STRIP = [
    "【戦略】", "【速報】", "【独占】", "【完全ガイド】", "【保存版】",
    "【最新】", "【公式】", "【注目】", "【まとめ】", "【解説】",
]
for _p in PREFIXES_TO_STRIP:
    if thumb_text.startswith(_p):
        thumb_text = thumb_text[len(_p):]
# 連続プレフィックスにも対応（例: 【戦略】【20周年】 → 【20周年】）
for _p in PREFIXES_TO_STRIP:
    if thumb_text.startswith(_p):
        thumb_text = thumb_text[len(_p):]
thumb_text = thumb_text.strip()
# 抽象語が単独で残った場合はサムネ向きの表現に置換
_ABSTRACT_REPLACEMENTS = {
    "まとめ": "完全まとめ",
    "解説": "徹底解説",
    "最新情報": "最新速報",
    "情報": "最新情報",
}
for _w, _r in _ABSTRACT_REPLACEMENTS.items():
    # タイトル末尾に「〇〇まとめ」のように来る場合のみ対象（先頭単独も対象）
    if thumb_text == _w or thumb_text.endswith(_w) and len(thumb_text) <= len(_w) + 2:
        thumb_text = thumb_text.replace(_w, _r, 1)
        break

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
FONT_LATIN = None  # 英字専用（Bebas Neue）

# メインフォント: NotoSansJP-Black 相当のみ許容（細字フォールバック禁止）
# 過去に NotoSansJP-Black.ttf がHTMLファイルに化けてRegular weightにフォールバックする
# 致命バグがあったため、ロード後に必ず .getname() で weight を検証する。
_BLACK_CANDIDATES = [
    f"{FONT_DIR}/NotoSansJP-Black.otf",
    f"{FONT_DIR}/NotoSansJP-Black.ttf",
    f"{FONT_DIR}/ZenKakuGothicNew-Black.ttf",
    f"{FONT_DIR}/MPLUSRounded1c-Black.ttf",
]
for p in _BLACK_CANDIDATES:
    if not os.path.exists(p):
        continue
    try:
        _f = ImageFont.truetype(p, 40)
        _name = _f.getname()  # (family, style)
        # 'Black' or 'ExtraBold' でないとサムネが細字化するので拒否
        if _name and len(_name) > 1 and any(
            w in (_name[1] or "") for w in ("Black", "ExtraBold", "Heavy")
        ):
            FONT_MAIN = p
            break
    except Exception:
        continue

# 英字フォント: Bebas Neue（タイポ主役の象徴）
_LATIN_CANDIDATE = f"{FONT_DIR}/BebasNeue-Regular.ttf"
if os.path.exists(_LATIN_CANDIDATE):
    try:
        ImageFont.truetype(_LATIN_CANDIDATE, 40)
        FONT_LATIN = _LATIN_CANDIDATE
    except Exception:
        pass

# Phase 1止血: フォントロード失敗時はラウドに失敗
if FONT_MAIN is None:
    sys.stderr.write(
        f"[FATAL] make_thumbnail.py: Black weight 日本語フォントが {FONT_DIR} に見つかりません。\n"
        f"        必須: NotoSansJP-Black.otf / ZenKakuGothicNew-Black.ttf / MPLUSRounded1c-Black.ttf のいずれか\n"
        f"        candidates checked: {_BLACK_CANDIDATES}\n"
    )
    sys.exit(1)


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
    "travel": {
        "bg": "live.png",
        "badge": "TRAVEL",
        "badge_bg": (30, 160, 100, 220),
        "badge_fg": (255, 255, 255),
        "band_color": (0, 20, 10),
        "band_opacity": 190,
        "text_color": (255, 255, 255),
        "stroke_color": (0, 0, 0),
        "highlight_color": (100, 255, 180),
    },
    "fashion": {
        "bg": "comeback.png",
        "badge": "FASHION",
        "badge_bg": (180, 50, 140, 220),
        "badge_fg": (255, 255, 255),
        "band_color": (20, 5, 20),
        "band_opacity": 195,
        "text_color": (255, 255, 255),
        "stroke_color": (0, 0, 0),
        "highlight_color": (255, 160, 230),
    },
}

DEFAULT_PATTERN = "breaking"


def detect_genre(text, title=""):
    """ジャンルを自動判定。元タイトルを優先してサムネテキストのノイズを排除。"""
    # 元タイトルを優先（サムネテキストに「速報」が入っていても騙されない）
    check_src = title if title else text
    t = check_src.lower()

    # travel（旅行・観光・カフェ）
    if any(w in t for w in ["旅行", "ソウル", "カフェ", "聖地巡礼", "観光", "グルメ", "ポップアップ", "聖地"]):
        return "travel"
    # beauty
    if any(w in t for w in ["美容", "コスメ", "スキンケア", "メイク", "ガラス肌", "韓国コスメ", "真似したい"]):
        return "beauty"
    # fashion
    if any(w in t for w in ["ファッション", "着用", "ブランド", "即完売", "コーデ", "outfit"]):
        return "fashion"
    # expose (裏側・暴露)
    if any(w in t for w in ["暴露", "裏側", "真相", "告白", "独占", "内部", "闇", "炎上", "騒動", "脱退", "訴訟", "事件"]):
        return "expose"
    # ranking
    if any(w in t for w in ["チャート", "ランキング", "1位", "chart", "順位", "比較", "どっち"]):
        return "ranking"
    # comeback
    if any(w in t for w in ["カムバック", "comeback", "新曲", "アルバム", "復帰", "復活", "新章"]):
        return "comeback"
    # live
    if any(w in t for w in ["ライブ", "ツアー", "コンサート", "公演", "ファンミ", "フェス", "来日", "日本上陸"]):
        return "live"
    # oshikatsu
    if any(w in t for w in ["推し", "尊い", "沼", "感動", "号泣"]):
        return "oshikatsu"
    # analysis
    if any(w in t for w in ["解説", "考察", "分析", "なぜ", "理由", "結論"]):
        return "analysis"
    # beginner
    if any(w in t for w in ["初心者", "入門", "5分で", "無料", "簡単", "ハウツー", "ガイド", "完全ガイド"]):
        return "beginner"
    # buzz
    if any(w in t for w in ["バズ", "レベチ", "バグ", "やばい", "ヤバい", "話題"]):
        return "buzz"
    # breaking: タイトルに速報系ワードがある場合のみ
    if any(w in t for w in ["速報", "緊急", "判明", "電撃", "衝撃", "まさか", "発覚"]):
        return "breaking"
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
    # 】 】 を最優先で分割点に。「【20周年】BIGBANG」のような構造を正しく処理する
    punctuation = ["】", "】", "、", "！", "？", "・", " ", "　"]

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
                "レベチ", "バグ", "尊い", "まさか", "完全", "即完売",
                "覚醒", "急変", "崩壊", "暴露", "激変", "独占", "注目",
                "緊急", "確定", "発覚", "衝撃的", "大暴露", "真相"]


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


# ────────────────────────────────────────────────────────────────
#  V2: エディトリアル・タイポグラフィ主導レイアウト
#  - 写真ナシでも"映える"海外メディア風（The FADER / Spotify Wrapped）
#  - Bebas Neue 英字ヒーロー + NotoSansJP-Black 日本語サブ
#  - グラデ背景 + ノイズテクスチャで「テンプレ感」を消す
# ────────────────────────────────────────────────────────────────

import re as _re
from datetime import datetime as _dt

# Tier1: 実アーティスト名（最優先）
ARTISTS_TIER1 = [
    "BTS", "BLACKPINK", "BIGBANG", "TWICE", "NEWJEANS", "STRAYKIDS", "STRAY KIDS",
    "ITZY", "AESPA", "IVE", "SEVENTEEN", "ENHYPEN", "LE SSERAFIM", "LESSERAFIM",
    "TXT", "ATEEZ", "NCT", "TWS", "NMIXX", "RIIZE", "ZEROBASEONE", "ZB1",
    "SUPER JUNIOR", "EXO", "SHINEE", "GOT7", "MONSTA X", "DAY6", "ASTRO",
    "ILLIT", "BABYMONSTER", "KISSOFLIFE", "KISS OF LIFE", "KICKFLIP",
    "RED VELVET", "MAMAMOO", "G-IDLE", "GIDLE", "(G)I-DLE", "FROMIS_9",
    "JIMIN", "JUNGKOOK", "JIN", "SUGA", "JHOPE",
    "JISOO", "JENNIE", "ROSE", "LISA", "ROSÉ",
    "AKMU", "악동뮤지션", "CHANHYUK", "SOOHYUN",
    "WINNER", "BIGBANG", "iKON", "IKON", "TREASURE",
    "TVXQ", "DBSK", "DONG BANG SHIN KI",
    "GIRLS GENERATION", "SNSD", "F(X)", "FX",
    "INFINITE", "B1A4", "B2ST", "BEAST", "BTOB", "CNBLUE", "FTISLAND",
    "APINK", "GFRIEND", "LOONA", "WEKI MEKI", "MOMOLAND",
    "PENTAGON", "THE BOYZ", "CRAVITY", "DRIPPIN", "ONEUS",
    "VICTON", "VERIVERY", "SF9", "OMEGA X", "XDINARY HEROES",
    "KARD", "SISTAR", "AOA", "SECRET", "T-ARA", "TARA",
    "CL", "SANDARA PARK", "DARA", "SEUNGRI", "G-DRAGON", "GD",
    "TAEYANG", "DAESUNG", "ZICO", "DEAN", "HEIZE", "IU",
    "BOL4", "BOLBBALGAN4", "EPIK HIGH", "DYNAMIC DUO",
    "LOCO", "CRUSH", "GARY", "JAY PARK", "SIMON DOMINIC",
    "HYUNA", "DAWN", "PENTAGON", "PSY",
]
# Tier2: ブランド名（フォールバック、Tier1が無い時のみ）
BRANDS_TIER2 = [
    "BILLBOARD", "MELON", "SPOTIFY", "COACHELLA", "GRAMMY", "OSCAR",
    "MAMA", "MNET", "KCON", "TIKTOK", "YOUTUBE",
]


def extract_eng_hero(text, full_title):
    """タイトルから英字ヒーロー文字列を抽出（実アー名 > ブランド > 大文字単語）"""
    combined = (full_title + " " + text)
    upper = combined.upper()

    # 1) Tier1 実アー名を優先（長いものから）
    for artist in sorted(ARTISTS_TIER1, key=len, reverse=True):
        if artist in upper:
            return artist

    # 2) Tier2 ブランド名（Tier1が無い時のみ）
    for brand in sorted(BRANDS_TIER2, key=len, reverse=True):
        if brand in upper:
            return brand

    # 3) 連続ASCII大文字3文字以上（汎用的すぎる単語は除外）
    _GENERIC_WORDS = {"POP", "KPOP", "THE", "AND", "FOR", "WITH", "FROM", "INTO",
                      "SONG", "STAR", "IDOL", "NEWS", "TOP", "HIT", "NEW", "HOT"}
    matches = _re.findall(r"[A-Z][A-Z0-9]{2,}", upper)
    for m in matches:
        if m not in _GENERIC_WORDS:
            return m

    # 4) 連続ASCII（混合）3文字以上（汎用語除外）
    matches = _re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", combined)
    for m in matches:
        if m.upper() not in _GENERIC_WORDS:
            return m.upper()

    return None


def strip_all_eng_from_jp(jp_text):
    """JP本文からASCII英単語を全部除去（ヒーローと重複や分断を防ぐ）

    重要: 末尾の digit は eat しない（例: 'Billboard1位' → '1位' を残す）。
         先頭の digit は eat する（例: '3DAYS' → 全消去）。
    """
    # \d* (先頭digit) + 3文字以上の英字/ハイフン/アポストロフィ (末尾digit禁止)
    cleaned = _re.sub(r"\d*[A-Za-z][A-Za-z'·\-]{2,}", "", jp_text)
    # 残った1-2文字の孤立大文字略語を追加除去（SM, GG, YG, JY 等）
    cleaned = _re.sub(r"(?<![A-Za-z\d])[A-Z]{1,2}(?![A-Za-z\d])", "", cleaned)
    # \n は行分割として保持し、各行内のスペースのみ正規化する
    lines = cleaned.split("\n")
    lines = [_re.sub(r"[ \t　]+", " ", l).strip(" 　・,、") for l in lines]
    cleaned = "\n".join(l for l in lines if l)
    return cleaned


def add_noise_texture(img, intensity=30, opacity_div=8):
    """グラデ背景にノイズテクスチャを乗せて『テンプレ感』を消す"""
    noise_mask = Image.effect_noise((W, H), intensity)
    noise_mask = noise_mask.point(lambda p: p // opacity_div)
    white_layer = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    white_layer.putalpha(noise_mask)
    return Image.alpha_composite(img.convert("RGBA"), white_layer).convert("RGB")


def get_latin_font(size):
    """Bebas Neue（無ければ Black 日本語フォントで代用）"""
    if FONT_LATIN:
        try:
            return ImageFont.truetype(FONT_LATIN, size)
        except Exception:
            pass
    return get_font(size)


def get_artist_background(artist_name):
    """アーティスト画像をローカルキャッシュ→Wikimediaの順で取得"""
    if not artist_name:
        return None
    cache_dir = "/home/aiuser/kpop-ai-system/assets/artist_cache"
    try:
        # libパス追加
        import sys as _sys
        _lib = "/home/aiuser/kpop-ai-system/lib"
        if _lib not in _sys.path:
            _sys.path.insert(0, _lib)
        from wikimedia import fetch_safe_image
        return fetch_safe_image(artist_name, cache_dir)
    except Exception as e:
        sys.stderr.write(f"[thumbnail] artist image fetch failed: {e}\n")
        return None


def compose_image_background(genre_key, artist_image_path):
    """アー画像を右半分に配置、左半分に暗グラデオーバーレイで可読性確保"""
    grad_colors = GRAD_FALLBACK.get(genre_key, ((30, 30, 50), (10, 10, 20)))
    base = create_gradient(W, H, grad_colors[0], grad_colors[1])

    try:
        img = Image.open(artist_image_path).convert("RGB")
    except Exception:
        return base

    # 右半分にカバー配置（centerクロップ風）
    img_w, img_h = img.size
    target_w = W  # 全幅使う
    target_h = H
    scale = max(target_w / img_w, target_h / img_h)
    new_w = int(img_w * scale)
    new_h = int(img_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    # センタークロップ
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))

    # 全体に暗めトーン（明るいコンサート写真に対応）
    dark_layer = Image.new("RGBA", (W, H), (0, 0, 0, 90))
    img = Image.alpha_composite(img.convert("RGBA"), dark_layer).convert("RGB")

    # 左半分に強い暗グラデ（テキスト領域、ほぼ完全な不透過から始まる）
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    # 0〜800px、alpha 250→0 の急峻なグラデ
    for x in range(0, 800):
        alpha = int(250 * (1 - x / 800) ** 1.3)
        odraw.line([(x, 0), (x, H)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    return img


def draw_thumbnail_v2(text, genre_key, full_title=""):
    """V2: エディトリアル・タイポグラフィ主導レイアウト
    アー画像があれば背景に合成、なければグラデのみ"""
    pat = PATTERNS.get(genre_key, PATTERNS[DEFAULT_PATTERN])

    # ── 1. 英字ヒーロー抽出（先にやって背景画像取得に使う） ──
    eng_hero_early = extract_eng_hero(text, full_title)

    # ── 旅行/ファッション/美容ジャンルは汎用英語ヒーローをジャンル固有テキストで上書き ──
    # "POP"等の無関係ワードがwikimediaで不適切画像を引かないよう制御
    _genre_hero_override = {
        "travel": "SEOUL",
        "fashion": "FASHION",
        "beauty": "BEAUTY",
    }
    if genre_key in _genre_hero_override:
        # Tier1アーティスト名が含まれていれば優先、なければジャンル固定ヒーロー
        _has_tier1 = eng_hero_early and any(
            eng_hero_early.upper() == a for a in ARTISTS_TIER1
        )
        if not _has_tier1:
            eng_hero_early = _genre_hero_override[genre_key]

    # ── 2. 背景: アーティスト画像 > ジャンルアセットpng > グラデ+ノイズ ──
    # 旅行/ファッション/美容ジャンルはwikimediaアーティスト画像を使わない（無関係画像防止）
    use_image = os.environ.get("THUMB_USE_IMAGE", "1") != "0"
    _skip_wikimedia_genres = {"travel", "fashion", "beauty"}
    artist_img_path = None
    if use_image and eng_hero_early and genre_key not in _skip_wikimedia_genres:
        artist_img_path = get_artist_background(eng_hero_early)

    has_image_bg = False
    if artist_img_path:
        img = compose_image_background(genre_key, artist_img_path)
        has_image_bg = True
    else:
        # ジャンルアセットpngを優先して使用（beauty.png / comeback.png 等）
        asset_img = load_background(pat)
        # グラデーションフォールバックと区別: アセットpngがある場合は背景変化あり
        bg_file = pat.get("bg", "")
        bg_path = os.path.join(ASSETS_DIR, bg_file)
        if bg_file and os.path.exists(bg_path):
            img = asset_img
            has_image_bg = True  # アセット背景はdark前提でテキスト白
        else:
            # グラデーション: ジャンルごとに微妙に色を変えてバリエーションを出す
            import hashlib
            _seed = int(hashlib.md5(text.encode()).hexdigest()[:6], 16) % 30
            grad_colors = GRAD_FALLBACK.get(genre_key, ((30, 30, 50), (10, 10, 20)))
            # seed値でわずかに色をずらす（同ジャンル連続投稿でも同一デザインにならない）
            _r_shift = _seed - 15
            c_top = tuple(max(0, min(255, c + _r_shift)) for c in grad_colors[0])
            c_bot = tuple(max(0, min(255, c + _r_shift // 2)) for c in grad_colors[1])
            img = create_gradient(W, H, c_top, c_bot)
            img = add_noise_texture(img, intensity=30, opacity_div=10)

    # ── 2. ジャンル別テーマカラー ──
    # beauty.png は淡いピンク系背景なのでテキストは暗色、それ以外は白
    # アセットpng使用時もbeautyジャンルなら暗色テキストを維持
    is_light = (genre_key == "beauty")
    fg = (40, 30, 35) if is_light else (255, 255, 255)
    fg_dim = (90, 80, 90) if is_light else (180, 180, 200)
    accent = pat.get("highlight_color", (100, 200, 255))
    if isinstance(accent, tuple) and len(accent) == 4:
        accent = accent[:3]

    draw = ImageDraw.Draw(img)

    # ── 3. トップバー: 縦アクセント + KPJロゴ + 日付 + バッジ ──
    # 左: 縦アクセントバー + ロゴ
    draw.rectangle((50, 38, 56, 78), fill=accent)
    font_logo_main = get_font(22)
    font_logo_sub = get_font(13)
    draw.text((68, 36), "K-POP JOURNAL", fill=fg, font=font_logo_main)
    draw.text((68, 64), "EDITORIAL · 2026", fill=fg_dim, font=font_logo_sub)

    # 右: 日付 + バッジ
    today = _dt.now().strftime("%Y.%m.%d")
    font_date = get_font(20)
    font_badge_v2 = get_font(13)
    date_bbox = draw.textbbox((0, 0), today, font=font_date)
    date_w = date_bbox[2] - date_bbox[0]
    badge_label = pat.get("badge", "K-POP")
    badge_bbox = draw.textbbox((0, 0), badge_label, font=font_badge_v2)
    badge_w = badge_bbox[2] - badge_bbox[0]
    right_x = W - 50
    draw.text((right_x - date_w, 40), today, fill=fg, font=font_date)
    # アクセント色のバッジ
    draw.text((right_x - badge_w, 68), badge_label, fill=accent, font=font_badge_v2)

    # ── 4. ヒーロー: 英字大見出し（Bebas Neue） ──
    eng_hero = eng_hero_early  # 上で取得済みを再利用
    hero_y = 130
    if eng_hero:
        # サイズは長さで動的調整
        if len(eng_hero) <= 6:
            hero_size = 220
        elif len(eng_hero) <= 10:
            hero_size = 170
        elif len(eng_hero) <= 14:
            hero_size = 130
        else:
            hero_size = 100
        font_hero = get_latin_font(hero_size)
        hero_bbox = draw.textbbox((0, 0), eng_hero, font=font_hero)
        hero_h = hero_bbox[3] - hero_bbox[1]
        hero_w = hero_bbox[2] - hero_bbox[0]
        # 画面幅を超えるならサイズダウン
        while hero_w > W - 100 and hero_size > 60:
            hero_size -= 10
            font_hero = get_latin_font(hero_size)
            hero_bbox = draw.textbbox((0, 0), eng_hero, font=font_hero)
            hero_w = hero_bbox[2] - hero_bbox[0]
            hero_h = hero_bbox[3] - hero_bbox[1]
        # 描画（軽いシャドウ）
        shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow_layer)
        sdraw.text((52, hero_y + 4), eng_hero, font=font_hero, fill=(0, 0, 0, 100))
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=8))
        img = Image.alpha_composite(img.convert("RGBA"), shadow_layer).convert("RGB")
        draw = ImageDraw.Draw(img)
        draw.text((50, hero_y), eng_hero, font=font_hero, fill=fg)
        hero_bottom = hero_y + hero_h
    else:
        hero_bottom = hero_y

    # ── 5. 罫線セパレータ ──
    rule_y = hero_bottom + 28
    draw.rectangle((50, rule_y, 250, rule_y + 4), fill=accent)

    # ── 6. 日本語サブ見出し ──
    jp_y = rule_y + 24
    # ASCII英単語を全部除去（ヒーロー重複・英単語分断防止）
    jp_text = strip_all_eng_from_jp(text)
    if not jp_text:
        jp_text = text  # 空になったら元に戻す
    # auto_split で2行化
    jp_lines = auto_split_text(jp_text)
    if len(jp_lines) == 0:
        jp_lines = [jp_text[:12]]

    # サイズは長さで動的調整
    longest_jp = max(jp_lines, key=len) if jp_lines else ""
    if len(longest_jp) <= 6:
        jp_size = 78
    elif len(longest_jp) <= 9:
        jp_size = 64
    else:
        jp_size = 52
    font_jp = get_font(jp_size)

    # ハイライトセグメント描画
    for i, line in enumerate(jp_lines[:2]):
        line_y = jp_y + i * (jp_size + 8)
        # シャドウ
        shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow_layer)
        sdraw.text((52, line_y + 3), line, font=font_jp, fill=(0, 0, 0, 120))
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=6))
        img = Image.alpha_composite(img.convert("RGBA"), shadow_layer).convert("RGB")
        draw = ImageDraw.Draw(img)
        # 強調ワードを accent 色に
        segments = split_for_highlight(line, accent)
        cx = 50
        for seg_text, seg_color in segments:
            fill = seg_color if seg_color else fg
            draw_text_with_stroke(draw, (cx, line_y), seg_text, font=font_jp,
                                  fill=fill, stroke_width=3, stroke_fill=(0, 0, 0, 200))
            seg_bbox = draw.textbbox((0, 0), seg_text, font=font_jp)
            cx += seg_bbox[2] - seg_bbox[0]

    # ── 7. フッターバー: タグ風メタ情報 ──
    footer_y = H - 50
    # 左: ハッシュタグ風
    font_footer = get_font(15)
    tags = []
    if eng_hero:
        tags.append(f"#{eng_hero.replace(' ', '')}")
    tags.append(f"#{badge_label}")
    tags.append("#KPOPJOURNAL")
    footer_text = "  ┃  ".join(tags)
    draw.text((50, footer_y), footer_text, fill=fg_dim, font=font_footer)
    # 右: KPJ印
    kpj_text = "KPJ ┃"
    kpj_bbox = draw.textbbox((0, 0), kpj_text, font=font_footer)
    kpj_w = kpj_bbox[2] - kpj_bbox[0]
    draw.text((W - 50 - kpj_w, footer_y), kpj_text, fill=accent, font=font_footer)

    return img


# ── メイン実行 ──
if genre is None:
    genre = detect_genre(thumb_text, full_title)

# パターンに無いジャンルはフォールバック
if genre not in PATTERNS:
    genre = DEFAULT_PATTERN

# レイアウト選択: --layout v1|v2 / 環境変数 THUMB_LAYOUT / デフォルト v2
layout = "v2"
for i, arg in enumerate(sys.argv):
    if arg == "--layout" and i + 1 < len(sys.argv):
        layout = sys.argv[i + 1]
if os.environ.get("THUMB_LAYOUT"):
    layout = os.environ["THUMB_LAYOUT"]

if layout == "v2":
    img = draw_thumbnail_v2(thumb_text, genre, full_title)
else:
    img = draw_thumbnail(thumb_text, genre, full_title)

img.save("thumbnail.webp", format="WEBP", quality=85)
img.save("thumbnail.jpg", format="JPEG", quality=95)
print(f"thumbnail.webp / thumbnail.jpg を作成しました (layout={layout}, genre={genre}, text='{thumb_text}')")

# 学習用メタ情報をstderrにJSONで出力（パイプライン側がパースして thumbnail_learner に流す）
# ジャンルアセットpngが存在するかを事前確認
_genre_pat = PATTERNS.get(genre, PATTERNS[DEFAULT_PATTERN])
_bg_file = _genre_pat.get("bg", "")
_bg_path = os.path.join(ASSETS_DIR, _bg_file)
_has_asset_bg = bool(_bg_file and os.path.exists(_bg_path))

_meta = {
    "layout": layout,
    "genre": genre,
    "thumb_text": thumb_text,
    "has_image": _has_asset_bg,  # ジャンルアセットpng or wikimediaアー画像がある場合True
    "eng_hero": "",
    "image_source": "asset" if _has_asset_bg else "",
}
if layout == "v2":
    try:
        _eng = extract_eng_hero(thumb_text, full_title)
        # 旅行/ファッション/美容ジャンルはTier1アーティスト名がない限りジャンル固有ヒーロー
        _genre_hero_map = {"travel": "SEOUL", "fashion": "FASHION", "beauty": "BEAUTY"}
        if genre in _genre_hero_map:
            _has_t1 = _eng and any(_eng.upper() == a for a in ARTISTS_TIER1)
            if not _has_t1:
                _eng = _genre_hero_map[genre]
        if _eng:
            _meta["eng_hero"] = _eng
            # 旅行/ファッション/美容ジャンルはwikimedia画像を使わない
            _skip_wiki = {"travel", "fashion", "beauty"}
            if genre not in _skip_wiki:
                # キャッシュに画像あればhas_image=True
                _cache_idx = "/home/aiuser/kpop-ai-system/assets/artist_cache/index.json"
                if os.path.exists(_cache_idx):
                    try:
                        import json as _j2
                        with open(_cache_idx) as _f:
                            _idx = _j2.load(_f)
                        _slug = _re.sub(r"[^a-zA-Z0-9_]+", "_", _eng.lower()).strip("_")[:40]
                        if _slug in _idx and _idx[_slug].get("files"):
                            _meta["has_image"] = True
                            _meta["image_source"] = "wikimedia"
                    except Exception:
                        pass
    except Exception:
        pass
import json as _json
sys.stderr.write("THUMB_META: " + _json.dumps(_meta, ensure_ascii=False) + "\n")
