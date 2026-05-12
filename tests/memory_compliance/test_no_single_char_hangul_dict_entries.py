"""
memory: feedback_no_single_char_hangul_dict_entries.md
規定: korean_proper_nouns.json の groups / members 等の翻訳辞書には
       1文字hangul (U+AC00-U+D7A3) のキーを置いてはならない。

理由: 1文字 hangul は他の K-POP 名や一般語の substring として誤マッチし、
       人物取り違えを誘発する (例: `진`→JIN が `진니`(Jinni)/`진서`(Jinseo) 等の
       前置部分にマッチして誤って JIN に変換される)。

過去事故:
- 2026-05-11 `4d44449` 진/비 を辞書から削除 + LLM 文脈翻訳指示で対処
- 2026-05-12 本セッション 탑(T.O.P) / 뷔(V) / 키(KEY) を削除

代替: LLM (GPT-4o-mini / Claude) はメンバー名を文脈で正しく訳せる
("BTS 뷔" → "BTS V") ため、1文字 entry は LLM 翻訳に委ねる。
"""
import json

DICT_PATH = '/home/aiuser/kpop-ai-system/config/korean_proper_nouns.json'


def _scan_single_char_hangul(obj, path=''):
    """再帰的に1文字hangul key を探す"""
    violations = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.startswith('_'):
                continue
            if isinstance(v, (dict, list)):
                violations.extend(_scan_single_char_hangul(v, f'{path}/{k}'))
            else:
                if isinstance(k, str) and len(k) == 1 and 0xAC00 <= ord(k) <= 0xD7A3:
                    violations.append((path or 'root', k, v))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            violations.extend(_scan_single_char_hangul(v, f'{path}[{i}]'))
    return violations


def test_korean_proper_nouns_no_single_char_hangul():
    """korean_proper_nouns.json に 1 文字 hangul キーが残っていないこと"""
    with open(DICT_PATH, encoding='utf-8') as f:
        d = json.load(f)
    violations = _scan_single_char_hangul(d)
    assert not violations, (
        "翻訳辞書に 1 文字 hangul キーが残存。substring trap で誤マッチ誘発:\n  " +
        "\n  ".join(f"{path}: {k!r} → {v!r}" for path, k, v in violations)
    )
