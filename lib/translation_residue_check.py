"""韓国語→日本語翻訳の残存ハングル検査 (共通lib)

translate_ko_to_ja が固有名詞・曲名・グループ名を訳し漏らすと、
タイトルや本文にハングルが残る。これは公開破壊レベルの事故になるため、
共通lib化して全公開経路から呼び出せるようにする。

使用箇所:
  - lib/pre_publish_gate.py (公開直前 BLOCK/WARN 判定)
  - tools/regenerate_thumbnail_wp.py (alt 検査)
  - audit/* (監査での検出)
"""
import re

# Hangul Syllables (가-힯) + Hangul Jamo (ᄀ-ᇿ) + Hangul Compatibility Jamo (㄰-㆏)
_HANGUL_RE = re.compile(r'[가-힯ᄀ-ᇿ㄰-㆏]')


def count_hangul(text: str) -> int:
    """テキスト中のハングル文字数を返す"""
    if not text:
        return 0
    return len(_HANGUL_RE.findall(text))


def has_hangul(text: str) -> bool:
    """ハングル文字を1文字でも含むか"""
    if not text:
        return False
    return bool(_HANGUL_RE.search(text))


def find_hangul_samples(text: str, n: int = 3) -> list[str]:
    """ハングルを含むコンテキスト断片を最大N個返す（デバッグ／報告用）"""
    if not text:
        return []
    samples = []
    seen = set()
    for m in _HANGUL_RE.finditer(text):
        start = max(0, m.start() - 10)
        end = min(len(text), m.end() + 10)
        snippet = text[start:end].strip()
        if snippet and snippet not in seen:
            seen.add(snippet)
            samples.append(snippet)
            if len(samples) >= n:
                break
    return samples


def _strip_quoted_proper_nouns(text: str) -> str:
    """引用符内 ('...' "..." 「...」) は固有名詞 (楽曲名/番組名) なので残存判定対象から除外
    例: BABYMONSTER「춤(CHOOM)」ライブ → 「춤(CHOOM)」を除いた残りで判定
    2026-05-10: 楽曲名のhangul残存で速報記事BLOCKされる事故対策
    """
    # 「」 ‘’ '' "" 内をスペース置換
    return re.sub(r"[「『\"'‘’“”][^」』\"'‘’“”]{1,30}[」』\"'‘’“”]", ' ', text)


# ハングル語 + （日本語gloss）: 양평군（ヤンピョングン）/ 경기사회복지공동모금회（京畿社会福祉共同募金会）
_HANGUL_TERM_GLOSS_RE = re.compile(
    r'[가-힯ᄀ-ᇿ㄰-㆏][가-힯ᄀ-ᇿ㄰-㆏\s·]{0,24}\s?[（(][^（）()]{1,30}[）)]')
# （ハングル併記）: BTS（방탄소년단）
_PAREN_SPAN_RE = re.compile(r'[（(][^（）()]{1,30}[）)]')


def _strip_proper_noun_glosses(text: str) -> str:
    """本文中の意図的な固有名詞併記/glossを残存判定対象から除外する。

    2026-07-04: body_translate_fail×351の実測で、BLOCK本文のハングルは
    「양평군（ヤンピョングン）」「BTS（방탄소년단）」のような固有名詞gloss
    だった(未翻訳文章ではない)。gloss形式は読者に読みが提供されており
    公開破壊でないため除外。括弧に入らない生の未翻訳文は従来通り残す。
    """
    if not text:
        return text
    text = _HANGUL_TERM_GLOSS_RE.sub(' ', text)
    return _PAREN_SPAN_RE.sub(
        lambda m: ' ' if _HANGUL_RE.search(m.group(0)) else m.group(0), text)


def assess_residue(title: str, body_text: str, alt_text: str = '') -> dict:
    """記事の翻訳残存ハングルを評価して verdict を返す

    Returns:
        {
            'verdict': 'PASS' | 'WARN' | 'BLOCK',
            'title_hangul': int,
            'body_hangul': int,
            'alt_hangul': int,
            'reason': str,
            'samples': [...],
        }
    """
    # 引用符内 (楽曲名・番組名) の固有名詞hangulは除外して判定
    # 2026-05-11: body_text にも適用 (チャート記事の楽曲名hangul誤検知対策)
    title_check = _strip_quoted_proper_nouns(title)
    alt_check = _strip_quoted_proper_nouns(alt_text)
    # 本文のみ gloss形式(固有名詞+括弧併記)も除外 (2026-07-04 skip率43%対策)。
    # タイトル/altは表示破壊リスクが高いため従来の厳格判定を維持。
    body_check = _strip_proper_noun_glosses(_strip_quoted_proper_nouns(body_text))

    th = count_hangul(title_check)
    ah = count_hangul(alt_check)
    bh = count_hangul(body_check)

    # タイトル / alt は1字でもアウト（公開破壊レベル、ただし引用符内固有名詞は許容）
    if th > 0:
        return {
            'verdict': 'BLOCK',
            'title_hangul': th, 'body_hangul': bh, 'alt_hangul': ah,
            'reason': f'タイトルにハングル{th}字混入 (翻訳漏れ)',
            'samples': find_hangul_samples(title_check),
        }
    if ah > 0:
        return {
            'verdict': 'BLOCK',
            'title_hangul': th, 'body_hangul': bh, 'alt_hangul': ah,
            'reason': f'画像alt文字列にハングル{ah}字混入',
            'samples': find_hangul_samples(alt_text),
        }
    # 本文ハングル: 20字超で BLOCK→draft化、5字超で WARN
    if bh >= 20:
        return {
            'verdict': 'BLOCK',
            'title_hangul': th, 'body_hangul': bh, 'alt_hangul': ah,
            'reason': f'本文にハングル{bh}字残存 (翻訳パイプライン破綻の疑い)',
            'samples': find_hangul_samples(body_text),
        }
    if bh >= 5:
        return {
            'verdict': 'WARN',
            'title_hangul': th, 'body_hangul': bh, 'alt_hangul': ah,
            'reason': f'本文にハングル{bh}字残存 (許容範囲だが要確認)',
            'samples': find_hangul_samples(body_text),
        }
    return {
        'verdict': 'PASS',
        'title_hangul': th, 'body_hangul': bh, 'alt_hangul': ah,
        'reason': '',
        'samples': [],
    }
