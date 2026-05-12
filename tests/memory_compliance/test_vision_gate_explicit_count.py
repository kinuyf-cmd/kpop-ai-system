"""
memory: vision_gate priming bias による people miscount を防ぐため、
       schema に people_count フィールドを必須化し、人数判定を verdict より前に出力させる。

2026-05-12 事故事例:
- 22024 BABYMONSTER 記事に 6人組 (NMIXX 系) の画像が刺さっていたが、
  旧 vision_gate は LLM priming で「7人と数えて BABYMONSTER 一致」と
  hallucination していた。
- schema に people_count を強制追加し「ステップ2: 画像内の人物を必ず指差し
  数える」を prompt に明記したところ、count=6 を正確に出力し
  「7人組BABYMONSTER とは人数不足、NMIXX に近い構成 → NO」と
  正しく判定するようになった (本セッション 87e4a1e 修正)。
"""
import inspect


def test_vision_gate_schema_includes_people_count():
    """thumbnail_vision_gate の output schema に people_count が必須項目として
    含まれていること"""
    from lib import thumbnail_vision_gate
    src = inspect.getsource(thumbnail_vision_gate)
    assert '"people_count"' in src, \
        "vision_gate schema に people_count フィールドが無い (priming bias 防御欠落)"
    assert "'people_count'" in src or '"people_count"' in src, \
        "people_count が required に含まれていない可能性"


def test_vision_gate_prompt_demands_explicit_counting():
    """prompt が明示的な「人数カウント」step を含むこと"""
    from lib import thumbnail_vision_gate
    src = inspect.getsource(thumbnail_vision_gate)
    # 人数を正確に数える instruction が prompt 内に存在
    assert '指差し数える' in src or '数えて' in src or '人数を正確' in src, \
        "vision_gate prompt が人数の明示カウント step を持たない"
    # priming 回避の文言
    assert 'fudge' in src or 'priming' in src or '合わせて' in src, \
        "vision_gate prompt が priming bias 回避の注意書きを欠く"
