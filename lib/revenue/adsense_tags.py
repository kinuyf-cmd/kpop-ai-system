#!/usr/bin/env python3
"""lib/revenue/adsense_tags.py — J-1 AdSenseタグ生成。

client id(ca-pub-XXXX)は config/revenue/revenue_settings.json または
環境変数 ADSENSE_CLIENT_ID から取得し、コードにハードコードしない。

配信(adsense_enabled())が False の間はタグを出力しない(空文字)。
本番化(Phase C-7)時にオーナーが client_id を設定し enabled=true にする。

Usage:
  python3 lib/revenue/adsense_tags.py head        # <head> 用ローダー
  python3 lib/revenue/adsense_tags.py in-article  # 記事内ユニット
  python3 lib/revenue/adsense_tags.py status      # 設定状況
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib.revenue import settings  # noqa: E402


def adsense_loader_tag() -> str:
    """<head> に入れる AdSense ローダー(auto ads 含む)。

    client id 未設定 or 配信無効なら空文字を返す(import/呼び出しは安全)。
    """
    client = settings.adsense_client_id()
    if not settings.adsense_enabled() or not client:
        return ""
    return (
        '<script async '
        f'src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={client}" '
        'crossorigin="anonymous"></script>'
    )


def adsense_in_article_unit(slot: str | None = None) -> str:
    """記事内ディスプレイ広告ユニット。slot 未指定なら config の in_article slot を使う。

    client id / slot 未設定 or 配信無効なら空文字。
    """
    client = settings.adsense_client_id()
    slot_id = (slot or settings.adsense_slot("in_article")).strip()
    if not settings.adsense_enabled() or not client or not slot_id:
        return ""
    return (
        '<div class="kpj-adsense kpj-adsense-in-article" style="margin:32px 0;text-align:center">\n'
        '  <ins class="adsbygoogle" style="display:block" '
        f'data-ad-client="{client}" data-ad-slot="{slot_id}" '
        'data-ad-format="fluid" data-ad-layout="in-article"></ins>\n'
        '  <script>(adsbygoogle = window.adsbygoogle || []).push({});</script>\n'
        "</div>"
    )


def adsense_display_unit(slot: str) -> str:
    """汎用レスポンシブディスプレイユニット。slot 必須。"""
    client = settings.adsense_client_id()
    slot = (slot or "").strip()
    if not settings.adsense_enabled() or not client or not slot:
        return ""
    return (
        '<div class="kpj-adsense" style="margin:24px 0;text-align:center">\n'
        '  <ins class="adsbygoogle" style="display:block" '
        f'data-ad-client="{client}" data-ad-slot="{slot}" '
        'data-ad-format="auto" data-full-width-responsive="true"></ins>\n'
        '  <script>(adsbygoogle = window.adsbygoogle || []).push({});</script>\n'
        "</div>"
    )


def status() -> dict:
    return {
        "adsense_enabled": settings.adsense_enabled(),
        "client_id_set": bool(settings.adsense_client_id()),
        "auto_ads": settings.adsense_auto_ads(),
        "in_article_slot_set": bool(settings.adsense_slot("in_article")),
        "loader_tag_active": bool(adsense_loader_tag()),
        "note": "本番化時に config/revenue/revenue_settings.json の adsense.client_id を設定し enabled=true にすると配信開始",
    }


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "status"
    if arg == "head":
        out = adsense_loader_tag()
        print(out if out else "[未設定] AdSense client_id 未設定または配信無効のためタグ出力なし")
    elif arg == "in-article":
        out = adsense_in_article_unit()
        print(out if out else "[未設定] AdSense client_id/slot 未設定または配信無効のためユニット出力なし")
    else:
        import json
        print(json.dumps(status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
