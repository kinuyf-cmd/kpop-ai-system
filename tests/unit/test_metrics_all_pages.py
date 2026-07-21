"""fetch_yesterday_metrics: 全ランディングページ/全クエリ取得の回帰テスト
(2026-07-21 修正: limit=10 固定による「上位10件を全体シェアと誤読」を根治)

背景:
  GA4 の top_landing_pages / GSC の top_pages・top_queries は limit=10 固定で、
  上位10件しか記録されていなかった。これを分母に「7記事で流入43.9%」と読む誤りが
  実際に起きた(実測では単日122ページ・5日集計429ページに流入があり、上位10件の
  シェアは34%でしかない)。

  修正方針は「既存キーは10件のまま据え置き、全件は別キーに持つ」。
  daily_brief_v2 と kpi_dashboard は top_pages を合算して「サイト全体のGSC指標」
  として報告しているため、件数を増やすと値が不連続に跳ねて前日比が壊れるから。

本テストの不変条件:
  1. top_* は all_* の先頭10件と完全一致(後方互換 = 合算値の連続性を守る)。
  2. 履歴(metrics_history.jsonl)には all_* を入れない。_append_history は全行を
     読み書きする実装で、1日67KB を積むと年24MB に肥大し日次 cron が重くなる。
  3. 件数(landing_page_count 等)は履歴に残す。後から「上位10件が全体の何%か」を
     検算できるようにするため。
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
    """google.* を stub して fetch_yesterday_metrics をロードする。

    test_metrics_history.py と同方式(実 API は叩かない)。
    """
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
    spec = importlib.util.spec_from_file_location("fym_all_pages_under_test", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _read(hist):
    return [json.loads(l) for l in hist.read_text(encoding="utf-8").splitlines() if l.strip()]


def _result_with_all_keys():
    """main() が組み立てる result 相当(all_* を含む)"""
    return {
        "date": "2026-07-18",
        "fetched_at": "2026-07-21",
        "ga4": {
            "summary": {"sessions": "289"},
            "top_landing_pages": [{"page": f"/p{i}/"} for i in range(10)],
            "all_landing_pages": [{"page": f"/p{i}/"} for i in range(122)],
            "landing_page_count": 122,
        },
        "gsc": {
            "top_pages": [{"page": f"/g{i}/"} for i in range(10)],
            "all_pages": [{"page": f"/g{i}/"} for i in range(401)],
            "top_queries": [{"query": f"q{i}"} for i in range(10)],
            "all_queries": [{"query": f"q{i}"} for i in range(385)],
            "page_count": 401,
            "query_count": 385,
        },
    }


def _strip_all_keys(result):
    """main() 内の履歴用スリム化と同じ処理"""
    hist = json.loads(json.dumps(result, ensure_ascii=False))
    for sec, keys in (("ga4", ("all_landing_pages",)),
                      ("gsc", ("all_queries", "all_pages"))):
        d = hist.get(sec)
        if isinstance(d, dict):
            for k in keys:
                d.pop(k, None)
    return hist


class TestLimitsAreConfigurable:
    def test_limits_are_not_hardcoded_to_ten(self):
        """取得上限が定数化され、10件固定でなくなっている"""
        m = _load_module()
        assert m.GA4_LANDING_PAGE_LIMIT > 10
        assert m.GSC_ROW_LIMIT > 10


class TestBackwardCompatibility:
    def test_top_keys_are_first_ten_of_all(self):
        """top_* は all_* の先頭10件(合算値の連続性を守る後方互換)"""
        r = _result_with_all_keys()
        assert r["ga4"]["top_landing_pages"] == r["ga4"]["all_landing_pages"][:10]
        assert r["gsc"]["top_pages"] == r["gsc"]["all_pages"][:10]
        assert r["gsc"]["top_queries"] == r["gsc"]["all_queries"][:10]


class TestHistoryStaysSlim:
    def test_history_excludes_all_keys(self, tmp_path):
        """履歴に all_* を入れない(肥大防止)"""
        m = _load_module()
        m.BASE_DIR = str(tmp_path)
        hist_path = tmp_path / "metrics_history.jsonl"

        m._append_history(_strip_all_keys(_result_with_all_keys()))

        row = _read(hist_path)[0]
        assert "all_landing_pages" not in row["ga4"]
        assert "all_pages" not in row["gsc"]
        assert "all_queries" not in row["gsc"]

    def test_history_keeps_counts_and_top_keys(self, tmp_path):
        """件数と top_* は履歴に残す(後から全体比率を検算できるように)"""
        m = _load_module()
        m.BASE_DIR = str(tmp_path)
        hist_path = tmp_path / "metrics_history.jsonl"

        m._append_history(_strip_all_keys(_result_with_all_keys()))

        row = _read(hist_path)[0]
        assert row["ga4"]["landing_page_count"] == 122
        assert row["gsc"]["page_count"] == 401
        assert len(row["ga4"]["top_landing_pages"]) == 10

    def test_stripping_does_not_mutate_snapshot(self):
        """スリム化はコピーに対して行い、スナップショット側の全件は保持される"""
        r = _result_with_all_keys()
        _strip_all_keys(r)
        assert len(r["ga4"]["all_landing_pages"]) == 122
        assert len(r["gsc"]["all_pages"]) == 401
