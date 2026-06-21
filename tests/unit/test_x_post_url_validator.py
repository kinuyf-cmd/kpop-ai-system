"""x_post_url_validator の純粋ロジック + HTTP分岐の回帰テスト。

実ネットワークは叩かない。requests.get / requests.head は mock し、
validate_url / validate_ogp_image / has_japanese_in_slug の挙動を
ソース実装(lib/x_post_url_validator.py)どおりに固定する。

対象: X投稿前の URL 事前検証(soft-404 / 日本語slug / OGP / og-default 検出)。
"""
from unittest import mock

from lib.x_post_url_validator import (
    has_japanese_in_slug,
    validate_ogp_image,
    validate_url,
)

VALID_OG = '<meta property="og:image" content="https://www.kpopjournal.tokyo/wp-content/uploads/thumb.jpg">'


def _resp(status=200, body="", headers=None):
    """requests レスポンス風の mock を作る。"""
    r = mock.Mock()
    r.status_code = status
    r.text = body
    r.headers = headers or {}
    return r


# ─── has_japanese_in_slug ────────────────────────────────────────────────
class TestHasJapaneseInSlug:
    def test_ascii_slug_is_clean(self):
        assert has_japanese_in_slug("https://www.kpopjournal.tokyo/golden-analysis/") is False

    def test_japanese_slug_detected(self):
        assert has_japanese_in_slug("https://www.kpopjournal.tokyo/速報-記事/") is True

    def test_percent_encoded_japanese_detected(self):
        # %E9%80%9F%E5%A0%B1 = 「速報」。unquote 後に検出される。
        url = "https://www.kpopjournal.tokyo/%E9%80%9F%E5%A0%B1/"
        assert has_japanese_in_slug(url) is True

    def test_trailing_slash_does_not_matter(self):
        assert has_japanese_in_slug("https://www.kpopjournal.tokyo/clean-slug") is False


# ─── validate_url のガード節(HTTP前に弾く) ───────────────────────────────
class TestValidateUrlGuards:
    def test_empty_url_rejected(self):
        r = validate_url("")
        assert r["ok"] is False and r["status"] == 0 and r["reason"] == "URL未設定"

    def test_placeholder_url_rejected(self):
        assert validate_url("（URL取得失敗）")["ok"] is False
        assert validate_url("（投稿失敗）")["ok"] is False

    def test_japanese_slug_rejected_before_http(self):
        r = validate_url("https://www.kpopjournal.tokyo/速報/")
        assert r["ok"] is False
        assert "日本語slug" in r["reason"]

    def test_off_domain_rejected(self):
        r = validate_url("https://example.com/some-article/")
        assert r["ok"] is False and r["reason"] == "対象ドメイン外"


# ─── validate_url の HTTP 分岐(mock) ─────────────────────────────────────
class TestValidateUrlHttp:
    URL = "https://www.kpopjournal.tokyo/some-slug/"

    def test_404_rejected(self):
        with mock.patch("lib.x_post_url_validator.requests.get",
                        return_value=_resp(status=404)):
            r = validate_url(self.URL)
        assert r["ok"] is False and r["status"] == 404

    def test_non_200_rejected(self):
        with mock.patch("lib.x_post_url_validator.requests.get",
                        return_value=_resp(status=500)):
            r = validate_url(self.URL)
        assert r["ok"] is False and r["status"] == 500

    def test_soft_404_detected(self):
        body = "<html><body>記事が見つかりません</body></html>"
        with mock.patch("lib.x_post_url_validator.requests.get",
                        return_value=_resp(status=200, body=body)):
            r = validate_url(self.URL)
        assert r["ok"] is False and r["status"] == 200
        assert "soft-404" in r["reason"]

    def test_timeout_handled(self):
        import requests as _rq
        with mock.patch("lib.x_post_url_validator.requests.get",
                        side_effect=_rq.Timeout()):
            r = validate_url(self.URL)
        assert r["ok"] is False and r["reason"] == "タイムアウト"

    def test_connection_error_handled(self):
        with mock.patch("lib.x_post_url_validator.requests.get",
                        side_effect=RuntimeError("boom")):
            r = validate_url(self.URL)
        assert r["ok"] is False and r["status"] == 0
        assert "接続エラー" in r["reason"]

    def test_happy_path_ok(self):
        body = f"<html><head>{VALID_OG}</head><body>記事本文</body></html>"
        # og:image HEAD は十分大きいサイズで 200 を返す
        head_ok = _resp(status=200, headers={"Content-Length": "200000"})
        with mock.patch("lib.x_post_url_validator.requests.get",
                        return_value=_resp(status=200, body=body)), \
             mock.patch("lib.x_post_url_validator.requests.head",
                        return_value=head_ok):
            r = validate_url(self.URL)
        assert r["ok"] is True and r["status"] == 200
        assert r["og_image"].endswith("thumb.jpg")

    def test_ogp_problem_blocks_even_on_200(self):
        # 本文200・soft-404なしだが og:image が無い → OGP問題で NG
        body = "<html><head></head><body>記事本文</body></html>"
        with mock.patch("lib.x_post_url_validator.requests.get",
                        return_value=_resp(status=200, body=body)):
            r = validate_url(self.URL)
        assert r["ok"] is False and r["status"] == 200
        assert "OGP問題" in r["reason"]


# ─── validate_ogp_image(HTML文字列 + HEAD mock) ──────────────────────────
class TestValidateOgpImage:
    PAGE = "https://www.kpopjournal.tokyo/some-slug/"

    def test_missing_og_image(self):
        r = validate_ogp_image("<html><head></head></html>", self.PAGE)
        assert r["ok"] is False and "存在しない" in r["reason"]

    def test_attr_order_reversed_is_supported(self):
        # content が先・property が後でも抽出できる(2つ目の正規表現)
        html = '<meta content="https://www.kpopjournal.tokyo/x/thumb.jpg" property="og:image">'
        with mock.patch("lib.x_post_url_validator.requests.head",
                        return_value=_resp(status=200, headers={"Content-Length": "150000"})):
            r = validate_ogp_image(html, self.PAGE)
        assert r["ok"] is True

    def test_og_default_rejected(self):
        html = '<meta property="og:image" content="https://www.kpopjournal.tokyo/og-default.png">'
        with mock.patch("lib.x_post_url_validator.requests.head",
                        return_value=_resp(status=200, headers={"Content-Length": "150000"})):
            r = validate_ogp_image(html, self.PAGE)
        assert r["ok"] is False and "og-default" in r["reason"]

    def test_tiny_image_rejected_as_placeholder(self):
        with mock.patch("lib.x_post_url_validator.requests.head",
                        return_value=_resp(status=200, headers={"Content-Length": "5000"})):
            r = validate_ogp_image(VALID_OG, self.PAGE)
        assert r["ok"] is False and "極小" in r["reason"]

    def test_image_http_error_rejected(self):
        with mock.patch("lib.x_post_url_validator.requests.head",
                        return_value=_resp(status=403, headers={})):
            r = validate_ogp_image(VALID_OG, self.PAGE)
        assert r["ok"] is False and "HTTP 403" in r["reason"]
