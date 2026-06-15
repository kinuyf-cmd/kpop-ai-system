#!/usr/bin/env python3
"""popup_event_fetcher.py — M7 段階7.2(F + G 項目)

PRTIMES /index.rdf と eplus sitemap_daily_kkn.xml から
K-POP 関連の Popup / Event シグナルを抽出して構造化 JSON に保存する。

実行:
    python3 lib/popup_event_fetcher.py            # 通常実行
    DRY_RUN=1 python3 lib/popup_event_fetcher.py  # ファイル出力なし

出力:
    ~/.kpop_recovery/popup_event_signals/{YYYYMMDD}.json

設計方針:
- 取得は週次(本スクリプトは1回呼ばれて完結する単発バッチ)
- robots.txt 準拠(PRTIMES Allow /、eplus は detail ページ Allow)
- レート制限: 1秒間隔(time.sleep(1))
- ハルシネーション最小化: タイトル/会場/日時は原文ママ抽出、推測しない
- Layer 2 引用記事 (60% 引用率) を生成する後段への入力データ
"""
from __future__ import annotations
import json
import os
import re
import sys
import time
import ssl
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

# ─── 設定 ──────────────────────────────────────────────
USER_AGENT = "KPOP-JOURNAL-Bot/1.0 (+https://kpopjournal.tokyo; citation-only)"
TIMEOUT = 30
SLEEP = 1.0  # 媒体ごとの間隔
OUT_DIR = Path.home() / ".kpop_recovery" / "popup_event_signals"
DRY_RUN = bool(int(os.environ.get("DRY_RUN", "0")))

# ─── SSL: kbuzzlab は Let's Encrypt 新ルート "ISRG Root YR" を使う。
# このルートはまだ OS / certifi の信頼ストアに未収録のため、検証が
# CERTIFICATE_VERIFY_FAILED で落ちる(2026-06 実測、5月以降 popup 取得停止の一因)。
# 対策: certifi に Root YR(X1クロス署名 + 自己署名)を足した独自バンドルを使う。
# バンドルは tools/refresh_ca_bundle.sh が生成・更新する。
# 不在時はデフォルト検証にフォールバック(他ホストは標準CAで通る)。
_CA_BUNDLE = Path(__file__).resolve().parent.parent / "data" / "ca" / "kpop_ca_bundle.pem"
def _make_ssl_context() -> ssl.SSLContext | None:
    if _CA_BUNDLE.is_file():
        try:
            return ssl.create_default_context(cafile=str(_CA_BUNDLE))
        except Exception:
            return None
    return None
_SSL_CTX = _make_ssl_context()

# K-POP キーワード — 短いラテン語キーワードは単語境界マッチ(false positive 防止)
# 例: "V" は "GRAPEVINE" にマッチさせない、"Lisa" は "LiSA" にマッチさせない
#
# 設計:
# - WORD_BOUND_KEYWORDS: 英数字記号のみ。正規表現で \b 境界マッチ
# - SUBSTRING_KEYWORDS:  日本語/韓国語含む。substring マッチで十分(誤マッチが起きにくい)
WORD_BOUND_KEYWORDS = [
    # ジャンル
    "K-POP", "K POP", "KPOP",
    # 単独だと曖昧な短語は WORD 境界(英大文字スペース区切り)で限定
    # "V" "RM" は 1-2 文字すぎて誤マッチ多発するため除外
    # (BTS 関連の文脈は BTS / 防弾少年団 / JIMIN 等でカバー)
    "BTS", "IVE", "NCT", "EXO", "ZB1", "TWS",
]
# 4文字以上の英大文字キーワードは substring マッチで足りる
SUBSTRING_KEYWORDS_EN = [
    "BLACKPINK", "NewJeans", "Newjeans", "NEWJEANS", "TWICE", "SEVENTEEN",
    "Stray Kids", "STRAY KIDS", "ENHYPEN", "TOMORROW X TOGETHER", "TXT",
    "aespa", "AESPA", "ITZY", "(G)I-DLE", "G-IDLE", "Le Sserafim", "LE SSERAFIM",
    "RIIZE", "ZEROBASEONE", "ILLIT", "ATEEZ", "TREASURE", "iKON", "IKON",
    "Red Velvet", "RED VELVET", "NMIXX", "Kep1er", "KEP1ER",
    "BABYMONSTER", "Babymonster", "MEOVV",
    # メンバー名(4文字以上、誤マッチしにくい)
    "Jimin", "JIMIN", "Jungkook", "Jung Kook", "JUNG KOOK",
    "Jennie", "JENNIE", "Rosé", "Jisoo", "JISOO",
    "Wonyoung", "WONYOUNG", "Yujin", "YUJIN",
    "Taeyong", "TAEYONG", "Karina", "KARINA",
    "TAEMIN", "Taemin", "BAEKHYUN", "Baekhyun", "CHANYEOL", "Chanyeol",
    "Hanni", "HANNI",
]
SUBSTRING_KEYWORDS = [
    # 日本語ジャンル
    "ケーポップ", "韓流", "韓国アイドル", "K-POP", "韓国ガールズグループ", "韓国ボーイズグループ",
    "韓国ボーイズバンド", "韓国ガールズバンド", "韓国男性アイドル", "韓国女性アイドル",
    # 日本語グループ名
    # 注: 一般的な日本語/ブランド名と substring 衝突する語は除外する
    #   ([[feedback_guard_false_positives]] / 実調査での誤マッチ):
    #   - "ライズ" → デジライズ / クリアライズ / Tales of ARISE
    #   - "エスパ" → エスパル(仙台の商業施設)
    #   - "セブンティーン" → セブンティーンアイス(アイス)
    #   - "ニジュー" → 二重 / にじゅう
    #   これらは SUBSTRING_KEYWORDS_EN の英表記(RIIZE/aespa/SEVENTEEN)でカバー。
    "防弾少年団", "ブラックピンク", "ニュージーンズ", "アイヴ", "トワイス", "セブチ",
    "ストレイキッズ", "エンハイフン", "トゥモローバイトゥギャザー", "テヨン", "テミン",
    "イッジ", "ジーアイドル", "ルセラフィム", "アイリット",
    "アチズ", "トレジャー", "エクソ", "ゼロベースワン",
    "トゥアス",  # TWS(日本デビュー済)。distinctive で誤マッチしにくい
    # 日本語メンバー名(リサ/ジス/V 等の短語は誤マッチが多いので除外。
    #  代わりに WORD_BOUND_KEYWORDS の英表記でカバー)
    "ジョングク", "ウォニョン",
    "カリナ", "ベクヒョン", "チャンヨル",
    # 韓国語(ハングル)
    "방탄소년단", "블랙핑크",
]

