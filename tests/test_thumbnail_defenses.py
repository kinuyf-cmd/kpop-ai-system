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


# === fallback_cache cross-artist mismatch (23224 事案) ===

def test_resolve_fallback_photo_rejects_non_latin_name():
    """非 Latin 名 (Hangul/Katakana) で _slug が空文字になる場合、
    glob '**.*' が全 cache match で別アーティスト写真を pick する事故を防ぐ。

    2026-05-15: post 23224 で アイキー → fallback_cache → IVE 写真混入の事故。
    """
    from lib.thumbnail_source_resolver import resolve_fallback_photo, _slug
    # 前提: _slug 自体は短い文字列を返す (修正対象ではない)
    assert _slug('アイキー') == ''
    assert _slug('아이유') == ''
    # 修正: 短すぎる slug は早期 return None
    assert resolve_fallback_photo('アイキー') is None
    assert resolve_fallback_photo('아이유') is None
    assert resolve_fallback_photo('') is None
    assert resolve_fallback_photo(None) is None


def test_wikimedia_fetch_safe_image_rejects_short_slug():
    """slug が空 → CACHE_INDEX に '' key を書き込んでしまう writer 側の事故防止。

    2026-05-15: CACHE_INDEX['' ] = {name:'아이유',...} が混入し、
    resolve_fallback_photo が空 slug lookup で IU を返していた。
    """
    from lib.wikimedia import fetch_safe_image
    # 非 Latin 名は writer 側で早期 return → cache 汚染なし
    assert fetch_safe_image('アイキー', '/tmp/test_cache_dummy') is None
    assert fetch_safe_image('아이유', '/tmp/test_cache_dummy') is None


def test_artist_cache_index_no_empty_keys():
    """CACHE_INDEX に空 key entry が残っていないこと (data hygiene)。"""
    idx_path = '/home/aiuser/kpop-ai-system/assets/artist_cache/index.json'
    if not os.path.exists(idx_path):
        pytest.skip('cache index 未生成')
    idx = json.loads(open(idx_path).read())
    bad = [k for k in idx.keys() if len(k) < 2]
    assert not bad, f"短すぎる key entries (cross-artist mismatch 原因): {bad}"


# === DALL-E → gpt-image-1 migration (2026-05-15) ===

def test_dalle_thumbnail_gen_uses_gpt_image_1():
    """dall-e-3 は OpenAI で廃止 ("model 'dall-e-3' does not exist")。
    gpt-image-1 (または後続) に移行されていること。
    """
    from lib import dalle_thumbnail_gen
    assert dalle_thumbnail_gen.MODEL != 'dall-e-3', \
        'dall-e-3 は廃止: gpt-image-1 系に移行すること'
    assert 'gpt-image' in dalle_thumbnail_gen.MODEL or \
           dalle_thumbnail_gen.MODEL.startswith('chatgpt-image'), \
        f'未知の image model: {dalle_thumbnail_gen.MODEL}'


# === cache purge endpoint ===

def test_cache_purge_url_has_trailing_slash():
    """101c1d3事案: /api/revalidate/ (trailing slash) でないと308"""
    src = open('/home/aiuser/kpop-ai-system/lib/frontend_cache.py').read()
    assert "/api/revalidate/'" in src, "trailing slash必須 (308 redirect回避)"


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
