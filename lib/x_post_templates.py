#!/usr/bin/env python3
"""
X/Twitter投稿テンプレートシステム (v13.0)

Usage:
  python3 lib/x_post_templates.py "記事タイトル" "https://url" --genre news

Output: 完成したツイートテキスト（そのまま投稿可能）

ジャンル (v13.0 — 4分類):
  news      ニュース速報   (速報・カムバック・チャート・炎上)
  analysis  分析/解説      (考察・ランキング・比較・歴史)
  beauty    美容/ノウハウ  (スキンケア・コスメ・ダイエット・ファッション)
  travel    旅行/まとめ    (聖地・ソウル観光・カフェ・ガイド)

投稿構造:
  1行目: フック（20文字以内・数字1つ・感情ワード含む）
  2行目: 感情行（未完結・答えを書かない）
  3行目: 空白
  4行目: コメント誘導（「どう思う？」等）

禁止: 説明文・完結文・答え記載・感情なし
"""
import argparse
import hashlib
import re
import sys

# --- アーティスト名抽出用パターン ---
KNOWN_ARTISTS = [
    "BTS", "BLACKPINK", "aespa", "SEVENTEEN", "Stray Kids", "NewJeans",
    "IVE", "LE SSERAFIM", "XG", "TWICE", "NCT", "ILLIT", "RIIZE",
    "BABYMONSTER", "ZEROBASEONE", "ITZY", "EXO", "BIGBANG", "MONSTA X",
    "TXT", "ENHYPEN", "ATEEZ", "TREASURE", "NMIXX", "(G)I-DLE",
    "Red Velvet", "MAMAMOO", "GOT7", "SHINee", "2NE1", "WINNER",
    "iKON", "BTOB", "ASTRO", "THE BOYZ", "ONEUS", "SF9",
    "Super Junior", "SHINee", "f(x)", "TVXQ", "2AM", "2PM",
    "SISTAR", "KARA", "T-ARA", "4MINUTE", "miss A", "After School",
    "DAY6", "PENTAGON", "VICTON", "CIX", "AB6IX", "CRAVITY",
    "TEMPEST", "TNX", "BOYNEXTDOOR", "KISS OF LIFE",
    "ジミン", "テテ", "ジョングク", "RM", "SUGA", "J-HOPE", "JIN",
    "リサ", "ジェニ", "ロゼ", "ジス",
    "ウォニョン", "ユジン", "レイ", "ガウル", "リズ", "イソ",
    "ミンジ", "ハニ", "ダニエル", "ヘリン", "ヘイン",
    "カリナ", "ウィンター", "ジゼル", "ニンニン",
    "サクラ", "チェウォン", "カズハ", "ユンジン", "ホンウンチェ",
]

# ─── ターゲット定義 ──────────────────────────────────────────────────────────
# v12.0 §1: 新規/ライト/コア の3分類
TARGET_NEW   = "新規"   # 検索未経験・初心者記事
TARGET_LIGHT = "ライト" # 知っている・考察記事
TARGET_CORE  = "コア"   # ファン・カムバック速報

