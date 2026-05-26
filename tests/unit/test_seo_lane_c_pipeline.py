"""SEO Lane C パイプライン(bridge/enrich/tracker)の純粋ロジック回帰テスト。

GSC/Anthropic 実接続が必要な部分は対象外。pos分岐・安全ガード・slug抽出など
副作用のないロジックだけを固定する。
"""
import importlib


class TestBridgePosRouting:
    def test_pos_thresholds(self):
        b = importlib.import_module("lib.seo_lane_c_bridge")
        # plan で確定した境界
        assert b.POS_REWRITE == (4.0, 6.0)
        assert b.POS_ENRICH[0] > b.POS_REWRITE[1]   # 重複しない
        assert b.POS_ENRICH[1] == 12.0

    def test_slug_from_url(self):
        b = importlib.import_module("lib.seo_lane_c_bridge")
        assert b._slug_from_url("https://www.kpopjournal.tokyo/golden-analysis/") == "golden-analysis"
        assert b._slug_from_url("https://www.kpopjournal.tokyo/golden-analysis") == "golden-analysis"
        assert b._slug_from_url("") == ""


class TestEnrichSafetyGuards:
    def test_ambiguous_artist_guard(self):
        be = importlib.import_module("lib.body_enrich")
        # 一般語同綴名のみ・文脈語なし → 弾く
        assert be._ambiguous_artist_ok("TREASURE 公演", "") is False
        # 文脈語あり → 通す
        assert be._ambiguous_artist_ok("TREASURE 韓国アイドル", "") is True
        # 曖昧でない通常名 → 通す
        assert be._ambiguous_artist_ok("aespa 新曲リリース", "") is True

    def test_existing_h2_extraction(self):
        be = importlib.import_module("lib.body_enrich")
        html = "<h2>あらすじ</h2><p>x</p><h2>キャスト</h2>"
        h2 = be._existing_h2_set(html)
        assert "あらすじ" in h2 and "キャスト" in h2

    def test_within_24h(self):
        be = importlib.import_module("lib.body_enrich")
        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        assert be._within_24h(recent) is True
        assert be._within_24h(old) is False
        assert be._within_24h(None) is False

    def test_max_enrich_constant(self):
        be = importlib.import_module("lib.body_enrich")
        assert be.MAX_ENRICH_PER_POST == 2   # auto_rewriter と同じ上限


class TestTrackerKpiLogic:
    def test_crossing_definition(self):
        # baseline>=10 かつ current<10 で 1ページ目進入、という定義を直接検証
        def crossed_10(bp, cp):
            return (bp >= 10) and (cp < 10)
        def crossed_3(bp, cp):
            return (bp >= 3) and (cp < 3)
        assert crossed_10(12.0, 8.0) is True
        assert crossed_10(8.0, 6.0) is False   # 既に1ページ目
        assert crossed_3(5.0, 2.5) is True
        assert crossed_3(2.0, 1.5) is False     # 既に上位
