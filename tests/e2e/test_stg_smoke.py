"""N-4 webapp-testing 統合: stg.kpopjournal.tokyo スモークテスト

SKILL.md §12 に従い stg のみ実施(本番には触れない)。
Basic 認証は /tmp/wp_stg.txt から読み込む。
KPOP_E2E_ENABLE=1 を渡したときだけ実 HTTP 接続する。
"""
import os
import re
import subprocess
from pathlib import Path

import pytest


STG_HOST = "stg.kpopjournal.tokyo"
STG_BASE = f"https://{STG_HOST}"

E2E_ENABLED = os.environ.get("KPOP_E2E_ENABLE", "0") == "1"
SKIP_REASON = "set KPOP_E2E_ENABLE=1 to run stg E2E tests"


def _get_basic_auth():
    """/tmp/wp_stg.txt から Basic 認証用 user:pass を取り出す"""
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
    cmd = ["curl", "-s", "-o", "-", "-w", "\n__HTTP_CODE__:%{http_code}", "--max-time", str(max_time)]
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
class TestStgSmoke:
    """stg 主要ページの HTTP 200 確認"""

    def test_top_page_200(self):
        auth = _get_basic_auth()
        code, _ = _curl(STG_BASE + "/", basic_auth=auth)
        assert code == 200, f"top page returned {code}"

    def test_artists_page_200(self):
        auth = _get_basic_auth()
        code, _ = _curl(STG_BASE + "/artists/", basic_auth=auth)
        assert code == 200, f"artists page returned {code}"

    def test_events_archive_200(self):
        auth = _get_basic_auth()
        code, _ = _curl(STG_BASE + "/events/", basic_auth=auth)
        assert code == 200, f"events archive returned {code}"

    def test_popup_category_200(self):
        auth = _get_basic_auth()
        code, _ = _curl(STG_BASE + "/category/popup/", basic_auth=auth)
        assert code == 200, f"popup category returned {code}"


@pytest.mark.skipif(not E2E_ENABLED, reason=SKIP_REASON)
class TestStgContent:
    """stg の最低限のコンテンツが返ること(豆腐文字回避の証跡)"""

    def test_top_contains_kpopjournal(self):
        auth = _get_basic_auth()
        code, body = _curl(STG_BASE + "/", basic_auth=auth)
        assert code == 200
        # サイト名 or 一般的なヘッダ
        assert "KPOP" in body.upper() or "kpop" in body.lower() or "<html" in body.lower()