# ─── フック (v13.0 — 4ジャンル) ────────────────────────────────────────────
# 条件: 20文字以内・感情ワード含む・数字1つ・未完結
#
# ジャンル設計方針:
#   news      速報性・驚き・緊迫感  → ファン(コア)向け
#   analysis  知的好奇心・納得感    → ライト/コア向け
#   beauty    共感・自己投影        → 新規/ライト向け
#   travel    憧れ・実用性          → 新規/ライト向け
HOOKS = {
    # ── ニュース速報 ────────────────────────────────────────────────────────
    # カバー範囲: 速報・カムバック・チャート・ライブ・炎上・コラボ
    "news": [
        "速報…{artist}が動いた",
        "{artist}から緊急発表",
        "{artist}がついに動いた",
        "{artist}が{number}冠の衝撃",
        "K-POPに衝撃が走った",
        "速報、誰も予想しなかった",
        "ファン騒然…{artist}の真相",
        "{artist}来日、{number}都市で開催",
    ],
    # ── 分析/解説 ─────────────────────────────────────────────────────────
    # カバー範囲: 考察・比較ランキング・歴史・業界解説・なぜ系
    "analysis": [
        "{artist}の快挙、その理由とは",
        "記録更新…何が起きた？",
        "{artist}ファン、これ知ってた？",
        "{artist}の真相、判明した",
        "K-POPの裏側、暴露された",
        "この数字の意味、分かる？",
        "{artist}の変化、気づいてた？",
    ],
    # ── 美容/ノウハウ ──────────────────────────────────────────────────────
    # カバー範囲: スキンケア・コスメ・ダイエット・ヘアケア・ファッション
    "beauty": [
        "{artist}肌の秘密が判明",
        "ガラス肌になれるのか？",
        "韓国コスメの真実とは",
        "{artist}の私服が完全判明",
        "このコーデ、真似できる？",
        "K-POPアイドルが選んだ方法",
        "知らないと損するケア術",
    ],
    # ── 旅行/まとめ ────────────────────────────────────────────────────────
    # カバー範囲: ソウル聖地・カフェ・ホテル・推し活ガイド・まとめ記事
    "travel": [
        "ソウル推し活スポット完全解禁",
        "知らないと損する聖地がある",
        "推し活ファン必見スポット解禁",
        "ソウル、完全変化を速報解禁",
        "現地に行った人しか知らない",
        "この場所、{artist}ファン聖地だった",
    ],
    # ── デフォルト（後方互換・旧ジャンル名） ──────────────────────────────
    "default": [
        "{artist}に衝撃の変化が起きた",
        "ついに{artist}が動いた",
        "{artist}の真相、判明した",
        "速報…{artist}に何かが起きた",
        "{artist}ファン、これ知ってた？",
    ],
    # 旧ジャンル名エイリアス（後方互換）
    "breaking":    ["速報…{artist}が動いた", "{artist}から緊急発表", "K-POPに衝撃が走った"],
    "comeback":    ["{artist}がついに動いた", "{artist}の新章が始まる"],
    "controversy": ["ファン騒然…{artist}の真相", "{artist}に何が起きたのか"],
    "live":        ["{artist}来日、{number}都市で開催", "チケット争奪戦が始まる"],
    "chart":       ["{artist}が{number}冠の衝撃", "記録更新…何が起きた？"],
    "fashion":     ["{artist}の私服が完全判明", "このコーデ、真似できる？"],
}

# ─── コメントトリガー (v13.0 — 4ジャンル対応) ──────────────────────────────
# カテゴリ: 論争系 / 感動系 / 記録系 の3パターン
# v13.0 ジャンル → タイプマッピング
COMMENT_TRIGGER_TYPE = {
    "news":        "論争系",   # 速報は賛否を呼ぶ
    "analysis":    "記録系",   # 考察は記録・驚きを強調
    "beauty":      "論争系",   # 美容は共感・試したい論争を誘発
    "travel":      "感動系",   # 旅行は憧れ・感動を誘発
    # 後方互換
    "breaking":    "論争系",
    "comeback":    "感動系",
    "controversy": "論争系",
    "live":        "感動系",
    "chart":       "記録系",
    "fashion":     "論争系",
    "default":     "論争系",
}

COMMENT_TRIGGERS = {
    "論争系": [
        "みんなはどう思う？私はアリだと思うけど…",
        "これ、どう思う？賛否あると思う",
        "あなたはどっち派？",
    ],
    "感動系": [
        "泣いた人いない？リプ欄に『😭』置いてって",
        "感動した？RTで教えて",
        "これ見て涙止まらなかった…どう思う？",
        "あなたも同じ気持ちだった？",
        "これ、みんなはどう感じた？",
    ],
    "記録系": [
        "これ超えられるグループ、他にある？",
        "この記録、どこまで続くと思う？",
        "歴史的瞬間だと思う人、どう思う？👇",
    ],
}

