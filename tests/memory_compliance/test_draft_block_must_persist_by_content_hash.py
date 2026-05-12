"""
memory: gate stochastic PASS で過去 BLOCK 済記事が publish される事故防止
規定: draft_auto_publisher は content_hash を block_history に記録し、
       同 content_hash で再 retry した場合は gate 再実行せず過去 BLOCK を維持する。

2026-05-12 事故事例:
- 22027 (CORTIS TNT): BLOCK 1/3, 2/3 で hallucination 検出済 → 3 回目で gate が
  偶発的に PASS を返して publish → kpop-auditor 実運用テストで AI 捏造曲名 3 件発覚
- 22024 (BABYMONSTER CHOOM): 同様に BLOCK 1/3, 2/3 → 3 回目で publish

root cause: pre_publish_gate は LLM ベース factcheck を含むため stochastic で、
同一 content でも実行ごとに verdict が変動。MAX_BLOCK_COUNT=3 が安全装置として
機能しなくなる。
"""
import inspect


def test_draft_auto_publisher_uses_content_hash_in_block_history():
    """draft_auto_publisher のソースに content_hash 永続化ロジックがあること"""
    from pipeline import draft_auto_publisher
    src = inspect.getsource(draft_auto_publisher)
    assert 'content_hash' in src, \
        "draft_auto_publisher.py に content_hash 永続化が無い (stochastic PASS 防御不在)"
    # ハッシュ計算と prior 比較が両方あること
    assert 'hashlib.sha256' in src, \
        "content_hash 計算 (hashlib.sha256) が見当たらない"
    assert "prior.get('content_hash') == content_hash" in src or \
           "prior['content_hash'] == content_hash" in src, \
        "prior block_history の content_hash 比較ロジックが無い"


def test_draft_auto_publisher_skips_gate_on_same_content_hash():
    """同 content_hash + prior count >= 1 の場合に gate 再実行をスキップしていること"""
    from pipeline import draft_auto_publisher
    src = inspect.getsource(draft_auto_publisher)
    # 同 content の retry は gate を呼ばずに verdict='BLOCK' を直接返す guard
    assert "'verdict': 'BLOCK'" in src or '"verdict": "BLOCK"' in src, \
        "content_hash 一致時の verdict='BLOCK' 強制返却ロジックが無い"
