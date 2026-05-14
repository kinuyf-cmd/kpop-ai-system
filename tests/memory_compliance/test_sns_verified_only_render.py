"""
2026-05-15: member 個別ページの personal Instagram は
`instagram_verified: true` flag が無いと render しない仕様の機械検証。

事故: LLM hallucination で `_groupname` suffix の fake handle が
artist_profiles に大量混入していた (NCT全員 / MOMOLAND全員 / NiziU全員 等)。
未検証 handle を表示すると本人ではないファン SNS / 偽 account 案内になり
信頼性失墜。
"""
import sys

sys.path.insert(0, '/home/aiuser/kpop-ai-system')


def test_render_member_html_skips_unverified_ig():
    """instagram_personal あり + instagram_verified なし → personal IG chip 出力なし"""
    from pipeline.profile_wiki_builder import render_member_html
    profile = {'agency': 'X', 'members': [
        {'name_en': 'Foo', 'name_kr': '푸', 'name_ja': 'フー',
         'instagram_personal': 'https://www.instagram.com/foo_fake/'}
    ]}
    html, _ = render_member_html('GroupX', 'group-x', profile['members'][0], profile)
    assert 'foo_fake' not in html, '未検証 IG が render に混入'
    assert '個人 Instagram' not in html, '未検証だが個人 Instagram label が表示された'


def test_render_member_html_shows_verified_ig():
    """instagram_verified=True なら personal IG chip 表示"""
    from pipeline.profile_wiki_builder import render_member_html
    profile = {'agency': 'X', 'members': [
        {'name_en': 'Bar', 'name_kr': '바', 'name_ja': 'バー',
         'instagram_personal': 'https://www.instagram.com/bar_real/',
         'instagram_verified': True}
    ]}
    html, _ = render_member_html('GroupX', 'group-x', profile['members'][0], profile)
    assert 'bar_real' in html, '検証済 IG が render されていない'
    assert '個人 Instagram' in html


def test_schema_org_sameAs_requires_verified():
    """schema.org の sameAs にも未検証 IG が乗らないこと"""
    from pipeline.profile_wiki_builder import _build_member_schema_org
    m = {'name_en': 'Foo', 'name_ja': 'フー',
         'instagram_personal': 'https://www.instagram.com/foo_fake/'}
    out = _build_member_schema_org('GroupX', 'group-x', m)
    assert 'foo_fake' not in out, 'schema.org sameAs に未検証 IG'

    m['instagram_verified'] = True
    out_v = _build_member_schema_org('GroupX', 'group-x', m)
    assert 'foo_fake' in out_v


def test_blackpink_members_have_verified_flag():
    """5/15 cleanup で BLACKPINK の 4 メンバーは verified=True 付与済"""
    import json
    d = json.load(open('/home/aiuser/kpop-ai-system/config/artist_profiles/blackpink.json',
                       encoding='utf-8'))
    members_with_ig = [m for m in d.get('members', []) if m.get('instagram_personal')]
    assert len(members_with_ig) >= 4
    for m in members_with_ig:
        assert m.get('instagram_verified') is True, \
            f"{m.get('name_en')} の BLACKPINK member に verified flag が無い"


def test_nct_fake_handles_removed():
    """5/15 cleanup で NCT の _nct suffix fake handle が削除されたこと"""
    import json
    d = json.load(open('/home/aiuser/kpop-ai-system/config/artist_profiles/nct.json',
                       encoding='utf-8'))
    for m in d.get('members', []):
        ip = m.get('instagram_personal') or ''
        if ip:
            assert '_nct' not in ip, \
                f"{m.get('name_en')} に残存する fake _nct handle: {ip}"
