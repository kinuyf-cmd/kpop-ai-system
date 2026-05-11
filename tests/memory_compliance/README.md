# memory_compliance テスト

## 目的
`~/.claude/projects/-home-aiuser-kpop-ai-system/memory/feedback_*.md` のうち**コードに影響するもの**を機械検証可能なテストに変換する。
2026-05-11発生 「memoryに明記されていたサムネpriorityを逆実装した」事故の再発防止。

## 命名規約
1 memory file = 1 test file。
- `memory: feedback_artist_photo_absolute_rule.md`
- `test: tests/memory_compliance/test_artist_photo_absolute_rule.py`

## テストの書き方
```python
"""
memory: feedback_<rule_name>.md
規定: <ルール本文の引用>
"""
def test_<rule>():
    # コードを呼んで規定通りの挙動か assert
    ...
```

## 実行
```
cd /home/aiuser/kpop-ai-system
python3 -m pytest tests/memory_compliance/ -v
```

## 強制
- pre-commit hook: commit時に全テスト pass を強制 (`tests/memory_compliance/run.sh`)
- Stop hook: assistant 完了主張時にもテスト結果を確認

## 違反時の対応
test fail → コードかmemoryのどちらが正しいかを確認 → memory正なら**コード修正**、memory誤なら**memory更新+test更新を同時commit**。
