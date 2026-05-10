"""回帰テストsuite (2026-05-10)

防御コードが将来のリファクタで壊れないようにする。
cron毎日11時に実行 (失敗ならDiscord通知)。

実行:
    python3 -m pytest tests/test_thumbnail_defenses.py -v
"""
import os
import sys
import json
import tempfile
sys.path.insert(0, '/home/aiuser/kpop-ai-system')

import pytest
from PIL import Image, ImageDraw

from lib.thumbnail_source_resolver import _is_shorts_thumbnail
from lib.collectors.korean_base import is_kpop_related
from lib.wikimedia import is_relevant_title


# === Shorts pattern detection ===

def _make_shorts_image(path: str):
    """Shortsパターン (中央コンテンツ + 左右ブラー) を作る"""
    import numpy as np
    arr = np.zeros((720, 1280, 3), dtype=np.uint8)
    # 左右: グラデーション色 (ブラーらしい弱いstdだが range>30)
    for x in range(0, 320):
        c = 50 + (x % 60)  # 50-110の範囲で色変化
        arr[:, x] = (c, c-20, c+10)
        arr[:, 1280-x-1] = (c, c-20, c+10)
    # 中央: 高stdのカラフル content
    np.random.seed(42)
    for y in range(720):
        for x in range(320, 960):
            arr[y, x] = np.random.randint(0, 256, 3)
    Image.fromarray(arr).save(path, 'JPEG', quality=85)


def _make_legit_landscape(path: str):
    """普通の横長写真 (中央も左右もデータ豊富)"""
    img = Image.new('RGB', (1280, 720), 'white')
    draw = ImageDraw.Draw(img)
    # 全体に色のばらつき
    for x in range(0, 1280, 50):
        draw.rectangle([x, 0, x+50, 720], fill=((x*2)%256, (x*3)%256, (x*5)%256))
    img.save(path, 'JPEG', quality=85)


def _make_logo_image(path: str):
    """単色背景logo (Shortsじゃないが左右暗い)"""
    img = Image.new('RGB', (1280, 720), '#FFE5E5')
    draw = ImageDraw.Draw(img)
    draw.text((550, 350), "BRAND LOGO", fill='black')
    img.save(path, 'JPEG', quality=85)


def test_shorts_detector_catches_shorts():
    """実Shorts画像 (TWS、白衣装+左右ブラー) を検出"""
    fixture = '/home/aiuser/kpop-ai-system/tests/fixtures/shorts_pattern.jpg'
    if not os.path.exists(fixture):
        pytest.skip(f"fixture missing: {fixture}")
    assert _is_shorts_thumbnail(fixture), "Real Shorts pattern must be detected"


def test_shorts_detector_passes_legit_photo():
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tf:
        _make_legit_landscape(tf.name)
        try:
            assert not _is_shorts_thumbnail(tf.name), "Legit landscape photo must NOT be flagged as Shorts"
        finally:
            os.unlink(tf.name)


def test_shorts_detector_passes_logo():
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tf:
        _make_logo_image(tf.name)
        try:
            assert not _is_shorts_thumbnail(tf.name), "Logo/single-color background must NOT be flagged as Shorts"
        finally:
            os.unlink(tf.name)


# === artist識別 ===

def test_artist_subject_first_ordering():
    """主語位置でartist順序が決まる (長さ順ではない)"""
    # 18881事案: BLACKPINK(9字) が BOYNEXTDOOR(11字) より先に出現するなら BLACKPINK 優先
    title = 'BLACKPINK ジス着用衣装をめぐる議論…BOYNEXTDOOR出演'
    arts = is_kpop_related(title)
    assert arts[0] == 'BLACKPINK', f"主語位置優先: BLACKPINK should come first, got {arts}"


def test_kstyle_concat_artist_detection():
    """kstyle連結タイトルでも先頭のチョ・スンヨンが識別される"""
    title = 'チョ・スンヨン、ファン対象に無給スタッフ募集？事務所が謝罪RIIZE、BOYNEXTDOOR、TWS出演'
    arts = is_kpop_related(title)
    assert 'チョ・スンヨン' in arts[:1], f"先頭のチョ・スンヨンが返るべき: {arts}"


