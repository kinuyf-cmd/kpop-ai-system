#!/usr/bin/env python3
"""画像処理 共通 util — アスペクト比保存リサイズ等

2026-05-15: lib/unified_publisher.py / pipeline/post_thumbnail_generator.py 等
複数箇所で `.resize((1200, 675))` を **アスペクト無視で直接実行**しており、
Instagram の portrait 写真 (1080x1350) や 1792x1024 DALL-E 出力が
1200x675 へ強制 stretch されて視認できるほど歪んでいた事故への根治。

Public API:
  aspect_preserve_resize(src_path: str, dst_path: str, target_w=1200, target_h=675,
                         quality=88) -> bool
"""
from __future__ import annotations
from PIL import Image


def aspect_preserve_resize(src_path: str, dst_path: str,
                           target_w: int = 1200, target_h: int = 675,
                           quality: int = 88) -> bool:
    """src 画像を target_w x target_h に「中心 crop → resize」して保存。
    アスペクト比を厳密に保ち、歪み (stretch) を発生させない。

    Algorithm:
      1. target_ratio = target_w / target_h を計算
      2. 元画像が横長過ぎる (cur_ratio > target_ratio) → 横を crop
      3. 元画像が縦長過ぎる (cur_ratio < target_ratio) → 縦を crop
      4. crop 後、target サイズへ LANCZOS resize (このとき crop で
         既にアスペクトが target に揃っているので stretch なし)
      5. RGB 変換 + JPEG quality で保存

    Returns:
        True if successful, False otherwise
    """
    try:
        with Image.open(src_path) as im:
            w, h = im.size
            if w <= 0 or h <= 0:
                return False
            target_ratio = target_w / target_h
            cur_ratio = w / h
            if cur_ratio > target_ratio:
                # 横長過ぎ → 中央の縦帯を残す
                new_w = int(round(h * target_ratio))
                x = (w - new_w) // 2
                im2 = im.crop((x, 0, x + new_w, h))
            elif cur_ratio < target_ratio:
                # 縦長過ぎ → 中央の横帯を残す
                new_h = int(round(w / target_ratio))
                y = (h - new_h) // 2
                im2 = im.crop((0, y, w, y + new_h))
            else:
                im2 = im.copy()
            im2 = im2.convert('RGB').resize((target_w, target_h), Image.LANCZOS)
            im2.save(dst_path, 'JPEG', quality=quality, optimize=True)
            return True
    except Exception:
        return False
