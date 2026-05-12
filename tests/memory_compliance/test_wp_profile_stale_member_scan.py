"""2026-05-12 post 22075 事故 (LLM幻覚で NMIXX プロフィール block に脱退済 Jinni
含む 7人と書かれて publish された) への再発防止 scan script の機械検証。

scripts/scan_wp_profile_stale_member.py が:
  - WP本文 <dl class="kpj-artist-profile"> 内の members 列を抽出できる
  - config/artist_database.json と照合して extra/missing を検出できる
  - 22075 と同 class の事例で violation を返す
  - config/artist_database.json の NMIXX が現役 6人で stale Jinni を含まない

を機械検証する。test_no_stale_departed_members.py (config 側) と対をなす本文側の番人。
"""
import sys
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
sys.path.insert(0, '/home/aiuser/kpop-ai-system/scripts')


def test_extract_profile_block_basic():
    """<dl class="kpj-artist-profile"> から members を抽出できる"""
    from scan_wp_profile_stale_member import extract_profile_block
    html = '''
    <p>記事本文</p>
    <div class="kpj-artist-profile">
      <h3>NMIXX プロフィール</h3>
      <dl>
        <dt>所属事務所</dt><dd>JYP</dd>
        <dt>メンバー</dt><dd>Lily, Haewon, Sullyoon, Bae, Jiwoo, Kyujin</dd>
      </dl>
    </div>
    '''
    b = extract_profile_block(html)
    assert b is not None
    assert b['artist_name'] == 'NMIXX'
    assert b['members'] == ['Lily', 'Haewon', 'Sullyoon', 'Bae', 'Jiwoo', 'Kyujin']


def test_extract_returns_none_for_no_block():
    """profile block が無い記事では None"""
    from scan_wp_profile_stale_member import extract_profile_block
    assert extract_profile_block('<p>plain article</p>') is None


def test_compare_detects_stale_extra():
    """WP本文に config に無い member (stale) があれば extra で検出"""
    from scan_wp_profile_stale_member import compare
    wp = ['Lily', 'Haewon', 'Sullyoon', 'Jinni', 'Bae', 'Jiwoo', 'Kyujin']
    db = ['Lily', 'Haewon', 'Sullyoon', 'Bae', 'Jiwoo', 'Kyujin']
    d = compare(wp, db)
    assert 'Jinni' in d['extra'], f'Jinni should be flagged as extra, got {d}'
    assert d['missing'] == []
    assert d['count_match'] is False


def test_compare_case_insensitive():
    """大文字小文字違いは同一視 (Lily ↔ LILY)"""
    from scan_wp_profile_stale_member import compare
    wp = ['Lily', 'Haewon']
    db = ['LILY', 'HAEWON']
    d = compare(wp, db)
    assert d['extra'] == []
    assert d['missing'] == []


def test_compare_clean_when_match():
    """完全一致なら違反なし"""
    from scan_wp_profile_stale_member import compare
    db = ['Lily', 'Haewon', 'Sullyoon', 'Bae', 'Jiwoo', 'Kyujin']
    d = compare(db, db)
    assert d['extra'] == [] and d['missing'] == []
    assert d['count_match'] is True


def test_scan_post_returns_violation_for_jinni_case():
    """22075 事故の再現: NMIXX プロフィールに Jinni 含む → violation 返却"""
    from scan_wp_profile_stale_member import scan_post
    mock_post = {
        'id': 22075,
        'link': 'https://example/22075',
        'content': {'rendered': '''
          <div class="kpj-artist-profile">
            <h3>NMIXX プロフィール</h3>
            <dl>
              <dt>メンバー</dt><dd>Lily, Haewon, Sullyoon, Jinni, Bae, Jiwoo, Kyujin</dd>
            </dl>
          </div>
        '''}
    }
    db = {'NMIXX': {'members': ['Lily', 'Haewon', 'Sullyoon', 'Bae', 'Jiwoo', 'Kyujin']}}
    v = scan_post(mock_post, db)
    assert v is not None
    assert v['post_id'] == 22075
    assert 'Jinni' in v['extra']
    assert v['severity'] == 'high'


def test_artist_database_nmixx_has_no_jinni():
    """config/artist_database.json の NMIXX に Jinni が残っていないこと"""
    import json
    d = json.load(open('/home/aiuser/kpop-ai-system/config/artist_database.json',
                       encoding='utf-8'))
    members = d.get('NMIXX', {}).get('members', [])
    assert members, 'NMIXX entry missing or members empty'
    assert 'Jinni' not in members, f'Jinni should not be in NMIXX members, got {members}'
    assert len(members) == 6, f'NMIXX should have 6 active members, got {len(members)}'


def test_scan_script_executable():
    """scan script が importable で main 関数を持つ"""
    import scan_wp_profile_stale_member as m
    assert hasattr(m, 'main')
    assert hasattr(m, 'scan_post')
    assert hasattr(m, 'extract_profile_block')
    assert hasattr(m, 'compare')
