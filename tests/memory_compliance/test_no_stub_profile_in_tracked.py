"""
2026-05-15 事故根治 (ALL(H)OURS / Aoen / GIRLSET / IDID):
profile_wiki_builder.build_one() の wiki_ok 判定が緩く、LLM が
"情報が見つかりませんでした" と返した時も True を返して stub 内容の
profile JSON + WP wiki page を生成していた事故への防壁。

git で tracked な config/artist_profiles/*.json に stub 内容が混入していない
ことを機械検証する。untracked な WIP stub (retry 待ち) は除外する。
"""
import json
import subprocess


REPO_ROOT = '/home/aiuser/kpop-ai-system'


def _is_stub(profile: dict) -> bool:
    agency = (profile.get('agency') or '').strip().lower()
    debut = (profile.get('debut_date') or '').strip().lower()
    if agency in ('unknown', '?', '') and debut in ('unknown', '?', ''):
        return True
    members = profile.get('members') or []
    if members and all(
        (m.get('name_en') or '').strip().lower() in ('unknown', '?', '')
        for m in members if isinstance(m, dict)
    ):
        return True
    summary = profile.get('summary_ja') or ''
    failure_phrases = (
        '確認できません', '確認することができません',
        '見つかりませんでした', '取得できません',
        '一時的に利用できない', '利用上限に達した',
    )
    if any(p in summary for p in failure_phrases):
        return True
    return False


def test_no_stub_in_tracked_artist_profiles():
    out = subprocess.check_output(
        ['git', '-C', REPO_ROOT, 'ls-files', 'config/artist_profiles/*.json'],
        text=True,
    )
    files = [line.strip() for line in out.splitlines() if line.strip()]
    assert files, 'git ls-files config/artist_profiles/*.json が空: glob 不一致の疑い'

    violations = []
    for rel in files:
        path = f'{REPO_ROOT}/{rel}'
        try:
            with open(path, encoding='utf-8') as f:
                d = json.load(f)
        except Exception:
            continue
        if _is_stub(d):
            violations.append(rel)

    assert not violations, (
        '\nstub profile が tracked artist_profiles に混入:\n  - '
        + '\n  - '.join(violations)
        + '\n→ profile_wiki_builder.build_one() を retry するか profile を削除してください。'
    )