# ─── 感情行 (2行目) v13.0 ── 4ジャンル ────────────────────────────────────
# 未完結・答えを書かない・感情を動かす
EMOTION_LINES = {
    # ── ニュース速報: 緊迫感・予想外・拡散欲求 ─────────────────────────────
    "news": [
        "ファンの間で賛否が広がっている…",
        "この展開、誰も予想していなかった",
        "関係者の間でも困惑が広がっている",
        "真相はまだ明かされていない",
        "ファンの反応が二極化している",
        "その勢いはまだ止まっていない",
    ],
    # ── 分析/解説: 知的好奇心・「実は知らなかった」 ─────────────────────────
    "analysis": [
        "この数字の裏に隠された真実がある",
        "業界関係者も驚いた結果だという",
        "その事実を知る人は少ない",
        "見落としていた人も多いはずだ",
        "ファンの間でひそかに話題になっている",
        "知っているようで知らない事実がある",
    ],
    # ── 美容/ノウハウ: 「自分もできる」「やってみたい」 ─────────────────────
    "beauty": [
        "その方法は意外にもシンプルだった",
        "多くの人が間違えていることがある",
        "このスタイル、誰もが気になっていた",
        "入手困難なアイテムに秘密がある",
        "センスの差がここに出る",
        "知っているようで知らない美容法がある",
    ],
    # ── 旅行/まとめ: 「行きたい」「知らなかった」 ──────────────────────────
    "travel": [
        "知らないと損する場所がある",
        "現地に行った人しか知らない",
        "K-POPファンが選ぶ理由がある",
        "この場所、ガイドブックには載っていない",
        "推し活ファンの間でひそかに話題だ",
    ],
    # 後方互換
    "breaking":    [
        "ファンの間で賛否が広がっている…",
        "この展開、誰も予想していなかった",
        "関係者の間でも困惑が広がっている",
    ],
    "comeback":    [
        "その変化は想像以上だった",
        "ファンが待ち続けた理由がある",
        "この決断には深い意味がある",
    ],
    "controversy": [
        "真相はまだ明かされていない",
        "関係者の証言が食い違っている",
        "ファンの反応が二極化している",
    ],
    "live":        [
        "演出が前回とは全く違う",
        "会場の熱気が異常だったという",
        "あの瞬間を見た人だけが知っている",
    ],
    "chart":       [
        "この数字の裏に隠された真実がある",
        "業界関係者も驚いた結果だという",
        "その勢いはまだ止まっていない",
    ],
    "fashion":     [
        "このスタイル、誰もが気になっていた",
        "入手困難なアイテムに秘密がある",
        "センスの差がここに出る",
    ],
    "default":     [
        "その事実を知る人は少ない",
        "ファンの間でひそかに話題になっている",
        "見落としていた人も多いはずだ",
    ],
}

# CATEGORY_ID → genre マッピング (v13.0 — 4ジャンル体系)
# news / analysis / beauty / travel の4分類に統一
CATEGORY_TO_GENRE = {
    # ── ニュース速報 (news) ─────────────────────────────────────────────────
    "71": "news",        # K-POPチャート
    "3":  "news",        # カムバック情報
    "6":  "news",        # カムバック系
    "5":  "news",        # ライブ・イベント・チケット
    "7":  "news",        # 速報系
    "28": "news",        # チャート系
    "8":  "news",        # ドラマ
    "27": "news",        # 速報系
    "10": "news",        # コラボ
    "15": "news",        # 速報系
    "13": "news",        # 速報系
    "14": "news",        # ゴシップ・事件（論争系ニュース）
    "9":  "news",        # 速報系
    # ── 分析/解説 (analysis) ───────────────────────────────────────────────
    "29": "analysis",    # バラエティー考察
    "4":  "analysis",    # 解説系
    "2":  "analysis",    # 一般解説
    # ── 美容/ノウハウ (beauty) ─────────────────────────────────────────────
    "12": "beauty",      # 美容系
    "30": "beauty",      # ファッション（美容カテゴリに統合）
    "51": "beauty",      # スキンケア
    "52": "beauty",      # ヘアケア
    "53": "beauty",      # ダイエット
    "54": "beauty",      # コスメ
    "55": "beauty",      # サロン＆クリニック
    "56": "beauty",      # インナーケア
    # ── 旅行/まとめ (travel) ───────────────────────────────────────────────
    "11": "travel",      # 旅行・観光・カフェ
    "62": "travel",      # カフェ・レストラン
    "63": "travel",      # ホテル
    "70": "travel",      # ソウル
    # ── 新規カテゴリ (2026-04-13追加) ───────────────────────────────────────
    "111": "analysis",   # 視聴方法・配信ガイド
    "112": "analysis",   # プロフィール
    "113": "analysis",   # 初心者ガイド
    "31":  "analysis",   # 特集
}


