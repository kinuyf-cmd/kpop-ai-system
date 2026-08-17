"""N-3 リグレッションテスト: 過去インシデント7件の再発防止

qa-test-generator SKILL.md §7 リグレッションテスト体系に基づく。
新規インシデントが起きたらここに追加 → 同じ事故を二度起こさない。

過去インシデント:
1. 嘘の完了宣言事件 → 完了宣言時に動作確認テストを必ず走らせる
2. review_queue 無限ループ → クールダウン動作のテスト
3. サムネの豆腐文字 → 文字化け検出
4. WordPress(ja) locale → 日本語タイトルでも検出
5. wp-cli /dev/stdin バグ → パスワードリセット動作
6. K-POPキーワード境界マッチ → V/RM/Lisa の誤マッチ防止
7. utf8mb4 接続 → 絵文字含む post_content の挿入
"""
import os
import re
import sys
from pathlib import Path

import pytest

# popup_event_to_post は 2026-08-17 に /tmp/wp_stg.txt 依存を廃止したため不要。
# このダミー生成は実害を出した(2026-07-10 → popup記事化が38日間全停止)。
# テストが本番の実行環境に副作用を残してはいけない。詳細は
# tests/unit/test_popup_event_to_post.py の同箇所コメント。

from lib.popup_event_fetcher import matches_kpop, classify
from lib.popup_event_to_post import slugify, esc_sql


ROOT = Path(__file__).resolve().parents[2]


class TestIncident1_FalseCompletion:
    """インシデント1: 嘘の完了宣言事件

    完了宣言時に error-evidence 4点が必須。
    qa_test_log.jsonl に実行ログが残ることが達成条件。
    """

    def test_qa_test_log_path_consistent(self):
        # SKILL.md §9 で定義された保存先と実装の一致を確認
        skill = Path.home() / ".claude" / "skills" / "qa-test-generator" / "SKILL.md"
        if skill.exists():
            text = skill.read_text(encoding="utf-8")
            assert "qa_test_log.jsonl" in text


class TestIncident2_ReviewQueueInfiniteLoop:
    """インシデント2: review_queue 無限ループ

    対象スクリプトに「クールダウン処理」「再実行ガード」相当の
    記述があることをチェック。
    """

    def test_review_loop_guards_exist(self):
        # auto_improve.py や retry_handler.py のクールダウンキーワード
        candidates = [
            ROOT / "lib" / "auto_improve.py",
            ROOT / "lib" / "retry_handler.py",
        ]
        existing = [p for p in candidates if p.exists()]
        if not existing:
            pytest.skip("retry/cooldown modules not present")
        # 少なくとも 1 ファイルにクールダウン関連の記述があること
        guard_keywords = ["cooldown", "retry", "max_retries", "MAX_RETRIES", "backoff"]
        found = False
        for p in existing:
            text = p.read_text(encoding="utf-8", errors="replace")
            if any(k in text for k in guard_keywords):
                found = True
                break
        assert found, "no retry/cooldown guard found in retry/auto_improve modules"


class TestIncident3_ThumbnailTofu:
    """インシデント3: サムネの豆腐文字

    make_thumbnail.py / lib/thumbnail_templates.py に
    フォント存在チェックロジックがあること。
    """

    def test_thumbnail_font_check(self):
        candidates = [
            ROOT / "make_thumbnail.py",
            ROOT / "lib" / "thumbnail_templates.py",
        ]
        existing = [p for p in candidates if p.exists()]
        if not existing:
            pytest.skip("thumbnail modules not present")
        text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in existing)
        # フォント関連の処理 + 日本語 (truetype + 日本語フォント名)
        assert "truetype" in text.lower() or "font" in text.lower(), \
            "font handling not found"


class TestIncident4_WordPressJaLocale:
    """インシデント4: WordPress(ja) locale で日本語タイトル

    slugify が日本語タイトルでも空文字を返さない(fallback あり)
    """

    def test_slugify_japanese_not_empty(self):
        s = slugify("ブラックピンク ポップアップストア")
        assert s, "slugify returned empty for Japanese-only title"
        assert len(s) > 0

    def test_slugify_mixed_language_works(self):
        s = slugify("BTS ポップアップ Tokyo")
        assert s
        # 英数字部分(bts や tokyo)が残ること
        assert re.search(r"[a-z0-9]", s)


