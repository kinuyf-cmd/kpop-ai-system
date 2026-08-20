"""CTA注入が h2 見出しの内側に入る破損の再発防止テスト。

2026-08-20 の事故:
  inject_cta_into_content が挿入位置を `</h2>` にマッチする正規表現の
  .start() で決めていたため、「2つ目のh2の直前」のつもりが実際には
  「h2 の閉じタグの直前 = 見出しの内側」に CTA ブロックを差し込んでいた。

    <h2>見出しB           ← 開いたまま
    <div class="kpj-cta-block"> …広告… </div>
    …本文・表…
    </h2>                 ← ここでようやく閉じる

  結果、公開済み43記事で h2 が広告と本文を丸ごと飲み込む状態になり、
  Google からは「見出しの中に広告」と見える形で imp 21,996 分の記事が
  順位10〜69位に沈んでいた。本文の中身は十分だったのに CTR 0% の
  クエリが多発していたのが症状。

  → 挿入位置は必ず h2 の *外側* でなければならない。
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib.cta_injector import inject_cta_into_content


_PARA = (
    "この段落はテスト用の本文です。実際の記事と同じくらいの長さを確保するために、"
    "意味のある文章を繰り返し記述しています。"
) * 2

# 注意: inject_cta_into_content は本文400字未満だと何もせず返すため、
#       サンプルは必ず実記事並みの長さにすること。短いサンプルだと CTA が
#       生成されず、テストが「素通りで pass」してしまい破損を検出できない。
SAMPLE = f"""<h2>そもそもAGE-Rブースタープロとは?基本から整理</h2>
<p>{_PARA}</p>
<p>{_PARA}</p>
<h2>スキンケアの順番｜化粧水・乳液・クリームのどこで使う?</h2>
<p>{_PARA}</p>
<p>{_PARA}</p>
<h2>使う前に知っておきたい注意点</h2>
<p>{_PARA}</p>
"""


def _inject(html: str = SAMPLE) -> str:
    """CTAが実際に挿入されたことを確認したうえで結果を返す。"""
    out = inject_cta_into_content("メディキューブ AGE-R ブースタープロの使い方", html)
    assert "kpj-cta" in out, (
        "CTAが挿入されていない。このテストは素通りでは意味がないため、"
        "サンプル本文の長さや広告プログラム設定を見直すこと。"
    )
    return out


def _h2_inner_texts(html: str):
    """<h2>…</h2> の中身を返す。"""
    return re.findall(r"<h2[^>]*>(.*?)</h2>", html, re.DOTALL)


def test_cta_never_lands_inside_h2():
    """CTA ブロックが h2 の内側に入ってはいけない。"""
    out = _inject()
    for inner in _h2_inner_texts(out):
        assert "kpj-cta" not in inner, f"CTAがh2の内側に入っている: {inner[:120]!r}"


def test_h2_tags_stay_balanced_and_short():
    """h2 が本文や表を飲み込んでいないこと(開閉数の一致 + 中身が短い)。"""
    out = _inject()
    assert len(re.findall(r"<h2\b", out)) == out.count("</h2>")
    for inner in _h2_inner_texts(out):
        assert "<p" not in inner, f"h2が段落を飲み込んでいる: {inner[:120]!r}"
        assert len(inner) < 200, f"h2の中身が長すぎる(飲み込みの疑い): {len(inner)}字"


def test_no_unclosed_h2_before_paragraph():
    """`<h2>テキスト</p>` という壊れた閉じ方が発生しないこと。

    本番DBの破損検出に使った正規表現と同じ形で検査する。
    """
    out = _inject()
    assert not re.search(r"<h2>[^<]*</p>", out), "h2が</p>で閉じられている(本番と同じ破損)"
