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


def _reload_with_env(env_overrides, clear_config=False):
    """env を差し替えて revenue モジュール群を reload し、(settings, adsense, ga4) を返す。

    clear_config=True のとき、reload 後に settings._CFG を空 dict に上書きして
    config/revenue/revenue_settings.json の値を無効化する。本番化済み(config に
    実 client_id/measurement_id 投入済み)の現状でも「本番化前=env も config も
    未設定」を純粋に再現するため(2026-05-25: config 実IDで誤失敗していた事案)。
    """
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
        if clear_config:
            s._CFG = {}
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
        }, clear_config=True)
        assert at.adsense_loader_tag() == ""
        assert at.adsense_in_article_unit() == ""

    def test_ga4_empty_when_no_measurement_id(self):
        _, _, ga = _reload_with_env({"GA4_MEASUREMENT_ID": None}, clear_config=True)
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


class TestTerminatedProgramsExcluded:
    """提携終了した A8 案件が CTA 選定に混ざらない。

    2026-08-03: DHOLIC/NUGU/カラパラ007 の終了後もリンクが残り、
    A8 で無効クリックが発生した。status/end_date による除外を恒久ガードとする。
    """

    TERMINATED = ("dholic_fashion", "nugu_fashion", "karapara007")

    def test_master_marks_terminated_programs(self):
        from lib.revenue import genre_classifier as gc
        raw = gc.load_a8_master_raw()
        for key in self.TERMINATED:
            assert raw["programs"][key].get("status") == "terminated", key

    def test_load_a8_master_filters_terminated(self):
        from lib.revenue import genre_classifier as gc
        progs = gc.load_a8_master().get("programs", {})
        for key in self.TERMINATED:
            assert key not in progs, f"{key} が除外されていない"
        assert len(progs) > 0, "全件除外は誤り"

    def test_programs_by_category_excludes_terminated(self):
        from lib.revenue import genre_classifier as gc
        keys = {p["key"] for p in gc.programs_by_category("korean_fashion")}
        assert keys, "稼働案件が残っているはず"
        assert not keys & set(self.TERMINATED)

    def test_category_matrix_excludes_terminated(self):
        from lib.revenue import genre_classifier as gc
        allkeys = {k for v in gc.category_matrix().values() for k in v}
        assert not allkeys & set(self.TERMINATED)

    def test_is_active_helper(self):
        from lib.revenue import genre_classifier as gc
        assert gc.is_active_program({}) is True
        assert gc.is_active_program({"status": "active"}) is True
        assert gc.is_active_program({"status": "terminated"}) is False
        # end_date 経過も終了扱い
        assert gc.is_active_program({"end_date": "2020-01-01"}) is False
        assert gc.is_active_program({"end_date": "2999-12-31"}) is True

    def test_affiliate_manager_blocks_terminated(self):
        import lib.affiliate_manager as am
        for key in self.TERMINATED:
            assert am.build_a8_link(key) is None, key

    def _injector(self):
        import importlib.util
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location(
            "npi", root / "cta" / "new_post_injector.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_banner_loader_excludes_terminated(self):
        m = self._injector()
        assert "dholic" not in m.load_banners()
        assert len(m.load_banners()) > 0

    def test_banner_html_empty_for_terminated(self):
        """終了案件を明示指定しても HTML を組まない(KeyError も出さない)。"""
        m = self._injector()
        banners = dict(m.load_banners())
        banners["dholic"] = {"name": "DHOLIC", "status": "terminated",
                             "button_text": "x"}  # sizes キー自体が無い
        for pos in ("position_top", "position_middle", "position_bottom"):
            assert m.build_hybrid_html("dholic", pos, banners,
                                       m.load_templates()) == ""

    def test_banner_html_still_works_for_active(self):
        m = self._injector()
        banners = m.load_banners()
        key = next(k for k, v in banners.items() if v.get("sizes"))
        out = m.build_hybrid_html(key, "position_middle", banners,
                                  m.load_templates())
        assert isinstance(out, str)


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
