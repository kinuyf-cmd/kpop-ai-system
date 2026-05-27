"""回帰: unified_publisher のゲートが「注入前 raw 本文」で content 判定する順序を固定
(2026-05-27 修正の不変条件)

自社の内部リンク/CTA 注入を factcheck より「後」に動かすと、自社注入物が
「無関係コンテンツ」と誤判定される自滅的ブロックが再発する。本テストは
unified_publish() のソース内で以下の順序が保たれていることを保証する:

  パス1 content ゲート(body_html=raw_content_for_gate)
      ↓  ← この間に注入が来てはならない
  内部リンク注入(_insert_inline_links)
  CTA 注入(inject_cta_into_content)
  再サニタイズ
  パス2 structural ゲート(structural_only=True)

実際の publish 実行は WP/LLM 副作用があるため、ここではソース構造で不変条件を検証する
(軽量・決定的・CI 安全)。
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent.parent / "lib" / "unified_publisher.py"


def _src():
    return SRC.read_text(encoding="utf-8")


def _pos(pattern, text):
    m = re.search(pattern, text)
    assert m, f"パターンが見つからない: {pattern}"
    return m.start()


class TestGateOrdering:
    def test_content_gate_uses_raw_body(self):
        """パス1ゲートは raw_content_for_gate(注入前)を渡す。"""
        s = _src()
        assert "raw_content_for_gate = content" in s
        assert re.search(r"body_html=raw_content_for_gate", s), \
            "パス1ゲートが注入前 raw 本文を渡していない"

    def test_content_gate_before_injection(self):
        """content ゲート(パス1)は内部リンク/CTA 注入より前にある。"""
        s = _src()
        gate1 = _pos(r"raw_content_for_gate = content", s)
        internal = _pos(r"_insert_inline_links\(content", s)
        cta = _pos(r"inject_cta_into_content\(title_final, content\)", s)
        assert gate1 < internal, "パス1ゲートが内部リンク注入より後ろにある(誤順)"
        assert gate1 < cta, "パス1ゲートが CTA 注入より後ろにある(誤順)"

    def test_structural_gate_after_injection(self):
        """structural ゲート(パス2)は注入の後にある。"""
        s = _src()
        cta = _pos(r"inject_cta_into_content\(title_final, content\)", s)
        gate2 = _pos(r"structural_only=True", s)
        assert cta < gate2, "パス2 structural ゲートが CTA 注入より前にある(誤順)"

    def test_merge_blocks_on_either_pass(self):
        """block_reasons は両パスの union で判定される。"""
        s = _src()
        # 両パスが同じ accumulator に足し込んでいる
        assert s.count("_gate_block_reasons +=") >= 2, \
            "block_reasons の union が2パス分そろっていない"
        assert "if _gate_block_reasons:" in s, "マージ後の BLOCK 判定が無い"
