"""K-POP判定ホワイトリスト拡張の回帰テスト(2026-05-27)
l-tike収集で取りこぼした曖昧でないK-POP組(iKON/JAEJOONG等)を追加した際の
①新規採用 ②誤爆防止 ③既存の曖昧名ガード維持 を固定する。
"""
from lib.eplus_enricher import _is_kpop


class TestWhitelistExpansion:
    def test_newly_added_unambiguous_accepted(self):
        assert _is_kpop("iKON") is True
        assert _is_kpop("iKON JAPAN TOUR 2026") is True
        assert _is_kpop("JAEJOONG") is True
        assert _is_kpop("ジェジュン ライブ") is True
        assert _is_kpop("ウィ・ハジュン ファンミーティング") is True

    def test_winner_requires_context(self):
        # WINNER は実在K-POPだが一般英単語と衝突 → 文脈語が要る
        assert _is_kpop("WINNER 2026 WORLD TOUR in JAPAN") is True
        assert _is_kpop("Best Award Winner Concert") is False

    def test_no_false_positive_substrings(self):
        assert _is_kpop("ikonic brand show") is False   # ikon ⊄ ikonic
        assert _is_kpop("MIDNIGHT DRIVE") is False        # ive ⊄ drive

    def test_existing_ambiguous_guard_preserved(self):
        # 既存の曖昧名(TREASURE/IVE)は文脈語なしでは却下のまま
        assert _is_kpop("TREASURE") is False
        assert _is_kpop("TREASURE WORLD TOUR") is True
        assert _is_kpop("IVE") is False

    def test_non_kpop_still_rejected(self):
        assert _is_kpop("【7月公演】スーパー歌舞伎『もののけ姫』") is False
        assert _is_kpop("山下智久") is False
