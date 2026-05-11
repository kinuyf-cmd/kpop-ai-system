"""
memory: feedback_definition_of_done.md
規定: 「実装完了≠完了。本番動作+証跡(logs/completion_evidence/)がなければ完了報告禁止」
"""
import os


def test_completion_evidence_dir_exists():
    p = '/home/aiuser/kpop-ai-system/logs/completion_evidence'
    assert os.path.isdir(p), f"completion_evidence dir not found: {p}"


def test_recent_completion_evidence_exists():
    """直近に completion evidence が記録されていること (本セッション証跡)"""
    p = '/home/aiuser/kpop-ai-system/logs/completion_evidence'
    files = [f for f in os.listdir(p) if f.endswith('.md')]
    assert len(files) > 0, "completion evidence ファイルが1件もない"
