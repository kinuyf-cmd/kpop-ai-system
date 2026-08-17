"""段階2(本人写真)の真因修理テスト(2026-06-16 systematic-debugging)。

真因: thumbnail_resolver の classify() が日本語ニックネーム('スキズ', key='')や
空を返し、artist_master/Wikimedia 照合に通らず本人写真が取れない。
一方 _tsr_resolve は canonical英名('Stray Kids')なら本人写真を返す。
→ 修理: 検出subjectを artist_resolver.resolve() で canonical化してから渡す。
"""
import os
import sys
from pathlib import Path

# popup_event_to_post は 2026-08-17 に /tmp/wp_stg.txt 依存を廃止したため不要。
# このダミー生成は実害を出した(2026-07-10 → popup記事化が38日間全停止)。
# テストが本番の実行環境に副作用を残してはいけない。

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


class TestCanonicalArtist:
    """thumbnail_resolver._canonical_artist: 検出名→canonical英名 正規化。"""

    def test_japanese_nickname_sukizu_to_straykids(self):
        from lib.thumbnail_resolver import _canonical_artist
        # 'スキズ' は本人写真取得に使えない→ 'Stray Kids' に正規化されるべき
        assert _canonical_artist("スキズ", "スキズOST一覧") == "Stray Kids"

    def test_canonical_english_passthrough(self):
        from lib.thumbnail_resolver import _canonical_artist
        assert _canonical_artist("Stray Kids", "Stray Kids OST") == "Stray Kids"

    def test_empty_subject_falls_back_to_title(self):
        from lib.thumbnail_resolver import _canonical_artist
        # classify が [] を返す(LE SSERAFIM実例)→ titleから解決
        assert _canonical_artist("", "LE SSERAFIM、10月カムバック") == "LE SSERAFIM"

    def test_katakana_lesserafim_to_canonical(self):
        from lib.thumbnail_resolver import _canonical_artist
        assert _canonical_artist("ルセラフィム", "ルセラフィム カムバック") == "LE SSERAFIM"

    def test_unresolvable_returns_original(self):
        from lib.thumbnail_resolver import _canonical_artist
        # 解決不能(LABUBU等の非アーティスト題材)→ 元の名前をそのまま返す(段階3へ流す)
        assert _canonical_artist("LABUBU", "ラブブ 中国で買う") == "LABUBU"

    def test_no_signal_returns_empty(self):
        from lib.thumbnail_resolver import _canonical_artist
        assert _canonical_artist("", "今日の天気") == ""
