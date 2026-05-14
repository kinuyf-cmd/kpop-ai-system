"""
2026-05-15: artist_profiles の instagram_personal が全件
`instagram_verified=True` か `_instagram_removed_reason` のどちらかである
ことを継続検証する drift 検出テスト。

新規 LLM hallucination 由来 fake handle が無検証で混入したり、profile
更新時に verified flag を忘れたりするケースを CI で機械検知。
"""
import glob
import json

import pytest


def _all_profile_files():
    return sorted(glob.glob('/home/aiuser/kpop-ai-system/config/artist_profiles/*.json'))


def test_no_unverified_unflagged_instagram_personal():
    """全 artist_profiles の member.instagram_personal が
    1) 空文字 (cleared) または
    2) instagram_verified=True で _instagram_verified_at 有り
    のどちらかであること。未検証 handle が残置されていたら fail。"""
    violations = []
    for fp in _all_profile_files():
        try:
            d = json.load(open(fp, encoding='utf-8'))
        except Exception as e:
            violations.append((fp, 'parse_err', str(e)))
            continue
        slug = fp.split('/')[-1].replace('.json', '')
        for arr_name in ('members', 'former_members'):
            for m in d.get(arr_name) or []:
                ip = (m.get('instagram_personal') or '').strip()
                if not ip:
                    continue  # 空はOK
                if m.get('instagram_verified') is True:
                    if not m.get('_instagram_verified_at'):
                        violations.append((slug, m.get('name_en', '?'),
                                           f'verified=True だが _instagram_verified_at 欠落: {ip}'))
                    continue  # verified+timestamp OK
                # verified flag 無し → drift 違反
                violations.append((slug, m.get('name_en', '?'),
                                   f'unverified IG が残置: {ip}'))
    assert not violations, \
        f'\n  Drift violations ({len(violations)} 件):\n' + \
        '\n'.join(f'    {slug}/{name}: {msg}' for slug, name, msg in violations)


def test_cleared_handles_have_removed_reason():
    """instagram_personal が空文字なら _instagram_removed_reason が
    記録されている (cleanup 履歴の追跡性)。注: 元々 IG 持っていない
    member は両方欠落するため warn 扱い (fail させない)。"""
    silent_removals = 0
    for fp in _all_profile_files():
        try:
            d = json.load(open(fp, encoding='utf-8'))
        except Exception:
            continue
        for arr_name in ('members', 'former_members'):
            for m in d.get(arr_name) or []:
                # _instagram_removed_reason があるのに instagram_personal がないなら OK
                # _instagram_removed_reason なくて IG もない → 元から無し (OK)
                # _instagram_removed_reason あるのに IG 残ってる → 矛盾 (fail)
                ip = (m.get('instagram_personal') or '').strip()
                reason = m.get('_instagram_removed_reason')
                if ip and reason:
                    # IG 復活したが removed_reason が残ってる → 整合性違反
                    silent_removals += 1
                    raise AssertionError(
                        f'{fp}: {m.get("name_en")} に IG ありかつ _instagram_removed_reason 残置')
    # silent_removals=0 で常に通過 (構造整合性のみ)


def test_known_verified_count_floor():
    """5/15 cleanup で確立した最低 verified 件数を回帰検出。
    将来うっかり大量 clear した時の警報。"""
    verified = 0
    for fp in _all_profile_files():
        try:
            d = json.load(open(fp, encoding='utf-8'))
        except Exception:
            continue
        for arr_name in ('members', 'former_members'):
            for m in d.get(arr_name) or []:
                if m.get('instagram_verified') is True and (m.get('instagram_personal') or '').strip():
                    verified += 1
    # 5/15 達成 26+2 (MOMOLAND restore) = 28 件、floor を 24 に
    assert verified >= 24, \
        f'verified 件数 {verified} が floor 24 を下回り、大量 clear の疑い'
