"""pre_publish_gate の structural_only パス + 2パス化の回帰テスト
(2026-05-27 修正: factcheck を「注入前 raw 本文」で判定する自滅的ブロック根絶)

背景:
  速報の「無関係コンテンツ混入」誤ブロックの真因は、unified_publisher が
  内部リンク/CTA を注入した「後」の本文を factcheck に渡していたこと。自社の
  アフィリエイトCTA・関連記事リンクが「無関係」と判定されブロックされていた。

  修正は 2 パス化:
    パス1 = 注入前 raw 本文に通常ゲート(factcheck/事実/関連性)
    パス2 = 注入後本文に structural_only=True(内部リンク数/タグ均衡のみ)

本テストの不変条件(LLM を呼ばず決定的に検証できる範囲):
  1. structural_only=True は LLM factcheck を呼ばない。
  2. structural_only=True は BLOCK を生まない(構造系は全て WARN 止まり)。
  3. structural_only=True は内部リンク数/タグ均衡など構造系のみ評価する
     (本文の「無関係性」やソース乖離などコンテンツ判定はしない)。
  4. pre_publish_gate のデフォルト(structural_only 既定 False)挙動は不変
     = 既存呼び出しに影響を与えない(シグネチャ後方互換)。
"""
import inspect
import lib.pre_publish_gate as ppg
from lib.pre_publish_gate import pre_publish_gate


def _long_body(paras=6):
    blocks = "".join(f"<p>{'本文テキストです。'*15}</p><h2>見出し{i}</h2>" for i in range(paras))
    return blocks


class TestStructuralOnlyPath:
    def test_does_not_block(self):
        """structural_only は BLOCK を生まない(WARN/PASS のみ)。"""
        r = pre_publish_gate(
            title="BTSが新曲を発表、ファンの反応まとめ",
            body_html=_long_body(),
            kind="breaking", slug="bts-new-song-reactions",
            featured_media=123, categories=[2],
            excerpt="BTSの新曲発表に関する最新情報を、ファンの反応とともに詳しくお届けします。",
            status="publish", structural_only=True,
        )
        assert r["verdict"] in ("WARN", "PASS")
        assert r["block_reasons"] == []

    def test_does_not_call_llm_factcheck(self):
        """structural_only は factcheck_v2(LLM)を呼ばない。
        本環境は base python に anthropic 未インストール=factcheck_v2 を import すると
        ModuleNotFoundError になる。それでも structural_only が例外なく完走することが、
        LLM パスに入っていない(= factcheck を呼んでいない)ことの証左になる。"""
        r = pre_publish_gate(
            title="aespaがカムバック、新アルバム情報",
            body_html=_long_body(),
            kind="breaking", slug="aespa-comeback-album",
            featured_media=1, categories=[2],
            excerpt="aespaのカムバックと新アルバムの情報を最新ニュースとして整理してお届けします。",
            status="publish", structural_only=True,
        )
        # 例外なく verdict が返る = LLM(anthropic)に触れていない
        assert r["verdict"] in ("WARN", "PASS")

    def test_ignores_content_relevance(self):
        """structural_only は本文の『無関係性』を判定しない。
        ニュース本文に無関係な広告風テキストを混ぜても BLOCK しない
        (= コンテンツ判定はパス1の責務であり、構造パスはノータッチ)。"""
        body = (
            "<p>" + "BTSの最新ニュースです。" * 10 + "</p>"
            "<h2>関連情報</h2>"
            "<p>航空券をかしこく予約 エアトリで探す 国内格安航空券</p>"  # 無関係っぽい広告風
            "<p>" + "続報をお伝えします。" * 10 + "</p>"
        )
        r = pre_publish_gate(
            title="BTSが新曲を発表",
            body_html=body, kind="breaking", slug="bts-song",
            featured_media=1, categories=[2],
            excerpt="BTSの新曲に関する最新情報を詳しくお届けする記事の概要文です。",
            status="publish", structural_only=True,
        )
        # 広告風テキストがあっても構造パスは BLOCK しない
        assert r["verdict"] != "BLOCK"


class TestBackwardCompat:
    def test_signature_has_structural_only_default_false(self):
        """structural_only は既定 False(既存呼び出しの後方互換)。"""
        sig = inspect.signature(pre_publish_gate)
        assert "structural_only" in sig.parameters
        assert sig.parameters["structural_only"].default is False

    def test_default_path_runs_full_checks(self, monkeypatch):
        """structural_only を指定しない通常呼び出しは従来通り
        コンテンツ検査も走る(本文空などの BLOCK が機能する)。"""
        # 本文空 → content_empty BLOCK(構造パスでは出ない壊滅チェック)
        r = pre_publish_gate(
            title="テスト", body_html="<p>短い</p>",
            kind="news", slug="test-empty", featured_media=1,
            categories=[2], excerpt="x" * 50, status="publish",
            skip_llm_factcheck=True,  # LLM は別軸なので無効化
        )
        # 通常パスは content_empty を BLOCK 候補として検出する
        types_found = [i.get("type") for i in r.get("issues", [])]
        assert "content_empty" in types_found
