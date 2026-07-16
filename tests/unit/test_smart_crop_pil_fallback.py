"""smart_crop の PIL フォールバック単体テスト(2026-07-16)

cv2(OpenCV)未インストール環境では smart_crop が ImportError を
except で握って return False していたため、縦長 og:image が横長化されず
letterbox 判定で REJECT → hallyu 経路は DALL-E 降格せず no_thumbnail BLOCK
になっていた(公開率低下の一因)。

cv2 が使えないときは PIL 版 aspect_preserve_resize(中央 crop)にフォールバックし、
縦長画像を横長サムネ枠へ crop できることを検証する。
"""
import sys
import builtins
from PIL import Image
from lib import thumbnail_resolver


def _make_portrait(path, w=650, h=898):
    """縦長のダミー画像を生成(letterbox 化しやすい 650x898)。"""
    im = Image.new("RGB", (w, h), (120, 90, 60))
    # 中央に色差を入れて単色 too_small 弾きを避ける
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            im.putpixel((x, y), ((x * 3) % 256, (y * 5) % 256, 90))
    im.save(path, "JPEG", quality=90)


def test_smart_crop_falls_back_to_pil_when_cv2_missing(tmp_path, monkeypatch):
    """cv2 が import できなくても縦長→横長 crop が成功し True を返す。"""
    p = tmp_path / "portrait.jpg"
    _make_portrait(str(p))

    # cv2 の import を強制的に失敗させる(未インストール環境を再現)
    real_import = builtins.__import__

    def _no_cv2(name, *args, **kwargs):
        if name == "cv2":
            raise ImportError("No module named 'cv2'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_cv2)

    ok = thumbnail_resolver.smart_crop(str(p), target_w=1200, target_h=675)
    assert ok is True, "cv2 欠落時に PIL フォールバックで True を返すべき"

    # 横長(16:9 近似)に変換されている
    with Image.open(str(p)) as out:
        w, h = out.size
    assert w > h, f"縦長のまま: {w}x{h}"
    assert abs(w / h - 1200 / 675) < 0.02, f"16:9 になっていない: {w}x{h}"
