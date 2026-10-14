"""翻訳品質の強化(2026-10-14)の回帰テスト。

- 本文の見出しにハングルが1字でも残れば止める(本文の総数が少なくても)
- 直訳語・日本人名の音写を公開前に直す
- 3行まとめが「N.Flying」のような英字表記の途中で文を切らない
- 残りやすい語(써클/한터/화보)と日本人名が辞書で置き換わる
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.article_summarizer import _split_sentences  # noqa: E402
from lib.korean_translator import apply_proper_noun_dict, fix_translation_calques  # noqa: E402
from lib.pre_publish_gate import _heading_hangul  # noqa: E402


def test_heading_with_hangul_is_detected():
    html = '<h2>써클チャート1位・한터チャート2位で初動好成績</h2><p>本文。</p>'
    assert _heading_hangul(html)


def test_heading_with_quoted_title_or_gloss_is_allowed():
    html = '<h2>新曲「춤」を披露</h2><h3>BTS（방탄소년단）が首位</h3><h2>普通の見出し</h2>'
    assert _heading_hangul(html) == []


def test_calques_and_japanese_names_fixed():
    out, n = fix_translation_calques('ミチエダ・シュンスケが化報を公開。自体コンテンツも配信。コチェラに出演。')
    assert out == '道枝駿佑が画報を公開。自主コンテンツも配信。コーチェラに出演。'
    assert n == 4


def test_plain_jitai_is_left_alone():
    out, n = fix_translation_calques('それ自体は問題ない。')
    assert out == 'それ自体は問題ない。' and n == 0


def test_summary_does_not_split_inside_abbreviation():
    s = _split_sentences('バンドN.Flyingがミニ9集をリリースし、好スタートを切った。次の文もここにある長さです。')
    assert s[0].startswith('バンドN.Flying')
    assert not any(x.startswith('Flying') for x in s)


def test_chart_names_and_photoshoot_translated_before_translation():
    out, _ = apply_proper_noun_dict('써클차트 1위, 한터차트 2위, 화보 공개', context_aware=True)
    assert 'サークルチャート' in out and 'ハンターチャート' in out and '画報' in out


def test_japanese_celebrity_name_translated():
    out, _ = apply_proper_noun_dict('미치에다 슌스케가 참석', context_aware=True)
    assert '道枝駿佑' in out
