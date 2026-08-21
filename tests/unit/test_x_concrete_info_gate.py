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
