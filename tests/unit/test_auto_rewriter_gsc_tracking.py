"""auto_rewriter / post_publish_evaluator の gsc_tracking.json 読み込み回帰テスト。

背景（2026-07-31 に発見・修理）:
  audit_72h.py は gsc_tracking.json を list[entry] 形式で書き出すが、
  auto_rewriter.safety_check と post_publish_evaluator.rank_post は
  dict を前提に .get(post_id) を呼んでいたため AttributeError で
  週次リライトが約3週間クラッシュし続けていた。
  さらに entry は "indexed" キーを持たず "index_status" を持つ。

  加えて seo_lane_c_bridge は post_id=None でキュー投入するため、
  slug からの解決が必須。
"""
import json

import pytest

from lib import auto_rewriter as ar
from lib import post_publish_evaluator as ppe


# audit_72h.py が実際に書き出す形式
SAMPLE_ENTRIES = [
    {
        "post_id": 9189,
        "url": "https://www.kpopjournal.tokyo/tettsui-kyoshi-cast-chart/",
        "sent_at": "",
        "index_status": "indexed",
        "elapsed_hours": None,
        "resubmit_flag": False,
        "p1_alert": False,
    },
    {
        "post_id": 11857,
        "url": "https://www.kpopjournal.tokyo/popup-20260709-a06c11e511/",
        "sent_at": "",
        "index_status": "not_indexed",
        "elapsed_hours": None,
        "resubmit_flag": False,
        "p1_alert": False,
    },
]


@pytest.fixture
def tracking_file(tmp_path):
    p = tmp_path / "gsc_tracking.json"
    p.write_text(json.dumps(SAMPLE_ENTRIES, ensure_ascii=False), encoding="utf-8")
    return str(p)


@pytest.mark.parametrize("loader", [ar.load_gsc_tracking, ppe.load_gsc_tracking])
def test_list_format_is_converted_to_dict(loader, tracking_file):
    """list 形式を post_id キーの dict に変換する（AttributeError の根治）。"""
    gsc = loader(tracking_file)
    assert isinstance(gsc, dict)
    assert set(gsc) == {"9189", "11857"}


@pytest.mark.parametrize("loader", [ar.load_gsc_tracking, ppe.load_gsc_tracking])
def test_indexed_is_derived_from_index_status(loader, tracking_file):
    """entry に indexed キーは無いので index_status から導出する。"""
    gsc = loader(tracking_file)
    assert gsc["9189"]["indexed"] is True
    assert gsc["11857"]["indexed"] is False


@pytest.mark.parametrize("loader", [ar.load_gsc_tracking, ppe.load_gsc_tracking])
def test_post_id_keys_are_strings(loader, tracking_file):
    """呼び出し側は str(post_id) でアクセスするためキーは文字列に揃える。"""
    gsc = loader(tracking_file)
    assert all(isinstance(k, str) for k in gsc)


@pytest.mark.parametrize("loader", [ar.load_gsc_tracking, ppe.load_gsc_tracking])
def test_missing_file_returns_empty_dict(loader, tmp_path):
    gsc = loader(str(tmp_path / "does_not_exist.json"))
    assert gsc == {}


@pytest.mark.parametrize("loader", [ar.load_gsc_tracking, ppe.load_gsc_tracking])
def test_entries_wrapper_dict_is_supported(loader, tmp_path):
    """{"entries": [...]} 形式でも壊れない（winning_pattern_tracker と同じ許容）。"""
    p = tmp_path / "wrapped.json"
    p.write_text(json.dumps({"entries": SAMPLE_ENTRIES}, ensure_ascii=False), encoding="utf-8")
    gsc = loader(str(p))
    assert gsc["9189"]["indexed"] is True


def test_safety_check_does_not_crash_on_list_format(tracking_file):
    """回帰の本丸: safety_check が list 由来データで例外を出さない。"""
    gsc = ar.load_gsc_tracking(tracking_file)
    ok, reason = ar.safety_check("9189", "REWRITE_NOW", gsc, {})
    assert ok is True
    assert reason == "ok"


def test_safety_check_blocks_second_title_change_when_indexed(tracking_file):
    """インデックス済み記事のタイトル変更は1回まで、という既存仕様を守る。"""
    gsc = ar.load_gsc_tracking(tracking_file)
    hist = {"9189": [{"executed_at": "2020-01-01T00:00:00+00:00", "title_changed": True}]}
    ok, reason = ar.safety_check("9189", "REWRITE_NOW", gsc, hist)
    assert ok is False
    assert "タイトル変更は1回まで" in reason


def test_resolve_post_id_prefers_explicit_value():
    assert ar.resolve_post_id({"post_id": 1317, "slug": "ignored"}) == "1317"


def test_resolve_post_id_falls_back_to_slug(monkeypatch):
    """seo_lane_c_bridge は post_id=None で投入するので slug 解決が要る。"""
    calls = {}

    def fake_wp_request(method, path, data=None):
        calls["path"] = path
        return [{"id": 9189}], None

    monkeypatch.setattr(ar, "wp_request", fake_wp_request)
    assert ar.resolve_post_id({"post_id": None, "slug": "tettsui-kyoshi-cast-chart"}) == "9189"
    assert "tettsui-kyoshi-cast-chart" in calls["path"]


def test_resolve_post_id_derives_slug_from_url(monkeypatch):
    monkeypatch.setattr(ar, "wp_request", lambda m, p, data=None: ([{"id": 42}], None))
    item = {"post_id": None, "url": "https://www.kpopjournal.tokyo/some-slug/"}
    assert ar.resolve_post_id(item) == "42"


def test_resolve_post_id_returns_none_when_unresolvable(monkeypatch):
    """解決できなければ None。呼び出し側はスキップして WP を触らない。"""
    monkeypatch.setattr(ar, "wp_request", lambda m, p, data=None: ([], None))
    assert ar.resolve_post_id({"post_id": None, "slug": "nope"}) is None


def test_process_item_skips_and_never_touches_wp_when_post_id_unresolved(monkeypatch):
    """post_id 未解決で update_wp_post が呼ばれないこと（/posts/None 防止）。"""
    monkeypatch.setattr(ar, "resolve_post_id", lambda item: None)

    def boom(*a, **k):
        raise AssertionError("post_id 未解決なのに WP を更新しようとした")

    monkeypatch.setattr(ar, "update_wp_post", boom)
    monkeypatch.setattr(ar, "post_to_x", boom)

    action = ar.process_item({"post_id": None, "slug": "ghost"}, {}, {})
    assert action["skipped"] is True
    assert "post_id未解決" in action["skip_reason"]
    assert action["wp_update_ok"] is False
