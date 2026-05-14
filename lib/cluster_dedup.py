#!/usr/bin/env python3
"""cluster duplicate publish 防止 共通 lib

全 publisher (simple_publish_pipeline / cluster_generator / breaking_news_detector
/ search_driven_generator 等) が publish 直前に呼べる共通 dedup 関数を提供する。

2026-05-14 監査で KATSEYE TOUR (23000/23006/23144) / LE SSERAFIM グッズ (23234/23237)
/ BTS V コーンドッグ (23173/23249) の3クラスタ計 8 記事が短時間内に重複 publish
された事故への根治。breaking_news_detector.py に閉じていた dedup ロジックを共通化。
"""
import os
import re
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Iterable

WP_API = 'https://www.kpopjournal.tokyo/wp-json/wp/v2'
HOOK_LOG = '/home/aiuser/kpop-ai-system/logs/cluster_dedup_blocks.jsonl'
# 直近 publish の title sliding-window file (WP indexing lag 吸収)
# publish 成功直後に append、cluster_dedup_check 時に WP search 結果と OR で参照
RECENT_PUBLISH_BUFFER = '/home/aiuser/kpop-ai-system/logs/recent_published_titles.jsonl'

# アーティスト/メンバー名の表記揺れ正規化 (英字 ⇔ カタカナ)
# breaking_news_detector.py から移植 (commit 6a8962a)
_NAME_NORMALIZE = {
    'Jimin': 'ジミン', 'jimin': 'ジミン', 'JIMIN': 'ジミン',
    'Jungkook': 'ジョングク', 'JUNGKOOK': 'ジョングク',
    'Jin': 'ジン', 'JIN': 'ジン',
    'Suga': 'シュガ', 'SUGA': 'シュガ',
    'V': 'V', 'テテ': 'V',
    'RM': 'RM',
    'J-Hope': 'ジェイホープ', 'JHope': 'ジェイホープ',
    'Taehyung': 'V', 'TAEHYUNG': 'V', 'テヒョン': 'V',
    'BTS': 'BTS', '防弾少年団': 'BTS',
    'BLACKPINK': 'BLACKPINK', 'ブラックピンク': 'BLACKPINK',
    'Lisa': 'リサ', 'LISA': 'リサ',
    'Jennie': 'ジェニ', 'JENNIE': 'ジェニ',
    'Rose': 'ロゼ', 'ROSE': 'ロゼ', 'Rosé': 'ロゼ',
    'Jisoo': 'ジス', 'JISOO': 'ジス',
    'NewJeans': 'NewJeans', 'ニュージーンズ': 'NewJeans',
    'IVE': 'IVE', 'アイブ': 'IVE',
    'Wonyoung': 'ウォニョン', 'WONYOUNG': 'ウォニョン',
    'Yujin': 'ユジン', 'YUJIN': 'ユジン',
    'aespa': 'aespa', 'エスパ': 'aespa', 'Aespa': 'aespa',
    'Karina': 'カリナ', 'KARINA': 'カリナ',
    'Winter': 'ウィンター', 'WINTER': 'ウィンター',
    'Ningning': 'ニンニン', 'NINGNING': 'ニンニン',
    'Giselle': 'ジゼル', 'GISELLE': 'ジゼル',
    'KATSEYE': 'KATSEYE', 'カットアイ': 'KATSEYE', 'キャットアイ': 'KATSEYE',
    'LE SSERAFIM': 'LE SSERAFIM', 'ルセラフィム': 'LE SSERAFIM',
    'ILLIT': 'ILLIT', 'アイリット': 'ILLIT',
    'MAMAMOO': 'MAMAMOO', 'ママムー': 'MAMAMOO',
    'CORTIS': 'CORTIS',
    'ATEEZ': 'ATEEZ', 'エイティーズ': 'ATEEZ',
    'TWICE': 'TWICE', 'トゥワイス': 'TWICE',
    'MONSTA X': 'MONSTA X', 'モンスタエックス': 'MONSTA X',
    'Red Velvet': 'Red Velvet', 'レッドベルベット': 'Red Velvet',
    'Joy': 'ジョイ', 'JOY': 'ジョイ',
    'Irene': 'アイリーン', 'IRENE': 'アイリーン',
}

_STOP = {'ガイド', '完全', '最新', '徹底', '紹介', '解説', 'まとめ', '速報', '必見',
         '発表', '公開', '判明', '披露', '批判', '反発', '受ける', '招く',
         '無視', '扱い'}

# 2-word group 名を 1 トークン化 (Red Velvet / LE SSERAFIM 等)
# これをしないと "Red Velvet ジョイ" と "Red Velvet アイリーン" が
# proper_overlap=2 (Red+Velvet) で誤って同テーマ判定される
_MULTIWORD_GROUPS = [
    'Red Velvet', 'LE SSERAFIM', 'MONSTA X',
]


def _collapse_multiword_groups(t: str) -> str:
    for g in _MULTIWORD_GROUPS:
        if g in t:
            t = t.replace(g, g.replace(' ', '_'))
    return t


def _normalize_keywords(words: set) -> set:
    return {_NAME_NORMALIZE.get(w, w) for w in words}


def _extract_kw(t: str) -> set:
    t = _collapse_multiword_groups(t)
    kw = set(re.findall(r'[A-Za-z][A-Za-z_]+|[ァ-ヶー]{3,}|[一-龥]{2,}', t))
    return _normalize_keywords(kw) - _STOP


