#!/usr/bin/env python3
"""日本語ファイル名のサムネイルを probe() が取得できること。

2026-08-23: 解像度スキャンが14件を 0x0(取得失敗)と報告していたが、
実際は全て日本語ファイル名で、URLエンコードせずにリクエストしていたのが原因。
「取得失敗」と「本当に1200px未満」が混ざり、実寸法が分からなくなっていた。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from lib.thumbnail_resolution_scan import build_image_url, UPLOADS


class TestBuildImageUrl:
    def test_ascii_path_is_unchanged(self):
        assert build_image_url("2026/08/og-default-20260821.jpg") == \
            UPLOADS + "2026/08/og-default-20260821.jpg"

    def test_japanese_filename_is_percent_encoded(self):
        u = build_image_url("2026/05/名称未設定のデザイン-6-2.png")
        assert "名称" not in u
        assert u.startswith(UPLOADS)
        assert "%" in u

    def test_slashes_are_preserved(self):
        u = build_image_url("2026/06/名称未設定のデザイン.jpg")
        assert u.count("/") >= UPLOADS.count("/") + 2

    def test_not_double_encoded(self):
        """%E5... を再エンコードして %25E5 にしないこと。"""
        assert "%25" not in build_image_url("2026/05/名称未設定のデザイン-6-2.png")

    def test_spaces_are_encoded(self):
        assert " " not in build_image_url("2026/05/my file.png")
