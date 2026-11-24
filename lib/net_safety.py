"""外部URL取得のSSRF対策(2026-11-24)。

ソースURL・og:image・リダイレクト先は外部(ニュースサイト/AIが拾ったURL)由来で、
内部アドレス(127.0.0.1・プライベートIP・169.254.169.254等)や file:// を指させうる。
  - is_public_http_url : http(s)のみ、解決先が全て公開IPのときTrue
  - safe_urlopen       : 最初のURLと「全てのリダイレクト先」を検査して開く
既知の限界: 名前解決→接続の間にDNSを差し替える攻撃(DNS rebinding)は防げない。
"""
import ipaddress
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse


def is_public_http_url(u) -> bool:
    try:
        pu = urlparse(str(u).strip())
        if pu.scheme not in ("http", "https") or not pu.hostname:
            return False
        infos = socket.getaddrinfo(pu.hostname, pu.port or (443 if pu.scheme == "https" else 80))
        return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)
    except (OSError, ValueError):
        return False


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_public_http_url(newurl):
            raise urllib.error.URLError(f"blocked redirect to non-public URL: {newurl[:80]}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_CheckedRedirect)


def safe_urlopen(req, timeout=20):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if not is_public_http_url(url):
        raise urllib.error.URLError(f"blocked non-public URL: {url[:80]}")
    return _OPENER.open(req, timeout=timeout)