# プリコンパイル: 短いキーワードは(ascii-)単語境界マッチ
# (?:^|(?<=[^A-Za-z0-9]))  ... (?:$|(?=[^A-Za-z0-9]))
# 日本語/句読点も「境界」扱いになるので "BTSのカフェ" でも BTS にマッチする
def _build_word_pattern(words):
    escaped = [re.escape(w) for w in sorted(words, key=len, reverse=True)]
    return re.compile(
        r"(?:^|(?<=[^A-Za-z0-9]))(" + "|".join(escaped) + r")(?:$|(?=[^A-Za-z0-9]))",
        re.IGNORECASE,
    )

_WORD_RE = _build_word_pattern(WORD_BOUND_KEYWORDS)

# Popup 判定キーワード
POPUP_KEYWORDS = ["ポップアップ", "ポップアップストア", "POP-UP", "POPUP", "POP UP STORE", "期間限定ストア", "コラボカフェ"]
# Event 判定キーワード(コンサート・ライブ・ファンミ等)
EVENT_KEYWORDS = ["ライブ", "コンサート", "公演", "ツアー", "フェス", "ファンミーティング", "ファンミ",
                  "FAN MEETING", "TOUR", "LIVE", "CONCERT", "ショーケース", "Showcase", "ファンイベント"]

