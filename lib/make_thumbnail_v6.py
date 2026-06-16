#!/usr/bin/env python3
"""make_thumbnail_v6 — サムネ段階3(DALL-E生成)のオーケストレータ。

VPS事故(2026-05)で欠損した本モジュールを再建(2026-06-16)。
thumbnail_resolver.resolve_thumbnail の段階3が呼ぶ:
    from make_thumbnail_v6 import _dalle_fallback
    r = _dalle_fallback(title, body, post_id, output_dir, theme_dalle_prompt=...)
    if r.get('verdict') == 'PASS': use r['output_path']  # PNG

役割: 記事タイトル/本文から「安全な編集用プロンプト」を構築し、
gpt-image-1(lib.dalle_thumbnail_gen.generate_thumbnail)で生成する。

安全設計(肖像権・誤認回避。[[thumbnail-low-quality-og-and-403]] /
[[red-team-audit-4articles-20260525]] の実在アイドル誤画像事故を踏まえる):
- **実在人物の顔・肖像を描かせない**。topical/editorial な抽象表現に限定。
- 段階1(出典og)・段階2(本人写真Wikimedia)が取れなかった時のみ到達する最終手段。
"""
from __future__ import annotations
import os

try:
    from dalle_thumbnail_gen import generate_thumbnail
except Exception:  # pragma: no cover - import 経路差吸収
    from lib.dalle_thumbnail_gen import generate_thumbnail


def _build_prompt(title: str, body: str = "", theme_dalle_prompt: str = "") -> str:
    """記事から安全な英語の編集用画像プロンプトを構築する。

    実在人物の顔は描かない(no recognizable real people)。K-pop 記事の
    雰囲気を抽象的・編集的に表現する。テーマ別プロンプトがあれば織り込む。
    """
    title = (title or "").strip()
    base = (
        f"A professional editorial thumbnail image for a K-pop news article "
        f"titled '{title[:120]}'. Modern, vibrant, magazine-quality, clean "
        f"composition with stage lighting, music and concert atmosphere."
    )
    if theme_dalle_prompt:
        base += f" {theme_dalle_prompt.strip()}"
    # 肖像権・誤認回避: 実在アイドルの顔を描かせない明示指示。
    base += (
        " Do not depict any real, recognizable people or celebrity faces; "
        "use abstract, symbolic, or atmospheric imagery only."
    )
    return base


def _dalle_fallback(title: str, body: str = "", post_id=0,
                    output_dir: str = "/tmp", theme_dalle_prompt: str = "") -> dict:
    """段階3 本体。生成成功で {'verdict':'PASS','output_path':<png>}、
    失敗で {'verdict':'FAIL','reason':...} を返す(段階2までで写真が取れなかった時のみ)。
    """
    os.makedirs(output_dir, exist_ok=True)
    png_path = os.path.join(output_dir, f"dalle_post{post_id}.png")
    prompt = _build_prompt(title, body, theme_dalle_prompt)
    try:
        r = generate_thumbnail(prompt=prompt, output_path=png_path,
                               size="1792x1024", quality="standard")
    except Exception as e:
        return {"verdict": "FAIL", "reason": f"generate error: {e}"}
    if r.get("success") and r.get("path") and os.path.exists(r["path"]):
        return {"verdict": "PASS", "output_path": r["path"],
                "cost_usd": r.get("cost_usd", 0.0)}
    return {"verdict": "FAIL", "reason": r.get("reason", "unknown")}
