"""M2 J 収益化モジュールのユニットテスト

lib/revenue/ (adsense_tags / ga4_events / genre_classifier / settings) を検証。
本番化(Phase C-7)前後の切替が設計どおり機能するかを env で再現する。

設計の要点:
- 配信無効(本番化前)はタグが空文字 → サイトに広告/計測が出ない
- client_id/measurement_id + enabled が揃って初めてタグ出力(本番化後)
- 機密(client_id 等)はコードにハードコードせず env/config 経由
"""
import importlib
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REVENUE = ROOT / "lib" / "revenue"


def _reload_with_env(env_overrides):
    """env を差し替えて revenue モジュール群を reload し、(settings, adsense, ga4) を返す。"""
    saved = {}
    for k, v in env_overrides.items():
        saved[k] = os.environ.get(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        from lib.revenue import settings as s
        importlib.reload(s)
        from lib.revenue import adsense_tags as at, ga4_events as ga
        importlib.reload(at)
        importlib.reload(ga)
        return s, at, ga
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestModulesImport:
    def test_all_modules_import(self):
        from lib.revenue import adsense_tags, ga4_events, genre_classifier, settings  # noqa
        assert True


class TestDeliveryDisabledByDefault:
    """本番化前: client_id/enabled 未設定なら全タグが空(広告・計測を出さない)。"""

    def test_adsense_empty_when_disabled(self):
        _, at, _ = _reload_with_env({
            "ADSENSE_CLIENT_ID": None, "ADSENSE_ENABLED": None,
            "REVENUE_DELIVERY_ENABLED": None,
        })
        assert at.adsense_loader_tag() == ""
        assert at.adsense_in_article_unit() == ""

    def test_ga4_empty_when_no_measurement_id(self):
        _, _, ga = _reload_with_env({"GA4_MEASUREMENT_ID": None})
        assert ga.gtag_loader_tag() == ""


class TestDeliveryEnabled:
    """本番化後: フラグが揃うと正しいタグを出力。"""

    def test_adsense_loader_emitted(self):
        _, at, _ = _reload_with_env({
            "ADSENSE_CLIENT_ID": "ca-pub-0000000000000000",
            "ADSENSE_ENABLED": "1",
        })
        tag = at.adsense_loader_tag()
        assert "adsbygoogle.js" in tag
        assert "ca-pub-0000000000000000" in tag

    def test_ga4_loader_emitted(self):
        _, _, ga = _reload_with_env({"GA4_MEASUREMENT_ID": "G-TESTID0000"})
        tag = ga.gtag_loader_tag()
        assert "googletagmanager.com/gtag/js" in tag
        assert "G-TESTID0000" in tag

    def test_adsense_in_article_needs_slot(self):
        # client+enabled でも slot 未設定なら空(誤配置防止)
        _, at, _ = _reload_with_env({
            "ADSENSE_CLIENT_ID": "ca-pub-0000000000000000",
            "ADSENSE_ENABLED": "1",
        })
        assert at.adsense_in_article_unit(slot="") == ""
        assert "data-ad-slot=\"1234567890\"" in at.adsense_in_article_unit(slot="1234567890")


class TestGenreClassifier:
    def test_classify_returns_known_genre(self):
        from lib.revenue import genre_classifier as gc
        assert gc.classify_genre("韓国ソウルのカフェ巡りガイド") == "korea_travel"

    def test_classify_falls_back_to_default(self):
        from lib.revenue import genre_classifier as gc
        # ジャンル手がかりの無いタイトルは default
        assert gc.classify_genre("xyzzy") == "default"

    def test_select_programs_returns_positions(self):
        # select_programs は {genre, positions:{position_top/middle/bottom}} を返す
        from lib.revenue import genre_classifier as gc
        progs = gc.select_programs("BTSカムバック")
        assert isinstance(progs, dict)
        assert "genre" in progs and "positions" in progs
        assert any(p.startswith("position_") for p in progs["positions"])

    def test_category_matrix_nonempty(self):
        from lib.revenue import genre_classifier as gc
        assert len(gc.category_matrix()) > 0


class TestNoHardcodedSecrets:
    """機密(client_id 実値 / token)がコードに直書きされていない。"""

    def test_no_real_pub_id_in_source(self):
        # ca-pub- の後に実数字16桁が直書きされていない(ダミー0000は許容)
        pat = re.compile(r"ca-pub-(?!0000)\d{16}")
        for py in REVENUE.glob("*.py"):
            assert not pat.search(py.read_text(encoding="utf-8")), f"hardcoded pub id in {py.name}"

    def test_secrets_read_from_env(self):
        src = (REVENUE / "settings.py").read_text(encoding="utf-8")
        assert "os.environ" in src or "getenv" in src


class TestSyntaxValid:
    def test_all_py_compile(self):
        for py in REVENUE.glob("*.py"):
            r = subprocess.run(["python3", "-m", "py_compile", str(py)],
                               capture_output=True, text=True)
            assert r.returncode == 0, f"{py.name}: {r.stderr}"
