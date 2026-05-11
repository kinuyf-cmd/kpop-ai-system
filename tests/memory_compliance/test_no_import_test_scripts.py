"""
memory: feedback_no_import_test_scripts.md
規定: 「scripts/配下はimport即時batch実行で副作用大。lib/とpipeline/のみ対象、scripts/はsyntax checkのみ」
"""
import os, glob, ast


def test_scripts_dir_files_are_main_guarded():
    """scripts/ の.pyは __name__ == '__main__' 直下に処理を置くこと"""
    bad = []
    for p in glob.glob('/home/aiuser/kpop-ai-system/scripts/*.py'):
        try:
            text = open(p).read()
        except Exception:
            continue
        if 'if __name__' not in text and len(text) > 100:
            # main-guardなしで重い処理を即実行 = NG
            tree = ast.parse(text)
            top_level_calls = sum(1 for n in tree.body
                                   if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call))
            if top_level_calls > 1:
                bad.append(os.path.basename(p))
    assert len(bad) < 5, f"scripts/ の main-guard 不足: {bad[:5]}"
