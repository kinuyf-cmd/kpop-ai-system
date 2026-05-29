"""非K-POPトピック除外フィルタ (2026-05-29)

XPORTSNEWS「엑's 이슈」等の混在型セクションが掲載する、サイト主題と無関係な
コンテンツ(婚活リアリティ番組の一般人出演者・政治論争・非アイドル芸能ゴシップ)の
記事化を防ぐ。collector と pre_publish_gate の両方から呼ばれる単一の判定点。

設計: docs/superpowers/specs/2026-05-29-non-kpop-topic-filter-design.md

照合規則は korean_base.is_kpop_related と揃える:
  - ハングルKW: substring + 直前ハングルなら部分一致疑いで却下
  - ASCII KW: ASCII単語境界必須
"""
import json
import os
import re

from lib.collectors.korean_base import is_kpop_related, GENERIC_EVENT_KW

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'config', 'ng_topics.json',
)

# politics / non_idol_celebrity_gossip は固有アーティスト名が共在すれば誤爆を避けて
# キャンセルする。reality_show_civilian(番組名固有名詞)は無条件で弾く。
_ARTIST_CANCELS = frozenset({'politics', 'non_idol_celebrity_gossip'})


def _load_ng_topics():
    with open(_CONFIG_PATH, encoding='utf-8') as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith('_')}


_NG_TOPICS = _load_ng_topics()


def _kw_matches(kw, text_lower):
    """korean_base と同じ部分一致規則で kw が text に含まれるか判定。"""
    kw_lower = kw.lower()
    has_hangul = bool(re.search(r'[가-힯]', kw))
    if has_hangul:
        m = re.search(re.escape(kw_lower), text_lower)
        if not m:
            return False
        if m.start() > 0 and re.match(r'[가-힯]', text_lower[m.start() - 1]):
            return False  # 直前ハングル = 部分一致疑い
        return True
    # ASCII: 単語境界必須
    for m in re.finditer(re.escape(kw_lower), text_lower):
        s, e = m.start(), m.end()
        before_ok = s == 0 or not (text_lower[s - 1].isascii() and text_lower[s - 1].isalnum())
        after_ok = e == len(text_lower) or not (text_lower[e].isascii() and text_lower[e].isalnum())
        if before_ok and after_ok:
            return True
    return False


def _has_proper_artist(text):
    """固有アーティスト名(ジェネリック語・事務所略号でない)が含まれるか。"""
    matches = is_kpop_related(text) or []
    return any(kw not in GENERIC_EVENT_KW for kw in matches)


def classify_non_kpop_topic(text):
    """非K-POPトピックなら理由カテゴリ名(str)を返す。問題なければ None。"""
    if not text:
        return None
    tl = text.lower()
    has_artist = None  # 遅延評価
    for category, keywords in _NG_TOPICS.items():
        for kw in keywords:
            if not _kw_matches(kw, tl):
                continue
            if category in _ARTIST_CANCELS:
                if has_artist is None:
                    has_artist = _has_proper_artist(text)
                if has_artist:
                    continue  # 固有アーティスト共在 → 正当なK-POP記事として通す
            return category
    return None
