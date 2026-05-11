"""
memory: feedback_crontab_temp_file_safety.md
規定: 「固定名temp file禁止 (/tmp/crontab_new等) → 残骸install事故。$$または mktemp 必須」
"""
import os, re


def test_no_fixed_temp_crontab_in_scripts():
    """scripts/pipeline/ に /tmp/crontab_<固定名> 参照がないこと"""
    import glob
    bad_pattern = re.compile(r'/tmp/crontab[a-z_]*\.txt|/tmp/cron_new')
    found = []
    for p in glob.glob('/home/aiuser/kpop-ai-system/{lib,scripts,pipeline}/**/*.{py,sh}',
                       recursive=True):
        try:
            text = open(p, encoding='utf-8', errors='ignore').read()
        except Exception:
            continue
        if bad_pattern.search(text):
            # ただし mktemp / $$ 経由の動的命名は除外
            for line in text.splitlines():
                if bad_pattern.search(line) and 'mktemp' not in line and '$$' not in line:
                    found.append(f"{p}: {line.strip()[:80]}")
                    break
    assert not found, f"固定名 /tmp/crontab*.txt 参照: {found[:5]}"
