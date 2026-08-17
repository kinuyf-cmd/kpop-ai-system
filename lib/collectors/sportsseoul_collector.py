#!/usr/bin/env python3
"""Sports Seoul (스포츠서울) scraper

トップページ (https://www.sportsseoul.com/) が /news/read/<id> 記事リンクを
静的に出力する唯一の確実な経路 (セクションlistは全404・navはJS依存)。

収集範囲は owner 方針により「主軸K-POP / 韓国系サイトとして韓国エンタメ全般を
幅広く許容」。よってフィルタはブラックリスト方式:
  - スポーツ/政治/事件・事故のみ除外 (Sports Seoul はスポーツ紙のため必須)
  - 残りの韓国エンタメ (俳優/コメディアン/ドラマ/芸能ゴシップ等) は幅広く通す

タイトル抽出の注意 (2026-05-30 バグ修正):
  トップの hero カードはアンカーが <img alt="タイトル"> を内包し、clean_title が
  </a> を越えて次カードの <h2> タイトルまで連結する事案を確認
  (이솔이 비키니 記事に「레드벨벳 조이」が連結し keyword 汚染 → 記事#4842)。
  対策: アンカー内 <img alt> を最優先で採用し、無ければ最初の </a> までの
  インナーテキストのみ採用。複数記事タイトルの連結を構造的に断つ。
"""
import sys, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.collectors.korean_base import (
    fetch_html, is_kpop_related, is_urgent, save_signals, make_signal, log, clean_title,
)

# 除外語 (ブラックリスト)。スポーツ専用語 + 政治・事件。
# K-POP generic語 (1위/데뷔 等) が野球記事(「데뷔 첫 홈런」「ERA 1위」)を
# 誤通過させる実例があるため is_kpop_related の前段で適用する。
#
# substring 判定で安全な語 (誤マッチしにくい固有スポーツ/政治用語)。
_EXCLUDE_SUBSTR = [
    # スポーツ (一般)
    '축구', '야구', '배구', '농구', '골프', '감독', '리그', '월드컵', '시구',
    '구단', '선수', '경기', '프로야구', '대표팀', '승부',
    '홈런', '투수', '타자', '쿼터', '득점', '결승골',
    '선발', '불펜', '볼질', '구원', '타석', '이닝', '안타', '선두권',
    # 韓国プロ野球チーム名 (ハングルは substring で安全)
    '두산', '롯데', '키움', '한화',
    # e-sports
    '젠지', '롤드컵', 'e스포츠',
    # 政治・社会 (韓国エンタメではない)
    '대통령', '국회', '의원', '장관', '정당', '선거', '검찰', '법원', '판결',
    '협회장', '취임', '사퇴', '대선', '여당', '야당',
]
# 単語境界が必要な語 (ASCII 略号/短語。エンタメタイトル内の偶発一致を防ぐ)。
# 例: 'kt' を substring 判定すると "Katseye" 等に誤マッチしうるため境界で囲む
# (KATSEYE/NCT は除外されないことを test で確認済)。
# 既知の許容誤差: CJK を語境界扱いするため 'LG전자'(LG電子) は 'lg' に一致し
# 除外される。LG電子モデルのエンタメ記事は稀で、下流の非K-POPフィルタが最終
# ゲートのため許容。KT롤스터/LG트윈스 等のスポーツ団体名を捉える方を優先する。
_EXCLUDE_WORD = [
    'kbo', 'kia', 'kt', 'lg', 'ssg', 'nc', 'npb', 'mlb', 'era',
    't1', 'lck', 'esports', 'k리그',
]


def is_excluded(title: str) -> bool:
    """韓国エンタメ対象外 (スポーツ/政治/事件) か。アーティスト名判定より優先。"""
    tl = title.lower()
    if any(s in tl for s in _EXCLUDE_SUBSTR):
        return True
    # 単語境界: 前後が ASCII 英数でないこと (CJK は語境界扱い)
    for w in _EXCLUDE_WORD:
        for m in re.finditer(re.escape(w), tl):
            s, e = m.start(), m.end()
            before_ok = s == 0 or not (tl[s - 1].isascii() and tl[s - 1].isalnum())
            after_ok = e == len(tl) or not (tl[e].isascii() and tl[e].isalnum())
            if before_ok and after_ok:
                return True
    return False


def extract_title(inner: str) -> str:
    """アンカー内 HTML からタイトルを抽出。

    複数記事タイトルの連結を断つため、以下の順で1記事分だけ取る:
      1. <img ... alt="..."> があれば alt をタイトルとする (hero カード)
      2. 無ければ最初の </a> までのインナーテキストを clean_title で整形
    """
    m_alt = re.search(r'<img[^>]*\salt="([^"]+)"', inner)
    if m_alt:
        return clean_title(m_alt.group(1))
    # 最初の </a> 以降を捨てる (次カードのタイトル連結を防ぐ)
    head = re.split(r'</a>', inner, 1)[0]
    return clean_title(head)


def collect():
    signals = []
    try:
        html = fetch_html('https://www.sportsseoul.com/')
    except Exception as e:
        log(f"Sports Seoul fetch error: {e}")
        return 0

    # アンカーは img を内包することがあるため、終端は最初の </a> に限定せず
    # 貪欲に取り、extract_title 側で1記事分に正規化する。
    pat = r'<a[^>]+href="(/news/read/\d+)"[^>]*>(.*?)</a>'
    seen = set()
    for m in re.finditer(pat, html, re.DOTALL):
        path = m.group(1)
        title = extract_title(m.group(2))
        url = 'https://www.sportsseoul.com' + path
        if url in seen or len(title) < 5:
            continue
        seen.add(url)
        # スポーツ紙のためスポーツ/政治は K-POP generic語に引っかかっても先に弾く
        if is_excluded(title):
            continue
        keywords = is_kpop_related(title)
        if not keywords:
            # K-POP 固有名が無くても、除外語に当たらない限り韓国エンタメとして通す
            # (ブラックリスト方式)。keyword は generic '한류' を付与。
            keywords = ['한류']
        signals.append(make_signal('sports_seoul', title, url, keywords, is_urgent(title)))
        if len(signals) >= 20:
            break

    save_signals(signals, source_id='sports_seoul')
    log(f"Sports Seoul: {len(signals)}")
    return len(signals)


if __name__ == '__main__':
    collect()
