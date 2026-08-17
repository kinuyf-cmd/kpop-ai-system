#!/usr/bin/env python3
"""x_trend_topics.py — X会話投稿のネタ元を「いま動いているトレンド」から取る

背景 (2026-08-17 の実測):
  Phase1再開後の会話型投稿19本は imp 平均82に対し、いいね計10・RT 0・返信1。
  8/15以降の10本は ER 0.12% とほぼ死んでいた。投稿文を読むと「なんか〜な気がする」
  のような、対象を差し替えても成立する空虚な感想が大半だった。

  真因はプロンプトではなくネタ元にあった。会話投稿は config/auto_directives.json の
  focus_themes を種にしていたが:
    - 295件のうち **期限内(expires_at >= today)はわずか37件**。残りは5〜7月の期限切れ
    - にもかかわらず _pick_theme_for() は expires_at を一切見ておらず、
      3ヶ月前の話題を「今の話題」として掴んでいた
    - 主要アーティストの期限内テーマは0〜1件。BTS/BLACKPINK/TWICE/SEVENTEEN/
      NewJeans/LE SSERAFIM はゼロ → 事実ゼロで LLM に書かせていた
    - topic 文字列が「Stray Kids速報の深掘り: RESCENE、…」のように壊れており、
      共演者の記事が別アーティストの話題として割り当たっていた

  一方 data/trend_signals.jsonl は30分毎に更新され、直近24hで185件・
  アーティスト名と engagement_score 付きで生きている。こちらを一次ソースにする。

方針:
  - 鮮度は timestamp で担保する(expires_at のような別フィールドに依存しない)
  - 主役の判定は keyword ではなく **title に名前が出るか** で行う
  - センシティブ話題(訴訟・逮捕・訃報等)は軽い独り言の種にしない
  - 種が無ければ None を返す。呼出側は投稿を見送ってよい(空虚な投稿を出さない)

使い方:
    from lib.x_trend_topics import pick_trend_topic, trending_artists
    topic = pick_trend_topic("TWICE")        # -> {"fact","url","score",...} or None
    arts  = trending_artists()               # -> ["IVE","Stray Kids",...] 出現順

CLI:
    python3 lib/x_trend_topics.py                 # 直近トレンドの一覧
    python3 lib/x_trend_topics.py --artist TWICE  # 指定アーティストの話題
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SIGNALS = ROOT / "data" / "trend_signals.jsonl"
# トレンドとして扱う鮮度。K-POPの話題は1日で入れ替わるため48hを上限にする。
DEFAULT_WINDOW_H = 48

# ─── 話題の扱いを2段階に分ける ────────────────────────────────────────────
# K-POP メディアである以上、ネガティブなニュースや未確定の報道も扱う。一律に
# 排除すると、いま最も読まれている話題を取り逃がす。分けるべきは「触れるか」
# ではなく「どう書くか」:
#
#   BLOCKED       … 軽い独り言として流すこと自体が加害になるもの。扱わない。
#   HEDGE_REQUIRED… 扱ってよいが、断定・便乗・面白がる口調を禁じるもの。
#                   pick_trend_topic は tone="hedged" を付けて返し、生成側の
#                   プロンプトが「報道段階であることを明示し、断定しない」形に
#                   切り替わる。

# 事件・事故・訃報など、本人や関係者への加害性が高く、
# 「ファンの独り言」という体裁自体が不適切なもの。
BLOCKED_WORDS = (
    # 日本語
    '盗作', '剽窃', '流出', '訴訟', '告訴', '起訴', '逮捕', '書類送検',
    '暴行', 'ハラスメント', 'いじめ', '学暴', '薬物', '飲酒運転',
    '死去', '訃報', '事故死', '自殺', '不倫',
    # 韓国語
    '표절', '유출', '소송', '고소', '기소', '체포', '폭행', '학폭',
    '마약', '음주운전', '사망', '별세', '자살', '불륜',
    # 英語
    'lawsuit', 'sued', 'arrest', 'indicted', 'assault', 'bullying',
    'drug', 'dui', 'passed away', 'suicide',
    # 本人の意図しない身体的ハプニング。伸びるが尊厳を損なうため扱わない。
    'malfunction', 'nip slip', 'wardrobe', 'divides the internet',
    'ハプニング', '衣装トラブル', '해프닝',
    # 第三者(ファン・関係者)の病気。感動話として消費すると当事者を傷つける。
    # 病名の誤訳も起きやすい(実測で「ソア癌」という意味不明の訳語が出た)。
    'cancer', 'tumor', 'terminal illness', 'rare disease',
    'patient', 'chemotherapy', 'hospice',
    '難病', '闘病', '癌', '腫瘍', '患者',
    '난치병', '투병', '암', '환자',
)

# 報道として扱ってよいが、断定させてはいけないもの。
# 噂・疑惑・移籍・体調・炎上など、続報で覆りうる/受け止めに幅がある話題。
HEDGE_WORDS = (
    # 未確定の報道・憶測
    'rumor', 'rumour', 'speculat', 'reportedly', 'alleged', 'in talks',
    'sparks concern', 'raises questions',
    '噂', '憶測', '説が浮上', '観測', '報じられ', 'とみられる',
    '소문', '추측',
    # 所属・契約の動き
    'departure', 'departs', 'exits', 'leaving', 'leaves', 'steps down',
    'not renew', 'renewal talks', 'terminat', 'disband', 'hiatus',
    '契約解除', '専属契約紛争', '活動中断', '脱退', '解散', '移籍',
    '계약해지', '활동중단', '탈퇴', '해체',
    # 批判・疑惑
    'criticism', 'backlash', 'under fire', 'allegation', 'accus',
    'slam', 'blast', 'called out', 'sparks outrage', 'faking',
    'controversy', 'apologiz', 'apologis',
    '疑惑', '批判', '論争', '物議', '炎上', '批判殺到', '謝罪', '非難', '釈明',
    '의혹', '비판', '논란', '사과',
    # 体調・欠席・変更
    'sits out', 'absent', 'health concern', 'inflammation', 'injur',
    'hospitaliz', 'fracture', 'unwell', 'illness', 'cancel', 'postpone',
    '体調', '欠席', '不参加', '中止', '延期', '骨折', '負傷', '入院', '手術',
    '컨디션', '불참', '취소', '연기', '골절', '부상', '입원', '수술',
    # 感情が高ぶった場面(扱えるが面白がらせない)
    'trembling', 'tearing up', 'in tears', 'breaks down',
    '涙ぐ', '号泣', '눈물',
    # 私生活
    'divorce', 'dating', '熱愛', '離婚', '이혼', '열애',
)

# 定期まとめ・一覧記事の見出し。特定の出来事を含まないため種にならない。
_ROUNDUP_PATTERNS = (
    r'^\s*weekly\b',
    r'^\s*daily\b',
    r'\bround-?up\b',
    r'\bthis\s+week\s+in\b',
    r'^\s*\[?(まとめ|一覧)\]?',
)

# 反応を呼ぶ「具体的な事実」の型。実測(2026-08-17)で、いいね/返信が付いた投稿は
# いずれも数字か初達成を含んでいた。逆に「なんか〜な気がする」型は ER 0%。
# 同点スコアのときはこちらを優先して選ぶ。
_BUZZ_PATTERNS = (
    r'\d',                                   # 数字(再生数・週数・順位・日付)
    r'\b1st\b|\bfirst\b|初|첫',               # 初達成
    r'record|기록|記録',
    r'\bno\.?\s*1\b|top\s+\d|1위|1位',
    r'announce|발표|発表|決定',
    r'comeback|컴백|カムバ',
    r'debut|데뷔|デビュー',
    r'tour|concert|투어|ツアー|公演',
)


def _norm(s: str) -> str:
    """比較用の正規化(空白/記号を落として小文字化)。
    「Stray Kids」と「straykids」、「LE SSERAFIM」と「lesserafim」を同一視する。"""
    return re.sub(r'[\s\-_.·・]', '', str(s or '')).lower()


def _mentions(artist: str, text: str) -> bool:
    """text がアーティスト名に **語として** 言及しているか。

    単純な部分一致だと "IVE" が "live" / "reveals" に、"NCT" が "instinct" に
    当たる。実データで allkpop の "…still live without personal phones…"
    (RESCENE の記事)が IVE の話題として選ばれていた。
    英数字名は語境界で照合し、それ以外(ハングル等)は部分一致で扱う。
    """
    name = str(artist or '').strip()
    if not name:
        return False
    # 表記ゆれ吸収のため、名前中の空白は「空白ありでも無しでも可」として組む
    parts = [re.escape(p) for p in re.split(r'[\s\-_.·・]+', name) if p]
    if not parts:
        return False
    body = r'[\s\-_.·・]*'.join(parts)
    if re.fullmatch(r'[A-Za-z0-9\s\-_.·・]+', name):
        pattern = rf'(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])'
    else:
        pattern = body
    return re.search(pattern, str(text or ''), re.IGNORECASE) is not None


def _clean_title(title: str) -> str:
    """soompi 等の見出しは &#8220; / &#038; のような HTML エンティティを生で含む。
    そのまま LLM に渡すと投稿文に文字化けが混入するため復号し、空白を整える。"""
    t = html.unescape(html.unescape(str(title or '')))
    return re.sub(r'\s+', ' ', t).strip()


# 見出しが構造的に壊れているソース(会話の種として使わない)。
# koreaherald は記事ページでなく一覧ページを収集しており、title に順位番号
# (「6 Twice's Jeongyeon leaves JYP…」)や隣の記事(「…collab Most Read K-pop」)が
# 混入し、80字で切断されている。誰の出来事か特定できないため除外する。
# 上流(lib/collectors/)の収集を直せば、このリストから外してよい。
# 2026-08-17: 収集側は根治済(lib/collectors/koreaherald_collector.py。
# 見出しを <p class="news_title"> から1件ずつ取るよう修正し、0件→25件で
# 連結・切断が解消)。ただし trend_signals.jsonl には修正前に書かれた
# 壊れた行が残っており、実測で 13件中11件が下流ガードをすり抜ける
# (「6 Twice's Jeongyeon leaves JYP…」「…collab Most Read K-pop」等)。
# 鮮度窓(DEFAULT_WINDOW_H=48h)から古い行が抜けきるまで除外を維持し、
# それ以降にこのタプルを空にすること。
UNRELIABLE_SOURCES = ("koreaherald",)


# 「主役; Performances By 脇役, And More」型の見出しで、脇役側の羅列が始まる位置。
# soompi/allkpop の音楽番組・チャートまとめは全てこの形をしている。ここより後ろに
# 名前が出るだけのアーティストは、その記事の主役ではない。
_SUPPORTING_CAST_MARKERS = (
    r';\s*performances?\s+by',
    r'\+\s*performances?\s+from',
    r',?\s*and\s+more\b',
    r'그\s*외',
    # 日本語見出しは「…開催決定！BLACKPINK リサ、ジス＆ロゼに続き…」のように
    # 感嘆符/句点のあとに参考情報として別アーティスト名を並べる。そこは主役ではない。
    r'[!！。]\s*\S',
    r'に続き',
)


def _strip_quotes(title: str) -> str:
    """発言の引用部分(「」“”)を取り除いた見出しを返す。

    「KIIRAS、こだわりを語る『…ロールモデルはBLACKPINK先輩』」のように、
    他人の発言の中で名前が出るだけのものを、その人の出来事と誤認しないため。
    ただし曲名・番組名も同じ括弧で書かれるので、この結果は**主役判定にのみ**使い、
    LLM へ渡す本文(fact)は元の見出しのまま保つ。
    """
    return re.sub(r'[「『"“][^」』"”]*[」』"”]', ' ', str(title or ''))


def _lead_part(title: str) -> str:
    """見出しのうち「主役が書かれている部分」だけを返す。

    脇役の羅列(Performances By …/, And More)を切り落とす。実データで
    Stray Kids が RESCENE の受賞記事を自分の話題として掴んでいた事故の根治。
    """
    t = str(title or '')
    cut = len(t)
    for pat in _SUPPORTING_CAST_MARKERS:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            cut = min(cut, m.start())
    return t[:cut].strip()


# 主役部分がこの数を超えるアーティスト名の羅列なら「誰の話題でもない」と見なす。
# 例: 「CORTIS, ATEEZ, BTS, RIIZE, … Sweep Top Spots On Billboard」
_MAX_NAMES_IN_LEAD = 3


def _is_name_list(lead: str) -> bool:
    """主役部分が単なる名前の羅列(まとめ記事)かを判定する。

    カンマ区切りの要素がどれも短い固有名詞的な断片ばかりなら羅列と見なす。
    こうした見出しは特定アーティストの出来事を含まないため、独り言の種にならない。
    """
    parts = [p.strip() for p in lead.split(',') if p.strip()]
    if len(parts) <= _MAX_NAMES_IN_LEAD:
        return False
    # 最後の要素は「ATEEZ Sweep Top Spots On …」のように述語を含むので除く
    heads = parts[:-1]
    return all(len(h.split()) <= 3 for h in heads)


def _is_blocked(text: str) -> bool:
    """軽い独り言として流すこと自体が加害になる話題か。"""
    low = str(text or '').lower()
    return any(w in low for w in BLOCKED_WORDS)


def needs_hedge(text: str) -> bool:
    """扱ってよいが、断定を避けるべき話題か(噂・疑惑・移籍・体調など)。"""
    low = str(text or '').lower()
    return any(w in low for w in HEDGE_WORDS)


def _buzz_score(title: str) -> int:
    """見出しが「反応を呼ぶ具体的な事実」をどれだけ含むか(0以上)。

    実測(2026-08-17)で ER が付いた投稿は例外なく数字か初達成を含んでいた。
    engagement_score(収集元での勢い)と別に、つぶやきの種としての強さを測る。
    """
    t = str(title or '')
    return sum(1 for p in _BUZZ_PATTERNS if re.search(p, t, re.IGNORECASE))


def _is_roundup(title: str) -> bool:
    """定期まとめ記事(Weekly allkpop 等)かどうか。"""
    t = str(title or '')
    return any(re.search(p, t, re.IGNORECASE) for p in _ROUNDUP_PATTERNS)


def _is_concatenated(title: str) -> bool:
    """複数の見出しが1つのシグナルに連結されているか。

    koreaherald の一覧ページ収集がこの形になり、
    「5 Fans revisit old BTS clips … 6 [Exclusive] 別の見出し」のように
    番号付きで複数記事が繋がる。どれが誰の出来事か特定できないため種にしない。
    """
    t = str(title or '')
    # 文中に現れる「数字だけの区切り」= 一覧の連番
    if len(re.findall(r'(?:^|\s)\d{1,2}(?=\s+[A-Z\[])', t)) >= 2:
        return True
    # [Exclusive] 等のセクションラベルが文中に出るのも一覧連結の印
    if re.search(r'\S\s+\[[A-Za-z]+\]', t):
        return True
    return False


def load_recent_signals(path: Path | str = SIGNALS,
                        window_h: int = DEFAULT_WINDOW_H) -> list[dict]:
    """直近 window_h 時間以内のシグナルを返す。

    鮮度は timestamp のみで判定する。focus_themes の expires_at を信用して
    3ヶ月前の話題を掴んだ事故(2026-08-17)の再発防止。
    """
    p = Path(path)
    if not p.exists():
        return []
    cutoff = datetime.now() - timedelta(hours=window_h)
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = d.get("timestamp")
        if not ts:
            continue
        try:
            if datetime.fromisoformat(str(ts)) < cutoff:
                continue
        except ValueError:
            continue
        out.append(d)
    return out


def _candidates(artist: str, signals: list[dict]) -> list[dict]:
    """artist が **見出し本文に登場する** シグナルだけを候補にする。

    keyword フィールドは「その記事に関係するグループ」であって主役とは限らない。
    実際に keyword='Stray Kids' で title が「RESCENE、Love Attackで1位」という
    シグナルが存在し、共演者の話題を Stray Kids の話題として投稿していた。
    """
    key = _norm(artist)
    if not key:
        return []
    out = []
    for s in signals:
        if s.get("source_id") in UNRELIABLE_SOURCES:
            continue
        title = _clean_title(s.get("title"))
        if not title:
            continue
        if _is_concatenated(title) or _is_roundup(title):
            continue
        # 主役判定は見出し全体ではなく先頭部分で行う(脇役の羅列を主役にしない)
        lead = _lead_part(title)
        # 主役判定は「発言の引用を除いた部分」に名前が出るかで行う。
        # (曲名・番組名の括弧も一緒に落ちるが、主役名は通常その外に書かれる)
        if not _mentions(artist, _strip_quotes(lead)):
            continue
        if _is_name_list(lead):
            continue
        if _is_blocked(title):
            continue
        out.append({
            "fact": title,
            "url": s.get("url", ""),
            "score": float(s.get("engagement_score") or 0),
            "buzz": _buzz_score(title),
            # "hedged" なら生成側が断定を避ける口調に切り替える
            "tone": "hedged" if needs_hedge(title) else "plain",
            "source_id": s.get("source_id", ""),
            "language": s.get("language", ""),
            "timestamp": s.get("timestamp", ""),
        })
    return out


def pick_trend_topic(artist: str, *, path: Path | str = SIGNALS,
                     window_h: int = DEFAULT_WINDOW_H,
                     used_urls: set[str] | None = None) -> dict | None:
    """artist の「いま動いている話題」を1件返す。無ければ None。

    None を返すことは失敗ではなく仕様。呼出側は投稿を見送ってよい —
    事実の裏付けが無い状態で書かせると、実測どおり空虚な感想しか出てこない。
    """
    cands = _candidates(artist, load_recent_signals(path, window_h))
    used = used_urls or set()
    cands = [c for c in cands if c["url"] not in used]
    if not cands:
        return None
    # 2026-08-17: hedged(噂・批判・体調)は plain より後回しにする。書き方を
    # 整えても話題選択が炎上に寄れば炎上便乗と変わらない(実測で8本中4本が
    # 批判系に偏った)。同じ勢いならポジティブな出来事を先に使い、他に無いときだけ
    # hedged を扱う。
    # 並び順: plain優先 → engagement_score → buzz → 新しさ
    cands.sort(key=lambda c: (c["tone"] == "hedged", -c["score"],
                              -c["buzz"], _neg_ts(c["timestamp"])))
    return cands[0]


def _neg_ts(ts: str) -> float:
    """新しいほど小さい値。ソートキー用(同点スコアで最新を先頭に)。"""
    try:
        return -datetime.fromisoformat(str(ts)).timestamp()
    except (ValueError, TypeError):
        return 0.0


def trending_artists(*, path: Path | str = SIGNALS,
                     window_h: int = DEFAULT_WINDOW_H,
                     pool: list[str] | None = None) -> list[str]:
    """直近シグナルで実際に話題になっているアーティストを、勢い順に返す。

    投稿対象を固定プール(DEFAULT_ARTIST_POOL)からランダムに選ぶと、話題が無い
    アーティストを引いて事実ゼロの投稿になる。逆に「話題がある側」から選ぶ。
    勢い = そのアーティストの候補シグナルの (score + buzz) 合計。
    """
    signals = load_recent_signals(path, window_h)
    if pool is None:
        from lib.x_conversation_starter import DEFAULT_ARTIST_POOL
        pool = DEFAULT_ARTIST_POOL
    scored = []
    for a in pool:
        cands = _candidates(a, signals)
        if cands:
            # hedged しか無いアーティストは勢いを割り引く。アーティスト選択の
            # 段階で炎上・噂しか話題が無い相手に寄ると、結局その話題を書くことになる。
            plain = [c for c in cands if c["tone"] == "plain"]
            heat = sum(c["score"] + c["buzz"] for c in (plain or cands))
            if not plain:
                heat *= 0.5
            scored.append((heat, len(cands), a))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [a for _, _, a in scored]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artist", help="指定アーティストの話題を1件表示")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW_H, help="鮮度(時間)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.artist:
        got = pick_trend_topic(args.artist, window_h=args.window)
        if args.json:
            print(json.dumps(got, ensure_ascii=False, indent=2))
        elif got:
            print(f"[{got['score']}] {got['fact']}\n  {got['url']}")
        else:
            print(f"(直近{args.window}hに {args.artist} の話題なし)")
        return 0 if got else 1

    arts = trending_artists(window_h=args.window)
    print(f"=== 直近{args.window}hのトレンド({len(arts)}組) ===")
    for a in arts:
        t = pick_trend_topic(a, window_h=args.window)
        print(f"  {a:14s} {t['fact'][:70] if t else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
