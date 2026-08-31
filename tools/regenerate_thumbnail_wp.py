#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""regenerate_thumbnail_wp.py — 記事のアイキャッチを生成し直して差し替える。

復元の経緯 (2026-08-31):
  post_publish_enricher はサムネ品質違反(dark_bg 等)を検出すると
  本スクリプトを subprocess で呼び、失敗したら記事を **draft 化**する。
  ところが本スクリプトは **存在しなかった**(VPS事故で消失したまま)。
  呼び出しは必ず FileNotFoundError となり再生成は 100% 失敗、
  **126件が機械的に非公開**にされていた(うち 122件が dark_bg)。
  日次13本公開に対し1〜3本＝公開数の約15%の損失。
  [[tests-are-spec-for-lost-code]] の方針通り、呼び出し側の契約から復元した。

呼び出し側との契約(壊すと再び静かに draft 化される):
  - 引数は post_id ひとつ
  - 成功時に stdout へ `featured_media: OK` を出す(enricher は文字列一致で判定)

  python3 tools/regenerate_thumbnail_wp.py 18833
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

WP_DOMAIN = "https://www.kpopjournal.tokyo"
WP_AUTH_FILE = Path.home() / ".wp_auth"

# unified_publisher と同じ一覧(サムネの画作りを揃えるため)
KNOWN_GROUPS = [
    'BTS', 'BLACKPINK', 'TWICE', 'aespa', 'NewJeans', 'IVE',
    'LE SSERAFIM', 'Stray Kids', 'SEVENTEEN', 'ENHYPEN', 'NMIXX',
    'ITZY', 'TXT', 'EXO', '2PM', 'BABYMONSTER', 'RIIZE', 'ILLIT',
    'NCT', 'Red Velvet', 'BIGBANG', 'SHINee', 'GOT7', 'ASTRO',
]


def _wp_headers() -> dict:
    if WP_AUTH_FILE.exists():
        for line in WP_AUTH_FILE.read_text().splitlines():
            if line.strip().startswith("header"):
                val = line.split("=", 1)[1].strip().strip('"')
                if ":" in val:
                    k, v = val.split(":", 1)
                    return {k.strip(): v.strip()}
    return {}


def artist_hint(title: str):
    """タイトルから既知グループ名を拾う。無ければ None。"""
    low = (title or "").lower()
    for g in KNOWN_GROUPS:
        if g.lower() in low:
            return g
    return None


def build_prompt(title: str) -> str:
    """生成プロンプト。

    再生成の理由は実測で 97%(122/126) が dark_bg。
    暗い画を作り直しても同じゲートで弾かれるだけなので、
    **明るさを明示的に要求する**。text_band 対策で文字も禁じる。
    """
    hint = artist_hint(title)
    who = f"related to K-pop group {hint}. " if hint else ""
    return (
        f"A professional editorial thumbnail image for a K-pop article titled '{title}'. "
        f"{who}"
        "Bright, well-lit, high-key lighting with a light airy background. "
        "Modern, vibrant, magazine-quality illustration with Korean pop culture aesthetic, "
        "1200x675 aspect ratio. "
        "No text overlay, no letters, no watermarks. "
        "Abstract artistic representation that matches the article theme."
    )


def fetch_post(post_id):
    """記事の最小情報を取る。取れなければ None。"""
    try:
        import requests
        r = requests.get(
            f"{WP_DOMAIN}/wp-json/wp/v2/posts/{post_id}",
            params={"_fields": "id,title", "context": "edit"},
            headers=_wp_headers(), timeout=15)
        if r.status_code != 200:
            print(f"[error] 記事取得失敗 HTTP {r.status_code}")
            return None
        d = r.json()
        t = d.get("title")
        title = t.get("raw") or t.get("rendered") if isinstance(t, dict) else str(t or "")
        return {"id": d.get("id"), "title": title}
    except Exception as e:
        print(f"[error] 記事取得例外: {type(e).__name__}: {str(e)[:80]}")
        return None


def generate(title: str, out_path: str) -> bool:
    """DALL-E で生成し 1200x675 に整えて out_path に置く。"""
    try:
        from lib.dalle_thumbnail_gen import generate_thumbnail
        from lib.image_utils import aspect_preserve_resize
    except Exception as e:
        print(f"[error] 生成モジュール読込失敗: {e}")
        return False

    with tempfile.TemporaryDirectory(prefix="regen_thumb_") as td:
        raw = os.path.join(td, "raw.jpg")
        r = generate_thumbnail(prompt=build_prompt(title), output_path=raw,
                               size="1792x1024", quality="standard")
        if not r.get("success") or not os.path.exists(raw):
            print(f"[error] DALL-E生成失敗: {r.get('reason', '?')}")
            return False
        # 1200px 未満はモバイルCTRが半減するため必ずこの寸法に揃える
        # ([[thumbnail-resolution-1200px-gate]])
        if not aspect_preserve_resize(raw, out_path):
            print("[error] リサイズ失敗")
            return False
    return os.path.exists(out_path)


def upload_and_attach(post_id, image_path: str, alt: str):
    """WPへアップロードし featured_media に設定。media_id か None。

    アップロードは unified_publisher の _upload_media に委譲する。
    ここには公開前 gate(不正サムネ拒否)と 413 対策の 1200px 縮小が入っており
    ([[upload-413-falls-back-to-dalle]])、経路を分けると両方を取りこぼす。
    """
    try:
        import requests
        from lib.unified_publisher import _upload_media
        media_id = _upload_media(image_path, alt_text=alt)
        if not media_id:
            print("[error] メディアアップロード失敗(gateで拒否された可能性)")
            return None
        r = requests.post(f"{WP_DOMAIN}/wp-json/wp/v2/posts/{post_id}",
                          headers=_wp_headers(),
                          json={"featured_media": media_id}, timeout=20)
        if r.status_code not in (200, 201):
            print(f"[error] featured_media設定失敗 HTTP {r.status_code}")
            return None
        return media_id
    except Exception as e:
        print(f"[error] アップロード例外: {type(e).__name__}: {str(e)[:80]}")
        return None


def regenerate(post_id) -> int:
    post = fetch_post(post_id)
    if not post:
        return 1
    title = post.get("title") or ""
    with tempfile.TemporaryDirectory(prefix="regen_out_") as td:
        out = os.path.join(td, "thumb.jpg")
        if not generate(title, out):
            return 1
        media_id = upload_and_attach(post_id, out, f"{title}のサムネイル画像")
        if not media_id:
            return 1
    # enricher はこの文字列一致で成否を見る。表記を変えないこと。
    print(f"featured_media: OK (media_id={media_id}, post={post_id})")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("usage: regenerate_thumbnail_wp.py <post_id>", file=sys.stderr)
        raise SystemExit(2)
    return regenerate(int(argv[0]))


if __name__ == "__main__":
    sys.exit(main())
