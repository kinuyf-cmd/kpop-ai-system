import urllib.error

import pytest

from lib import net_safety as N


@pytest.mark.parametrize("u", ["file:///etc/passwd", "http://127.0.0.1/x", "http://169.254.169.254/latest",
                               "http://10.0.0.5/", "http://[::1]/", "ftp://example.com/", "http://localhost/", ""])
def test_rejects_non_public(u):
    assert not N.is_public_http_url(u)


def test_safe_urlopen_blocks_internal():
    with pytest.raises(urllib.error.URLError):
        N.safe_urlopen(__import__("urllib.request").request.Request("http://127.0.0.1:9/"))


def test_redirect_to_internal_is_blocked(monkeypatch):
    h = N._CheckedRedirect()
    req = __import__("urllib.request").request.Request("http://example.com/")
    monkeypatch.setattr(N, "is_public_http_url", lambda u: "169.254" not in u)
    with pytest.raises(urllib.error.URLError):
        h.redirect_request(req, None, 302, "Found", {}, "http://169.254.169.254/latest/meta-data")
