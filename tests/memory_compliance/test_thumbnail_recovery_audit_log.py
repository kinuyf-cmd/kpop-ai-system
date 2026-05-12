"""
memory: feedback_thumbnail_recovery_audit_log.md
規定: WP featured_media を更新する recovery/regen script は、update 直後に
       `lib.audit_steps_log.record_step(pid, 'thumbnail', 'ok', ...)` を必ず呼ぶ。
       これを怠ると audit_steps_enforcer cron が status=error の旧 entry を見て
       自動 draft 化する (21541 ユナ事例の再発 root cause)。
"""
import re

RECOVERY_SCRIPTS = [
    '/home/aiuser/kpop-ai-system/lib/regen_thumbnails_last24h.py',
]


def test_recovery_scripts_call_record_step():
    """各 recovery script が record_step('thumbnail', 'ok', ...) を含むこと"""
    violations = []
    for path in RECOVERY_SCRIPTS:
        with open(path, encoding='utf-8') as f:
            src = f.read()
        has_import = (
            'from lib.audit_steps_log import record_step' in src
            or 'from lib.audit_steps_log import' in src and 'record_step' in src
        )
        # thumbnail step の record_step 呼出 (引数順は柔軟に許容)
        has_call = bool(
            re.search(
                r"record_step\s*\([^)]*['\"]thumbnail['\"][^)]*['\"]ok['\"]",
                src,
                re.DOTALL,
            )
        )
        if not (has_import and has_call):
            violations.append(
                (path.split('/')[-1], f'import={has_import} call={has_call}')
            )
    assert not violations, (
        "recovery script が thumbnail update 後の record_step を呼んでいない。"
        " enforcer が誤 draft 化する穴になる:\n  " +
        "\n  ".join(f"{p}: {d}" for p, d in violations)
    )
