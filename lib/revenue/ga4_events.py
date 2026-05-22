#!/usr/bin/env python3
"""lib/revenue/ga4_events.py — J-3 GA4イベント送信タグ。

measurement id(G-XXXX)は config/revenue/revenue_settings.json または
環境変数 GA4_MEASUREMENT_ID から取得し、ハードコードしない。

既存テーマ(Cocoon等)が gtag.js を読み込んでいる環境では gtag ローダーは不要。
その場合 measurement_id を空のままにすれば、ローダーは出力されず、
クリック計測JS(lib/ui_cta_tracker.build_cta_tracking_js)だけが使われる。

CTAクリック計測の本体JSは lib/ui_cta_tracker.py に既存(二重実装を避けるため再利用)。

Usage:
  python3 lib/revenue/ga4_events.py head     # gtag.js ローダー(measurement id があれば)
  python3 lib/revenue/ga4_events.py tracking # CTAクリック計測JS(ui_cta_tracker再利用)
  python3 lib/revenue/ga4_events.py status
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib.revenue import settings  # noqa: E402


def gtag_loader_tag() -> str:
    """gtag.js ローダー + 初期化。measurement id 未設定なら空文字。

    既存テーマに gtag があるなら measurement_id を空のままにして
    このローダーを出さない運用が推奨(二重ロード防止)。
    """
    mid = settings.ga4_measurement_id()
    if not mid:
        return ""
    return (
        f'<script async src="https://www.googletagmanager.com/gtag/js?id={mid}"></script>\n'
        "<script>\n"
        "  window.dataLayer = window.dataLayer || [];\n"
        "  function gtag(){dataLayer.push(arguments);}\n"
        "  gtag('js', new Date());\n"
        f"  gtag('config', '{mid}');\n"
        "</script>"
    )


def cta_tracking_js() -> str:
    """CTAクリック/表示計測JS。既存 ui_cta_tracker の実装を再利用(二重実装回避)。"""
    try:
        from lib.ui_cta_tracker import build_cta_tracking_js
        return build_cta_tracking_js()
    except Exception as e:  # フォールバック: 最小のクリック計測
        return _fallback_tracking_js(str(e))


def _fallback_tracking_js(reason: str = "") -> str:
    """ui_cta_tracker が import できない場合の最小フォールバック。"""
    return (
        f"<!-- GA4 CTA tracking (fallback: {reason}) -->\n"
        "<script>\n"
        "(function(){\n"
        "  if (typeof gtag !== 'function' && typeof dataLayer === 'undefined') return;\n"
        "  var g = (typeof gtag === 'function') ? gtag : function(){ (window.dataLayer=window.dataLayer||[]).push(arguments); };\n"
        "  document.querySelectorAll('.revenue-cta a, .cta-box a, .kpj-cta-btn').forEach(function(a){\n"
        "    a.addEventListener('click', function(){\n"
        "      g('event','cta_click',{page_path:location.pathname,cta_label:(a.textContent||'').trim().slice(0,50)});\n"
        "    });\n"
        "  });\n"
        "})();\n"
        "</script>"
    )


def status() -> dict:
    ui_ok = True
    try:
        from lib.ui_cta_tracker import build_cta_tracking_js  # noqa: F401
    except Exception:
        ui_ok = False
    return {
        "ga4_measurement_id_set": bool(settings.ga4_measurement_id()),
        "ga4_property_id_set": bool(settings.ga4_property_id()),
        "gtag_loader_active": bool(gtag_loader_tag()),
        "ui_cta_tracker_available": ui_ok,
        "note": "既存テーマにgtagがあれば measurement_id は空のままでOK(計測JSのみ使用)。AdSense独自ロードが要る場合のみ GA4_MEASUREMENT_ID を設定。",
    }


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "status"
    if arg == "head":
        out = gtag_loader_tag()
        print(out if out else "[未設定] GA4 measurement_id 未設定のため gtag ローダー出力なし(既存テーマのgtagを使用)")
    elif arg == "tracking":
        print(cta_tracking_js())
    else:
        import json
        print(json.dumps(status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
