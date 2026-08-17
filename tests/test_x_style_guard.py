#!/usr/bin/env python3
"""生成本文の「AI感」を実測パターンで検出するガードのテスト。

背景 (2026-08-17 実測 / conversation 126本):
  「けど、」62% / 「〜だろう」33% / 「なんか」27% と、語彙と構文が固定化していた。
  さらに直近12本はほぼ全てが **「主題、感想〜けど、疑問…」という同一構文**。
  人間のツイートはここまで同じ形にならない。抽象的に「毎回ちがう構文で」と
  指示しても効かなかったため、実測した癖を名指しで検出して作り直させる。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.x_persona_voice import _is_ai_ish  # noqa: E402


def test_主題読点感想けど疑問の定型を弾く():
    """実測で最も多かった型。これが出たら作り直す。"""
    assert _is_ai_ish("BLACKPINKの空港ファッション、最近のスタイリングはちょっと"
                      "カジュアルすぎな気がするけど、逆にそれが新鮮だったりするのかな。")


def test_気がするけどを弾く():
    assert _is_ai_ish("ILLITの新曲、やっぱり音が全然違う気がするけど、どういう意図なんだろう。")


def test_なんだろうで締める型を弾く():
    assert _is_ai_ish("Stray Kidsのパフォーマンス、なんであんなに引き込まれるんだろう…")


def test_やっぱりほんとにすごいの型を弾く():
    assert _is_ai_ish("TWICEの新曲、やっぱりこの曲のキャッチーさはほんとにすごいよね。")


def test_具体的で素っ気ない文は通る():
    """事実に触れて言い切らずとも、定型でなければ通す。"""
    assert not _is_ai_ish("NCT127がAGT出るのか。地上波であれやるんだ")


def test_短い実況調は通る():
    assert not _is_ai_ish("ARIRANGまだUKチャートに居るらしい。21週目")


def test_問いかけ一つだけなら通る():
    assert not _is_ai_ish("Stray KidsがRolling Stonesと同じ記録って、どういう規模の話なんだ")


def test_署名や名乗りを弾く():
    """個人アカウントの独り言に毎回名前が入るのは不自然(owner指摘 2026-08-17)。"""
    assert _is_ai_ish("NCT127がAGT出るらしい\n💐ももか💐")


def test_気になるで締める型を弾く():
    """実測でガード後も残った最頻型。「〜けど/〜って、…気になる」。"""
    assert _is_ai_ish("TWICEのチェヨンがJYPを離れるらしいけど、"
                      "これからのグループ活動がどうなるのか気になるな。")
    assert _is_ai_ish("NCT127がAGTに生出演するって、どんなパフォーマンスか気になる")


def test_感想の後に気になる部分が多いと続ける型を弾く():
    assert _is_ai_ish("グループがこれからどうなるのか、ファンとしては気になる部分が多い")


def test_すごい系の空虚な強調を弾く():
    assert _is_ai_ish("本当にすごい展開だな〜、ファンとしてはドキドキする")
    assert _is_ai_ish("マジで意味深すぎるよね")


def test_事実だけの素っ気ない文は通る():
    assert not _is_ai_ish("ARIRANG、UKチャート21週目。まだ居るのか")
    assert not _is_ai_ish("チェヨンのJYP退所、公式発表出てた")
