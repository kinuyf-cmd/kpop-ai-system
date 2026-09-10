"""factcheck のローマ字表記ノイズ除去(2026-09-10)

韓国語のローマ字表記は日本語カタカナと一対一に対応しない。
LLM が英語ソース(HanCinema等)のローマ字を根拠に「日本語表記が誤り」と
critical を出す誤検知があり、pot+593 の最大機会が着手不能になっていた。

実例: 『鉄槌教師』の女優を「チン・ギジュ」と書いた記事に対し
`Jin Ki-joo` を根拠に「ジンが正しい」と指摘 —
日本語版Wikipedia/オリコンでは「チン・ギジュ」が正しく、記事の方が正しかった。

一方、初版の正規表現は緩すぎて **正当な critical 3件まで除去**していた。
このテストはその両方を固定する。
"""
import sys

sys.path.insert(0, "/home/aiuser/kpop-ai-system")

from lib.factcheck_v2 import _is_romaji_name_noise


NOISE = [
    # ローマ字を根拠にカナ表記の姓だけを否定している = 誤検知
    "「イム・ハンリム 演: チン・ギジュ」と記載されているが、web検索(HanCinema)に"
    "よれば同役はJin Ki-joo(ジン・ギジュ)が演じており、姓が『チン』ではなく"
    "『ジン』であるべき。姓の誤記であり人名間違いに該当する疑いがある。",
]

REAL_ISSUES = [
    # 別人物の混同(ローマ字が併記されていても実体のある誤り)
    "「Leeseo・ジン」という人名がIVEのLeeseo(이서)を想起させるが、本文の文脈からは"
    "俳優の『イ・ソジン』(Lee Seo-jin、俳優)を指している可能性が高く、"
    "IVEのLeeseoとは無関係の人物と誤認・混同させる表記になっている。",
    # 漢字表記そのものの誤り
    "本文中で「朴珉貴（パク・ギュリ、37歳）」という氏名表記が誤り。"
    "実名は박규리（Park Gyu-ri）であり、「朴珉貴」という漢字表記は別人と考えられる。",
    # タイトルと本文でグループが完全に違う
    "タイトルは『LE SSERAFIM ウォニョンとミナミの美貌話題』となっているが、"
    "本文は一貫して『RESCENE』というグループについて記述しており、"
    "LE SSERAFIMとは全く別のグループ・メンバーである。",
    # ローマ字と無関係な通常の critical
    "メンバー数が5人と記載されているが実際は6人である",
    "本文中の『コンサート観覧の申し込みは段階的に行われ』という記述は捏造の疑い",
]


def test_romaji_name_noise_is_detected():
    for text in NOISE:
        assert _is_romaji_name_noise(text), f"誤検知を除去できていない: {text[:60]}"


def test_real_name_errors_are_kept():
    for text in REAL_ISSUES:
        assert not _is_romaji_name_noise(text), f"正当な指摘を消している: {text[:60]}"


def test_empty_and_non_string_are_safe():
    for value in ("", None, 123, [], {}):
        assert _is_romaji_name_noise(value) is False