# ─── ユーティリティ ─────────────────────────────────────
def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def fetch(url: str, accept: str = "*/*") -> str:
    """URLを取得しテキストを返す。失敗時は空文字。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_SSL_CTX) as r:
            data = r.read()
            ctype = r.headers.get("Content-Type", "")
            # decode
            charset = "utf-8"
            m = re.search(r"charset=([\w-]+)", ctype, re.I)
            if m:
                charset = m.group(1)
            try:
                return data.decode(charset, errors="replace")
            except LookupError:
                return data.decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        log(f"  fetch error {url}: {e}")
        return ""

def matches_kpop(title: str) -> str | None:
    """タイトルが K-POP 関連なら、マッチした最初のキーワードを返す。

    - WORD_BOUND_KEYWORDS は \\b 境界マッチ(短い英大文字キーワード)
    - SUBSTRING_KEYWORDS_EN は単純な含有マッチ(4文字以上の英表記、誤マッチ低)
    - SUBSTRING_KEYWORDS は単純な含有マッチ(日本語/韓国語)
    """
    if not title:
        return None
    m = _WORD_RE.search(title)
    if m:
        return m.group(0)
    for kw in SUBSTRING_KEYWORDS_EN:
        if kw in title:
            return kw
    for kw in SUBSTRING_KEYWORDS:
        if kw in title:
            return kw
    return None

# ─── 韓国関連ジャンル判定(タスク#26: K-POP限定 → 韓国関連全般に拡大)──
#   オーナー指定の対象ジャンル:
#     ①K-POP ②韓国ドラマ・俳優・映画 ③韓国コスメ・ビューティー
#     ④韓国フード・グルメ ⑤韓国ファッション
#
#   PRTIMES(日本ソース)の判定を K-POP 限定から韓国関連全般に広げる。
#   ただし誤マッチ厳禁([[feedback_guard_false_positives]]):
#   - 「韓国」を含むだけの無関係リリースや、一般語(「コスメ」「グルメ」
#     「ドラマ」単独)で日本の無関係 popup を拾ってはならない。
#   - 原則「韓国/K-/韓流 などの韓国シグナル」を内包する複合語のみを採用する
#     (例: 「韓国コスメ」○ / 「コスメ」単独 ×)。
#   - 単独でも安全な確実な韓国固有名詞(誤マッチ低い実在ブランド/作品名)だけ
#     を厳選追加する(推測で大量追加しない)。
#   さらに parse_prtimes() 側で classify()(popup/event 判定)との二重ゲートを
#   かけるため、ジャンル語が当たっても popup/event でなければ signal 化しない。

# ジャンル → マッチ語のテーブル。値はいずれも「韓国シグナルを内包する複合語」
# または「単独で安全な確実な韓国固有名詞」のみ。
KOREA_GENRE_KEYWORDS: dict[str, list[str]] = {
    # ② 韓国ドラマ・俳優・映画(Kドラマ/韓流)
    "drama": [
        "韓国ドラマ", "韓流ドラマ", "Kドラマ", "K-ドラマ", "韓国映画", "韓国俳優",
        "韓流スター", "韓流俳優", "韓国時代劇",
        # 確実な固有名(著名・一般語衝突しない作品/俳優名のみ厳選)
        "愛の不時着", "梨泰院クラス", "イカゲーム", "イ・ミンホ", "ヒョンビン",
    ],
    # ③ 韓国コスメ・ビューティー(K-beauty)
    "beauty": [
        "韓国コスメ", "韓国スキンケア", "韓国ビューティー", "Kビューティー", "韓国メイク",
        "K-beauty", "K-BEAUTY", "K-Beauty", "Kビューティ", "韓国発コスメ",
        # 確実なブランド名(実在・誤マッチ低い distinctive 表記のみ。
        # PRTIMES 実フィードで韓国コスメ文脈で確認できたものを優先採用)
        "ロムアンド", "rom&nd", "MEDIHEAL", "メディヒール", "COSRX", "コスアールエックス",
        "Anua", "アヌア", "TIRTIR", "ティルティル", "BANILA CO", "バニラコ",
    ],
    # ④ 韓国フード・グルメ(Kフード)
    "food": [
        "韓国グルメ", "韓国料理", "韓国フード", "Kフード", "K-FOOD", "K-Food",
        "韓国スイーツ", "韓国カフェ", "韓国食品",
        # 「コラボカフェ」は韓国文脈時のみ(=このテーブルは韓国シグナル前提なので
        #  ここに単独で入れず、food 用 distinctive 語は上記の複合語に限定)
    ],
    # ⑤ 韓国ファッション(Kファッション)
    "fashion": [
        "韓国ファッション", "Kファッション", "K-FASHION", "K-Fashion", "韓国アパレル",
        "韓国系ファッション", "オルチャンファッション",
    ],
}

# プリコンパイル: ジャンル語は基本日本語/distinctive 英表記なので substring で十分。
# 大文字小文字を無視したいので lower 化したテーブルも持つ。
_KOREA_GENRE_LOWER: dict[str, list[str]] = {
    g: [kw.lower() for kw in kws] for g, kws in KOREA_GENRE_KEYWORDS.items()
}


def detect_korea_genre(*texts: str) -> tuple[str, str] | None:
    """韓国関連ジャンルを判定し (genre, matched_keyword) を返す。

    K-POP は既存の matches_kpop() でカバーするためここでは扱わず、
    呼び出し側で K-POP 判定を優先する(KOREA_GENRE_KEYWORDS は K-POP 以外の
    4ジャンルのみ)。

    判定対象は title / keywords 等、複数文字列を OR で見る。
    各ジャンル語は韓国シグナルを内包するか確実な韓国固有名なので、
    substring マッチで誤マッチが起きにくい。
    """
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return None
    for genre, kws in _KOREA_GENRE_LOWER.items():
        for kw in kws:
            if kw in blob:
                # 元の正規表記を返す(matched index 経由)
                idx = _KOREA_GENRE_LOWER[genre].index(kw)
                return genre, KOREA_GENRE_KEYWORDS[genre][idx]
    return None


def matches_korea(title: str, keywords: str = "") -> tuple[str, str] | None:
    """韓国関連全般(K-POP + 4ジャンル)判定。

    戻り値: (korea_genre, matched_keyword)
      - K-POP がヒットした場合: ("kpop", matched_kpop_keyword)
      - ドラマ/コスメ/フード/ファッションがヒットした場合: (genre, matched_keyword)
      - いずれもヒットしない場合: None

    K-POP を最優先(既存判定を壊さない)。次に 4ジャンルを判定。
    """
    # K-POP 優先(既存 matches_kpop は title/keywords を個別に見る運用)
    kpop_kw = matches_kpop(title) or matches_kpop(keywords)
    if kpop_kw:
        return "kpop", kpop_kw
    # 韓国関連 4ジャンル
    g = detect_korea_genre(title, keywords)
    if g:
        return g
    return None


def classify(title: str) -> str | None:
    """popup / event / None を返す。popup 優先。"""
    if not title:
        return None
    upper = title.upper()
    for kw in POPUP_KEYWORDS:
        if kw.upper() in upper:
            return "popup"
    for kw in EVENT_KEYWORDS:
        if kw.upper() in upper:
            return "event"
    return None

def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=9))).isoformat()

# ─── PRTIMES sitemap-news パーサ ────────────────────────
#   2026-05-21 改修(タスク#25 日本popupソース強化):
#   旧実装は /index.rdf(直近約200件・全カテゴリ)のみを見ていたため、
#   日本の K-POP popup が流れる前に取りこぼし、実質 0 件だった。
#
#   実調査で確認した事実(全て curl 200・中身取得済):
#   - /index.rdf            … 201 件のみ。流量が速く popup を捕捉しづらい。
#   - keyword ページ        … HTTP200 だが完全 JS 描画。サーバHTMLに
#                             release URL も __NEXT_DATA__ も無し(抽出不可)。
#   - keyword別RSS(K-POP.rdf)… 404(存在しない)。
#   - companyrdf.php?company_id=<id> … 実在(application/xml)。ただし
#                             K-POP系レーベルの company_id を実在確認できる
#                             安定手段が無く(ID推測は捏造リスク)、不採用。
#   - ★ /sitemap-news.xml    … HTTP200・1700件超。各 <url> に
#                             <loc>(release URL)+<news:title>(完全タイトル)
#                             +<news:keywords>(カテゴリ/アーティスト/ブランドタグ)
#                             +<news:publication_date> がサーバ側で入っている。
#                             robots.txt に sitemap: として明記=公式に開放。
#   → PRTIMES ソースを sitemap-news.xml に切替。title だけでなく
#     keywords も K-POP 判定の対象にし(アーティスト名が keywords にのみ
#     入る popup を拾うため)、取りこぼしを大幅に減らす。
#   ※ keywords には「韓国」「韓国コスメ」等が大量に付くため、bare「韓国」では
#     誤マッチ(食品/旅行/コスメ)が爆発する([[feedback_guard_false_positives]])。
#     そこで判定は「K-POP/グループ名/メンバー名(matches_kpop)」に限定し、
#     さらに popup/event 分類が成立したものだけを signal 化する(二重ゲート)。
PRTIMES_NEWS_SITEMAP = "https://prtimes.jp/sitemap-news.xml"


def _html_unescape_min(s: str) -> str:
    return (
        s.replace("&amp;", "&")
        .replace("&apos;", "'")
        .replace("&quot;", '"')
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


# XML 1.0 で許されない制御文字(PRTIMES sitemap には稀に \x0b 等が混入し
# strict パーサが落ちる)を除去する。許可: \t \n \r と U+0020 以降。
_ILLEGAL_XML_RE = re.compile(
    "[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]"
)


def _sanitize_xml(body: str) -> str:
    return _ILLEGAL_XML_RE.sub("", body)


def _parse_news_with_regex(body: str) -> list[tuple[str, str, str, str]]:
    """ET が落ちた場合のフォールバック。
    各 <url> ブロックから (loc, title, keywords, date) を正規表現で取り出す。
    """
    out = []
    for blk in re.findall(r"<url>(.*?)</url>", body, re.S):
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", blk, re.S)
        if not loc:
            continue
        title = re.search(r"<news:title>(.*?)</news:title>", blk, re.S)
        kw    = re.search(r"<news:keywords>(.*?)</news:keywords>", blk, re.S)
        date  = re.search(r"<news:publication_date>(.*?)</news:publication_date>", blk, re.S)
        out.append((
            loc.group(1).strip(),
            (title.group(1).strip() if title else ""),
            (kw.group(1).strip() if kw else ""),
            (date.group(1).strip() if date else ""),
        ))
    return out


# ─── PRTIMES 個別リリースページからの開催情報抽出(タスク#27)──────
#   2026-05-21 実調査(curl 200・中身確認済):
#   - リリース詳細 (例 /main/html/rd/p/000000063.000030872.html) は
#     <script id="__NEXT_DATA__" type="application/json" nonce="...">{...}</script>
#     に構造化 JSON を持つ。props.pageProps.pressRelease に
#       title / subtitle / text(本文HTML) / keywords / locations / referenceUrl
#     が入っている。本文 text は HTML(<p><br><h2> 等)。
#   - 日本の popup リリースは本文末尾に「■ ...開催概要」ブロックを持ち、
#       ・日時  → 5/22（金）〜5/24（日） 11:00～19:00
#       ・会場  → LAIDOUT SHIBUYA（東京都渋谷区渋谷1-15-12）
#     のように「ラベル行 → 値行」で並ぶ(実データで確認)。
#   - ただし B2B/recap 系リリースは概要ブロックが無い。その場合は
#     何も抽出しない(捏造禁止)。会社概要の「所在地」を会場と誤認しない、
#     prose 中の「会場は…」を会場値と誤認しない、を厳格に防ぐ。
#   - レート負荷を上げないため popup と判定した PRTIMES signal だけ詳細 fetch。

# 開催情報のラベル → ACF フィールド対応。各 field 内は優先度順。
_PR_LABELS: dict[str, list[str]] = {
    "period":  ["開催期間", "開催日時", "開催日程", "開催期日", "会期", "開催日", "日時", "日程", "期間"],
    "venue":   ["会場", "開催場所", "開催地", "開催店舗", "実施店舗", "場所"],
    "hours":   ["営業時間", "オープン時間", "開館時間"],
    # 住所のみ採用。会社概要に頻出する「所在地」は発行元 HQ なので会場住所と
    # 誤認するため除外する([[feedback_guard_false_positives]])。
    "address": ["住所"],
}
_PR_ALL_LABELS = [lb for v in _PR_LABELS.values() for lb in v]
# ラベル行の先頭に付きうる装飾(箇条書き記号・全角空白)
_PR_BULLET = "・■◆●▼【 　［"
# period 値は日付らしさを必須にする(prose 誤マッチ防止)
_PR_DATE_RE = re.compile(r"(\d{1,2}\s*[/／月]\s*\d{1,2}|\d{4}\s*年|\d{1,2}\s*月\s*\d{1,2})")
# period 値から営業時間(HH:MM〜HH:MM)を分離
_PR_TIME_RE = re.compile(r"(\d{1,2}\s*[:：]\s*\d{2}\s*[~〜～\-―]\s*\d{1,2}\s*[:：]\s*\d{2})")


def _pr_clean_lines(text_html: str) -> list[str]:
    """pressRelease.text(HTML)を行単位プレーンテキストへ。
    <br> とブロック要素終端を改行にし、タグ除去 → エンティティ復元 → 空白圧縮。
    """
    t = re.sub(r"(?i)<br\s*/?>", "\n", text_html or "")
    t = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|li|tr|figcaption|table)>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = _html_unescape_min(t).replace("&nbsp;", " ")
    out = []
    for ln in t.split("\n"):
        ln = re.sub(r"[ \t　]+", " ", ln).strip()
        if ln:
            out.append(ln)
    return out


def _pr_label_inline(line: str, labels: list[str]) -> str | None:
    """line がいずれかの label の「ラベル行」なら、同一行の残り値(無ければ "")を返す。
    ラベル行 = 任意の装飾記号 + ラベル + (区切り：: または括弧/空白 or 行末)。
    ラベル直後が仮名/漢字で文章が続く場合(例 "会場は…")は None(prose 除外)。
    """
    s = line.lstrip(_PR_BULLET)
    for lb in labels:
        if s.startswith(lb):
            after = s[len(lb):]
            if after == "" or after[0] in "：:　 ([（［":
                return after.lstrip("：:・ ").strip()
    return None


def _pr_is_label_line(line: str) -> bool:
    """任意のラベル行 or 「■見出し」なら True(値行探索の打ち切り用)。"""
    s = line.lstrip(_PR_BULLET)
    for lb in _PR_ALL_LABELS:
        if s.startswith(lb):
            after = s[len(lb):]
            if after == "" or after[0] in "：:　 ([（［":
                return True
    return s[:1] == "■"


def extract_prtimes_event_info(text_html: str) -> dict:
    """PRTIMES 本文 HTML から開催期間/会場/営業時間/住所を抽出。

    実データ(コスきゅん vol.3 リリース)で検証:
      {"period": "5/22（金）〜5/24（日） 11:00～19:00",
       "venue":  "LAIDOUT SHIBUYA（東京都渋谷区渋谷1-15-12）"}
    recap/B2B リリース(株式会社ビーツ)では {} を返す(捏造しない)。

    戻り値は kbz_info 互換の日本語キー(開催期間/会場/営業時間/住所)dict。
    add_popup_acf_meta() がそのまま読めるようにする。
    """
    lines = _pr_clean_lines(text_html)
    n = len(lines)
    found: dict[str, str] = {}
    for i, line in enumerate(lines):
        for field, labels in _PR_LABELS.items():
            if field in found:
                continue
            inline = _pr_label_inline(line, labels)
            if inline is None:
                continue
            val = inline
            if not val:
                # 値は後続の非空・非ラベル行(注記 ※ はスキップ)
                for j in range(i + 1, min(i + 4, n)):
                    cand = lines[j].lstrip("・ ").strip()
                    if not cand:
                        continue
                    if _pr_is_label_line(lines[j]):
                        break
                    if cand.startswith("※"):
                        continue
                    val = cand
                    break
            if not val:
                continue
            if field == "period" and not _PR_DATE_RE.search(val):
                continue  # 日付らしさが無い値は period にしない
            found[field] = val[:200]
            break

    # kbz_info 互換キーへ変換。営業時間は period 内の時刻レンジから補完できる。
    info: dict[str, str] = {}
    if found.get("period"):
        info["開催期間"] = found["period"]
    if found.get("venue"):
        info["会場"] = found["venue"]
    hours = found.get("hours", "")
    if not hours and found.get("period"):
        tm = _PR_TIME_RE.search(found["period"])
        if tm:
            hours = tm.group(1).replace("：", ":").replace(" ", "")
    if hours:
        info["営業時間"] = hours
    if found.get("address"):
        info["住所"] = found["address"]
    return info


def _extract_next_data_press_release(html: str) -> dict | None:
    """PRTIMES 詳細ページの __NEXT_DATA__ から pressRelease オブジェクトを返す。"""
    m = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S
    )
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return None
    pr = data.get("props", {}).get("pageProps", {}).get("pressRelease")
    return pr if isinstance(pr, dict) else None


def fetch_prtimes_detail(url: str) -> dict:
    """PRTIMES 個別リリースページを fetch し開催情報(kbz_info 互換)を返す。

    レート負荷を上げないため、呼び出し側(parse_prtimes)で popup と判定された
    signal のみ呼ぶこと。本関数内でも SLEEP を入れる。

    失敗(取得不可/NEXT_DATA 無し)時は {}(捏造せず空)。
    """
    time.sleep(SLEEP)
    html = fetch(url)
    if not html:
        log(f"  detail fetch 失敗: {url}")
        return {}
    pr = _extract_next_data_press_release(html)
    if not pr:
        log(f"  detail NEXT_DATA 無し: {url}")
        return {}
    info = extract_prtimes_event_info(pr.get("text") or "")
    return info


def parse_prtimes(max_items: int = 60) -> list[dict]:
    """PRTIMES /sitemap-news.xml から K-POP 関連 popup/event を抽出。

    sitemap-news.xml の各 <url> はサーバ側に title/keywords/date を持つので、
    判定はここだけで完結する(レート負荷なし・高速)。

    popup と判定した signal のみ個別リリースページを追加 fetch し、
    開催期間/会場/営業時間/住所を抽出して kbz_info 互換 dict に格納する
    (タスク#27)。event は eplus/TEC 側で日時を扱うため詳細 fetch しない。

    max_items: signal 化する最大件数(暴発防止の上限)。
    """
    log("PRTIMES /sitemap-news.xml 取得開始")
    body = fetch(PRTIMES_NEWS_SITEMAP, accept="application/xml,text/xml")
    if not body:
        return []

    # PRTIMES sitemap には稀に不正な制御文字(\x0b 等)が混入する。
    # まず除去してから strict パーサに渡し、それでも落ちたら regex でフォールバック。
    body = _sanitize_xml(body)

    # (loc, title, keywords, date) のタプル列を作る
    records: list[tuple[str, str, str, str]] = []
    try:
        ns = {
            "sm":   "http://www.sitemaps.org/schemas/sitemap/0.9",
            "news": "http://www.google.com/schemas/sitemap-news/0.9",
        }
        root = ET.fromstring(body)
        urls = root.findall("sm:url", ns)
        log(f"  url entries 取得(ET): {len(urls)}")
        for u in urls:
            loc_el = u.find("sm:loc", ns)
            if loc_el is None or not (loc_el.text or "").strip():
                continue
            title_el = u.find("news:news/news:title", ns)
            kw_el    = u.find("news:news/news:keywords", ns)
            date_el  = u.find("news:news/news:publication_date", ns)
            records.append((
                loc_el.text.strip(),
                (title_el.text or "").strip() if title_el is not None else "",
                (kw_el.text or "").strip() if kw_el is not None else "",
                (date_el.text or "").strip() if date_el is not None else "",
            ))
    except ET.ParseError as e:
        log(f"  ET parse error ({e}) — regex フォールバックに切替")
        records = _parse_news_with_regex(body)
        log(f"  url entries 取得(regex): {len(records)}")

    signals = []
    for link, title, keywords, pub_date in records:
        title = _html_unescape_min(title)
        keywords = _html_unescape_min(keywords)
        if not title:
            continue

        # 韓国関連判定は title + keywords の両方を対象にする
        # (アーティスト名/ブランド名が keywords にのみ入る popup を取りこぼさない)
        # タスク#26: K-POP 限定 → 韓国関連全般(K-POP/ドラマ/コスメ/フード/
        # ファッション)に拡大。matches_korea は (genre, keyword) を返す。
        ko = matches_korea(title, keywords)
        if not ko:
            continue
        korea_genre, matched_kw = ko
        # popup/event 分類は title のみで判定する。
        # keywords にはブランド名(例: BookLive=LIVE、D'PARTMENT=PART 等)が
        # 入り substring 衝突で誤分類するため([[feedback_guard_false_positives]])、
        # 説明的な文である title だけを分類ゲートにする(二重ゲートの安全側)。
        sig_type = classify(title)
        if not sig_type:
            continue

        sig = {
            "type": sig_type,
            "title": title,
            "source_url": link,
            "source_media": "PRTIMES",
            "artist_keyword": matched_kw,
            "korea_genre": korea_genre,
            "description_snippet": keywords[:200],
            "published_at": pub_date,
            "fetched_at": now_iso(),
        }
        # タスク#27: popup のみ個別リリースページから開催情報を抽出して kbz_info
        # 互換 dict に格納(add_popup_acf_meta が読む)。event は詳細 fetch しない
        # (レート負荷を抑える / 日時は eplus/TEC 側で扱う)。
        if sig_type == "popup":
            info = fetch_prtimes_detail(link)
            if info:
                sig["kbz_info"] = info
                log(f"    開催情報抽出: {', '.join(info.keys())}")
        signals.append(sig)
        log(f"  HIT [{sig_type}/{korea_genre}] {title[:60]}... (kw={matched_kw})")
        if len(signals) >= max_items:
            log(f"  max_items={max_items} 到達、打ち切り")
            break
    return signals

# ─── eplus sitemap_daily_kkn パーサ ─────────────────────
def parse_eplus(max_pages: int = 40) -> list[dict]:
    """eplus sitemap_daily_kkn.xml から URL リスト取得 → 個別ページから K-POP 抽出。

    max_pages: 個別ページの最大取得数(レート制限の観点で制限)
    """
    log("eplus sitemap_daily_kkn.xml 取得開始")
    body = fetch("https://eplus.jp/s/eplus.jp/sitemap_daily_kkn.xml", accept="application/xml")
    if not body:
        return []

    urls = []
    try:
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        root = ET.fromstring(body)
        for u in root.findall("sm:url", ns):
            loc = u.find("sm:loc", ns)
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
    except ET.ParseError as e:
        log(f"  eplus sitemap parse error: {e}")
        return []

    log(f"  URL 数: {len(urls)}, 最大 {max_pages} ページ取得します")

    signals = []
    for i, url in enumerate(urls[:max_pages]):
        time.sleep(SLEEP)
        html = fetch(url)
        if not html:
            continue
        # <title>タグから抽出
        m_title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = ""
        if m_title:
            title = re.sub(r"\s+", " ", m_title.group(1)).strip()
            # eplus は通常 "公演名 | チケットぴあ" のフォーマット
            title = re.sub(r"\s*[\|｜]\s*(イープラス|eplus|チケット\s*[a-z]*).*$", "", title, flags=re.I).strip()

        kpop_kw = matches_kpop(title)
        if not kpop_kw:
            continue
        sig_type = classify(title)
        # eplus は基本的にチケット販売 = ライブ/コンサート(events)優先
        if not sig_type:
            sig_type = "event"

        # 簡易な日時抽出(eplus 個別ページから)
        date_match = re.search(r"(\d{4})[./年-](\d{1,2})[./月-](\d{1,2})[日)]?", html)
        start_date = ""
        if date_match:
            try:
                start_date = f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
            except ValueError:
                start_date = ""

        signals.append({
            "type": sig_type,
            "title": title[:200],
            "source_url": url,
            "source_media": "eplus",
            "artist_keyword": kpop_kw,
            "start_date": start_date,
            "fetched_at": now_iso(),
        })
        log(f"  HIT [{sig_type}] {title[:60]}... (kw={kpop_kw})")
    return signals

# ─── kbuzzlab.com(M11.5 段階9.5、Day 9 追加)──────────
#   オーナー友人運営媒体、口頭了承済。robots.txt は Disallow なし。
#   経路: popup_event-sitemap.xml(632件)→ 個別ページの og:title + sp-info-block を抽出。
#   Layer 2 引用記事(60% 上限)、HARD_FAIL の source_url を必ず保持。
KBZ_SITEMAP = "https://kbuzzlab.com/popup_event-sitemap.xml"

# kbuzzlab は「韓国トレンド全般」(K-POP + 韓国コスメ + 韓国カフェ + 韓国ファッション + 聖水/江南エリア)
# K-POP 限定の matches_kpop だけだとほぼ全件 skip されるため、kbuzzlab 用に判定を緩める。
# ただし無関係(日本ローカル等)は弾く必要があるため「韓国シグナル」キーワードでチェック。
KBZ_KOREA_SIGNALS = [
    "聖水", "ソンス", "江南", "カンナム", "弘大", "ホンデ", "明洞", "ミョンドン",
    "ソウル", "釜山", "プサン", "梨泰院", "イテウォン", "圏内", "韓国",
    "Korea", "Seoul", "Busan", "Gangnam", "Seongsu",
]
_KBZ_RE = re.compile("|".join(re.escape(w) for w in KBZ_KOREA_SIGNALS), re.IGNORECASE)


def _matches_korea(text: str) -> str | None:
    """kbuzzlab 用: K-POP より広い「韓国シグナル」判定"""
    if not text:
        return None
    m = _KBZ_RE.search(text)
    if m:
        return m.group(0)
    # K-POP キーワードもカバーしておく(BTS popup 等)
    return matches_kpop(text)


def parse_kbuzzlab(max_items: int = 30) -> list[dict]:
    """kbuzzlab.com の popup_event を sitemap.xml 経由で取得。

    1. sitemap.xml で <loc> + <lastmod> の対を取得
    2. lastmod が新しい順に max_items 件まで個別 URL を fetch
    3. og:title / og:description / og:image / sp-info-block から構造化

    判定: K-POP に限定せず「韓国シグナル」全般(コスメ/カフェ/カンナム等)を取得。
    kbuzzlab は韓国トレンド総合メディアで、KPOP JOURNAL の popup ハブの
    補完 source として活用する。
    """
    log("=== parse_kbuzzlab() 開始 ===")
    sitemap = fetch(KBZ_SITEMAP, accept="application/xml")
    if not sitemap:
        log("  sitemap 取得失敗")
        return []
    # <url><loc>...</loc><lastmod>...</lastmod></url>
    entries = re.findall(
        r"<url>\s*<loc>(https://kbuzzlab\.com/popup_event/[^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>",
        sitemap,
    )
    log(f"  sitemap entries: {len(entries)}")
    # lastmod 新しい順
    entries.sort(key=lambda x: x[1], reverse=True)
    entries = entries[:max_items]

    signals = []
    for url, lastmod in entries:
        time.sleep(SLEEP)
        html = fetch(url)
        if not html:
            continue
        title = _extract_meta(html, "og:title") or ""
        desc  = _extract_meta(html, "og:description") or ""
        image = _extract_meta(html, "og:image") or ""
        # 韓国シグナルでなければ skip(K-POP より広い判定)
        kpop_kw = _matches_korea(title) or _matches_korea(desc[:300])
        if not kpop_kw:
            continue
        sig_type = classify(title) or classify(desc[:200]) or "popup"
        info = _extract_kbz_info(html)
        # タスク#26: 後段(popup_event_to_post.py)の popup_genre 付与のために
        # ジャンルも残す。kbuzzlab は韓国シグナルで既にヒット済なので、K-POP/
        # 4ジャンルを判定し、どれにも当たらなければ "korea"(韓国一般)とする。
        ko = matches_korea(title, desc[:300])
        korea_genre = ko[0] if ko else "korea"
        signals.append({
            "type": sig_type,
            "source_media": "kbuzzlab",
            "source_url": url,
            "title": title.strip(),
            "description_snippet": desc.strip()[:300],
            "thumbnail_url": image,
            "kpop_keyword": kpop_kw,
            # popup_event_to_post.py との互換性のため artist_keyword キーを設定
            # kbuzzlab は K-POP 限定でないため、検出キーワード(聖水/Korea 等)を入れる
            "artist_keyword": kpop_kw,
            "korea_genre": korea_genre,
            "kbz_info": info,
            "lastmod": lastmod,
            "fetched_at": now_iso(),
        })
        log(f"  HIT [{sig_type}] {title[:60]}... (kw={kpop_kw})")
    log(f"=== parse_kbuzzlab() 完了: {len(signals)} 件 ===")
    return signals


def _extract_meta(html: str, prop: str) -> str | None:
    """og:* / article:* / twitter:* など property タグから内容を抽出"""
    m = re.search(
        r'<meta\s+[^>]*property=["\']' + re.escape(prop) + r'["\'][^>]*content=["\']([^"\']+)["\']',
        html,
    )
    if m:
        return m.group(1)
    m = re.search(
        r'<meta\s+[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']' + re.escape(prop) + r'["\']',
        html,
    )
    return m.group(1) if m else None


def _clean_kbz_value(raw: str) -> str:
    """sp-info-value 内の HTML 断片をプレーンテキストへ整形。
    タグ除去 → 絵文字除去 → 連続空白圧縮。
    """
    if not raw:
        return ""
    # <br> は改行扱い(住所/営業時間の複数行を保つ)
    text = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    # 残りのタグを除去
    text = re.sub(r"<[^>]+>", " ", text)
    # HTML エンティティの最低限の復元
    text = (
        text.replace("&amp;", "&")
        .replace("&nbsp;", " ")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    # 絵文字を除去(📅🕒📍 等)
    text = re.sub(r"[\U0001F300-\U0001FAFF☀-➿️]", "", text)
    # 行内の連続空白を圧縮しつつ改行は保持
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(ln for ln in lines if ln)
    return text.strip()


def _extract_kbz_info(html: str) -> dict:
    """kbuzzlab の sp-info-block から label/value ペアを抽出。

    多くの記事で「開催期間 / 営業時間 / 開催エリア / 住所 / 予約」のいずれかが入る。

    1.2 修正(2026-05-21): メモリ kbuzzlab-popup-dom-contract の知見に基づき
    入れ子 div / 属性付き value を正しく拾えるようにする。
    旧実装の `sp-info-value">(.*?)</` は、
      - 住所: value が <div itemprop="address"><div itemprop="streetAddress">…</div></div>
        の入れ子で、最初の `</` が内側 div の開始タグ前に来ず途中で切れていた
      - 期間/エリア: value 内に itemprop 等の属性付き子要素があり同様に途中で切れていた
    ため 6 行中 3 行しか拾えなかった。

    対策:
      - sp-info-value の中身を「対応する閉じ位置まで」貪欲に取得(従来の
        `</div></div>` 終端前提を捨て、ブロック全体から value 開始タグ以降を
        取り出して整形)。
      - itemprop="streetAddress" があれば住所はそれを優先抽出。
    既存の動く 3 行(期間/エリア等)は _clean_kbz_value で同じ結果になるよう後方互換。
    """
    info: dict = {}
    # sp-info-block 単位で分割(次の sp-info-block か、末尾まで)。
    # 住所ブロックは style="border-bottom:none;" 付きで開始するため、
    # class="sp-info-block" の後に任意の属性が続くケースを許容する。
    blocks = re.findall(
        r'<div class="sp-info-block"[^>]*>(.*?)(?=<div class="sp-info-block"[^>]*>|$)',
        html,
        re.S,
    )
    for b in blocks:
        lbl_m = re.search(r'class="sp-info-label"[^>]*>([^<]+)<', b)
        if not lbl_m:
            continue
        label = lbl_m.group(1).strip()

        value = ""
        # 住所など: itemprop="streetAddress" を最優先(入れ子 div の本文)
        street_m = re.search(
            r'itemprop="streetAddress"[^>]*>(.*?)</div>', b, re.S,
        )
        if street_m:
            value = _clean_kbz_value(street_m.group(1))
        # 通常: sp-info-value 開始タグ以降〜次の sp-info-* / ブロック末尾まで。
        # 属性付き(itemprop 等)子要素を含んでいても途中で切らない。
        if not value:
            val_m = re.search(
                r'class="sp-info-value"[^>]*>(.*?)'
                r'(?=<div class="sp-info-(?:label|block)"[^>]*>|$)',
                b,
                re.S,
            )
            if val_m:
                value = _clean_kbz_value(val_m.group(1))

        if label and value:
            info[label] = value[:200]

    # Google Maps embed URL(あれば。kbuzzlab は通常 naver.me のみ)
    map_m = re.search(r'src="(https://www\.google\.com/maps/embed[^"]+)"', html)
    if map_m:
        info["map_embed"] = map_m.group(1)
    # SNS URL(最初の 3 つ)
    sns = re.findall(
        r'href="(https://(?:www\.)?(?:instagram|tiktok|youtube|naver|x|twitter)\.[^"]+)"',
        html,
    )
    # 自分の twitter intent は除外
    sns = [s for s in sns if "intent/tweet" not in s][:3]
    if sns:
        info["sns"] = sns
    return info


# ─── pops-in.com(日本+韓国 popup アグリゲーター)───────────
# 2026-05-25: 日本国内 K-POP popup ソースが kbuzzlab(韓国専用)のみで日本popupゼロ
# だった問題への対応。pops-in は日本+韓国の popup を /idol-events/ 一覧で配信、
# event-card に title(img alt)/location/date を内包し個別fetch不要(kbuzzlabより軽量)。
# robots 全許可・引用ポリシー順守。DOM契約: [[popsin-popup-dom-contract]]。
POPSIN_IDOL = "https://pops-in.com/idol-events/"

def parse_popsin(max_items: int = 20) -> list[dict]:
    """pops-in.com /idol-events/ から K-POP popup を抽出(日本+韓国)。
    event-card 1ブロック = 1 popup。title/location/date は一覧カード内に揃う。
    location 先頭の国名(日本/韓国)で開催国を判別し signal に残す。
    """
    log("=== parse_popsin() 開始 ===")
    signals: list[dict] = []
    try:
        body = fetch(POPSIN_IDOL, accept="text/html")
    except Exception as e:
        log(f"  pops-in fetch失敗: {e}")
        return signals
    if not body:
        return signals
    # event-card ブロックを個別に取り出す
    cards = re.findall(r'<a class="event-card"[^>]*href="([^"]*?number=\d+)"[^>]*>(.*?)</a>', body, re.S)
    log(f"  event-card: {len(cards)} 件")
    for href, card in cards[:max_items]:
        url = href if href.startswith("http") else "https://pops-in.com" + href
        title_m = re.search(r'<img[^>]*alt="([^"]*)"', card)
        title = _html_unescape_min(title_m.group(1)).strip() if title_m else ""
        if not title:
            continue
        cats = re.findall(r'category-tag">\s*([^<]+?)\s*<', card)
        loc_m = re.search(r'class="location"[^>]*>(.*?)</p>', card, re.S)
        date_m = re.search(r'class="date"[^>]*>(.*?)</p>', card, re.S)
        location = _html_unescape_min(re.sub(r"<[^>]+>","",loc_m.group(1))).strip() if loc_m else ""
        period = _html_unescape_min(re.sub(r"<[^>]+>","",date_m.group(1))).strip() if date_m else ""
        img_m = re.search(r'<img[^>]*src="([^"]*)"', card)
        thumb = img_m.group(1) if img_m else None
        # K-POP/韓国シグナル判定(title + categories)。#アイドル カテゴリは既にidol-events由来。
        kw = _matches_korea(title) or _matches_korea(" ".join(cats)) or ("アイドル" if any("アイドル" in c for c in cats) else None)
        if not kw:
            continue
        sig_type = classify(title) or "popup"
        # kbz_info 互換: 会場(location)/開催期間(date)を日本語ラベルキーで格納
        # → 後段 add_popup_acf_meta / _japan_area が読む(location先頭の国名で開催国判定)
        kbz_info: dict = {}
        if location:
            kbz_info["会場"] = location
        if period:
            kbz_info["開催期間"] = period
        signals.append({
            "type": sig_type if sig_type == "popup" else "popup",  # idol-events は popup 主体
            "source_media": "pops-in",
            "source_url": url,
            "title": title,
            "description_snippet": (" / ".join(cats) + " " + location + " " + period).strip()[:300],
            "thumbnail_url": thumb,
            "kpop_keyword": kw,
            "artist_keyword": kw,
            "korea_genre": "korea",
            "kbz_info": kbz_info,
            "lastmod": "",
            "fetched_at": now_iso(),
        })
        log(f"  HIT [popup] {title[:55]}... (loc={location})")
    log(f"=== parse_popsin() 完了: {len(signals)} 件 ===")
    return signals


# ─── popap.biz(日本国内の韓国カルチャー popup)────────────
# 2026-05-25: 日本国内 popup ソース。pops-in/kbuzzlab は韓国popupのみで日本popupゼロ
# だった問題への本命対応。popap は日本(東京中心)の popup メディアで、numbuzin(韓国コスメ)/
# ROLAROLA(韓国ファッション)等の日本開催・韓国カルチャー popup を配信。
# サイト全体は非韓国popupも多いので title で韓国シグナルを必須フィルタ(K-POP限定でなく
# K-beauty/K-fashion/韓流 全般を対象=オーナー方針)。Squarespace 製: 一覧 <a href="/popup-list/..">
# に data-title、card内に summary-thumbnail-event-date。個別ページに開催期間/会場/住所。
# robots: /config /search /account のみ禁止=popup-list 可。DOM契約: [[popsin-popup-dom-contract]]。
POPAP_TOKYO = "https://www.popap.biz/popup-tokyo"
# 日本国内の韓国カルチャー判定キーワード(韓国シグナル必須=無関係popup誤拾い防止)
_POPAP_KO_KW = [
    "韓国", "韓流", "K-POP", "KPOP", "K-pop", "K-beauty", "K-BEAUTY", "Kビューティ",
    "韓国コスメ", "韓国スキンケア", "韓国ファッション", "オルチャン", "新大久保",
    "numbuzin", "ROLAROLA", "rom&nd", "ロムアンド", "MEDIHEAL", "Anua", "TIRTIR",
    # K-POPアーティスト(SUBSTRING_KEYWORDS_EN を流用したいが循環回避のため主要のみ)
    "LE SSERAFIM", "BTS", "TWICE", "SEVENTEEN", "RIIZE", "aespa", "JO1", "NCT",
    "ENHYPEN", "Stray Kids", "TXT", "ILLIT", "IVE", "NewJeans", "TREASURE",
]

def parse_popap(max_items: int = 12) -> list[dict]:
    """popap.biz /popup-tokyo から日本開催の韓国カルチャー popup を抽出。
    一覧で title(data-title)を韓国シグナルでフィルタ → 該当のみ個別ページfetchで
    開催期間/会場/住所を取得(extract_prtimes_event_info 流用)。
    """
    log("=== parse_popap() 開始 ===")
    signals: list[dict] = []
    try:
        body = fetch(POPAP_TOKYO, accept="text/html")
    except Exception as e:
        log(f"  popap fetch失敗: {e}")
        return signals
    if not body:
        return signals
    cards = re.findall(r'<a[^>]*href="(/popup-list/[a-z0-9-]+)"[^>]*data-title="([^"]*)"', body)
    log(f"  popup-list カード: {len(cards)} 件")
    seen: set[str] = set()
    for href, title_raw in cards:
        title = _html_unescape_min(title_raw).strip()
        if not title or href in seen:
            continue
        # 韓国カルチャーシグナル必須(無関係な日本popupを拾わない)
        kw = next((k for k in _POPAP_KO_KW if k.lower() in title.lower()), None)
        if not kw:
            continue
        seen.add(href)
        url = "https://www.popap.biz" + href
        # 個別ページから開催情報を取得(レート配慮、popup判定済みのみ)
        kbz_info: dict = {}
        try:
            detail = fetch(url, accept="text/html")
            time.sleep(SLEEP)
            if detail:
                kbz_info = extract_prtimes_event_info(detail)
                # 住所を補完抽出(会場が英名/romajiだと _guess_popup_area が日本判定できないため、
                # 〒/都道府県を含む住所を拾って kbz_info['住所'] に格納→東京/渋谷等で tokyo 判定可能に)
                if "住所" not in kbz_info:
                    dt = _html_unescape_min(re.sub(r"<[^>]+>", " ", detail))
                    dt = re.sub(r"\s+", " ", dt)
                    am = re.search(r"(〒\s*\d{3}-?\d{4}\s*[^。\s]{2,40}|(?:東京都|大阪府|京都府|北海道|[^\s。]{2,3}県)[^。\s]{2,40})", dt)
                    if am:
                        kbz_info["住所"] = am.group(1).strip()
        except Exception as e:
            log(f"  detail fetch失敗 {href}: {e}")
        # 韓国ジャンル分類(beauty/fashion/food/drama or korea)
        ko = matches_korea(title, title) or matches_korea("", " ".join(_POPAP_KO_KW))
        korea_genre = ko[0] if ko else "korea"
        signals.append({
            "type": "popup",
            "source_media": "popap",
            "source_url": url,
            "title": title,
            "description_snippet": title[:300],
            "thumbnail_url": None,  # Squarespace CDN は data-src 後段解決(featured resolverに委譲)
            "kpop_keyword": kw,
            "artist_keyword": kw,
            "korea_genre": korea_genre,
            "kbz_info": kbz_info,
            "lastmod": "",
            "fetched_at": now_iso(),
        })
        log(f"  HIT [popup] {title[:50]}... (kw={kw}, 会場={kbz_info.get('会場','?')})")
        if len(signals) >= max_items:
            break
    log(f"=== parse_popap() 完了: {len(signals)} 件 ===")
    return signals


# ─── メイン ────────────────────────────────────────────
def main() -> int:
    log("=== popup_event_fetcher.py 開始 ===")
    log(f"DRY_RUN={DRY_RUN}, OUT_DIR={OUT_DIR}")

    all_signals = []
    all_signals.extend(parse_prtimes())
    time.sleep(SLEEP)
    all_signals.extend(parse_eplus())
    time.sleep(SLEEP)
    # M11.5 段階9.5: kbuzzlab 追加
    all_signals.extend(parse_kbuzzlab(max_items=int(os.environ.get("KBZ_MAX", "20"))))
    time.sleep(SLEEP)
    # 2026-05-25: pops-in 追加(韓国idol popup。日本popupは取れないがkbuzzlabより構造クリーン)
    all_signals.extend(parse_popsin(max_items=int(os.environ.get("POPSIN_MAX", "20"))))
    time.sleep(SLEEP)
    # 2026-05-25: popap 追加(★日本国内の韓国カルチャーpopup。日本popup源の本命)
    all_signals.extend(parse_popap(max_items=int(os.environ.get("POPAP_MAX", "12"))))

    # type 別集計
    popup_n = sum(1 for s in all_signals if s["type"] == "popup")
    event_n = sum(1 for s in all_signals if s["type"] == "event")
    log(f"=== シグナル収集完了: {len(all_signals)} 件 (popup={popup_n}, event={event_n}) ===")

    if not all_signals:
        log("シグナル 0 件のため出力をスキップ")
        return 0

    if DRY_RUN:
        log("DRY_RUN: ファイル出力をスキップ。プレビュー:")
        for s in all_signals[:5]:
            log(f"  - [{s['type']}] {s['title'][:80]}")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / f"{datetime.now().strftime('%Y%m%d')}.json"
    out_file.write_text(json.dumps({
        "fetched_at": now_iso(),
        "counts": {"total": len(all_signals), "popup": popup_n, "event": event_n},
        "signals": all_signals,
    }, ensure_ascii=False, indent=2))
    log(f"出力: {out_file}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