def determine_target(title: str, genre: str) -> str:
    """v12.0 §1: 記事テーマからターゲットを判定する。
    カムバック速報→コア / 考察→ライト / 初心者記事→新規
    """
    core_keywords = [
        "カムバック", "新曲", "MV公開", "アルバム発売", "速報", "緊急", "解禁",
        "来日", "ツアー決定", "1位", "チャート",
    ]
    light_keywords = [
        "考察", "なぜ", "理由", "秘密", "真相", "裏側", "比較", "ランキング",
        "歴史", "解説", "分析",
    ]
    new_keywords = [
        "入門", "初心者", "基本", "完全ガイド", "とは", "わかりやすく",
        "始め方", "まとめ",
    ]

    if genre in ("breaking", "comeback", "live", "chart"):
        return TARGET_CORE
    for kw in core_keywords:
        if kw in title:
            return TARGET_CORE
    for kw in new_keywords:
        if kw in title:
            return TARGET_NEW
    for kw in light_keywords:
        if kw in title:
            return TARGET_LIGHT
    return TARGET_LIGHT  # デフォルトはライト


def extract_artist(title: str) -> str:
    """タイトルからアーティスト名を抽出する"""
    for artist in KNOWN_ARTISTS:
        if artist.lower() in title.lower():
            return artist
    # 「○○の」「○○が」等のパターンで先頭名詞を抽出
    m = re.match(r'^([^のがはをにで、。!！?？\s]{2,10})[のがはをにで]', title)
    if m:
        return m.group(1)
    # フォールバック: タイトル先頭から意味のある語句を抽出
    m2 = re.match(r'^[【（\[]?([A-Za-z0-9\u30a0-\u30ff\u4e00-\u9fff]{2,8})[】）\]]?', title)
    if m2:
        candidate = m2.group(1)
        stopwords = {"K-POP", "KPO", "2026", "2025", "K-P", "韓国K", "完全"}
        if candidate not in stopwords and len(candidate) >= 2:
            return candidate
    return "K-POP"


def extract_event(title: str) -> str:
    """タイトルからイベント/出来事キーワードを抽出する"""
    event_words = [
        "カムバック", "復帰", "新曲", "MV", "アルバム", "ツアー", "来日",
        "コンサート", "脱退", "炎上", "熱愛", "結婚", "入隊", "除隊",
        "1位", "記録", "コラボ", "出演", "発表", "決定", "公開",
    ]
    for word in event_words:
        if word in title:
            return word
    return "動向"


def extract_number(title: str) -> str:
    """タイトルから意味のある数字を抽出する（年号・日付は除外）"""
    # 年号(2024〜2030)・日付(01〜31)を除いた数字を優先
    for m in re.finditer(r'(\d+)', title):
        n = int(m.group(1))
        if 2020 <= n <= 2035:  # 年号はスキップ
            continue
        if n > 100:  # 大きすぎる数字はスキップ
            continue
        return str(n)
    return "新"


def select_hook(genre: str, title: str, artist: str) -> str:
    """ジャンルに基づいてフックを選択し、プレースホルダを埋める"""
    hooks = HOOKS.get(genre, HOOKS["default"])
    # アーティスト名が有効な場合は {artist} を含むフックを優先選択
    if artist and artist not in ("K-POP", "K-POPアイドル"):
        artist_hooks = [h for h in hooks if "{artist}" in h]
        if artist_hooks:
            idx = int(hashlib.md5(title.encode()).hexdigest(), 16) % len(artist_hooks)
            hook = artist_hooks[idx]
        else:
            idx = int(hashlib.md5(title.encode()).hexdigest(), 16) % len(hooks)
            hook = hooks[idx]
    else:
        idx = int(hashlib.md5(title.encode()).hexdigest(), 16) % len(hooks)
        hook = hooks[idx]

    event = extract_event(title)
    number = extract_number(title)

    hook = hook.replace("{artist}", artist)
    hook = hook.replace("{event}", event)
    hook = hook.replace("{number}", number)

    # アーティスト名が空の場合 → タイトルからK-POPキーワードで代替
    if not artist and "{artist}" not in hooks[idx]:
        pass  # プレースホルダなしフックはそのまま使用
    elif not artist:
        # アーティスト名が取れない場合はフックごとタイトル先頭から抽出
        import re as _re
        title_short = _re.sub(r'【[^】]*】|（[^）]*）|\([^)]*\)', '', title).strip()[:12]
        hook = hook.replace("{artist}", title_short) if title_short else hook.replace("{artist}に", "K-POPに").replace("{artist}", "K-POP")

    return hook