def _kanji_substring_overlap(s1: set, s2: set) -> int:
    """漢字熟語の包含チェック: s1 中の漢字語が s2 中のどれかに含まれる/含むなら 1 個カウント"""
    count = 0
    kanji_s1 = {w for w in s1 if re.match(r'^[一-龥]+$', w)}
    kanji_s2 = {w for w in s2 if re.match(r'^[一-龥]+$', w)}
    matched = set()
    for w1 in kanji_s1:
        for w2 in kanji_s2:
            if w1 == w2 or w1 in w2 or w2 in w1:
                if w1 not in matched:
                    matched.add(w1)
                    count += 1
                break
    return count


def is_duplicate_title(candidate: str, recent_titles: Iterable[str]) -> tuple[bool, str]:
    """候補タイトルが直近 publish 済記事と重複するかチェック

    Returns:
        (is_duplicate: bool, matched_title: str)

    判定条件:
      - 固有名詞 (英字/カタカナ) 2個以上の exact 一致 → dup
      - 固有名詞1個 + 漢字熟語包含1個 → dup
      - 全体3個以上の exact 一致 → dup
    """
    new_kw = _extract_kw(candidate)
    if not new_kw:
        return False, ''
    for rt in recent_titles:
        if not rt:
            continue
        rt_kw = _extract_kw(rt)
        if not rt_kw:
            continue
        exact_overlap = new_kw & rt_kw
        proper_overlap = {w for w in exact_overlap
                          if re.match(r'[A-Za-z]|[ァ-ヶー]', w)}
        kanji_overlap = _kanji_substring_overlap(new_kw, rt_kw)
        if len(proper_overlap) >= 2:
            return True, rt
        if len(proper_overlap) >= 1 and kanji_overlap >= 1:
            return True, rt
        if len(exact_overlap) >= 3:
            return True, rt
    return False, ''


def fetch_recent_wp_titles(hours: int = 3, per_page: int = 50,
                           exclude_post_id: int | None = None) -> list[str]:
    """WP REST API で直近 hours 内に publish 済みの記事タイトル一覧を取得

    Args:
        hours: 何時間前まで遡るか
        per_page: 1ページあたり最大件数
        exclude_post_id: 自身の post_id (publish 直前 self-match 除外用)
    """
    after = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    qs = urllib.parse.urlencode({
        'after': after, 'per_page': per_page,
        'status': 'publish',
        '_fields': 'id,title',
        'orderby': 'date', 'order': 'desc',
    })
    titles = []
    try:
        req = urllib.request.Request(f'{WP_API}/posts?{qs}')
        with urllib.request.urlopen(req, timeout=15) as r:
            for p in json.loads(r.read()):
                if exclude_post_id and p.get('id') == exclude_post_id:
                    continue
                t = p.get('title', {})
                t = t.get('rendered', '') if isinstance(t, dict) else str(t)
                if t:
                    titles.append(t)
    except Exception:
        pass
    return titles


def _read_recent_buffer(hours: int) -> list[str]:
    """直近 publish された title sliding-window を読む (WP indexing lag 吸収)"""
    if not os.path.exists(RECENT_PUBLISH_BUFFER):
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    titles = []
    try:
        with open(RECENT_PUBLISH_BUFFER, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                ts_str = d.get('ts', '')
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str)
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                t = d.get('title', '')
                if t:
                    titles.append(t)
    except Exception:
        pass
    return titles


def record_publish(title: str, post_id: int | None = None,
                   source: str = '') -> None:
    """publish 成功直後に call。次の publisher の WP indexing lag 吸収用。"""
    if not title:
        return
    try:
        os.makedirs(os.path.dirname(RECENT_PUBLISH_BUFFER), exist_ok=True)
        with open(RECENT_PUBLISH_BUFFER, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'ts': datetime.now(timezone.utc).isoformat(),
                'title': title,
                'post_id': post_id,
                'source': source,
            }, ensure_ascii=False) + '\n')
    except Exception:
        pass


def cluster_dedup_check(candidate_title: str, *,
                       hours: int = 3,
                       extra_titles: Iterable[str] = (),
                       exclude_post_id: int | None = None,
                       source: str = '') -> tuple[bool, str]:
    """publish 直前の cluster duplicate gate

    Args:
        candidate_title: 公開しようとしている記事のタイトル
        hours: 直近何時間内の記事と比較するか
        extra_titles: WP search に出てこない just_published 候補等を追加
        exclude_post_id: 自身の post_id (再 publish hook 内での self-match 除外用)
        source: caller 識別 (log 用)

    Returns:
        (is_duplicate, matched_title)
    """
    recent = fetch_recent_wp_titles(hours=hours, exclude_post_id=exclude_post_id)
    buffer = _read_recent_buffer(hours=hours)
    all_titles = list(recent) + list(buffer) + list(extra_titles)
    is_dup, matched = is_duplicate_title(candidate_title, all_titles)
    if is_dup:
        try:
            with open(HOOK_LOG, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    'ts': datetime.now(timezone.utc).isoformat(),
                    'source': source,
                    'candidate': candidate_title,
                    'matched': matched,
                    'exclude_post_id': exclude_post_id,
                    'hours': hours,
                }, ensure_ascii=False) + '\n')
        except Exception:
            pass
    return is_dup, matched
