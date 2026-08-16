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
import html as _html
import random
import re
import sys
import time


def sanitize_tweet(text: str) -> str:
    """ツイート本文の最終サニタイズ。
    注記(2026-05-26): かつて lib/x_boost_selector.py に置く想定だったが同ファイルは
    現存しない。この関数がサニタイズの唯一の実体(他に import 元なし)。旧コメントの
    「x_boost_selector.py 由来」は別ファイルを読めば全容が分かるという誤解を生むため修正。"""
    if not text:
        return ""
    s = _html.unescape(text)
    s = re.sub(r"\d[\d,]*impr[^|]*\|\s*", "", s)
    s = re.sub(r"CTR[0-9.]+%\s*\|\s*", "", s)
    s = s.replace("　", " ")
    s = re.sub(r"[ \t]+\n", "\n", s).strip()
    return s

# --- アーティスト名抽出用パターン ---
# 2026-05-12: 新世代 (2023-2026 デビュー) を補強。本日 CORTIS が K-POP fallback
# された事故対策。
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
    # 2023-2026 新世代追加
    "CORTIS", "Hearts2Hearts", "MEOVV", "KATSEYE", "fromis_9", "fromis9",
    "TWS", "NEXZ", "NiziU", "IZNA", "ALLDAY PROJECT", "AHOF", "UNCHILD",
    "EVNNE", "EVAN", "P1Harmony", "TIOT", "ARTMS",
    # メンバー名
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
    # 2026-05-12 刷新: 「動いた/注目が集まっている/動向」等の抽象 AI 臭テンプレを撲滅
    # 数値・固有名詞を必ず含める設計に変更
    # event/number が抽出できない場合は plain テンプレ ({event}/{number} なし) を採用
    "news": [
        # 事実駆動型 — 数値・固有名詞を埋め込む (event/number 必須)
        "{artist}、{event}を発表",
        "{artist}、{event}が確定",
        "{artist}が{number}冠",
        "{artist}、{number}都市で公演決定",
        "{artist}来日、{event}の詳細",
        "{artist}、新譜{event}リリース",
        "{artist}、{event}の参加メンバー判明",
        "{artist}、{event}で記録更新",
        "{artist}が{event}で1位",
        "{artist}、{event}発表",
        # event/number 抽出失敗時用 plain テンプレ (placeholderなし)
        "{artist}の最新ニュース",
        "{artist}、公式発表",
        "{artist}が話題に",
        "{artist}、新情報",
        "{artist}、ファン反応続出",
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
        "判明…{artist}の本当の実力",
        "なぜ{artist}だけ違うのか",
        "{artist}の秘密、解禁された",
        "歴史的快挙…その裏側とは",
        "驚愕の事実…知ってた？",
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
        "衝撃…{artist}の美容法とは",
        "神コスメ、ついに解禁",
        "韓国で即完売した理由とは",
        "アイドル愛用コスメが判明",
        "これ知らないと損する美容法",
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
        "穴場スポット、ついに解禁",
        "推し活聖地、{number}選を解禁",
        "ガイドブックに載ってない場所",
        "ファン必見…新スポット判明",
        "行った人だけ知ってる場所",
    ],
    # ── デフォルト（後方互換・旧ジャンル名） ──────────────────────────────
    # 2026-05-12 刷新: 「動いた/動きがあった/速報」抽象テンプレを撲滅
    "default": [
        "{artist}、{event}の最新情報",
        "{artist}、{event}を発表",
        "{artist}、{event}で話題",
        "{artist}が{event}",
    ],
    # 旧ジャンル名エイリアス（後方互換) — 2026-05-12 刷新
    # 各 alias に plain fallback (placeholder無し) を1件以上含めて、extract 失敗時の
    # 「位」「冠を達成」「都市で開催」(数値空のまま) などの誤表示を回避
    "breaking":    ["{artist}、{event}を発表", "{artist}、{event}が確定",
                    "{artist}、{event}でファン反応",
                    "{artist}、新情報", "{artist}、公式発表"],
    "comeback":    ["{artist}、{event}リリース決定", "{artist}カムバック日程発表",
                    "{artist}、新譜{event}", "{artist}、{event}で復帰",
                    "{artist}、新曲リリース予定"],
    "controversy": ["{artist}、{event}の経緯", "{artist}、{event}に公式コメント",
                    "{artist}、{event}に対する反応",
                    "{artist}、公式声明発表"],
    "live":        ["{artist}来日公演、{number}都市で開催", "{artist}、{event}追加公演",
                    "{artist}、新{event}発表", "{artist}、{event}決定",
                    "{artist}、新公演発表", "{artist}、ツアー追加"],
    "chart":       ["{artist}が{number}冠を達成", "{artist}、{event}で記録更新",
                    "{artist}、{event}ランキング", "{artist}、{number}位",
                    "{artist}、新記録達成", "{artist}、チャート好調"],
    "fashion":     ["{artist}、{event}スタイル公開", "{artist}着用{event}公開",
                    "{artist}コーデ{event}",
                    "{artist}、新スタイル公開"],
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
    # 2026-05-12 刷新: 「記事にまとめている」「ファンの反応はリプ欄へ」「どう感じた?」
    # 等の AI 臭定型を撲滅。短い疑問・断定でユーザーに考える余白を作る。
    "論争系": [
        "どう見る?",
        "賛否は分かれそう",
        "ファンの意見は?",
        "詳細記事↓",
    ],
    "感動系": [
        "応援したい",
        "ファンの反応は?",
        "続報待ち",
        "詳細記事↓",
    ],
    "記録系": [
        "新記録の意味",
        "詳細データ↓",
        "今後の展開は",
        "詳細記事↓",
    ],
}

