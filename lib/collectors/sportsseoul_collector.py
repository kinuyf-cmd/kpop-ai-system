#!/usr/bin/env python3
"""Sports Seoul (스포츠서울) scraper

トップページ (https://www.sportsseoul.com/) が /news/read/<id> 記事リンクを
静的に出力する唯一の確実な経路 (セクションlistは全404・navはJS依存)。
収集範囲は owner 決定により韓流芸能全般:
  - K-POP は is_kpop_related で従来通り
  - K-POP 不在でも芸能語 (드라마/배우/예능/OST/한류 等) を含めば '한류' signal 化
  - スポーツ専用語 (축구/야구/배구/감독/리그/월드컵/시구 等) は除外
signal 段階の過剰収集は許容 (記事化は下流の非K-POPトピック除外フィルタ476ed0aが最終防御)。
"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import (
    fetch_html, is_kpop_related, is_urgent, save_signals, make_signal, log, clean_title,
)

# 韓流芸能ゲート (K-POP ゲートを通らなかったタイトルの second-chance)
_ENT_KW = [
    '드라마', '영화', '예능', '배우', 'ost', '한류', '넷플릭스', '디즈니+', '티빙',
    '주연', '출연', '방영', '시즌', '캐스팅', '뮤지컬', '미니시리즈', '시사회',
    '컴백', '신곡', '데뷔',  # 芸能寄りだが korean_base GENERIC と重複しても無害
]
# スポーツ記事を弾く除外語 (Sports Seoul はスポーツ紙のため必須)。
# K-POP generic語 (1위/데뷔 等) が NPB野球記事(「데뷔 첫 홈런」「ERA 1위」)を
# 誤通過させる実例を確認したため、is_kpop_related の前段でも適用する。
_SPORTS_KW = [
    '축구', '야구', '배구', '농구', '골프', '감독', '리그', '월드컵', '시구',
    '구단', '선수', '경기', 'kbo', 'k리그', '프로야구', '대표팀', '승부',
    '홈런', '투수', '타자', '쿼터', 'npb', 'mlb', 'era', '득점', '결승골',
]


def is_sports(title: str) -> bool:
    """スポーツ紙由来の純スポーツ記事か。アーティスト名より優先して弾く。"""
    return any(s in title.lower() for s in _SPORTS_KW)


def is_entertainment(title: str) -> bool:
    """K-POP 以外の韓流芸能か。芸能語を含む場合 True (スポーツ除外は呼び出し側)。"""
    tl = title.lower()
    return any(k in tl for k in _ENT_KW)


def collect():
    signals = []
    try:
        html = fetch_html('https://www.sportsseoul.com/')
    except Exception as e:
        log(f"Sports Seoul fetch error: {e}")
        return 0

    pat = r'<a[^>]+href="(/news/read/\d+)"[^>]*>((?:<[^>]*>|[^<]){5,200})</a>'
    seen = set()
    for m in re.finditer(pat, html, re.DOTALL):
        path = m.group(1)
        title = clean_title(m.group(2))
        url = 'https://www.sportsseoul.com' + path
        if url in seen or len(title) < 5:
            continue
        seen.add(url)
        # スポーツ紙のため純スポーツ記事は K-POP generic語(1위/데뷔等)に
        # 引っかかっても先に弾く
        if is_sports(title):
            continue
        keywords = is_kpop_related(title)
        if not keywords:
            if is_entertainment(title):
                keywords = ['한류']
            else:
                continue
        signals.append(make_signal('sports_seoul', title, url, keywords, is_urgent(title)))
        if len(signals) >= 20:
            break

    save_signals(signals)
    log(f"Sports Seoul: {len(signals)}")
    return len(signals)


if __name__ == '__main__':
    collect()