def build_emotion_line(genre: str, title: str, idx: int) -> str:
    """v12.0 §3: 感情行（2行目）— 未完結・答えを書かない"""
    lines = EMOTION_LINES.get(genre, EMOTION_LINES["default"])
    return lines[idx % len(lines)]


def build_comment_trigger(genre: str, idx: int) -> str:
    """v12.0 §5 + CTO: 動的コメントトリガー
    論争系・感動系・記録系 の3タイプからジャンルに応じて選択
    """
    trigger_type = COMMENT_TRIGGER_TYPE.get(genre, "論争系")
    triggers = COMMENT_TRIGGERS[trigger_type]
    return triggers[idx % len(triggers)]


def build_hashtags(artist: str, genre: str) -> str:
    """ハッシュタグを生成する（2-3個）"""
    tags = ["#KPOP"]

    # アーティスト名ハッシュタグ
    artist_tag = artist.replace(" ", "")
    # 汎用フォールバック・数字・年月は除外
    _invalid = {"K-POP", "K-POPアイドル", "韓国K", "K-P"}
    if (artist_tag and len(artist_tag) >= 2
            and artist_tag not in _invalid
            and not artist_tag.isdigit()
            and not re.search(r'^\d{4}年', artist_tag)):
        tags.append(f"#{artist_tag}")

    # ジャンル別追加タグ
    genre_tags = {
        "breaking": "#速報",
        "comeback": "#カムバック",
        "controversy": "#韓国芸能",
        "beauty": "#韓国コスメ",
        "live": "#コンサート",
        "chart": "#チャート",
        "default": "#韓国",
    }
    extra = genre_tags.get(genre, "#韓国")
    if len(tags) < 3 and extra not in tags:
        tags.append(extra)
    # 重複除去しつつ順序を維持
    seen = set()
    tags = [t for t in tags if not (t in seen or seen.add(t))]

    return " ".join(tags)


def fragment_title(title: str, artist: str) -> str:
    """CTO指示: 情報を「断片化」して寸止めを創出する。
    ×「NewJeansが1位を獲って涙を流しました」
    ○「NewJeansが流した涙。その"本当の理由"を知って震えた。」
    """
    # イベントキーワードを抽出して断片化パターンを適用
    fragment_patterns = [
        # 「〜した」→「〜したこと。その"本当の理由"が…」
        (r'(.{4,15})(した|した。|している)', r'\1したこと。\nその"本当の理由"を知って震えた。'),
        # 「〜を発表」→「〜を発表。\nこの決断の裏に何があったのか。」
        (r'(.{4,12})(を発表|が発表)', r'\1を発表。\nこの決断の裏に何があったのか。'),
        # 「〜が判明」→「〜が判明。\nこれを知ったファンの反応が…」
        (r'(.{4,12})(が判明|と判明)', r'\1が判明。\nこれを知ったファンの反応が凄い。'),
        # 「〜で1位」→「〜での1位。\nその数字の裏にある"本当の話"。」
        (r'(.{2,10})(で\d+位|が\d+冠)', r'\1での記録。\nその数字の裏にある"本当の話"。'),
    ]
    import re as _re
    for pat, repl in fragment_patterns:
        m = _re.search(pat, title)
        if m:
            return _re.sub(pat, repl, title, count=1)

    # フォールバック: タイトルを断片化
    if len(title) > 20:
        mid = len(title) // 2
        return f'{title[:mid]}…\nその\u201c真相\u201d、知ってる？'
    return title