# ─── 感情行 (2行目) v13.0 ── 4ジャンル ────────────────────────────────────
# 未完結・答えを書かない・感情を動かす
EMOTION_LINES = {
    # ── ニュース速報: 緊迫感・予想外・拡散欲求 ─────────────────────────────
    # 2026-05-12 刷新: 「動いている/注目が集まっている/分かっていること/まとめている」
    # 等の AI 臭抽象テンプレを撲滅。タイトル断片を必ず含む形式に変更。
    "news": [
        "{title_frag}",
        "{title_frag}が判明",
        "公式発表は{title_frag}",
        "{title_frag} — その理由は",
        "{title_frag}が話題",
        "{title_frag}に反響",
        "{title_frag}の背景",
        "{title_frag}の詳細",
    ],
    # ── 分析/解説: 知的好奇心・「実は知らなかった」 ─────────────────────────
    "analysis": [
        "この数字の裏に隠された真実がある",
        "業界関係者も驚いた結果だという",
        "その事実を知る人は少ない",
        "見落としていた人も多いはずだ",
        "ファンの間でひそかに話題になっている",
        "知っているようで知らない事実がある",
        "データが語る真実は意外だった",
        "比較してみると驚きの結果になった",
        "この視点、意外と盲点だった",
        "冷静に見ると異常な数字だ",
    ],
    # ── 美容/ノウハウ: 「自分もできる」「やってみたい」 ─────────────────────
    "beauty": [
        "その方法は意外にもシンプルだった",
        "多くの人が間違えていることがある",
        "このスタイル、誰もが気になっていた",
        "入手困難なアイテムに秘密がある",
        "センスの差がここに出る",
        "知っているようで知らない美容法がある",
        "韓国では常識だという美容法がある",
        "これ、もっと早く知りたかった",
        "プロが教える方法は違った",
        "実はコスパ最強だったアイテムがある",
    ],
    # ── 旅行/まとめ: 「行きたい」「知らなかった」 ──────────────────────────
    "travel": [
        "知らないと損する場所がある",
        "現地に行った人しか知らない",
        "K-POPファンが選ぶ理由がある",
        "この場所、ガイドブックには載っていない",
        "推し活ファンの間でひそかに話題だ",
        "SNSで話題沸騰中のスポットがある",
        "行った人の満足度が異常に高い",
        "この場所、まだ穴場だった",
        "ファンが集まる理由がわかった",
    ],
    # 2026-05-12 刷新: 後方互換 alias も AI 臭抽象テンプレを撲滅、title_frag 駆動に
    "breaking":    [
        "{title_frag}",
        "{title_frag}が判明",
        "公式発表は{title_frag}",
    ],
    "comeback":    [
        "{title_frag}",
        "{title_frag}リリース確定",
        "新譜は{title_frag}",
    ],
    "controversy": [
        "{title_frag}",
        "公式は{title_frag}と発表",
        "{title_frag}に反応",
    ],
    "live":        [
        "{title_frag}",
        "公演詳細は{title_frag}",
        "{title_frag}で開催",
    ],
    "chart":       [
        "{title_frag}",
        "新記録は{title_frag}",
        "{title_frag}に到達",
    ],
    "fashion":     [
        "{title_frag}",
        "着用は{title_frag}",
        "{title_frag}スタイル",
    ],
    "default":     [
        "{title_frag}",
        "{title_frag}が判明",
        "公式は{title_frag}と発表",
        "{title_frag}に反応",
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
    """タイトルからアーティスト名を抽出する（KNOWN_ARTISTSのみ信頼）

    2026-05-26: 部分文字列誤マッチを修正。素の `in` だと「TREASURE」が「IVE」に、
    「ATEEZ」が…といった短い ASCII 名の包含で誤抽出していた(X ハッシュタグが
    #IVE になる事故)。ASCII 名は単語境界、長い名前を優先して照合する。
    """
    tl = title.lower()
    # 長い名前を優先(「Stray Kids」を「Kids」より、「TREASURE」を含む語を先に判定)
    for artist in sorted(KNOWN_ARTISTS, key=len, reverse=True):
        al = artist.lower()
        # ASCII を含む名前は前後が英数字でない位置でのみ一致(単語境界)。
        # 日本語名(カタカナ等)はそのまま包含で可。
        if re.search(r'[a-z0-9]', al):
            pat = r'(?<![a-z0-9])' + re.escape(al) + r'(?![a-z0-9])'
            if re.search(pat, tl):
                return artist
        elif al in tl:
            return artist
    # KNOWN_ARTISTSに一致しない場合はカタカナ名のみフォールバック
    # （英字ブランド名やショップ名の誤抽出を防止）
    m = re.match(r'^([ァ-ヶー]{3,10})[のがはをにで]', title)
    if m:
        candidate = m.group(1)
        # 一般名詞を除外
        generic = {"ポップアップ", "スキンケア", "ファッション", "コスメ", "ダイエット", "ソウル"}
        if candidate not in generic:
            return candidate
    return ""


def extract_event(title: str) -> str:
    """タイトルからイベント/出来事キーワードを抽出する。
    2026-05-12: 「動向」fallback を廃止 (抽象 AI 臭の主犯)。
    マッチしない場合は空文字を返し、呼び出し側で event 必須テンプレを skip させる。
    """
    event_words = [
        "カムバック", "復帰", "新曲", "MV", "ミニアルバム", "アルバム", "ツアー", "来日",
        "コンサート", "ファンミーティング", "脱退", "炎上", "熱愛", "結婚", "入隊", "除隊",
        "コラボ", "出演", "ソロデビュー", "ソロ曲", "シングル", "リリース",
        "ペンライト", "グッズ", "OST", "ドラマ", "映画", "ファンサ", "サイン会",
        "受賞", "ノミネート",
    ]
    for word in event_words:
        if word in title:
            return word
    return ""


def extract_number(title: str) -> str:
    """タイトルから意味のある数字を抽出する（年号・日付は除外）。
    2026-05-12:
      - fallback "新" を空文字に変更
      - extract_metric が成立する時は空を返す (例: 「3冠達成」がある時に
        「3位」誤テンプレを避ける)。metric 側で正確な数値+単位が拾われる。
    """
    if extract_metric(title):
        return ""
    for m in re.finditer(r'(\d+)', title):
        n = int(m.group(1))
        if 2020 <= n <= 2035:
            continue
        if n > 100:
            continue
        return str(n)
    return ""


def extract_metric(title: str) -> str:
    """タイトルから「数値+単位」を1つ抽出する (X投稿の具体性向上用)。
    例: 「Billboard 200で7週連続TOP10」→「7週連続TOP10」
        「25都市40公演」→「25都市40公演」
        「13年ぶりミニアルバム」→「13年ぶり」
        「3年ぶり韓国コンサート」→「3年ぶり」
    年号 (2020-2035) は除外、日付パターン (5月12日) も除外。
    """
    metric_patterns = [
        # 数値+単位+α (具体的な記録/達成)
        r'(\d+週連続TOP\d+)',
        r'(\d+週連続\d+位)',
        r'(\d+冠達成)',
        r'(TOP\d+)',
        r'(\d+\.\d+万人)',
        r'(\d+万人)',
        r'(\d+都市\d+公演)',
        r'(\d+都市)',
        r'(\d+公演)',
        r'(\d+ヶ国)',
        r'(\d+年ぶり)',
        r'(\d+周年)',
        r'(\d+冠)',
        r'(\d+位)',
        r'(\d+連覇)',
        r'(\d+万部)',
        r'(\d+億)',
    ]
    for pat in metric_patterns:
        m = re.search(pat, title)
        if m:
            v = m.group(1)
            # 年号誤検出ガード
            if re.match(r'^20[2-3]\d', v):
                continue
            return v
    return ""


def _random_idx(items_len: int, title: str = "") -> int:
    """タイムスタンプベースのランダムインデックスを返す。
    同じタイトルでも呼び出し時刻が違えば異なるインデックスになる。
    """
    # time.time_ns() でナノ秒精度のエントロピーを混ぜる
    seed = int(time.time_ns()) ^ hash(title) ^ random.randint(0, 2**32)
    return seed % items_len


def _recently_used_hooks(days: int = 5) -> set:
    """直近N日間のX投稿で使われたhookパターン(1行目)を返す。
    novelty向上のため同一テンプレ再利用を回避する。
    """
    import json as _json
    from datetime import datetime as _dt, timedelta as _td
    log_path = '/home/aiuser/kpop-ai-system/logs/x_posts.jsonl'
    cutoff = _dt.now() - _td(days=days)
    used = set()
    try:
        with open(log_path, encoding='utf-8') as _f:
            for _line in _f:
                try:
                    d = _json.loads(_line)
                    ts = d.get('ts', '')
                    if ts:
                        if _dt.fromisoformat(ts) < cutoff:
                            continue
                    text = d.get('text', '')
                    first_line = text.split('\n', 1)[0].strip()
                    if first_line:
                        used.add(first_line)
                except (ValueError, _json.JSONDecodeError):
                    continue
    except OSError:
        pass
    return used


def _hook_signature(hook_template: str, artist: str, event: str, number: str) -> str:
    """hook templateを実際の投稿1行目相当に展開してシグネチャ化"""
    s = hook_template.replace('{artist}', artist or 'K-POP')
    s = s.replace('{event}', event or '')
    s = s.replace('{number}', number or '')
    return s.strip()


def select_hook(genre: str, title: str, artist: str) -> str:
    """ジャンルに基づいてフックをランダム選択し、プレースホルダを埋める。
    直近5日に使ったhookは可能な限り回避 (novelty確保)

    2026-05-12: event/number が抽出できない場合、それを placeholder にもつ
    テンプレを skip (空文字埋め込みで「{artist}、を発表」のような壊れた hook を
    生成しないため)。
    """
    hooks = HOOKS.get(genre, HOOKS["default"])
    event = extract_event(title)
    number = extract_number(title)
    recent_used = _recently_used_hooks(days=5)

    # アーティスト名が有効な場合は {artist} を含むフックを優先選択
    if artist and artist not in ("K-POP", "K-POPアイドル", ""):
        candidates = [h for h in hooks if "{artist}" in h] or hooks
    else:
        candidates = [h for h in hooks if "{artist}" not in h] or hooks

    # event/number 必須テンプレを抽出失敗時に除外 (空埋め込み防止)
    if not event:
        candidates = [h for h in candidates if "{event}" not in h] or candidates
    if not number:
        candidates = [h for h in candidates if "{number}" not in h] or candidates

    # recent dedup: 直近使われたhookを除外したプールを優先
    fresh = [h for h in candidates
             if _hook_signature(h, artist, event, number) not in recent_used]
    pool = fresh if fresh else candidates  # 全部使用済みならフォールバック
    idx = _random_idx(len(pool), title)
    hook = pool[idx]

    hook = hook.replace("{artist}", artist or "K-POP")
    hook = hook.replace("{event}", event)
    hook = hook.replace("{number}", number)

    return hook


def build_emotion_line(genre: str, title: str, idx: int = 0) -> str:
    """v12.0 §3: 感情行（2行目）— 未完結・答えを書かない
    ランダム選択で毎回異なる感情行を生成する。
    2026-05-12: {title_frag} placeholder をサポート (タイトル断片を埋め込む)。
    title_frag が抽出できないテンプレは skip。
    """
    lines = EMOTION_LINES.get(genre, EMOTION_LINES["default"])
    artist = extract_artist(title)
    title_frag = extract_title_fragment(title, artist)
    # {title_frag} 必須テンプレは frag 抽出失敗時に skip
    if not title_frag:
        lines = [l for l in lines if "{title_frag}" not in l] or lines
    line = lines[_random_idx(len(lines), title)]
    return line.replace("{title_frag}", title_frag or "").strip()


def build_comment_trigger(genre: str, idx: int = 0) -> str:
    """v12.0 §5 + CTO: 動的コメントトリガー
    論争系・感動系・記録系 の3タイプからジャンルに応じてランダム選択
    """
    trigger_type = COMMENT_TRIGGER_TYPE.get(genre, "論争系")
    triggers = COMMENT_TRIGGERS[trigger_type]
    return triggers[_random_idx(len(triggers))]


def build_hashtags(artist: str, genre: str) -> str:
    """ハッシュタグを生成する。
    2026-05-12 刷新: 検索されない bot タグ (#KPOP好きと繋がりたい / #推し活 /
    #韓国エンタメ等) を削減し、**アーティスト名タグ + 検索される実タグ**を中心に。
    順序: [#アーティスト名] → [#ジャンル関連] → 計 2-3個 (4個は過剰)。
    #KPOPJOURNAL 自社ブランドタグは検索されないため最後尾、かつ高 CTR ジャンル
    のみに付与 (毎回付ける必要なし)。
    """
    tags = []

    # 1. アーティスト名タグ最優先 (ファンが検索する)
    # 2026-08-16: artist がハングルのまま渡ることがある(速報の artist は韓国語ソース
    # 由来。実測でキュー7件中3件が 에이핑크/휘인/김중연)。そのままだと #에이핑크 という
    # 日本のファンが検索しないタグになるか、抽出失敗でアーティストタグが消える。
    # 実測ではタグ2個の投稿(中央値74)が1個(61)を上回るため、取りこぼしは損失。
    # 正規化辞書で英名へ寄せてからタグ化する(引けなければ従来どおり素通し)。
    artist = (artist or "").strip()
    if re.search(r'[가-힣]', artist):
        try:
            import sys as _sys
            _sys.path.insert(0, '/home/aiuser/kpop-ai-system/lib')
            from thumbnail_source_resolver import normalize_artist_name as _norm
            _n = _norm(artist)
            if _n and not re.search(r'[가-힣]', _n):
                artist = _n
            else:
                artist = ""  # 同定できないハングルはタグにしない(検索されない)
        except Exception:
            artist = ""
    artist_tag = artist.replace(" ", "")
    _invalid = {"K-POP", "K-POPアイドル", "韓国K", "K-P", ""}
    has_artist_tag = (artist_tag and len(artist_tag) >= 2
                      and artist_tag not in _invalid
                      and not artist_tag.isdigit()
                      and not re.search(r'^\d{4}年', artist_tag))
    if has_artist_tag:
        tags.append(f"#{artist_tag}")

    # ジャンル別追加タグプール（複数候補からランダム選択）
    genre_tag_pools = {
        # 2026-05-12 刷新: 検索される実タグだけ。bot ハッシュタグを排除
        "news":        ["#KPOP", "#Kpopニュース"],
        "breaking":    ["#速報", "#KPOP"],
        "comeback":    ["#カムバック", "#新曲", "#kpopcomeback"],
        "controversy": ["#KPOP", "#話題"],
        "beauty":      ["#韓国コスメ", "#美容"],
        "travel":      ["#韓国旅行", "#ソウル"],
        "live":        ["#KPOPライブ", "#来日公演"],
        "chart":       ["#KPOPチャート", "#Billboard"],
        "analysis":    ["#KPOP考察"],
        "fashion":     ["#韓国ファッション"],
        "default":     ["#KPOP"],
    }
    pool = genre_tag_pools.get(genre, genre_tag_pools["default"])
    available = [t for t in pool if t not in tags]
    if available:
        extra = available[_random_idx(len(available))]
        tags.append(extra)

    # ブランドタグ #KPOPJOURNAL は付けない(2026-08-16)。
    # 自社タグは検索需要がほぼ無いのに3枠のうち1つを占有し、実際に検索される
    # アーティスト名タグ/ジャンルタグを押し出していた。Phase1実測では
    # タグ2個の投稿(imp中央値74)が1個(61)・0個(47)を上回っており、
    # 「枠を実タグで埋める」方が効く。ブランド想起はプロフィール/署名で担う。

    seen = set()
    tags = [t for t in tags if not (t in seen or seen.add(t))]

    # 最大3個（post_to_x.sh互換: 4個以上はBLOCKされる）
    return " ".join(tags[:3])


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


def extract_title_fragment(title: str, artist: str) -> str:
    """タイトルからキーワード断片を抽出して引用テキストを生成する。
    毎回異なる引用フレーズを作ることで duplicate content を回避する。
    2026-05-12: extract_metric で「数値+単位」を最優先抽出 (X 投稿の具体性向上)。
    """
    # 「数値+単位」を最優先 (7週連続TOP10 / 25都市40公演 / 13年ぶり 等)
    metric = extract_metric(title)
    if metric:
        return metric

    # タイトルから括弧・アーティスト名を除去して本体を取る
    clean = re.sub(r'【[^】]*】|（[^）]*）|\([^)]*\)', '', title).strip()
    clean = clean.replace(artist, '').strip() if artist else clean

    # タイトルからキーワードを抽出（助詞で分割）
    parts = re.split(r'[のがはをにでと、。！？!?\s]+', clean)
    # 日本語キーワードのみ抽出（英字ブランド名の誤抽出を防止）
    _stopkw = {"ポップアップ", "コレクション", "オープン", "スペシャル", "トレンド", "サマー"}
    keywords = [p for p in parts if len(p) >= 2 and not p.isdigit()
                and p not in _stopkw and not p.isascii()]

    if not keywords:
        return ""

    # 文字境界尊重: 12字以内のkeywordを優先選択
    # 2026-05-07: 「Mnet新ダンスプログラ」のような語中切断を防ぐ
    short_keywords = [k for k in keywords if len(k) <= 12]
    pool = short_keywords or keywords
    kw = random.choice(pool)
    if len(kw) > 12:
        # やむを得ず長すぎる語のみ→助詞境界か文字種境界で切る
        # カタカナ/漢字/ひらがなの境目を探して、そこまでに収める
        cut = 12
        for i in range(min(12, len(kw)-1), 4, -1):
            ch_a, ch_b = kw[i-1], kw[i]
            # 文字種が変わる位置を境界とみなす
            def _kind(c):
                if '゠' <= c <= 'ヿ': return 'kata'
                if '぀' <= c <= 'ゟ': return 'hira'
                if '一' <= c <= '鿿': return 'kanji'
                return 'other'
            if _kind(ch_a) != _kind(ch_b):
                cut = i
                break
        kw = kw[:cut]
    # 2026-05-12 刷新: 「のあらまし」「のポイント」「を簡単に」等の AI 臭 suffix を撲滅。
    # キーワードそのまま or 最小限の修飾 (「」括弧のみ) で具体性を保つ。
    fragment_patterns = [
        '「{kw}」',
        '{kw}',
        '"{kw}"',
    ]
    pattern = fragment_patterns[_random_idx(len(fragment_patterns), title)]
    return pattern.format(kw=kw)


def generate_tweet(title: str, url: str, genre: str, include_url: bool = True) -> str:
    """完成したツイートテキストを生成する (v14.0 — Phase 1 即時止血)

    2026-05-12 v14.0 刷新理由:
      v13.0 まで「フック+感情行+title_frag+comment_trigger」の多行テンプレを
      採用していたが、title_frag 抽出が「資格取得」「写真投稿」「満足度」等の
      意味のない短語を引用し、同じ単語が3行繰り返される word salad を量産。
      文法も破綻 (「公式発表は満足度」等) して X 上で表示品質が壊滅。

      v14.0 Phase 1: faceless aggregator 戦略に回帰。タイトルそのまま +
      最小限のハッシュタグ。AI 臭の煽り (まさかの展開/賛否は分かれそう) を
      完全撤廃し、可読性と「文章として成立する」最低保証を確保する。

      Phase 2 (別 PR): gpt-4o-mini で記事本文を読んで自然な引用+数値型の
      ツイートを生成 (LLM 駆動)。Phase 1 で止血した上で実装する。

    構造 (v14.0):
      1行目: 記事タイトル (そのまま、整形のみ)
      2行目: 空白
      3行目: URL (include_url=True の場合のみ)
      4行目: 空白
      5行目: ハッシュタグ (artist + 1 topic、最大2個)

    include_url=False: フック専用投稿（URLペナルティ回避）→ タイトル+タグのみ
    include_url=True:  URL付き完全投稿
    """
    artist = extract_artist(title)
    hashtags = build_hashtags(artist, genre)

    # タイトルを軽く整形 (Twitter 安全文字列化)
    body = sanitize_tweet(title.strip())

    # タイトル + URL + ハッシュタグの最小構成
    if include_url:
        tweet = f"{body}\n\n{url}\n\n{hashtags}"
    else:
        tweet = f"{body}\n\n{hashtags}"
    return tweet


def _llm_tweet_body(title: str, source_text: str, genre: str) -> str:
    """gpt-4o-mini で記事本文を読んで自然な日本語ツイート本文 (タイトル相当) を生成。

    禁止フレーズ:
      - 煽り (まさかの展開, 賛否分かれそう, 衝撃の事実, ファン反応続出)
      - engagement bait (みんなはどう思う?, 私はアリだと思うけど)
      - meta (本記事では, この記事は, まとめている)

    要件:
      - 体言止め1-2文 (合計 200字以内、180字 推奨)
      - 数値・固有名詞・日付があれば必ず含める
      - 引用は「」 で囲む
      - URL/ハッシュタグは含めない (呼び出し側で別途追加)
      - 結果は1行 (改行禁止) — 改行は呼び出し側でレイアウト

    失敗時は空文字を返し、呼び出し側で Phase 1 (タイトルそのまま) にフォールバック。
    """
    import os
    import json
    import urllib.request
    api_key = os.getenv('OPENAI_API_KEY', '')
    if not api_key or not source_text:
        return ''

    system = (
        "あなたは K-POP ニュースサイトの編集者です。"
        "記事から X (Twitter) 用のツイート本文を1つ書きます。"
        "\n\n【禁止】"
        "\n- 「まさかの展開」「賛否分かれそう」「衝撃の事実」「ファン反応続出」等の煽り文句"
        "\n- 「みんなはどう思う?」「私はアリだと思うけど」等の engagement bait"
        "\n- 「本記事では」「この記事は」「まとめている」等の meta 表現"
        "\n- ハッシュタグ・URL・絵文字の出力"
        "\n- 改行 (出力は必ず1行)"
        "\n\n【要件】"
        "\n- 体言止め1-2文、合計 180 字以内"
        "\n- 数値・固有名詞・日付・場所がソースにあれば必ず含める"
        "\n- 引用がある場合は「」で囲む"
        "\n- タイトルを丸コピーしない (タイトル≠ツイート本文)"
        "\n- 客観的・事実駆動の faceless aggregator スタイル"
    )
    user = f"タイトル: {title}\n\n本文 (抜粋): {source_text[:1200]}\n\nツイート本文 (1行のみ、ハッシュタグ・URL なし):"

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
        'temperature': 0.3,
        'max_tokens': 200,
    }).encode()
    req = urllib.request.Request(
        'https://api.openai.com/v1/chat/completions',
        data=body,
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read())
        out = res['choices'][0]['message']['content'].strip()
    except Exception:
        return ''

    # 2026-05-13: cost ledger に記録 (kpi_dashboard で集計、Phase 2 重複呼出監視)
    try:
        from datetime import datetime, timezone, timedelta
        from pathlib import Path
        usage = res.get('usage', {})
        in_tok = int(usage.get('prompt_tokens', 0))
        out_tok = int(usage.get('completion_tokens', 0))
        # gpt-4o-mini pricing: input $0.00015 / output $0.0006 per 1K
        cost = in_tok / 1000 * 0.00015 + out_tok / 1000 * 0.0006
        JST = timezone(timedelta(hours=9))
        now = datetime.now(JST)
        entry = {
            'ts': now.isoformat(),
            'date': now.strftime('%Y-%m-%d'),
            'caller': 'x_tweet_llm',
            'model': 'gpt-4o-mini',
            'input': in_tok,
            'output': out_tok,
            'cost_usd': round(cost, 6),
        }
        log_path = Path('/home/aiuser/kpop-ai-system/logs/x_tweet_llm.jsonl')
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, 'a', encoding='utf-8') as _f:
            _f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass

    # 後処理: 改行・URL・ハッシュタグ・エンコード残骸を除去
    out = out.replace('\n', ' ').replace('\r', ' ').strip()
    out = re.sub(r'https?://\S+', '', out).strip()
    out = re.sub(r'#\S+', '', out).strip()
    # 禁止フレーズ post-check (LLM がプロンプト指示を破った場合の二段防御)
    forbidden = [
        'まさかの展開', '賛否は分かれそう', '賛否分かれそう', '衝撃の事実',
        'ファン反応続出', 'みんなはどう思う', '私はアリだと思う',
        '本記事では', 'この記事は', 'まとめている', 'どう思う?', 'どう思う？',
        '動向', 'あらまし', 'ポイント',
    ]
    for kw in forbidden:
        if kw in out:
            return ''
    # 長すぎる場合は切る (200 字想定だが念のため)
    if len(out) > 200:
        out = out[:198] + '…'
    return out if out else ''


