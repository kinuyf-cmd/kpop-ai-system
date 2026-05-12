"""
memory: (G)I-DLE Soojin / NMIXX Jinni / TREASURE Yedam 等の脱退ドリフト全般。
規定: artist_profiles/*.json の `members` 配列に「脱退」を note に持つ member が
       残っていてはならない。脱退メンバーは `former_members` 配列に移すこと。
       (G)I-DLE Soojin (e0a2e2a), NMIXX Jinni (4f941ea) と同 root cause class。

このテストは「現メンバーリストの精度」を守る生命線:
  - 記事生成 LLM に渡される profile データが古いと「N人組」の人数が誤表示される
  - メンバー紹介で脱退者が混入する
  - サムネ ↔ メンバー数の不整合が発生する (BABYMONSTER 22024 と同 class)
"""
import glob, json

PROFILE_GLOB = '/home/aiuser/kpop-ai-system/config/artist_profiles/*.json'


def test_no_departed_member_in_current_roster():
    """`members` 配列の各 entry の note に「脱退」が含まれていないこと

    note に「脱退」が含まれる member は former_members に移すべき。
    """
    violations = []
    for p in sorted(glob.glob(PROFILE_GLOB)):
        try:
            d = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        for m in d.get('members', []):
            if not isinstance(m, dict):
                continue
            note = m.get('note', '')
            if '脱退' in note:
                violations.append((
                    p.split('/')[-1],
                    m.get('name_en', '?'),
                    note[:80],
                ))
    assert not violations, (
        "現メンバー (members) に脱退記載のある member が残存しています。"
        " former_members へ移動してください:\n  " +
        "\n  ".join(f"{f}: {n} — {note}" for f, n, note in violations)
    )


def test_former_members_are_not_in_current_members():
    """former_members に含まれる name_en が members にも重複登場していないこと"""
    violations = []
    for p in sorted(glob.glob(PROFILE_GLOB)):
        try:
            d = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        current_names = {
            m.get('name_en') for m in d.get('members', []) if isinstance(m, dict)
        }
        for fm in d.get('former_members', []):
            if isinstance(fm, dict) and fm.get('name_en') in current_names:
                violations.append((p.split('/')[-1], fm.get('name_en')))
    assert not violations, (
        "former_members と members に同一 name_en が重複登場:\n  " +
        "\n  ".join(f"{f}: {n}" for f, n in violations)
    )


def test_known_departed_members_absent_from_compact_database():
    """artist_database.json の compact `members` リストにも脱退メンバーが残っていないこと

    artist_profiles と database.json の二箇所同期失敗を防ぐ。
    """
    DEPARTED = {
        '(G)I-DLE': ['Soojin'],
        'NMIXX': ['Jinni'],
        'RIIZE': ['Seunghan'],
        # TREASURE Yedam は元から database.json 不在、profile のみ
    }
    d = json.load(open(
        '/home/aiuser/kpop-ai-system/config/artist_database.json',
        encoding='utf-8'))
    violations = []
    for group, departed_names in DEPARTED.items():
        members = d.get(group, {}).get('members', [])
        for name in departed_names:
            if name in members:
                violations.append((group, name))
    assert not violations, (
        "artist_database.json の compact roster に脱退メンバーが残存:\n  " +
        "\n  ".join(f"{g}: {n}" for g, n in violations)
    )
