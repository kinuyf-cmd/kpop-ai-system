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
    th = count_hangul(title)
    ah = count_hangul(alt_text)
    bh = count_hangul(body_text)

    # タイトル / alt は1字でもアウト（公開破壊レベル）
    if th > 0:
        return {
            'verdict': 'BLOCK',
            'title_hangul': th, 'body_hangul': bh, 'alt_hangul': ah,
            'reason': f'タイトルにハングル{th}字混入 (翻訳漏れ)',
            'samples': find_hangul_samples(title),
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
