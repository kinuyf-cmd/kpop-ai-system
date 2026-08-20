"""サムネイルの解像度不足を検出できることを保証する。

2026-08-20 の発見:
  `鉄槌教師 声優一覧`(imp 15,460)のアイキャッチが 299x168px / 5.2KB だった。
  Google のモバイル検索・Discover で大きなサムネイルが表示される要件は
  幅1200px以上で、299px はそれを大きく下回るため画像付きの表示にならない。

  imp>=300 の50記事を全数測定したところ 22本が1200px未満で、
  同じ pos6-10 帯で層別しても CTR に約2倍の差があった:
      1200px未満 : imp 72,340 / CTR 4.13%
      1200px以上 : imp 14,611 / CTR 8.50%

  thumbnail_audit.py は解像度を一切検査していなかったため、
  299x168px が本番に残り続けていた。それを塞ぐ。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib.thumbnail_audit import check_resolution, MIN_THUMBNAIL_WIDTH


def test_min_width_is_1200():
    """Google推奨の1200px未満を不合格とする閾値であること。"""
    assert MIN_THUMBNAIL_WIDTH == 1200


def test_too_small_thumbnail_is_flagged():
    """実際に本番で見つかった 299x168 は不合格になること。"""
    r = check_resolution(299, 168)
    assert r["ok"] is False
    assert "1200" in r["issue"]


def test_borderline_below_threshold_is_flagged():
    """1024x576(相関図記事の実例)も1200px未満なので不合格。"""
    assert check_resolution(1024, 576)["ok"] is False


def test_sufficient_thumbnail_passes():
    assert check_resolution(1200, 675)["ok"] is True
    assert check_resolution(1920, 1080)["ok"] is True


def test_unknown_size_is_flagged_not_passed():
    """寸法が取得できなかった画像を「合格」にしてはいけない。

    明洞K-POPショップ記事(imp 1,233)は画像取得自体に失敗しており、
    ここを黙って通すと壊れたサムネイルが監査をすり抜ける。
    """
    r = check_resolution(0, 0)
    assert r["ok"] is False
