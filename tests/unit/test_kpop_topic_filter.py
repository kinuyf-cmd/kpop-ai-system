"""非K-POPトピック除外フィルタのテスト(2026-05-29 監査対応)

XPORTSNEWS「엑's 이슈」セクションが混在掲載する非K-POPコンテンツの記事化を防ぐ。
実害ケース:
  - 『나는 SOLO / 私はソロ』婚活リアリティ番組(一般人出演) ID 4802/3158
  - 故女優の娘の政治論争(チェ・ジュニ スタバ) ID 4798

設計: docs/superpowers/specs/2026-05-29-non-kpop-topic-filter-design.md
"""
from lib.kpop_topic_filter import classify_non_kpop_topic


class TestRealityShowCivilian:
    def test_naneun_solo_korean_blocked(self):
        assert classify_non_kpop_topic(
            "나는 솔로 31기 출연진 논란 계속"
        ) == "reality_show_civilian"

    def test_naneun_solo_japanese_title_blocked(self):
        # 実害タイトル(ID 3158 系)
        assert classify_non_kpop_topic(
            "「私はソロ」31期メンバー団体飲み会、ギョンスとスンジャ不在"
        ) == "reality_show_civilian"

    def test_x_issue_31_title_blocked(self):
        # 実害タイトル(ID 4802)。"나솔" 略称を含む文脈
        assert classify_non_kpop_topic(
            "나솔 31기 출연진만 논란 인식 못했나 [엑's 이슈]"
        ) == "reality_show_civilian"


class TestPolitics:
    def test_leftist_country_blocked(self):
        # 実害タイトル(ID 4798 本文の核)
        assert classify_non_kpop_topic(
            "최준희 \"좌파 없는 나라에 살고 싶다\" 발언 논란"
        ) == "politics"

    def test_impeachment_blocked(self):
        assert classify_non_kpop_topic("배우 탄핵 집회 참석 논란") == "politics"


class TestLegitKpopPasses:
    def test_normal_comeback_passes(self):
        assert classify_non_kpop_topic(
            "aespa、正規2集『LEMONADE』でカムバック"
        ) is None

    def test_bts_v_marriage_remark_passes(self):
        # 公開中の正当記事(ID 4509)。論争語を含むが固有アーティスト名あり
        assert classify_non_kpop_topic(
            "BTSのV、コンサートで結婚発言し話題に"
        ) is None

    def test_kpop_artist_with_politics_word_passes(self):
        # 安全装置: 固有アーティスト名が共在すれば政治語があっても通す
        assert classify_non_kpop_topic(
            "BLACKPINK ジェニー、대선 関連の寄付で話題"
        ) is None

    def test_empty_text_passes(self):
        assert classify_non_kpop_topic("") is None


class TestNoFalsePositiveOnSubstring:
    def test_solo_song_not_blocked(self):
        # K-POPの「ソロ曲(솔로곡)」は番組『나는 솔로』ではない
        assert classify_non_kpop_topic(
            "IUの솔로곡が音源チャート1位"
        ) is None