def generate_tweet(title: str, url: str, genre: str, include_url: bool = True) -> str:
    """完成したツイートテキストを生成する (v12.0 + CTO指示 準拠)

    構造 (CTOハック: 1ポスト目にURLなし → IMP最大化):
      1行目: フック（20文字以内・感情ワード・未完結）
      2行目: 感情行 OR 断片化タイトル（寸止め）
      3行目: 空白  ← スマホスクロール誘発
      4行目: コメントトリガー（論争系/感動系/記録系）
      5行目: 空白
      6行目: URL（include_url=False の場合は省略 → リプライで後から挿入）
      7行目: 空白
      8行目: ハッシュタグ

    include_url=False: フック専用投稿（URLペナルティ回避）
    include_url=True:  URL付き完全投稿（リプライ挿入用）
    """
    artist = extract_artist(title)
    idx = int(hashlib.md5(title.encode()).hexdigest(), 16)

    # フック生成（20文字以内）
    hook = select_hook(genre, title, artist)
    if len(hook) > 20:
        number = extract_number(title)
        event = extract_event(title)
        alt_hooks = []
        for h in HOOKS.get(genre, HOOKS["default"]):
            if "{artist}" in h:
                continue
            h2 = h.replace("{number}", number).replace("{event}", event)
            if len(h2) <= 20:
                alt_hooks.append(h2)
        hook = alt_hooks[0] if alt_hooks else hook[:19] + "…"

    # 感情行: 断片化 or 感情ライン
    emotion = build_emotion_line(genre, title, idx)

    # コメントトリガー（動的3タイプ）
    comment_trigger = build_comment_trigger(genre, idx)

    hashtags = build_hashtags(artist, genre)

    if include_url:
        tweet = f"{hook}\n{emotion}\n\n{comment_trigger}\n\n{url}\n\n{hashtags}"
    else:
        # CTOハック: URLなし → IMP最大化フック投稿
        tweet = f"{hook}\n{emotion}\n\n{comment_trigger}\n\n{hashtags}"
    return tweet


def generate_url_reply(url: str, hashtags: str = "") -> str:
    """CTOハック §8: IMP条件達成後にリプライとして投稿するURL文"""
    return f"📖 記事全文はこちら👇\n{url}"


def generate_single(title: str, url: str, genre: str,
                    no_url_in_hook: bool = True) -> str:
    """v12.0 シングル投稿モード: 最もスコアが高い1パターンを返す。

    no_url_in_hook=True (デフォルト):
      CTOハック準拠 — フック本文にURLを含めない。
      URLは post_to_x.sh がリプライとして後から投稿する。
    no_url_in_hook=False:
      URL込みの完全投稿（後方互換・dry-run確認用）
    """
    import sys
    sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
    from x_pre_score import preflight_score

    include_url = not no_url_in_hook

    # 指定ジャンルのフック全バリエーションを先に生成（スコア選定の主候補）
    seen = set()
    candidates = []  # (score, text, is_primary_genre)

    # 1) 指定ジャンルのフック全パターン
    primary_hooks = HOOKS.get(genre, HOOKS["default"])
    for hook_template in primary_hooks:
        t = generate_tweet(title, url, genre, include_url=include_url)
        if t not in seen:
            seen.add(t)
            result = preflight_score(t)
            candidates.append((result["total"], t, True))

    # 2) フォールバック候補（指定ジャンルでスコア不足時のみ採用）
    fallback_genres = ["breaking", "comeback", "chart", "live"]
    if genre not in fallback_genres:
        for g in fallback_genres:
            t = generate_tweet(title, url, g, include_url=include_url)
            if t not in seen:
                seen.add(t)
                result = preflight_score(t)
                candidates.append((result["total"], t, False))

    # スコア評価: 指定ジャンル候補を優先（スコアが5点以上なら指定ジャンルを採用）
    primary = [(s, t) for s, t, is_p in candidates if is_p]
    fallback = [(s, t) for s, t, is_p in candidates if not is_p]

    if primary:
        best_primary_score, best_primary_text = max(primary, key=lambda x: x[0])
        # 指定ジャンルのスコアが十分なら採用（スコア閾値: 60）
        if best_primary_score >= 60:
            return best_primary_text
        # フォールバックと比較して高い方を採用
        if fallback:
            best_fallback_score, best_fallback_text = max(fallback, key=lambda x: x[0])
            return best_primary_text if best_primary_score >= best_fallback_score - 10 else best_fallback_text
        return best_primary_text

    # フォールバックのみの場合
    if fallback:
        return max(fallback, key=lambda x: x[0])[1]

    return candidates[0][1] if candidates else ""


