"""イベント誤分類ガードの回帰テスト(2026-05-26 事故対応)

本番で非K-POP公演を K-POP アーティストのイベントとして捏造した事故の再発防止。
- BABY SHARK LIVE!(The Hidden Treasure)→ TREASURE 誤判定
- TREASURE05X(日本のロックフェス)→ TREASURE 誤判定
- vanvanV4 → V/IVE 誤判定

多層防御を検証:
  1) lib/eplus_enricher._is_kpop          … 収集の入口
  2) lib/ticket_signals_to_event_input._is_kpop_eplus … チケット収集
"""
from lib.eplus_enricher import _is_kpop
from lib.ticket_signals_to_event_input import _is_kpop_eplus


# (タイトル, K-POPとして採用すべきか)
CASES = [
    # 非K-POP公演 = 弾くべき(誤分類の実害ケース)
    ("BABY SHARK LIVE! -The Hidden Treasure-", False),
    ("Newfound Treasures", False),
    ("TREASURE05X 2026", False),          # 日本の野外フェス
    ("NAOTO Concert Tour 2026", False),   # 三代目系
    ("vanvanV4 45th Anniversary", False),
    # 本物のK-POP = 通すべき(文脈語 or 曖昧でない名)
    ("TREASURE WORLD TOUR in Korea", True),
    ("TREASURE 트레저 JAPAN", True),
    ("aespa JAPAN FANMEETING 2026", True),
    ("NCT 127 LIVE", True),
    ("SHINee WORLD", True),
    ("RIIZE JAPAN FANMEETING 2026", True),
]


class TestEplusEnricherGuard:
    def test_ambiguous_artist_blocked_without_context(self):
        assert _is_kpop("BABY SHARK LIVE! -The Hidden Treasure-") is False
        assert _is_kpop("TREASURE05X 2026") is False

    def test_real_kpop_with_context_passes(self):
        assert _is_kpop("TREASURE WORLD TOUR in Korea") is True
        assert _is_kpop("TREASURE 트레저 JAPAN") is True

    def test_unambiguous_artist_passes(self):
        assert _is_kpop("aespa JAPAN FANMEETING") is True
        assert _is_kpop("NCT 127 LIVE") is True


class TestTicketSignalsGuard:
    def test_matches_eplus_enricher_behavior(self):
        # 2経路で同じ判定になること(統一済み)
        for title, expected in CASES:
            assert _is_kpop_eplus(title) is expected, f"ticket judge mismatch: {title}"


class TestBothPathsConsistent:
    def test_all_cases_both_paths(self):
        for title, expected in CASES:
            assert _is_kpop(title) is expected, f"eplus judge: {title}"
            assert _is_kpop_eplus(title) is expected, f"ticket judge: {title}"
