"""fetch_yesterday_metrics._append_history の回帰テスト。

GA4 PV の日次履歴が残らず PV/検索トレンドを追えなかった盲点の修正
(2026-06-22)を固定する。実API は叩かない。google.* 依存は import 時に
解決されるため stub してからモジュールをロードする(conftest が anthropic を
stub するのと同じ方式)。
"""
import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _stub(name):
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
    return sys.modules[name]


def _load_module():
    """google.* を stub して fetch_yesterday_metrics をロードする。"""
    # 必要な属性を持つダミーを用意(import 文が from ... import NAME 形式のため)
    for n in [
        "google", "google.oauth2", "google.oauth2.service_account",
        "google.oauth2.credentials", "google_auth_oauthlib",
        "google_auth_oauthlib.flow", "google.analytics",
        "google.analytics.data_v1beta", "google.analytics.data_v1beta.types",
        "googleapiclient", "googleapiclient.discovery",
        "google.auth", "google.auth.transport", "google.auth.transport.requests",
        "google.auth.exceptions",
    ]:
        _stub(n)
    # from X import Y で参照される名前にダミーを生やす
    sys.modules["google.oauth2.service_account"].Credentials = object
    sys.modules["google.oauth2.credentials"].Credentials = object
    sys.modules["google_auth_oauthlib.flow"].InstalledAppFlow = object
    sys.modules["google.analytics.data_v1beta"].BetaAnalyticsDataClient = object
    t = sys.modules["google.analytics.data_v1beta.types"]
    t.DateRange = t.Dimension = t.Metric = t.RunReportRequest = object
    sys.modules["googleapiclient.discovery"].build = lambda *a, **k: None
    sys.modules["google.auth.transport.requests"].Request = object
    sys.modules["google.auth.exceptions"].RefreshError = Exception

    path = ROOT / "google_metrics" / "fetch_yesterday_metrics.py"
    spec = importlib.util.spec_from_file_location("fym_under_test", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _read(hist):
    return [json.loads(l) for l in hist.read_text(encoding="utf-8").splitlines() if l.strip()]


class TestAppendHistory:
    def _setup(self, tmp_path):
        m = _load_module()
        m.BASE_DIR = str(tmp_path)
        return m, tmp_path / "metrics_history.jsonl"

    def test_first_append_creates_file(self, tmp_path):
        m, hist = self._setup(tmp_path)
        m._append_history({"date": "2026-06-20", "ga4": {"summary": {"pageviews": "116"}}})
        rows = _read(hist)
        assert len(rows) == 1 and rows[0]["date"] == "2026-06-20"

    def test_multiple_days_sorted(self, tmp_path):
        m, hist = self._setup(tmp_path)
        m._append_history({"date": "2026-06-21", "ga4": {}})
        m._append_history({"date": "2026-06-20", "ga4": {}})
        assert [r["date"] for r in _read(hist)] == ["2026-06-20", "2026-06-21"]

    def test_same_date_rerun_replaces(self, tmp_path):
        m, hist = self._setup(tmp_path)
        m._append_history({"date": "2026-06-20", "ga4": {"summary": {"pageviews": "116"}}})
        m._append_history({"date": "2026-06-20", "ga4": {"summary": {"pageviews": "999"}}})
        rows = _read(hist)
        assert len(rows) == 1
        assert rows[0]["ga4"]["summary"]["pageviews"] == "999"

    def test_corrupt_line_is_skipped(self, tmp_path):
        m, hist = self._setup(tmp_path)
        m._append_history({"date": "2026-06-20", "ga4": {}})
        hist.write_text(hist.read_text() + "NOT JSON\n", encoding="utf-8")
        m._append_history({"date": "2026-06-21", "ga4": {}})
        # 壊れた行は除外され、有効2日分のみ残る
        assert [r["date"] for r in _read(hist)] == ["2026-06-20", "2026-06-21"]

    def test_failure_is_swallowed(self, tmp_path, capsys):
        m, _ = self._setup(tmp_path)
        # BASE_DIR を書込不能なパスにしても例外を投げず警告のみ
        m.BASE_DIR = "/proc/nonexistent_dir_xyz"
        m._append_history({"date": "2026-06-20"})  # 例外が出ないこと
        assert "WARN" in capsys.readouterr().out
