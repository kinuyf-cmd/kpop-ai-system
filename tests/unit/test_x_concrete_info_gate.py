#!/usr/bin/env python3
"""型A本文に「読者が行動を変えられる具体」があるかのゲート。

背景(2026-08-21 実測): Phase1以降のトップレベル投稿38本を自動/手動で分けると
  自動 n=34 平均imp 109.5 / 中央75
  手動 n= 4 平均imp 991.2 / 中央1397   ← 1本あたり9倍
伸びた手動投稿に共通するのは「日時・場所・価格・条件」といった具体で、
自動投稿は「〜どうなるんだろう…楽しみ」と感想だけで情報量がゼロだった。
型A(check_hook_structure_type_a)は構文しか見ないため、中身の薄さを通してしまう。
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from lib.x_traffic_picker import has_concrete_info


class TestPassesOnRealWinners:
    """実測で伸びた手動投稿(imp 453〜1632)は通ること。"""

    def test_summer_sonic_payment(self):
        t = ("サマソニ行く人へ、現金だけで行くと詰みます。\n\n"
             "グッズ売場=キャッシュレスのみ(現金不可)\n飲食=電子マネーのみ\n"
             "あと身分証(顔写真付き・コピー不可)がないとリストバンド交換できません")
        assert has_concrete_info(t)["ok"], has_concrete_info(t)

    def test_time_and_exclusivity(self):
        t = ("サマソニ初日、K-POP勢が濃い。\n\nBABYMONSTER 14:05〜(MARINE)\n"
             "しかもベビモンは大阪に出ないから、今日を逃すと現地では見られません。")
        assert has_concrete_info(t)["ok"]

    def test_date_and_condition(self):
        t = ("NCT DREAM 10周年ファンミが8/23に韓国から生中継されます。日本語字幕付き\n\n"
             "ファンミはトークが中心なので、字幕ありで見られるかどうかで体験がかなり変わります")
        assert has_concrete_info(t)["ok"]


class TestRejectsVagueAutoPosts:
    """実測で伸びなかった自動投稿(感想のみ・情報量ゼロ)は弾くこと。"""

    def test_pure_impression(self):
        t = "NCT127が新曲のカムバックを控えてるって、これから何が来るのか期待しかない…大きな動きがある！"
        assert not has_concrete_info(t)["ok"]

    def test_vague_admiration(self):
        t = "RIIZEの新曲、聴いてるだけでなんか気分上がるけど、あのビジュアルどうやって保ってんのか謎すぎw"
        assert not has_concrete_info(t)["ok"]

    def test_no_information(self):
        t = "TWICEの最近のパフォーマンス、なんかもう何回見ても飽きない気がするんだけど、どうなってんだろう。"
        assert not has_concrete_info(t)["ok"]

    def test_nomination_count_alone_is_not_actionable(self):
        """『4部門』のような単なる数量は行動を変えない(日時/場所/条件ではない)。"""
        t = "LISAが4部門ノミネートって、どれだけ目立つつもりなんだろう…これは楽しみだ。"
        assert not has_concrete_info(t)["ok"]


class TestSignals:
    def test_detects_date(self):
        assert has_concrete_info("8/23に生中継されます。字幕付きで見られるかが分かれ目です")["ok"]

    def test_detects_time(self):
        assert has_concrete_info("出番は14:05から。この時間を逃すと現地では見られません")["ok"]

    def test_detects_price(self):
        assert has_concrete_info("チケットは12,000円から。先行は明日までの受付です")["ok"]

    def test_reports_reason_when_missing(self):
        r = has_concrete_info("すごく楽しみだなぁ、どうなるんだろう")
        assert not r["ok"] and r["issue"]

    def test_empty_is_rejected(self):
        assert not has_concrete_info("")["ok"]


class TestPastDatesAreNotActionable:
    """過去の出来事の日付は「行動を変える具体」ではない(実測での誤検知)。"""

    def test_past_broadcast_record(self):
        t = ("JTBCのドラマ「アパート」が2026年08月15日の最終回で自己最高視聴率7.7%を記録し、"
             "全チャンネル同時間帯で1位を獲得した")
        assert not has_concrete_info(t)["ok"]

    def test_past_selca_post(self):
        t = ("OH MY GIRLのYooAが2026年08月19日、マスクパックを付けたセルカを公開。"
             "リラックスした室内でスキンケアに集中する姿がファンに好評")
        assert not has_concrete_info(t)["ok"]

    def test_future_date_still_passes(self):
        """未来の予定は通す(告知として行動を変えられる)。"""
        t = "ファンミは8/23に生中継されます。日本語字幕付きで見られるかが分かれ目です"
        assert has_concrete_info(t)["ok"]


class TestConditionPatternIsNotOverbroad:
    """『条件』パターンの誤検知(実生成で判明)。日常語を条件と数えない。"""

    def test_hitsuyou_sugiru_is_not_a_condition(self):
        t = ("NCT DREAM、メンバー全員がSMと再契約を締結したそうだけど、"
             "同じ時期にそれぞれの道を進むって、ファンとしては心の準備が必要すぎる。")
        assert not has_concrete_info(t)["ok"], has_concrete_info(t)

    def test_tsuki_in_ordinary_word_is_not_a_condition(self):
        assert not has_concrete_info("この曲は勢いがあって、思い付きで聴いても楽しめる感じがするなぁ")["ok"]

    def test_real_condition_still_passes(self):
        assert has_concrete_info("グッズ売場はキャッシュレスのみ。現金は使えません")["ok"]

    def test_reservation_required_passes(self):
        assert has_concrete_info("入場は事前予約が必須です。当日券はありません")["ok"]


class TestBareTimeWordIsNotEnough:
    """『今日』『週末』だけでは行動を変えられない(実生成での誤検知)。

    伸びた実例は「今日を逃すと現地では見られません」のように、時期語が
    時刻・場所・可否とセットで出ていた。単独の時期語は具体と数えない。
    """

    def test_bare_kyou_is_rejected(self):
        t = ("NCT DREAM、メンバー全員がSMと再契約を締結したのに、"
             "SEVENTEENのバーノンが今日入隊って、何か運命的なタイミングだよね…")
        assert not has_concrete_info(t)["ok"], has_concrete_info(t)

    def test_time_word_with_place_and_time_passes(self):
        t = ("サマソニ初日、K-POP勢が濃い。BABYMONSTER 14:05〜(MARINE)。"
             "しかも大阪に出ないから、今日を逃すと現地では見られません。")
        assert has_concrete_info(t)["ok"]

    def test_time_word_with_deadline_passes(self):
        assert has_concrete_info("先行受付は今日までです。逃すと一般販売を待つことになります")["ok"]


class TestNegativePotentialIsNotAvailability:
    """『理解できない』のような心情表現は可否条件ではない(実生成での誤検知)。

    可否として拾いたいのは「入れません」「買えません」のように、読者の行動が
    制約される場合だけ。主語が自分の感情/理解であるものは具体にならない。
    """

    def test_cannot_understand_is_not_availability(self):
        t = ("Red Velvetのウェンディ、身体や容姿に対する悪質な投稿もあって、"
             "ほんとにひどいよね…何でそんなことするのか全然理解できない。")
        assert not has_concrete_info(t)["ok"], has_concrete_info(t)

    def test_cannot_wait_is_not_availability(self):
        assert not has_concrete_info("新曲が楽しみで待ちきれない、もう我慢できない気持ち")["ok"]

    def test_real_unavailability_passes(self):
        assert has_concrete_info("当日券はありません。事前予約がないと入れません")["ok"]

    def test_cannot_see_at_venue_passes(self):
        t = "ベビモンは大阪に出ないから、今日を逃すと現地では見られません"
        assert has_concrete_info(t)["ok"]


class TestPastReportPatternsAreBroadEnough:
    """過去の出来事の報告は、語尾が多様でも日付を具体と数えない。

    旧投稿(型A導入前)を通してしまう実例から採取。現行経路では出ないが、
    生成が揺れたときの再発源になるので塞いでおく。
    """

    def test_showcased(self):
        t = "正勝煥が2026年5月31日に「ビューティフル・ミント・ライフ2026」で新曲を披露し、観客との距離を縮めた"
        assert not has_concrete_info(t)["ok"]

    def test_achieved_soldout(self):
        t = ("TWICEの6thワールドツアーのソウルアンコール公演が、2026年7月10日から12日に"
             "KSPO DOMEで全席完売を達成。国内外のファンの高い関心が示された")
        assert not has_concrete_info(t)["ok"]

    def test_attended_event(self):
        t = "IVEのLeeseoが2026年5月29日にソウルで行われたイベントに参加し、美しさを披露"
        assert not has_concrete_info(t)["ok"]

    def test_future_release_still_passes(self):
        """未来の予定は通す(告知として行動を変えられる)。"""
        t = "新曲は6月22日午後1時にリリース予定。配信開始と同時に聴けます"
        assert has_concrete_info(t)["ok"]

    def test_future_event_still_passes(self):
        t = "アンコール公演は7月10日から12日、KSPO DOME。チケットは事前予約が必須です"
        assert has_concrete_info(t)["ok"]


class TestStaleDatesAreRejected:
    """『本日(8/20)』を8/21に投稿すると誤情報になる(実生成で発覚)。

    ネタ元の見出しに載った日付をそのまま引き継ぐため起きる。今日でない日を
    「本日/今日」と呼んでいる本文は、具体として通してはいけない。
    """

    def test_yesterday_called_today_is_rejected(self):
        t = ("NCT DREAM、メンバー全員がSMと再契約を締結したのに、"
             "SEVENTEENのバーノンが本日（8/20）入隊って、なんか時代の変わり目を感じるなぁ…")
        assert not has_concrete_info(t, today="2026-08-21")["ok"]

    def test_today_called_today_passes(self):
        t = "バーノンが本日（8/21）入隊って、なんか時代の変わり目を感じるなぁ…"
        assert has_concrete_info(t, today="2026-08-21")["ok"]

    def test_future_date_without_today_word_passes(self):
        t = "ファンミは8/23に生中継されます。日本語字幕付きで見られるかが分かれ目ですね"
        assert has_concrete_info(t, today="2026-08-21")["ok"]

    def test_past_date_without_today_word_is_untouched_by_this_rule(self):
        """このルールは『本日/今日』と併記された日付だけを見る。"""
        t = "先行受付は8/25まで。事前予約がないと入れません"
        assert has_concrete_info(t, today="2026-08-21")["ok"]