def generate_tweet_ab(title_a: str, title_b: str, url: str, genre: str) -> dict:
    """ABテスト用: 2パターンのツイートを生成する。
    パターンA: 情報型タイトルベース
    パターンB: 感情型タイトルベース
    """
    tweet_a = generate_tweet(title_a, url, genre)
    tweet_b = generate_tweet(title_b, url, genre)
    return {"tweet_a": tweet_a, "tweet_b": tweet_b}


def generate_best_scoring_tweet(title: str, url: str, genre: str) -> str:
    """
    --force-best モード: 全フックバリアントを試してスコア最高のものを返す。
    スキップが続く場合の最終手段として呼ばれる。
    """
    import subprocess
    import json
    import sys

    artist = extract_artist(title)
    hashtags = build_hashtags(artist, genre)
    best_text = ""
    best_score = 0.0

    hooks_list = HOOKS.get(genre, HOOKS["default"])
    for i, raw_hook in enumerate(hooks_list):
        event = extract_event(title)
        number = extract_number(title)
        hook = raw_hook.replace("{artist}", artist).replace("{event}", event).replace("{number}", number)
        emotion = build_emotion_line(genre, title, i)
        trigger = build_comment_trigger(genre, i)
        tweet = f"{hook}\n{emotion}\n\n{trigger}\n\n{url}\n\n{hashtags}"

        try:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "x_pre_score.py"), tweet],
                capture_output=True, text=True, timeout=10,
                cwd=str(Path(__file__).parent.parent)
            )
            if not result.stdout.strip():
                continue
            d = json.loads(result.stdout)
            score = float(d.get("total", 0))
            if score > best_score:
                best_score = score
                best_text = tweet
        except Exception:
            continue

    # フォールバック: スコアリング全失敗時は最初のフックで生成
    if not best_text and hooks_list:
        raw_hook = hooks_list[0]
        event = extract_event(title)
        number = extract_number(title)
        hook = raw_hook.replace("{artist}", artist).replace("{event}", event).replace("{number}", number)
        emotion = build_emotion_line(genre, title, 0)
        trigger = build_comment_trigger(genre, 0)
        best_text = f"{hook}\n{emotion}\n\n{trigger}\n\n{url}\n\n{hashtags}"

    return best_text


def main():
    parser = argparse.ArgumentParser(description="X/Twitter投稿テンプレート生成")
    parser.add_argument("title", help="記事タイトル")
    parser.add_argument("url", help="記事URL")
    parser.add_argument("--genre", default="default",
                        choices=["news", "analysis", "beauty", "travel",
                                 # 後方互換エイリアス
                                 "breaking", "comeback", "controversy",
                                 "live", "chart", "fashion", "default"],
                        help="ジャンル: news/analysis/beauty/travel (v13.0)")
    parser.add_argument("--category-id", default="",
                        help="CATEGORY_IDから自動でgenreを判定")
    parser.add_argument("--title-b", default="",
                        help="ABテスト用タイトルB（感情型）")
    parser.add_argument("--ab", action="store_true",
                        help="ABテストモード: 2パターン出力")
    parser.add_argument("--force-best", action="store_true",
                        help="全バリアントをスコアリングして最高スコアを出力")
    args = parser.parse_args()

    genre = args.genre
    if args.category_id:
        genre = CATEGORY_TO_GENRE.get(args.category_id, genre)

    if args.ab and args.title_b:
        import json
        result = generate_tweet_ab(args.title, args.title_b, args.url, genre)
        print(json.dumps(result, ensure_ascii=False))
    elif args.force_best:
        tweet = generate_best_scoring_tweet(args.title, args.url, genre)
        print(tweet)
    else:
        tweet = generate_tweet(args.title, args.url, genre)
        print(tweet)


if __name__ == "__main__":
    main()
