"""表記ガード: 翻訳で化けた固有名詞を、LLMに頼らず決定的に検出する(2026-11-18)。

背景: factcheck_v2 は誤検知対策で「人名の表記揺れ」を報告しない設計のため、
表記の誤りを見る担当がいなかった。実例:
  - 백지헌 → 「ペク・ジヘン」(正: ペク・ジホン)。辞書未登録で読みをモデルが推測
  - 체포하겠어 → 「体ポハゲッソ」。頭の 체 だけ漢字(体)化し残りを音写。ハングル0字で残存検査も通過

検査は3つ:
  1. dict_notation_mismatch : 元記事タイトルにある辞書登録の人名が、記事で正表記になっていない
  2. kanji_katakana_hybrid  : 「」『』内の「漢字1字+カタカナ4字以上」の造語
  3. name_inconsistency     : 同じ記事の中で、同じ姓の人名が1字違いで2通りに書かれている
  4. roman_notation_mismatch: 元記事タイトルのローマ字人名(Jeongyeon等)が、正表記で書かれていない
     (2026-11-24: 「TWICEチョン・ヨン」と題に出た。本文は「ジョンヨン」で、1〜3は全て素通りした)
"""
import difflib
import json
import os
import re

_DICT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'config', 'korean_proper_nouns.json')
_NAME_SECTIONS = ('members', 'personalities')

_KATA = 'ァ-ヺー'          # ァ-ヺ + ー
_NAME_RE = re.compile(rf'[{_KATA}]{{1,4}}・[{_KATA}]{{2,5}}')
_QUOTE_RE = re.compile(r'[「『]([^」』]{1,40})[」』]')
# 先頭が漢字1字(直前も漢字でない)+ カタカナ4字以上。「新ジャンル」等の一般語は
# 実測で拾わないよう、引用符の中身全体がこの形の時だけ判定する(括弧の補足は除外)
_HYBRID_RE = re.compile(rf'^[一-鿿][{_KATA}]{{4,}}$')

# 日本語で「漢字1字+カタカナ語」を普通に作る接頭漢字(新ジャンル/超カワイイ/神ステージ 等)は除外
_JA_PREFIX_KANJI = set('新超神真激爆大小全各初再元旧最裏表純生名高低反非無不半約準副総')

_dict_cache = None
_ROMAN_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'config', 'roman_name_map.json')


def _load_roman_map():
    try:
        with open(_ROMAN_PATH, encoding='utf-8') as f:
            return {k: v for k, v in json.load(f).items() if not k.startswith('_')}
    except Exception:
        return {}


def _strip_html(html):
    return re.sub(r'<[^>]+>', ' ', html or '')


def _load_name_dict():
    global _dict_cache
    if _dict_cache is None:
        try:
            with open(_DICT_PATH, encoding='utf-8') as f:
                d = json.load(f)
            vals = {}
            for sec in _NAME_SECTIONS:
                for ko, v in (d.get(sec) or {}).items():
                    if isinstance(v, str) and '・' in v and _NAME_RE.fullmatch(v):
                        vals[v] = ko
            _dict_cache = vals
        except Exception:
            _dict_cache = {}
    return _dict_cache


def _edit1_same_len(a, b):
    return len(a) == len(b) and a != b and sum(x != y for x, y in zip(a, b)) == 1


def _names(text):
    return set(_NAME_RE.findall(text))


def check_notation(title, body_html, source_title=None, name_dict=None, roman_map=None):
    """Returns list of issue dicts (pre_publish_gate 形式)。"""
    text = f'{title or ""}\n{_strip_html(body_html)}'
    issues = []
    names = _names(text)
    nd = _load_name_dict() if name_dict is None else name_dict

    # 1. 元記事タイトルにある辞書登録の人名(フルネーム)が、正表記で書かれているか
    #    (2026-11-18実測: 「辞書の1字違い」方式は30日403本で9件中9件が別人の誤検知
    #     =キム・ダヒョン/キム・スヒョン。韓国人名は短く1字違いは普通に別人なので、
    #     元記事に実際に出ている人物だけを照合する方式にした)
    if source_title:
        for v, ko in nd.items():
            if ko in source_title and v not in text:
                issues.append({
                    'type': 'dict_notation_mismatch', 'severity': 'block',
                    'detail': f'人名表記の誤り: 元記事の「{ko}」は「{v}」と書く(記事に正表記がない)',
                })

    # 4. ローマ字の人名(元記事タイトル)が正表記で書かれているか。題と本文の両方を見る:
    #    題だけ誤表記で本文が正しい場合、本文に正表記があっても題の誤りは残るので、題を優先して照合する
    rm = _load_roman_map() if roman_map is None else roman_map
    if source_title and rm:
        for rom, ja in rm.items():
            if not re.search(rf'(?<![A-Za-z]){re.escape(rom)}(?![A-Za-z])', source_title, re.I):
                continue
            if ja not in text:
                issues.append({
                    'type': 'roman_notation_mismatch', 'severity': 'block',
                    'detail': f'人名表記の誤り: 元記事の「{rom}」は「{ja}」と書く(記事に正表記がない)',
                })
                continue
            # 本文は正表記でも、題に似た別表記(チョン・ヨン等)が出ていれば誤り
            if ja not in (title or ''):
                for tok in re.findall(rf'[{_KATA}・]{{3,10}}', title or ''):
                    n = tok.replace('・', '')
                    if n != ja and difflib.SequenceMatcher(None, n, ja).ratio() >= 0.75:
                        issues.append({
                            'type': 'roman_notation_mismatch', 'severity': 'block',
                            'detail': f'人名表記の誤り: タイトルの「{tok}」は「{ja}」の誤表記の疑い(元記事は「{rom}」)',
                        })
                        break

    # 2. 漢字1字+カタカナの造語
    seen = set()
    for q in _QUOTE_RE.findall(text):
        core = re.sub(r'[\(（].*$', '', q).strip()
        if core not in seen and _HYBRID_RE.match(core) and core[0] not in _JA_PREFIX_KANJI:
            seen.add(core)
            issues.append({
                'type': 'kanji_katakana_hybrid', 'severity': 'block',
                'detail': f'翻訳で化けた造語の疑い: 「{core}」(ハングルの一部が漢字化し残りを音写した形)',
            })

    # 3. 記事内の表記不一致(同じ姓・1字違い)
    flagged = set()
    lst = sorted(names)
    for i, a in enumerate(lst):
        for b in lst[i + 1:]:
            sa, ga = a.split('・', 1)
            sb, gb = b.split('・', 1)
            if sa == sb and _edit1_same_len(ga, gb) and len(ga) >= 2:
                key = (a, b)
                if key not in flagged:
                    flagged.add(key)
                    issues.append({
                        'type': 'name_inconsistency', 'severity': 'block',
                        'detail': f'同じ人物の表記が2通りの疑い: 「{a}」と「{b}」',
                    })
    return issues
