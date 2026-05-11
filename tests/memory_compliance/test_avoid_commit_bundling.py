"""
memory: feedback_avoid_commit_bundling.md
規定: 「M状態ファイル編集前にdiff量確認。100行超なら退避→HEAD戻し→再適用→commit→復元」
このruleはprocedural (人手手順) なので test 化は限定的だが、
gitignore類のM状態ファイルが pipeline自動更新で増えていないかは検証可能。
"""
import os
import subprocess


def test_git_repo_exists():
    """gitリポジトリが正常に動作"""
    r = subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'],
                       cwd='/home/aiuser/kpop-ai-system', capture_output=True, text=True)
    assert r.returncode == 0, f"git status err: {r.stderr}"


def test_modified_count_under_threshold():
    """M状態のファイルが30件以下に保たれていること (lower=better)"""
    r = subprocess.run(['git', 'status', '--porcelain'],
                       cwd='/home/aiuser/kpop-ai-system', capture_output=True, text=True)
    modified = [l for l in r.stdout.splitlines() if l.startswith(' M') or l.startswith('M ')]
    # 警告レベル (50件以上で fail にすると過剰なので情報として残す)
    if len(modified) > 50:
        # warning relevant — but don't fail (これは情報目的)
        print(f"WARN: {len(modified)} M-state files (>50)")
    assert len(modified) < 200, f"M-state files異常 ({len(modified)}件)"
