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
import random
import re
import sys
import time

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
    "breaking":    ["{artist}、{event}を発表", "{artist}、{event}が確定",
                    "{artist}、{event}でファン反応"],
    "comeback":    ["{artist}、{event}リリース決定", "{artist}カムバック日程発表",
                    "{artist}、新譜{event}", "{artist}、{event}で復帰"],
    "controversy": ["{artist}、{event}の経緯", "{artist}、{event}に公式コメント",
                    "{artist}、{event}に対する反応"],
    "live":        ["{artist}来日公演、{number}都市で開催", "{artist}、{event}追加公演",
                    "{artist}ツアー{event}", "{artist}、{event}決定"],
    "chart":       ["{artist}が{number}冠を達成", "{artist}、{event}で記録更新",
                    "{artist}、{event}ランキング", "{artist}、{number}位"],
    "fashion":     ["{artist}、{event}スタイル公開", "{artist}着用{event}公開",
                    "{artist}コーデ{event}"],
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
    """タイトルからアーティスト名を抽出する（KNOWN_ARTISTSのみ信頼）"""
    for artist in KNOWN_ARTISTS:
        if artist.lower() in title.lower():
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
    2026-05-12: fallback "新" を空文字に変更。
    抽出失敗時は呼び出し側で {number} 必須テンプレを skip させる。
    """
    for m in re.finditer(r'(\d+)', title):
        n = int(m.group(1))
        if 2020 <= n <= 2035:
            continue
        if n > 100:
            continue
        return str(n)
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
    """ハッシュタグを生成する（3-4個: KPOPJOURNAL固定 + ランダム2-3個）"""
    # ブランドタグ固定（サイト認知用）
    tags = ["#KPOPJOURNAL"]
    # ベースタグプール（ここからランダムに1つ選ぶ）
    base_pool = ["#KPOP", "#K-POP速報", "#韓国", "#推し活", "#KPOP好きと繋がりたい"]
    base_tag = base_pool[_random_idx(len(base_pool))]
    tags.append(base_tag)

    # アーティスト名ハッシュタグ
    artist_tag = artist.replace(" ", "")
    # 汎用フォールバック・数字・年月は除外
    _invalid = {"K-POP", "K-POPアイドル", "韓国K", "K-P"}
    if (artist_tag and len(artist_tag) >= 2
            and artist_tag not in _invalid
            and not artist_tag.isdigit()
            and not re.search(r'^\d{4}年', artist_tag)):
        tags.append(f"#{artist_tag}")

    # ジャンル別追加タグプール（複数候補からランダム選択）
    genre_tag_pools = {
        "news":        ["#速報", "#韓国芸能", "#K-POPニュース", "#芸能ニュース"],
        "breaking":    ["#速報", "#緊急速報", "#K-POP速報", "#芸能ニュース"],
        "comeback":    ["#カムバック", "#新曲", "#MV", "#K-POP新曲"],
        "controversy": ["#韓国芸能", "#芸能ニュース", "#K-POP", "#話題"],
        "beauty":      ["#韓国コスメ", "#美容", "#スキンケア", "#コスメ好き"],
        "travel":      ["#韓国旅行", "#ソウル", "#推し活旅行", "#聖地巡礼"],
        "live":        ["#コンサート", "#ライブ", "#来日公演", "#チケット"],
        "chart":       ["#チャート", "#1位", "#記録更新", "#K-POPチャート"],
        "analysis":    ["#考察", "#K-POP解説", "#韓国芸能", "#分析"],
        "fashion":     ["#韓国ファッション", "#コーデ", "#私服", "#ファッション"],
        "default":     ["#韓国", "#推し活", "#K-POP好き", "#韓国エンタメ"],
    }
    pool = genre_tag_pools.get(genre, genre_tag_pools["default"])
    # poolからランダムに1つ選ぶ（baseと重複しないもの）
    available = [t for t in pool if t not in tags]
    if available:
        extra = available[_random_idx(len(available))]
        tags.append(extra)

    # 重複除去しつつ順序を維持
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
    """
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

    # フック生成（20文字以内）
    hook = select_hook(genre, title, artist)
    if len(hook) > 20:
        number = extract_number(title)
        event = extract_event(title)
        alt_hooks = []
        for h in HOOKS.get(genre, HOOKS["default"]):
            if "{artist}" in h:
                continue
            # event/number 必須テンプレを抽出失敗時に skip (2026-05-12 修正)
            if "{event}" in h and not event:
                continue
            if "{number}" in h and not number:
                continue
            h2 = h.replace("{number}", number).replace("{event}", event)
            if len(h2) <= 20:
                alt_hooks.append(h2)
        hook = alt_hooks[_random_idx(len(alt_hooks), title)] if alt_hooks else hook[:19] + "…"

    # 感情行: ランダム選択
    emotion = build_emotion_line(genre, title)

    # タイトル断片引用（duplicate content回避の要）
    title_fragment = extract_title_fragment(title, artist)

    # コメントトリガー（動的3タイプ、ランダム選択）
    comment_trigger = build_comment_trigger(genre)

    hashtags = build_hashtags(artist, genre)

    # タイトル断片がある場合は感情行の後に挿入
    if title_fragment:
        body = f"{hook}\n{emotion}\n{title_fragment}\n\n{comment_trigger}"
    else:
        body = f"{hook}\n{emotion}\n\n{comment_trigger}"

    if include_url:
        tweet = f"{body}\n\n{url}\n\n{hashtags}"
    else:
        # CTOハック: URLなし → IMP最大化フック投稿
        tweet = f"{body}\n\n{hashtags}"
    return tweet


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