class TestIncident5_WpCliStdin:
    """インシデント5: wp-cli /dev/stdin バグ

    パスワード等の機密データを stdin で渡す処理がある場合、
    --prompt= 形式やヒアドキュメント形式に統一されていることを
    軽量チェック。本来は wp-cli 直接実行できないので、
    ここはコードベース内検索で代用。
    """

    def test_wp_cli_no_dev_stdin_pattern(self):
        # /dev/stdin を wp-cli に渡す古いパターンがないこと
        scripts = list(ROOT.glob("*.sh"))
        for s in scripts:
            text = s.read_text(encoding="utf-8", errors="replace")
            # `wp user update ... </dev/stdin` のようなパターンは禁止
            assert not re.search(r"wp\s+user\s+update.*</dev/stdin", text), \
                f"obsolete wp-cli stdin pattern in {s.name}"


class TestIncident6_KpopKeywordBoundary:
    """インシデント6: K-POPキーワード境界マッチ

    短語 V / RM / Lisa の誤マッチを防止。
    test_popup_event_fetcher.py::TestWordBoundary と重複するが、
    リグレッション体系として独立保持。
    """

    def test_v_not_match_grapevine(self):
        assert matches_kpop("GRAPEVINE 来日公演") is None

    def test_lisa_not_match_jp_artist(self):
        assert matches_kpop("LiSA SOLO LIVE") is None

    def test_rm_not_match_random_word(self):
        assert matches_kpop("RMコーヒー店舗オープン") is None


class TestIncident7_Utf8mb4Connection:
    """インシデント7: utf8mb4 接続必須

    popup_event_to_post.py の run_mysql が --default-character-set=utf8mb4
    を指定していることをチェック。
    """

    def test_run_mysql_uses_utf8mb4(self):
        # 2026-08-17: run_mysql は mysql 直叩き(--default-character-set=utf8mb4)から
        # sudo ラッパー(kpop-wp-rw.sh)経由に変更した。/tmp/wp_stg.txt の資格情報が
        # 消える/キー名が食い違う問題で38日間 popup が全停止したため。
        # utf8mb4 はラッパー側で保証されており、実測で絵文字・日本語とも
        # 往復して壊れないことを確認済み(SELECT '🎤絵文字テスト💜' が無傷で返る)。
        # よって検査対象を「文字列 utf8mb4 の有無」から「資格情報を直接扱わず
        # ラッパー経由であること」に変更する。
        src = ROOT / "lib" / "popup_event_to_post.py"
        if not src.exists():
            pytest.skip("popup_event_to_post.py not present")
        text = src.read_text(encoding="utf-8", errors="replace")
        assert "kpop-wp-rw.sh" in text, "run_mysql should go through the sudo wrapper"
        assert 'DB["WP_DB_USER"]' not in text, "run_mysql must not read raw DB creds"


class TestIncident_SqlInjectionPrevention:
    """補足: SQL injection 防止(後付け基本ガード)"""

    def test_esc_sql_handles_quote(self):
        assert esc_sql("'; DROP TABLE;--") == "''; DROP TABLE;--"

    def test_esc_sql_handles_backslash(self):
        # \' に対するエスケープが文字列リテラル外に漏れない
        result = esc_sql("\\'")
        assert "\\\\" in result


class TestIncident8_BreakingDedupEnJaMismatch:
    """インシデント8: 速報selector dedup が EN signal title ⇄ JA 公開title で
    照合不能 → 既出ネタを再選出(2026-05-23 本番公開後監査で検出)。
    主キーを soompi記事ID(URLの /article/<id>)に変更して回避。"""

    def _mod(self):
        from lib import breaking_news_selector as m
        return m

    def test_soompi_id_extracted_from_url(self):
        m = self._mod()
        assert m._soompi_id("https://www.soompi.com/article/1842246wpp/onf-x") == "1842246"
        assert m._soompi_id("https://example.com/no-article") == ""

    def test_duplicate_matched_by_soompi_id_not_title(self):
        # EN signal title だが、既出 soompi記事ID と一致 → 重複判定されること
        m = self._mod()
        sig = {"url": "https://www.soompi.com/article/1842246wpp/onf-announces",
               "title": "ONF Announces Comeback"}  # JA公開titleとは別言語
        dup, reason = m.is_duplicate(sig, set(), {"1842246"}, set())
        assert dup is True and "ID" in reason

    def test_new_soompi_id_not_excluded(self):
        m = self._mod()
        sig = {"url": "https://www.soompi.com/article/9999999wpp/new", "title": "X"}
        dup, _ = m.is_duplicate(sig, set(), {"1842246"}, set())
        assert dup is False
