"""X会話型 本文の構成(型A)を検査する。

owner指定(2026-08-20):
    型A(引っ張る型)
      本文    : 感想(1文) → 起(+承転)。**結は書かない**
      リプライ: 結 + URL

  結を本文に書いてしまうと、リプ(=URLのある側)を読む理由が消える。
  逆に本文が起だけだと「中身のない出し渋り」になり、飛んだ読者を裏切る
  (実測で Direct 直帰 65% の既往あり)。感想で入り、起で状況を示し、
  結だけを残す — というバランスをコードで担保する。

  既存メモリ「抽象指示は効かない/プロンプトで効かない文体はコードで担保」
  に従い、プロンプト任せにせず検査関数で判定する。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib.x_traffic_picker import check_hook_structure_type_a


def test_opens_with_impression_and_withholds_conclusion():
    """感想で入り、起があり、結を出していない本文は合格。"""
    t = "これ地味にすごいなと思った。8月の公演分だけで先行の申込がもう埋まってるらしい。"
    assert check_hook_structure_type_a(t)["ok"] is True


def test_missing_impression_is_rejected():
    """事実だけで感想が無いものは型Aではない。"""
    t = "8月の公演分の先行申込が埋まった。追加公演の発表については現時点で未定とのこと。"
    r = check_hook_structure_type_a(t)
    assert r["ok"] is False
    assert "感想" in r["issue"]


def test_conclusion_in_body_is_rejected():
    """結(=リプで渡すはずの答え)を本文に書いてしまうと不合格。"""
    t = "これ地味にすごいと思った。先行が埋まったのは、会場が去年の半分の広さだから。"
    r = check_hook_structure_type_a(t)
    assert r["ok"] is False
    assert "結" in r["issue"]


def test_too_short_body_is_rejected():
    """感想だけで起が無いものは出し渋りになる。"""
    r = check_hook_structure_type_a("これ地味にすごいなと思った。")
    assert r["ok"] is False


def test_url_in_body_is_rejected():
    """型Aは本文にURLを置かない(suppression回避)。"""
    r = check_hook_structure_type_a(
        "すごいなと思った。先行がもう埋まってるらしい。https://example.com/a")
    assert r["ok"] is False
    assert "URL" in r["issue"]


# ── 実ログ由来の回帰ケース(2026-08-20) ──────────────────────────────
# tools/x_type_a_report.py で直近20本を判定して洗い出したもの。
# 推測ではなく実際に出た投稿なので、ここが壊れたら判定精度が落ちたと分かる。

def test_real_log_impression_forms_are_accepted():
    """実ログで「感想があるのに×」だった言い回しを取りこぼさない。"""
    for t in [
        "NCT 127が10周年を迎えるって、もうそんなに経ったんだなぁ。"
        "「Nice 127」ってどんな内容になるのか、ワクワクする…。",
        "TWICEの「FANCY」700万回再生、やっぱりこの曲のキャッチーさは"
        "いつ聞いてもすごいよね。",
    ]:
        assert check_hook_structure_type_a(t)["ok"] is True, t


def test_real_log_article_copy_is_rejected():
    """記事本文の平叙コピー(感想なし)は型Aとして弾く。

    「URLもフックも無い、記事本文の平叙文コピー」は実際に流入ゼロだった型。
    """
    t = ("JTBCのドラマ「アパート」が2026年08月15日の最終回で自己最高視聴率7.7%を記録し、"
         "全チャンネル同時間帯で1位を獲得した。")
    r = check_hook_structure_type_a(t)
    assert r["ok"] is False
    assert "感想" in r["issue"]