def generate_tweet_llm(title: str, url: str, source_text: str, genre: str,
                      include_url: bool = True) -> str:
    """v14.0 Phase 2: LLM 駆動ツイート生成。

    記事本文 (source_text) を gpt-4o-mini に渡して、自然な事実駆動の
    ツイート本文を生成する。失敗時は Phase 1 (generate_tweet) にフォールバック。

    呼び出し側 (lib/x_poster.py 等) で X_TWEET_LLM=1 環境変数で有効化を制御。
    """
    body = _llm_tweet_body(title, source_text, genre)
    if not body:
        # LLM 失敗 → Phase 1 (タイトルそのまま) にフォールバック
        return generate_tweet(title, url, genre, include_url=include_url)

    artist = extract_artist(title)
    hashtags = build_hashtags(artist, genre)
    body = sanitize_tweet(body)

    if include_url:
        return f"{body}\n\n{url}\n\n{hashtags}"
    else:
        return f"{body}\n\n{hashtags}"


def generate_url_reply(url: str, hashtags: str = "") -> str:
    """CTOハック §8: IMP条件達成後にリプライとして投稿するURL文
    毎回異なるリプライ文でduplicate contentを回避する。
    """
    reply_templates = [
        "📖 記事全文はこちら👇\n{url}",
        "📰 詳しくはこちら👇\n{url}",
        "🔗 全文はこちらから\n{url}",
        "📖 続きはこちら👇\n{url}",
        "📝 記事の詳細はこちら\n{url}",
        "🔗 気になる人はチェック👇\n{url}",
        "📖 詳細レポートはこちら\n{url}",
        "📰 記事の全文はこちらから\n{url}",
    ]
    template = reply_templates[_random_idx(len(reply_templates))]
    return template.format(url=url)


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
    emotion_lines = EMOTION_LINES.get(genre, EMOTION_LINES["default"])
    trigger_type = COMMENT_TRIGGER_TYPE.get(genre, "論争系")
    triggers_list = COMMENT_TRIGGERS[trigger_type]
    for i, raw_hook in enumerate(hooks_list):
        event = extract_event(title)
        number = extract_number(title)
        hook = raw_hook.replace("{artist}", artist).replace("{event}", event).replace("{number}", number)
        emotion = emotion_lines[i % len(emotion_lines)]
        trigger = triggers_list[i % len(triggers_list)]
        title_frag = extract_title_fragment(title, artist)
        frag_line = f"\n{title_frag}" if title_frag else ""
        tweet = f"{hook}\n{emotion}{frag_line}\n\n{trigger}\n\n{url}\n\n{hashtags}"

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
        emotion = build_emotion_line(genre, title)
        trigger = build_comment_trigger(genre)
        title_frag = extract_title_fragment(title, artist)
        frag_line = f"\n{title_frag}" if title_frag else ""
        best_text = f"{hook}\n{emotion}{frag_line}\n\n{trigger}\n\n{url}\n\n{hashtags}"

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