def test_full_name_detection():
    """フルネーム形 (TOMORROW X TOGETHER等) も識別"""
    title = 'TOMORROW X TOGETHER、日本5大ドームツアー決定！'
    arts = is_kpop_related(title)
    assert 'TOMORROW X TOGETHER' in arts


def test_html_entity_apostrophe():
    """U+2019 apostrophe (’) も識別"""
    title = "CAT’S EYE、英シングルチャートにランクイン"
    arts = is_kpop_related(title)
    assert "CAT’S EYE" in arts or "CAT'S EYE" in arts


# === Wikimedia ambiguous-name guard ===

def test_wikimedia_jennie_blocks_western():
    """JENNIE のWikimediaマッチで西洋人名を弾く"""
    assert not is_relevant_title('File:Peter_Gabriel_Tour_Jennie_Abrahamson.jpg', 'JENNIE')


def test_wikimedia_jennie_passes_blackpink():
    """JENNIE BLACKPINK のWikimediaマッチは通す"""
    assert is_relevant_title('File:JENNIE BLACKPINK 2024 concert.jpg', 'JENNIE')


def test_wikimedia_lisa_blocks_korean_namesake():
    """『Lisa (Korean vocalist)』(別人) を弾く"""
    assert not is_relevant_title('File:Lisa (Korean vocalist).jpg', 'LISA')


def test_wikimedia_lisa_passes_blackpink_lalisa():
    """LISA + BLACKPINK or LALISA は通す"""
    assert is_relevant_title('File:Lisa BLACKPINK PUBG ad.png', 'LISA')
    assert is_relevant_title('File:LALISA Lisa solo MV.jpg', 'LISA')


def test_wikimedia_treasure_blocks_dragon():
    """TREASURE で dragon fantasy art を弾く"""
    assert not is_relevant_title('File:dragon-and-treasure-painting.jpg', 'TREASURE')


def test_wikimedia_treasure_passes_korean():
    """TREASURE 트레저 はマッチ"""
    assert is_relevant_title('File:230815 트레저 TREASURE Hello Tour.jpg', 'TREASURE')


# === unified_publisher gate ===

def test_validate_thumbnail_rejects_portrait():
    """縦長画像はBLOCK"""
    from lib.unified_publisher import _validate_thumbnail
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tf:
        Image.new('RGB', (500, 1000), 'white').save(tf.name)
        try:
            ok, reason = _validate_thumbnail(tf.name)
            assert not ok and 'portrait' in reason
        finally:
            os.unlink(tf.name)


def test_validate_thumbnail_rejects_too_small():
    """極小画像はBLOCK"""
    from lib.unified_publisher import _validate_thumbnail
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tf:
        Image.new('RGB', (100, 80), 'white').save(tf.name)
        try:
            ok, reason = _validate_thumbnail(tf.name)
            assert not ok and 'small' in reason.lower()
        finally:
            os.unlink(tf.name)


def test_validate_thumbnail_passes_landscape():
    """普通の横長画像 (artist指定なし) は通る"""
    from lib.unified_publisher import _validate_thumbnail
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tf:
        _make_legit_landscape(tf.name)
        try:
            ok, reason = _validate_thumbnail(tf.name)  # no expected_artist
            assert ok, f"legit landscape should pass: {reason}"
        finally:
            os.unlink(tf.name)


# === youtube order config ===

def test_article_themes_use_viewcount():
    """全テーマがviewCount (date順は使わない)"""
    cfg = json.load(open('/home/aiuser/kpop-ai-system/config/article_themes.json'))
    for tname, tcfg in cfg['themes'].items():
        order = tcfg.get('youtube_order')
        assert order == 'viewCount', f"{tname}: youtube_order should be 'viewCount', got '{order}'"
    assert cfg['default_theme'].get('youtube_order') == 'viewCount'


# === official_accounts.json ===

def test_official_accounts_has_treasure():
    """TREASURE登録済 (e0c8d9e事案)"""
    accounts = json.load(open('/home/aiuser/kpop-ai-system/config/official_accounts.json'))
    assert 'treasure' in accounts


# === cache purge endpoint ===

def test_cache_purge_url_has_trailing_slash():
    """101c1d3事案: /api/revalidate/ (trailing slash) でないと308"""
    src = open('/home/aiuser/kpop-ai-system/lib/frontend_cache.py').read()
    assert "/api/revalidate/'" in src, "trailing slash必須 (308 redirect回避)"


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
