"""N-4 webapp-testing 統合: 本番(www.kpopjournal.tokyo)スモークテスト

2026-05-22 の cutover で実体が stg(Basic認証付き)→ www(公開)へ移行したため、
既定の検証先を本番 www に更新(旧 stg を叩き続けて全 401 になる陳腐化を解消)。
検証先は環境変数 KPOP_E2E_HOST で上書き可能(stg等を叩きたい場合)。
本番は公開済みのため Basic 認証は不要。stg を指す場合のみ /tmp/wp_stg.txt から
認証を読む(後方互換)。

KPOP_E2E_ENABLE=1 を渡したときだけ実 HTTP 接続する(従来どおり)。

このスモークは popup サイドバーの「ポップアップ一覧」空 href 不具合
(get_cat_ID 誤用、2026-05-25 修正)と広告ページ /advertise/ の再発防止も兼ねる。
"""
import os
import re
import subprocess
from pathlib import Path

import pytest


# cutover 後の本番ホスト。KPOP_E2E_HOST で上書き可(例: stg.kpopjournal.tokyo)
E2E_HOST = os.environ.get("KPOP_E2E_HOST", "www.kpopjournal.tokyo")
E2E_BASE = f"https://{E2E_HOST}"
IS_STG = "stg." in E2E_HOST  # stg を指すときだけ Basic 認証を使う

E2E_ENABLED = os.environ.get("KPOP_E2E_ENABLE", "0") == "1"
SKIP_REASON = "set KPOP_E2E_ENABLE=1 to run E2E HTTP tests"


def _get_basic_auth():
    """stg を指すときのみ /tmp/wp_stg.txt から Basic 認証 user:pass を取り出す。
    本番(www)は公開済みのため認証不要 → None を返す。"""
    if not IS_STG:
        return None
    p = Path("/tmp/wp_stg.txt")
    if not p.exists():
        return None
    user, pw = None, None
    for line in p.read_text().splitlines():
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        if k == "BASIC_USER":
            user = v
        elif k == "BASIC_PASS":
            pw = v
    if user and pw:
        return f"{user}:{pw}"
    return None


def _curl(url, basic_auth=None, max_time=20):
    """curl で URL を叩き、(http_code, body) を返す"""
    cmd = ["curl", "-s", "-o", "-", "-w", "\n__HTTP_CODE__:%{http_code}",
           "-A", "Mozilla/5.0 kpop-e2e", "--max-time", str(max_time)]
    if basic_auth:
        cmd.extend(["-u", basic_auth])
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=max_time + 5)
    out = result.stdout
    m = re.search(r"__HTTP_CODE__:(\d+)$", out)
    code = int(m.group(1)) if m else 0
    body = out[: m.start()] if m else out
    return code, body


@pytest.mark.skipif(not E2E_ENABLED, reason=SKIP_REASON)
class TestSiteSmoke:
    """主要ページの HTTP 200 確認"""

    def test_top_page_200(self):
        code, _ = _curl(E2E_BASE + "/", basic_auth=_get_basic_auth())
        assert code == 200, f"top page returned {code}"

    def test_artists_page_200(self):
        code, _ = _curl(E2E_BASE + "/artists/", basic_auth=_get_basic_auth())
        assert code == 200, f"artists page returned {code}"

    def test_events_archive_200(self):
        code, _ = _curl(E2E_BASE + "/events/", basic_auth=_get_basic_auth())
        assert code == 200, f"events archive returned {code}"

    def test_popup_category_200(self):
        code, _ = _curl(E2E_BASE + "/category/popup/", basic_auth=_get_basic_auth())
        assert code == 200, f"popup category returned {code}"

    def test_advertise_page_200(self):
        """広告掲載ページ(2026-05-25 追加)が公開され 200 を返すこと"""
        code, _ = _curl(E2E_BASE + "/advertise/", basic_auth=_get_basic_auth())
        assert code == 200, f"advertise page returned {code}"


@pytest.mark.skipif(not E2E_ENABLED, reason=SKIP_REASON)
class TestSiteContent:
    """最低限のコンテンツ・今回修正分の再発防止チェック"""

    def test_top_contains_kpopjournal(self):
        code, body = _curl(E2E_BASE + "/", basic_auth=_get_basic_auth())
        assert code == 200
        assert "KPOP" in body.upper() or "<html" in body.lower()

    def test_popup_category_has_cards(self):
        """popup 一覧にカードが描画されていること(category-popup.php 健全性)"""
        code, body = _curl(E2E_BASE + "/category/popup/", basic_auth=_get_basic_auth())
        assert code == 200
        assert "popup-card" in body, "popup 一覧にカードが無い(テンプレ異常の疑い)"

    def test_advertise_has_form(self):
        """広告ページに問い合わせフォームが出ていること"""
        code, body = _curl(E2E_BASE + "/advertise/", basic_auth=_get_basic_auth())
        assert code == 200
        assert "kpop-advertise-form" in body, "広告ページにフォームが無い(KSES除去等の疑い)"

    def test_popup_sidebar_list_link_not_empty(self):
        """【再発防止】popup 詳細サイドバーの「ポップアップ一覧」リンクが
        空 href でないこと。get_cat_ID('popup') 誤用で href="" になった
        2026-05-25 の不具合の回帰検知。popup 詳細記事を 1 本叩いて確認する。"""
        # popup_area を持つ実 popup 記事(popup- prefix の代表 slug)
        popup_slug = os.environ.get(
            "KPOP_E2E_POPUP_SLUG",
            "popup-niceghostclub-cowboybebop-collab-seongsu-pop",
        )
        code, body = _curl(E2E_BASE + f"/{popup_slug}/", basic_auth=_get_basic_auth())
        assert code == 200, f"popup 詳細記事が {code}"
        # サイドナビが存在し、見出しリンクの href が空でないこと
        assert "kpop-popup-sidenav" in body, "popup サイドナビが描画されていない"
        m = re.search(r'kpop-popup-sidenav-heading"><a href="([^"]*)"', body)
        assert m is not None, "「ポップアップ一覧」リンクが見つからない"
        href = m.group(1)
        assert href.strip() != "", "「ポップアップ一覧」リンクの href が空(回帰)"
        assert "/category/popup/" in href, f"一覧リンクが想定URLでない: {href}"
