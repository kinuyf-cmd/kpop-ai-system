#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""popup_detail(prose)から 予約要否 / 特典 を保守的に抽出する。

背景: kbuzzlab は sp-info-block に 予約/特典 ラベルを持たない(probe確認、2026-05-23)。
これらの情報は「イベント詳細」prose(=ACF popup_detail)にのみ存在する。
そのため popup_reservation / popup_benefit は空のまま。本パーサで prose から抽出する。

絶対方針(誤抽出・捏造ゼロ):
  - 予約: 明確な定型表現のみ正規化して返す。曖昧なら空(=テンプレ側で行非表示)。
  - 特典: trigger 語を含む「文」を **verbatim(原文のまま)** 引用して返す。要約しない
          (要約は誤情報を生むため)。trigger が無ければ空。
  - どちらも自信が無ければ空。読者に不正確な情報を出さない。

スタンドアロン実行(DB書き込みなし・照合用):
  python3 lib/popup_reservation_benefit_parser.py "<popup_detail本文>"
"""
import re
import sys

# 文の区切り: 全角句点・改行に加え、kbuzzlab prose が文区切りに使う絵文字も境界扱い。
# (例 397「…プレゼント🎁 毎日12:00〜営業」、394「…開催⚽ 全商品…ノベルティも」では
#  絵文字の後ろが別文。絵文字を境界にしないと benefit 文に営業時間/タイトルが混入する。)
_EMOJI = r"[\U0001F000-\U0001FAFF☀-➿️‍]"
_SENT_SPLIT = re.compile(r"(?<=。)|\n|" + _EMOJI + r"+")

# ── 予約: 定型表現 → 正規化ラベル(優先順。先にマッチしたものを採用)──────────
_RESERVATION_RULES = [
    (re.compile(r"事前予約制|事前予約が必要|要事前予約"), "事前予約制"),
    (re.compile(r"予約制(?!度)"),                          "予約制"),
    (re.compile(r"予約不要|予約なしで?入場|予約は不要"),   "予約不要"),
    (re.compile(r"予約優先"),                              "予約優先"),
    (re.compile(r"当日(?:現地)?(?:受付|入場|来店|販売)"),  "当日入場可"),
]

# ── 特典: この語を含む「文」を verbatim 抽出 ────────────────────────────────
_BENEFIT_TRIGGER = re.compile(
    r"進呈|プレゼント|特典|先着|来場|購入で|購入特典|もらえる|配布|ノベルティ|景品"
)
# 特典「ではない」誤検出を弾く除外(例: 「購入できます」だけの販促文など)
_BENEFIT_EXCLUDE = re.compile(r"購入可能(?!.*(進呈|プレゼント|もらえ|特典))")


def extract_reservation(detail: str) -> str:
    """予約要否を定型表現から抽出。曖昧/不在は空文字。"""
    if not detail:
        return ""
    text = detail.strip()
    for pat, label in _RESERVATION_RULES:
        if pat.search(text):
            return label
    return ""


def extract_benefit(detail: str) -> str:
    """特典 trigger を含む文を verbatim 引用。複数文なら結合。不在は空文字。"""
    if not detail:
        return ""
    sentences = [s.strip() for s in _SENT_SPLIT.split(detail) if s and s.strip()]
    hits = []
    for s in sentences:
        if _BENEFIT_TRIGGER.search(s):
            # 単なる「購入可能」止まり(進呈等を伴わない)は特典でないので除外
            if _BENEFIT_EXCLUDE.search(s) and not re.search(r"進呈|プレゼント|もらえ|特典|先着|配布|ノベルティ|景品", s):
                continue
            hits.append(s)
    return "。".join(h.rstrip("。") for h in hits) + ("。" if hits else "")


def parse(detail: str) -> dict:
    return {
        "popup_reservation": extract_reservation(detail),
        "popup_benefit": extract_benefit(detail),
    }


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    r = parse(src)
    print("popup_reservation =", repr(r["popup_reservation"]))
    print("popup_benefit     =", repr(r["popup_benefit"]))
