#!/usr/bin/env python3
"""lib/x_traffic_picker.py のテスト — トレンド連動の記事選択。

背景 (2026-08-17):
  X からサイトへの流入が実質ゼロだった。記事枠(12時)は Phase2 で復活していたが
  8/12以降 1回しか動いておらず、その1本も URL もフックも無い平叙文だった。
  さらに x_post_queue.json は4件しかなく、いま話題の出来事とは無関係。

  owner決定(2026-08-17):
    - 導線は「本文URLなし + 自己リプにURL」
    - 出す記事は「トレンド連動」= いま話題の出来事に関連する自社記事
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.x_traffic_picker import match_article, build_hook  # noqa: E402


ARTICLES = [
    {"title": "Stray Kids ビルボード200 1位までの記録まとめ",
     "url": "https://www.kpopjournal.tokyo/skz-billboard/", "post_id": 101},
    {"title": "BABYMONSTER 日本ツアー 全公演日程",
     "url": "https://www.kpopjournal.tokyo/babymonster-tour/", "post_id": 102},
    {"title": "aespa 日本活動まとめ",
     "url": "https://www.kpopjournal.tokyo/aespa-japan/", "post_id": 103},
]


def test_数字が一致すれば同じ話題とみなす():
    """日英で語は重ならなくても、数字(200/21週など)は一致する。"""
    got = match_article("Stray Kids", "Stray Kids Ties Record On Billboard 200",
                        articles=ARTICLES)
    assert got and got["post_id"] == 101


def test_関連記事が無ければNone():
    """無関係な記事を無理に出さない。出す物が無い日は投稿を見送る。"""
    assert match_article("TXT", "TXT To Headline Global Citizen Festival",
                         articles=ARTICLES) is None


def test_日本語同士なら語の重なりで判定する():
    got = match_article("aespa", "aespa、日本初の冠バラエティ番組が配信決定",
                        articles=ARTICLES)
    assert got and got["post_id"] == 103


def test_フックにURLを含めない():
    """本文は URL なし(自己リプ側に置く)。本文リンクはシャドウバン再発トリガー。"""
    hook = build_hook("Stray Kids", "Stray Kids Ties The Rolling Stones' Record",
                      ARTICLES[0])
    assert "http" not in hook


def test_フックが記事タイトルの丸写しでない():
    """タイトルそのままはAI/bot感が強く、実測でも伸びなかった。"""
    hook = build_hook("Stray Kids", "Stray Kids Ties The Rolling Stones' Record",
                      ARTICLES[0])
    assert hook.strip() != ARTICLES[0]["title"]


def test_フックが空にならない():
    hook = build_hook("aespa", "aespa、日本初の冠バラエティ番組が配信決定", ARTICLES[2])
    assert len(hook.strip()) >= 10


def test_話題と無関係な記事は選ばない():
    """アーティスト名が一致するだけでは不十分。実データで
    「BTS ARIRANG UKチャート21週」に「BTSのVが交通事故の噂」が当たった。
    話題を見て来た読者が別の記事に飛ばされると直帰する。"""
    arts = [{"title": "BTSのVが軽微な交通事故に関与との噂",
             "url": "https://x.test/v-accident", "post_id": 201}]
    assert match_article("BTS", "ARIRANG Becomes BTS's 1st Album To Spend 21 Weeks On UK Chart",
                         articles=arts) is None


def test_話題に重なる記事なら選ぶ():
    arts = [{"title": "BTSのVが軽微な交通事故に関与との噂",
             "url": "https://x.test/v-accident", "post_id": 201},
            {"title": "BTS「ARIRANG」UKチャート記録まとめ",
             "url": "https://x.test/arirang", "post_id": 202}]
    got = match_article("BTS", "ARIRANG Becomes BTS's 1st Album To Spend 21 Weeks On UK Chart",
                        articles=arts)
    assert got and got["post_id"] == 202


# ─── 自己リプは「URLだけ」でなく本文の続きを書く(owner指摘 2026-08-17) ───
from lib.x_traffic_picker import build_reply, has_substance, extract_payoff  # noqa: E402


def test_中身のある記事は引きに使える():
    """記事に「続き」として渡せる具体(数字・固有名・手順)があるか検証する。
    owner決定(A案): 引きを作る前に記事側の中身を確認する。中身が無い記事で
    引きだけ作ると、飛んだ読者を裏切りアカウントの信用を削る。"""
    body = ("Stray Kidsの9回目の1位は、アルバム単位で数えた場合の記録です。"
            "EPを含めると11作となり、Melonの集計では順位が別になります。"
            "2026年8月時点でビルボード200に9作が1位で入った例は3組のみです。"
            "一方、初週売上で見ると順位は入れ替わります。ただしこの集計には"
            "ストリーミング換算が含まれるため、フィジカル売上のみの比較とは"
            "別の数字になります。理由は集計方式の違いにあり、Billboardは"
            "SEA(ストリーミング換算アルバム)とTEA(トラック換算アルバム)を"
            "合算する一方、Circleチャートは出荷枚数を基準にしているためです。"
            "内訳を並べると、9作のうち5作がEP、4作がフルアルバムでした。")
    assert has_substance(body), f"len={len(body)}"


def test_中身の薄い記事は引きに使わない():
    """速報の3行記事など、リプで渡せる具体が無いものは弾く。"""
    assert not has_substance("Stray Kidsが1位を獲得しました。おめでとうございます。今後の活躍に期待です。")
    assert not has_substance("")


def test_リプがURL単体にならない():
    r = build_reply("Stray Kids", "Stray Kids Ties Rolling Stones Record On Billboard 200",
                    {"title": "Stray Kids ビルボード記録まとめ", "url": "https://x.test/a"},
                    hook="ビルボードでRolling Stonesと並んだらしい")
    assert "http" in r
    body = r.replace("https://x.test/a", "").strip()
    assert len(body) >= 10, "リプにURL以外の中身が無い"


def test_本文とリプで同じ文を繰り返さない():
    hook = "ビルボードでRolling Stonesと並んだらしい"
    r = build_reply("Stray Kids", "Stray Kids Ties Rolling Stones Record",
                    {"title": "まとめ", "url": "https://x.test/a"}, hook=hook)
    assert hook not in r


# ─── 広報口調の排除(個人アカウントに見えない文を弾く) ─────────────────
from lib.x_traffic_picker import is_pr_tone  # noqa: E402


def test_広報口調を弾く():
    """実測で出た型。メディア/事務所の発表文に見えると個人の投稿として読まれない。"""
    assert is_pr_tone("RESCENEは音楽番組での快進撃を続けており、さらなる活躍に注目が集まります")
    assert is_pr_tone("各アーティストが魅力的なステージを披露しました")
    assert is_pr_tone("今後の新曲やパフォーマンスに注目が集まります")


def test_個人の口調は通る():
    assert not is_pr_tone("RESCENEがLove Attackで1位。デビュー年でこれは早い")
    assert not is_pr_tone("Inkigayoの出演者、今週やたら多かった")


def test_番組出演者一覧のような記事は引きに使わない():
    """『今回の放送ではAが〜、Bが〜』と列挙するだけの記事は、
    リプで渡せる『続き』が無い。数字や固有名は多いので長さ判定だけでは通る。"""
    body = ("2026年08月17日、SBS音楽番組『Inkigayo』の最新回が放送された。"
            "今回の放送では、Splayitが「Last bus」でデビューを飾ったほか、"
            "Stray Kidsが「This & That」、Jeong Eun Jiが「i love LOVE」、"
            "WayVが「Vision Wings」、KISS OF LIFEが「SWEAT」、"
            "KiiiKiiiが「Candy Pink」、ARTMSが「Born Stunner」、"
            "POWが「Flavor」、WHIBが「CHERRY PIE」、NOWZが「Achilles」、"
            "AxMxPが「10 Reasons to Date」をそれぞれ披露した。")
    assert not has_substance(body)
