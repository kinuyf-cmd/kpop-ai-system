"""factcheck_v2: 「知識基盤に無い=架空」「BTS兵役中」誤検知フィルタの回帰テスト (2026-10-13)。

実ログの指摘文をそのまま使う。正当な指摘まで消さないことを同じ重みで検証する。
"""
import pytest

from lib import factcheck_v2 as f

FALSE_POSITIVES = [
    "「MODYSSEY」はK-pop知識基盤(覚え書き・確定データ)に存在せず、一般にも実在性が確認できないグループ名であり、架空または誤情報の可能性が高い。",
    "「リセンヌ」（ウォニ、リヴ、ミナミ、メイ、ジェナ）というグループはK-pop知識基盤に存在せず、実在が確認できない。",
    "POWというグループはK-pop主要アーティスト覚え書き及び一般的に知られるK-POPグループに該当せず、実在性・メンバー構成が信頼できる情報源で確認できない。架空または誤情報の可能性が高い。",
    "「キックフリップ」はK-pop知識基盤(覚え書き・確定データ)に存在せず、一般にも実在性が確認できないグループ名であり、架空または誤情報の可能性が高い。",
    "「リセンヌ」というグループはK-pop知識基盤に実在が確認できず、過去の検出事例でも同様の問題が指摘されている架空または誤情報の可能性が高いグループ名である。",
]

BTS_STALE = [
    "BTSは2025年6月に全員兵役(軍服務)のため活動を休止しており、2026年10月時点で南米ワールドツアーを7人揃って開催しているという事実は裏付けが取れない。",
    "BTSは2025年6月から全員兵役(兵役義務による活動休止)中であり、ペルー・リマでワールドツアーを開催したという事実は確認できない。",
    "2026年5月のメキシコシティ3公演での15万人動員という記述も同様にBTSの兵役休止期間と矛盾しており、事実関係の検証ができない。",
]

# 絶対に消してはいけない正当な指摘
REAL_ERRORS = [
    "BABYMONSTERのメンバーを『RUKA、PHARITA、ASA、AHYEON、RAMI、CHIQUITA、HARA の7人』としているが、『HARA』は存在しない人物。基礎情報と矛盾する人名誤記。",
    "SEVENTEENのメンバーに「Woongsan」という人物は基礎情報コーパスに記載がなく、実在が確認できない。",
    "Hyolyn(효리수)という表記は、知識基盤にあるHyolyn(효린)と明らかに異なる韓国語表記であり、誤記または捏造の疑いがある。",
    "「BTSが40週連続で首位を堅持」と明記しているが、BTSは兵役・活動休止期間を経て2025年に全員除隊し活動再開したばかりであり、40週連続1位という記述は検証が取れない。",
    "HOSHIは現在陸軍兵役中で、軍服務中に前十字靭帯断裂の重傷を負ったという内容にもかかわらず新曲を発表するとしており矛盾がある。",
    "タイトルは『YooA』個人名を主語としているが、本文冒頭ではグループ名が記載されており主語が矛盾している。",
    "本文の途中に『(ここに引用を入れる)』という編集者向けの指示文がそのまま残っている。",
]


@pytest.mark.parametrize("text", FALSE_POSITIVES)
def test_kb_absence_is_noise(text):
    assert f._is_kb_absence_noise(text)
    assert f.is_lesson_noise(text)


@pytest.mark.parametrize("text", BTS_STALE)
def test_bts_stale_military_is_noise(text):
    assert f._is_stale_knowledge_noise(text)
    assert f.is_lesson_noise(text)


@pytest.mark.parametrize("text", REAL_ERRORS)
def test_real_errors_survive(text):
    assert not f._is_kb_absence_noise(text)
    assert not f._is_stale_knowledge_noise(text)
    out = f._strip_cta_noise({"critical": [text], "high": [], "medium": []})
    assert out["critical"] == [text]


def test_strip_removes_noise_and_keeps_rest():
    r = {"critical": [FALSE_POSITIVES[0], REAL_ERRORS[0], BTS_STALE[0]], "high": [], "medium": []}
    assert f._strip_cta_noise(r)["critical"] == [REAL_ERRORS[0]]


def test_scope_complaint_stays_in_result_but_not_in_lessons():
    t = "この記事はK-POPと完全に無関係なハリウッド映画に関する記事であり、K-pop専門メディアの校閲対象ではない。"
    assert f._strip_cta_noise({"critical": [t]})["critical"] == [t]
    assert f.is_lesson_noise(t)


def test_prompt_states_scope_and_current_facts():
    p = f.KPOP_FACTCHECK_PREFIX
    assert "韓国ドラマ" in p and "載っていないことを理由に" in p
    assert "2025年6月に全員が除隊" in p and "ジョンヨン" in p


OUTLOOK_FALSE_POSITIVES = [
    "末尾に『今後の注目ポイント』という箇条書きの構成案・取材メモがそのまま本文に残存しており、編集未完成の内容が公開されている(過去指摘事例と同型の問題)。",
    "本文中に『今後の注目ポイント』という箇条書きの構成案・取材メモがそのまま本文として残存しており、編集未完成の内容が公開されている。",
]


@pytest.mark.parametrize("text", OUTLOOK_FALSE_POSITIVES)
def test_outlook_section_is_noise(text):
    # 「今後の注目ポイント」は生成プロンプトが必ず付ける定型セクション
    assert f._is_outlook_section_noise(text)
    assert f.is_lesson_noise(text)
    out = f._strip_cta_noise({'critical': [text], 'high': [text]})
    assert out['critical'] == [] and out['high'] == []


def test_outlook_section_real_issue_kept():
    text = "『今後の注目ポイント』に挙げた来日公演の日程が本文の日程と食い違っている。"
    assert not f._is_outlook_section_noise(text)


def test_prompt_allows_outlook_section():
    assert '今後の注目ポイント' in f.KPOP_FACTCHECK_PREFIX
