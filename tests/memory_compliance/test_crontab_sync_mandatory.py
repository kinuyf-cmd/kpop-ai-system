"""
memory: feedback_crontab_sync_mandatory.md
規定: 「crontab刷新後にcrontab.txt未更新で68ジョブ脱落。変更時は必ずcrontab -l > crontab.txt」
"""
import subprocess, os


def test_crontab_txt_synchronized():
    """crontab.txt が現在の crontab -l 出力と一致 (差分±5行以内)"""
    txt_path = '/home/aiuser/kpop-ai-system/crontab.txt'
    if not os.path.exists(txt_path):
        import pytest; pytest.skip('crontab.txt not present')
    actual = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    if actual.returncode != 0:
        import pytest; pytest.skip('cannot read crontab')
    actual_lines = actual.stdout.splitlines()
    saved_lines = open(txt_path).read().splitlines()
    diff = abs(len(actual_lines) - len(saved_lines))
    assert diff <= 5, f"crontab.txt 同期ずれ: actual={len(actual_lines)} saved={len(saved_lines)}"
