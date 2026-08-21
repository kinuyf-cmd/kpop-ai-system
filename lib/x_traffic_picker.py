#!/usr/bin/env python3
"""x_traffic_picker.py — トレンド連動でサイト流入用の記事を選ぶ

背景 (2026-08-17 実測):
  X からサイトへの流入が実質ゼロだった。
    - 記事枠(12時)は Phase2 で復活していたが、8/12以降 1回しか動いていない
    - その1本も URL もフックも無い、記事本文の平叙文コピーだった
    - 配信元の x_post_queue.json は4件しかなく、いま話題の出来事とは無関係

  owner決定(2026-08-17):
    導線 = 本文は URL なしのフック / 自己リプに URL を置く
           (本文リンクはシャドウバン再発の主トリガーだったため戻さない)
    記事 = トレンド連動。いま話題の出来事に関連する自社記事だけを出す。
           関連記事が無い日は出さない(無関係な記事を投げても読まれない)。

使い方:
    from lib.x_traffic_picker import pick_traffic_post
    post = pick_traffic_post()   # -> {"hook","url","post_id","artist","fact"} or None

CLI:
    python3 lib/x_traffic_picker.py            # いま出せる流入投稿を1件表示
    python3 lib/x_traffic_picker.py --list     # トレンドと関連記事の対応を一覧
"""
from __future__ import annotations

import argparse
import json
import os
import html
import re
import sys
from datetime import date, datetime
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# .env を読む(OPENAI_API_KEY 等)。CLI/cron 直実行でもフック生成が働くよう、
# x_conversation_starter と同様にここで明示ロードする。
try:
    from dotenv import load_dotenv
    load_dotenv(str(ROOT / ".env"))
except Exception:
    pass

WP_SEARCH = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
QUEUE_FILE = ROOT / "config" / "x_post_queue.json"
# 流入投稿で使った記事の記録(同じ記事を続けて出さない)
USED_FILE = Path.home() / ".kpop_recovery" / "x_traffic_used.jsonl"
USED_WINDOW_DAYS = 14


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_.·・'’\"“”]", "", str(s or "")).lower()


def _mentions(artist: str, text: str) -> bool:
    """記事タイトルがそのアーティストを指しているか(語境界で照合)。"""
    from lib.x_trend_topics import _mentions as m
    return m(artist, text)


def search_articles(artist: str, limit: int = 20) -> list[dict]:
    """WP REST でアーティスト名を含む公開記事を検索する。

    失敗時は空リストを返し、呼出側は投稿を見送る(壊れた導線を出さない)。
    """
    try:
        q = urllib.parse.urlencode({
            "search": artist, "per_page": limit, "status": "publish",
            "_fields": "id,title,link,featured_media",
        })
        req = urllib.request.Request(f"{WP_SEARCH}?{q}",
                                     headers={"User-Agent": "KpopJournal-Bot/2.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception:
        return []
    out = []
    for d in data:
        # featured_media が無い記事は OGP がデフォルト画像になり、リプの
        # カードがサイトと無関係な絵になる(既存 x_poster と同じ判断)。
        if not d.get("featured_media"):
            continue
        title = (d.get("title") or {}).get("rendered", "")
        title = re.sub(r"<[^>]+>", "", title).strip()
        if not title or not d.get("link"):
            continue
        out.append({"title": title, "url": d["link"], "post_id": d.get("id")})
    return out


def _recent_used_ids() -> set:
    """直近 USED_WINDOW_DAYS 日に流入投稿で使った post_id。"""
    if not USED_FILE.exists():
        return set()
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(days=USED_WINDOW_DAYS)
    out = set()
    try:
        lines = USED_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    for line in lines:
        try:
            d = json.loads(line)
            if datetime.fromisoformat(d["ts"]) >= cutoff:
                out.add(d.get("post_id"))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
    return out


def remember_used(post_id) -> None:
    if not post_id:
        return
    from datetime import datetime
    USED_FILE.parent.mkdir(exist_ok=True)
    try:
        with USED_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now().isoformat(),
                                "post_id": post_id}, ensure_ascii=False) + "\n")
    except OSError:
        pass


# 話題の一致判定から外す語。どの記事にも出るため、重なっても関連の証拠にならない。
_STOPWORDS = {
    "kpop", "the", "for", "and", "with", "his", "her", "その", "こと", "ため",
    "した", "する", "して", "いる", "れる", "など", "から", "まで", "より",
    "公開", "発表", "話題", "注目", "最新", "情報", "まとめ",
}


def _topic_tokens(text: str, artist: str = "") -> set:
    """話題の一致判定に使う語を取り出す。

    アーティスト名そのものは除く(名前が一致するのは前提であって、
    「同じ話題を扱っているか」の証拠にはならない)。
    """
    s = str(text or "")
    toks = set(re.findall(r"[A-Za-z]{3,}", s))
    toks = {t.lower() for t in toks}
    # 数字は日英をまたいで一致する数少ない手掛かり(「Billboard 200」↔「ビルボード200」、
    # 「21 Weeks」↔「21週」)。話題の同一性を測る材料として重要。
    toks |= set(re.findall(r"\d+", s))
    # 日本語は連なると長い1語になってしまうため、2〜4字の部分文字列に分解して重ねる
    # (「日本初の冠バラエティ番組」と「日本活動まとめ」が『日本』で一致するように)。
    for run in re.findall(r"[ぁ-んァ-ヶ一-龠ー]{2,}", s):
        for n in (2, 3, 4):
            for i in range(len(run) - n + 1):
                toks.add(run[i:i + n])
    drop = set(_STOPWORDS)
    for part in re.split(r"[\s\-_.·・]+", str(artist or "")):
        if part:
            drop.add(part.lower())
    return {t for t in toks if t not in drop}


def match_article(artist: str, fact: str, articles: list[dict] | None = None,
                  used_ids: set | None = None) -> dict | None:
    """トレンドの出来事に関連する自社記事を1件返す。無ければ None。

    None は失敗ではなく仕様。関連記事が無い日に無関係な記事を投げても読まれず、
    リンク付き投稿だけが増えて可視性リスクを取ることになる。
    """
    if articles is None:
        articles = search_articles(artist)
    used = used_ids or set()
    cands = [a for a in articles
             if _mentions(artist, a.get("title", "")) and a.get("post_id") not in used]
    if not cands:
        return None
    # 2026-08-17: アーティスト名の一致だけでは不十分。実データで
    # 「BTS ARIRANG UKチャート21週」に「BTSのVが交通事故の噂」が当たった。
    # 話題を見て来た読者を別の記事へ飛ばすと直帰するので、**出来事と記事タイトルに
    # アーティスト名以外の重なりが1語以上ある**ことを条件にする。
    fact_tokens = _topic_tokens(fact, artist)

    def overlap(a: dict) -> int:
        return len(fact_tokens & _topic_tokens(a.get("title", ""), artist))

    scored = [(overlap(a), a) for a in cands]
    scored = [(n, a) for n, a in scored if n >= 1]
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], x[1].get("post_id", 0)))
    return scored[0][1]


def fetch_body(post_id) -> str:
    """記事本文のプレーンテキストを取得する。失敗時は空文字。"""
    if not post_id:
        return ""
    try:
        u = (f"{WP_SEARCH}/{post_id}"
             "?_fields=content&status=publish")
        req = urllib.request.Request(u, headers={"User-Agent": "KpopJournal-Bot/2.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read())
    except Exception:
        return ""
    html = (d.get("content") or {}).get("rendered", "")
    if not html:
        return ""
    try:
        from lib.article_summarizer import _extract_text
        return _extract_text(html)
    except Exception:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


# 「続き」として渡せる具体が本文にあるかの判定に使う手掛かり。
# 数字・固有名・比較・条件など、読者が知りたくなる具体性の指標。
_SUBSTANCE_HINTS = (
    r"\d",                                   # 数字(日付・順位・回数・金額)
    r"[A-Z][A-Za-z]{2,}",                    # 英字の固有名(曲名・番組名・チャート名)
    r"(?:一方|ただし|実は|なお|ちなみに|逆に)",   # 対比・補足=続きの素
    r"(?:場合|条件|理由|背景|内訳|一覧|比較)",
)

# 本文がこれ未満の長さなら、リプに渡せる中身が無いと判断する。
_MIN_BODY_CHARS = 300
# 具体性の手掛かりがこの種類数以上あることを要求する。
_MIN_SUBSTANCE_KINDS = 3


# メディア/事務所の発表文に見える言い回し。個人アカウントの投稿として読まれなくなる。
# 2026-08-17 実測で「快進撃」「魅力的なステージを披露」「注目が集まります」が出た。
_PR_TONE_PATTERNS = (
    r"注目が集まり",
    r"さらなる(?:活躍|飛躍|成長)",
    r"快進撃",
    r"魅力的な",
    r"披露(?:し|さ)(?:ました|れた|ます)",
    r"期待が(?:高ま|寄せ)",
    r"話題を呼んで",
    r"目が離せ(?:ない|ません)",
    r"今後の(?:活躍|展開)に(?:期待|注目)",
    r"(?:活躍|成功)を(?:続けて|拡大)",
    # 2026-08-17 第2波: 称賛語もメディア発表文の印。個人の続きに見えない。
    r"大(?:成功|盛況|好評)",
    r"(?:感動|圧巻|素晴らし)",
    r"盛り上がりを見せ",
    r"熱狂的な",
    r"絆を(?:深め|強化)",
    r"成功させ",
)


def is_pr_tone(text: str) -> bool:
    """広報・発表文口調か。個人アカウントの投稿としては不自然なので作り直す。"""
    t = str(text or "")
    return any(re.search(p, t) for p in _PR_TONE_PATTERNS)


# 列挙が主体の記事(番組の出演者一覧など)は、リプで渡せる「続き」が無い。
# 数字と固有名は多いので長さ・具体性の判定だけでは通ってしまう。
def _is_listing_body(body: str) -> bool:
    t = str(body or "")
    # 「Xが「曲名」」の形が多数並ぶ = 出演者一覧
    pairs = len(re.findall(r"[^、。]{2,20}が[「『][^」』]{1,40}[」』]", t))
    return pairs >= 5


def has_substance(body: str) -> bool:
    """記事本文に「引きの続き」として渡せる中身があるか。

    owner決定(2026-08-17, A案): 引きを作る前に記事側を検証する。
    中身の無い記事で引きだけ作ると、飛んだ読者を裏切る。実測でも Direct 直帰が
    65% だった既往があり、流入させても直帰では意味がない。
    """
    t = str(body or "").strip()
    if len(t) < _MIN_BODY_CHARS:
        return False
    # 出演者一覧のような列挙記事は、具体は多いが「続き」にならない
    if _is_listing_body(t):
        return False
    kinds = sum(1 for p in _SUBSTANCE_HINTS if re.search(p, t))
    return kinds >= _MIN_SUBSTANCE_KINDS


def extract_payoff(body: str, fact: str = "", artist: str = "") -> str:
    """本文から「リプで渡す続き」を1〜2文で作る。

    記事の要約ではなく、本文を読んだ人が『そこが知りたかった』と思う具体
    (数字の内訳・条件・比較)を抜く。LLM が使えない場合は、具体を含む文を
    本文から選んで返す。
    """
    t = re.sub(r"\s+", " ", str(body or "")).strip()
    if not t:
        return ""
    try:
        from lib.x_persona_voice import _call_llm
        system = (
            "あなたは K-POP メディアの編集者です。X の投稿本文で話題を提示したあと、"
            "自己リプライで『続き』を1〜2文だけ書きます。"
            "\n- 記事の要約や宣伝文にしない。読者が『そこが知りたかった』と思う具体を書く"
            "\n- 数字の内訳・条件・他との比較・理由のうち、本文に書かれているものだけ使う"
            "\n- 本文に無い事実は絶対に書かない"
            "\n- 60〜110字。煽らない。『詳しくは記事で』のような案内文は書かない"
            "\n- 出力は本文のみ。URL・ハッシュタグ・絵文字は付けない"
            # 2026-08-17: 実測で「大成功!」「盛り上がりを見せています」といった
            # 広報文が返り続けた。個人アカウントの続きとして読める文にする。
            "\n\n【禁止 — これが出ると個人の投稿に見えない】"
            "\n- 『大成功』『大盛況』『感動』『圧巻』『素晴らしい』などの称賛語"
            "\n- 『注目が集まります』『期待大』『目が離せない』などの締め"
            "\n- 感嘆符(!)を使わない。淡々と事実の内訳だけを書く"
        )
        user = (
            f"話題: {fact}\n\n記事本文(この中の情報だけ使う):\n{t[:2500]}\n\n"
            "自己リプに置く『続き』(1〜2文):"
        )
        from lib.x_persona_voice import _numbers_consistent
        for _ in range(3):
            out = (_call_llm(system, user, "editorial") or "").strip()
            out = re.sub(r"https?://\S+", "", out).strip()
            if not (20 <= len(out) <= 180):
                continue
            # 広報口調は個人アカウントの投稿として不自然(実測で出た)
            if is_pr_tone(out):
                continue
            # 本文にない数字を出していないか検査(捏造防止)
            if _numbers_consistent(out, t):
                return out
    except Exception:
        pass
    # フォールバック: 具体(数字)を含む文を本文から拾う
    for sent in re.split(r"(?<=[。．!?])", t):
        s = sent.strip()
        if 25 <= len(s) <= 140 and re.search(r"\d", s):
            return s
    return ""


def build_reply(artist: str, fact: str, article: dict, hook: str = "",
                body: str = "") -> str:
    """自己リプ本文を組み立てる。『続き + URL』の形にする。

    owner指摘(2026-08-17): リプに URL だけ置くのではなく、本文の続きを書いて
    「本文を見たら続きを見たくなる」形にする。本文で価値の大半を渡し、
    最後の具体だけをリプに置くのが、いま伸びている型。
    """
    url = article.get("url", "")
    payoff = extract_payoff(body, fact, artist) if body else ""
    # 本文と同じ文を繰り返さない(同じことを2回言うと続きに見えない)
    if payoff and hook and (payoff in hook or hook in payoff):
        payoff = ""
    if not payoff:
        # 続きが作れないなら、記事の切り口だけ示す(URL単体にはしない)
        payoff = f"このあたり整理したのがこれ({article.get('title','')[:40]})"
    return f"{payoff}\n{url}".strip()


# ── 型A(引っ張る型)の構成検査 ───────────────────────────────────────────
# owner指定(2026-08-20):
#   本文    : 感想(1文) → 起(+承転)。結は書かない
#   リプライ: 結 + URL
# 結を本文に出すとリプ(URL側)を読む理由が消える。逆に感想だけだと
# 「中身のない出し渋り」になり、飛んだ読者を裏切る(Direct直帰65%の既往)。
# 既存メモリ「抽象指示は効かない/効かない文体はコードで担保」に従い検査する。

# 感想=書き手の主観が出ている印。断定的な事実文にはまず出ない語。
# 2026-08-20: 実生成6本で検証して調整。「どんな〜なんだろう」「想像がつかない」
#   のような、書き手の心の動きが出ている言い回しを感想として拾えていなかった。
_IMPRESSION_HINTS = (
    "と思", "気がする", "感じ", "なんか", "地味に", "意外と", "けっこう", "結構",
    "びっくり", "驚", "知らなかった", "初めて知", "らしくて", "いいな", "好き",
    "気になる", "うれし", "嬉し", "さすが", "そうなんだ", "らしい",
    # 想像・期待・戸惑いも書き手の主観(実測で最頻)
    "だろう", "だろ", "かな", "つかない", "楽しみ", "期待", "想像",
    "どうなる", "わからない", "分からない", "しちゃう", "みたい",
    "意外な", "意外だ", "大事だ",
    # 2026-08-20 第2次調整: 実ログ20本で誤判定(感想があるのに×)を洗い出して追加。
    #   「なんだなぁ」「ワクワク」「やっぱり」「すごい」を拾えていなかった。
    "なぁ", "なあ", "ワクワク", "どきどき", "ハラハラ", "やっぱり", "やはり",
    "すごい", "すごく", "切ない", "ざわざわ", "だよね", "よね",
    "しみじみ", "感動", "心が",
)

# 結=「なぜそうなのか/だからどうなるのか」を言い切ってしまっている印。
# これが本文にあると、リプで渡すものが残らない。
# 2026-08-20: 「が判明」を入れていたが、これは出来事(theme)そのものの提示であって
#   「結」ではない。実生成の大半を誤って弾いたため外した。ここで弾きたいのは
#   「なぜそうなのか/だからどうなるのか」を本文で言い切ってしまう形だけ。
_CONCLUSION_HINTS = (
    "だから", "そのため", "理由は", "原因は", "という理由", "なぜなら",
    "つまり", "要するに", "結論", "ということになる",
)


# 2026-08-21: 「読者が行動を変えられる具体」の検出パターン。
#   実測(Phase1以降38本)で自動 平均imp 109.5 に対し手動 991.2 と9倍差がつき、
#   伸びた手動投稿はいずれも 日時/時刻/場所/価格/可否条件 を含んでいた。
#   型A(構文)を満たしても中身が「〜楽しみ」だけの投稿は伸びない。
_CONCRETE_PATTERNS = (
    # 日付: 8/23, 8月23日, 明日, 今日中
    (r"\d{1,2}\s*[/月]\s*\d{1,2}\s*日?", "日付"),
    (r"(今日|明日|明後日|今夜|週末|今週|来週)", "時期"),
    # 時刻: 14:05, 14時05分, 21時〜
    (r"\d{1,2}\s*[:：]\s*\d{2}", "時刻"),
    (r"\d{1,2}\s*時(\d{1,2}分|半)?\s*[〜~から]", "時刻"),
    # 価格
    (r"[0-9０-９,，]+\s*円", "価格"),
    # 場所・会場(固有の開催地を示す語)
    (r"(会場|開催地|ホール|アリーナ|ドーム|スタジアム|劇場|MARINE|MOUNTAIN)", "場所"),
    # 可否・制約条件: 〜のみ/〜不可/〜必須/〜限定/事前予約/先行受付。
    # 2026-08-21: 当初 "要\s*\S" と "付き" を入れていたが、「必要すぎる」「思い付き」
    # のような日常語を条件と誤検知して空虚な本文を通した(実生成で判明)。
    # 制度・運用を指す語だけに絞る。
    (r"(限定|不可|必須|同伴|抽選|整理券|事前(予約|申込|登録)|先行(販売|受付|抽選)|"
     r"[^\s]{2,12}のみ|要(予約|登録|申込|整理券))", "条件"),
    # 2026-08-21: 当初「できません|できない」を入れていたが、「理解できない」
    # 「我慢できない」のような心情表現まで可否と誤検知した(実生成で判明)。
    # 読者の行動が実際に制約される動詞だけに絞る。
    (r"(見られません|見られない|買えません|買えない|入れません|入れない|"
     r"入場できません|購入できません|参加できません|予約できません|"
     r"間に合わ(ない|ません)|使えません|使えない)", "可否"),
    # 機会損失: 〜を逃すと / 〜しないと
    (r"(逃すと|逃せば|しないと|でないと|過ぎると|until|まで(に|は))", "期限"),
)


def has_concrete_info(text: str) -> dict:
    """本文に「読者が行動を変えられる具体」があるかを判定する。

    型A(check_hook_structure_type_a)は構文だけを見るため、
    「〜って、どうなるんだろう…楽しみ」のような情報量ゼロの本文を通してしまう。
    実測ではそれが伸びない主因だったので、中身の側をここで検査する。

    通す条件: 日時・時刻・場所・価格・可否条件・期限 のいずれかを1つ以上含む。
    単なる数量(「4部門」「700万回」)は行動を変えないため具体とみなさない。
    """
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not t:
        return {"ok": False, "issue": "本文が空", "signals": []}
    # 過去の出来事の報告は「行動を変える具体」ではない。
    # 実測誤検知: 「2026年08月15日の最終回で…7.7%を記録した」は日付を含むが
    # 読者にできることが何も無い。完了形で締めているものは日付を具体と数えない。
    # 「予定」「〜します」のような未来の告知は、過去語尾を含んでいても告知として扱う。
    has_future_marker = bool(re.search(
        r"(予定|される予定|開催します|リリースします|発売|受付|募集|"
        r"申込|エントリー|先行|抽選|要予約|事前予約)", t))
    is_past_report = (not has_future_marker) and bool(re.search(
        r"(を?記録した|を?獲得した|公開した|を?公開。|発表した|明らかにした|"
        r"となった|었|했|"
        # 連用中止で事実報告を並べる形(旧投稿で多発): 「披露し、」「参加し、」
        r"を?(披露|達成|完売|出席|参加|登場|受賞|開催|実施|発表|公開)(し(た|、|。)|"
        r"を?達成。|を?達成した)|"
        r"(話題に|好評|注目を集め))", t))
    found = []
    for pat, label in _CONCRETE_PATTERNS:
        if not re.search(pat, t):
            continue
        if is_past_report and label in ("日付", "時期", "時刻"):
            continue
        if label not in found:
            found.append(label)
    # 「時期」だけ(今日/週末など)は単独では行動を変えられない。
    # 伸びた実例は「今日を逃すと現地では見られません」のように、必ず
    # 時刻・場所・可否・期限とセットだった。単独なら具体とみなさない。
    if found == ["時期"]:
        return {"ok": False,
                "issue": "時期語だけで具体が無い(『今日』等は単独では行動を変えない)",
                "signals": []}
    if not found:
        return {"ok": False,
                "issue": "具体が無い(日時/場所/価格/条件のいずれも書かれていない)",
                "signals": []}
    return {"ok": True, "issue": "", "signals": found}


def extract_concrete_facts(body: str) -> dict:
    """記事本文から会場・会期・営業時間・価格を抜き出す。

    2026-08-21: trend_signals の見出しは具体を 1/24 しか含まないため、
    具体ゲートだけでは自動投稿が止まる。自社記事の本文(特にポップアップ/
    イベント)には会場・会期・営業時間が揃っているので、そこから拾って
    本文に載せる。抜けなければ空 dict(=その話題は会話型に回さない)。
    """
    t = re.sub(r"[ \t\u3000]+", " ", str(body or ""))
    if not t.strip():
        return {}
    out: dict = {}

    def _grab(label_pat, value_pat, key, limit=1):
        vals = []
        for m in re.finditer(label_pat + r"\s*[:：]?\s*(" + value_pat + ")", t):
            v = m.group(1).strip(" 　·・")
            if v and v not in vals:
                vals.append(v)
            if len(vals) >= limit:
                break
        if vals:
            out[key] = vals

    # 会場: 「会場 「○○」」を優先し、鉤括弧が無ければ行末までを拾う。
    # 「開催地・期間・営業時間などの詳細は…」のような説明文に引っかからないよう、
    # ラベル直後が助詞(・/の/は)で続くものは会場名ではないとみなす。
    _grab(r"(?:会場|開催地|場所)(?![・のはをがでも])", r"「[^」]{2,40}」", "venue")
    if "venue" not in out:
        _grab(r"(?:会場|開催地|場所)(?![・のはをがでも])", r"[^\n:：]{2,40}?(?=\s|$)", "venue")
    # 国名/地方名だけの会場は「どこへ行けばいいか」が分からず具体にならない。
    # 実データ誤抽出: 「会場 韓国」。散文の途中で拾った断片も同様に落とす。
    if "venue" in out:
        vs = [v for v in out["venue"]
              if v.strip("「」") not in _TOO_BROAD_VENUES
              and not v.endswith(("。", "です", "ます", "でした"))]
        if vs:
            out["venue"] = vs
        else:
            out.pop("venue")
    # 会期: 「開催期間 2026年7月4日（土）～8月16日（日）」
    _grab(r"(?:開催期間|会期|期間)", r"[0-9０-９][^\n]{4,50}", "period")
    # 営業時間: 「営業時間 11:00～20:00」
    _grab(r"(?:営業時間|開場|開演|時間)", r"\d{1,2}[:：]\d{2}[^\n]{0,20}", "hours")
    # 価格
    _grab(r"(?:料金|価格|チケット|入場)", r"[^\n]{0,12}[0-9０-９,，]+\s*円[^\n]{0,10}", "price")
    return out


# 会場としては広すぎて行動につながらない値(実データ誤抽出より)
_TOO_BROAD_VENUES = {"韓国", "日本", "ソウル", "東京", "大阪", "全国", "海外", "現地"}

# 具体を本文に足すときのラベル(短く保つ。X は本文が長いと読まれない)
_MAX_HOOK_CHARS = 190

_CONCRETE_ORDER = (("venue", ""), ("period", ""), ("hours", ""), ("price", ""))


def concrete_line(facts: dict) -> str:
    """extract_concrete_facts() の結果を本文に足せる1行にする。"""
    if not facts:
        return ""
    parts = []
    for key, _ in _CONCRETE_ORDER:
        for v in facts.get(key, []):
            v = re.sub(r"\s+", " ", v).strip()
            if v:
                parts.append(v)
            break
    line = " / ".join(parts)
    return line[:80]


def _parse_period(period: str) -> tuple:
    """会期文字列から (開始日, 終了日) を date で返す。読めなければ (None, None)。

    実データの表記ゆれ: 「2026年8月19日（水）～8月30日（日）」「2026/08/08〜2026/08/20」
    終了側は年が省略されることが多いので、開始の年を引き継ぐ。
    """
    t = re.sub(r"[（(][^）)]*[）)]", "", str(period or ""))
    t = t.replace("〜", "~").replace("～", "~").replace("－", "~").replace("-", "~")
    parts = [p.strip() for p in t.split("~") if p.strip()]
    if not parts:
        return (None, None)

    def _d(sv, year=None):
        m = re.search(r"(\d{4})\s*[年/.]\s*(\d{1,2})\s*[月/.]\s*(\d{1,2})", sv)
        if m:
            y, mo, da = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m = re.search(r"(\d{1,2})\s*[月/.]\s*(\d{1,2})", sv)
            if not m or year is None:
                return None
            y, mo, da = year, int(m.group(1)), int(m.group(2))
        try:
            return date(y, mo, da)
        except ValueError:
            return None

    start = _d(parts[0])
    if start is None:
        return (None, None)
    end = _d(parts[1], start.year) if len(parts) > 1 else start
    # 「12月28日~1月5日」のような年またぎ
    if end and end < start:
        try:
            end = date(end.year + 1, end.month, end.day)
        except ValueError:
            pass
    return (start, end or start)


def _today(today: str = "") -> "date":
    if today:
        y, m, d = (int(x) for x in str(today).split("-"))
        return date(y, m, d)
    return datetime.now().date()


def is_currently_open(period: str, today: str = "") -> bool:
    """会期が「いま行ける」状態かを返す。"""
    start, end = _parse_period(period)
    if not start:
        return False
    now = _today(today)
    return start <= now <= end


def upcoming_window(period: str, today: str = "", days: int = 7) -> bool:
    """まだ始まっていないが days 日以内に始まるか。"""
    start, end = _parse_period(period)
    if not start:
        return False
    now = _today(today)
    if start <= now:
        return False
    return (start - now).days <= days


def check_hook_structure_type_a(text: str) -> dict:
    """本文が型A(感想→起、結は伏せる)の形になっているか判定する。"""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    if not t:
        return {"ok": False, "issue": "本文が空"}
    if re.search(r"https?://", t):
        return {"ok": False, "issue": "本文にURLがある(型AはリプにURLを置く)"}
    if len(t) < 30:
        return {"ok": False, "issue": f"短すぎて起が無い({len(t)}字/30字以上)"}
    if not any(h in t for h in _IMPRESSION_HINTS):
        return {"ok": False, "issue": "感想が無い(事実の提示だけになっている)"}
    for h in _CONCLUSION_HINTS:
        if h in t:
            return {"ok": False, "issue": f"結を本文に書いている(『{h}』)"}
    return {"ok": True, "issue": ""}


def build_hook(artist: str, fact: str, article: dict, body_text: str = "") -> str:
    """本文(URLなし)のフックを作る。

    設計(owner指摘 2026-08-17): 本文で全部書き切らず、途中で止めて続きをリプに置く。
    ただし出し渋りではなく、**本文だけでも読む価値がある**状態にして、最後の具体
    (内訳・条件・理由)だけをリプに残す。これがいま伸びている型。

    記事タイトルの丸写しは bot 感が強く実測でも伸びなかったため、LLM で組む。
    """
    body = str(body_text or "")
    # 2026-08-17: 当初は専用プロンプトで _call_llm を直叩きしたが、実測で毎回
    # 「大成功！」「感動」「期待大！」といった広報文になり、しかも指示した字数
    # (60〜130字)を守らず 150〜176字で返してガードに全部落ちた(=英語見出しの
    # フォールバックしか出なかった)。会話型で AI 感を抑えられているペルソナ経路
    # (_POST_FORMS・_is_ai_ish・捏造ガードが効く)に統一する。
    try:
        from lib.x_persona_voice import generate_persona_post
        for _ in range(3):
            out = generate_persona_post(
                {"artist": artist, "theme": fact, "tone": "plain"},
                kind="conversation", genre="default",
            )
            text = (out.get("text") or "").strip()
            if not text:
                continue
            # ハッシュタグ行は落とす(リプ側で記事に誘導するので本文は素のまま)
            text = re.sub(r"\n+#.*$", "", text).strip()
            if not text or "http" in text:
                continue
            if is_pr_tone(text):
                continue
            # 型A(感想→起、結は伏せる)を満たすものだけ通す。
            # プロンプトに構成を書いても守られない実績があるため、ここで検査する。
            if not check_hook_structure_type_a(text)["ok"]:
                continue
            # 2026-08-21: 型A(構文)を満たしても「〜楽しみ」だけの本文は伸びない。
            # 実測で伸びた投稿はいずれも日時/会場/条件を含んでいたので、
            # 本文に具体が無ければ記事から抜いて1行足す。足せないなら出さない。
            if not has_concrete_info(text)["ok"]:
                line = concrete_line(extract_concrete_facts(body))
                if not line:
                    continue
                text = f"{text}\n\n{line}"
                if len(text) > _MAX_HOOK_CHARS:
                    continue
            return text
    except Exception:
        pass
    # フォールバック: 出来事をそのまま短く提示する(URLは付けない)。
    # ここは感想も具体も乗らないため、pick_traffic_post() 側の
    # has_concrete_info() で落ちる想定(黙って薄い投稿を出さない)。
    # ここは感想が乗らないので型Aは満たさない。pick 側で型Aを必須にする場合は
    # check_hook_structure_type_a() で弾かれる想定。
    return str(fact or article.get("title", ""))[:100]


def _is_reachable_venue(body: str) -> bool:
    """日本の読者が実際に行ける開催かを判定する。

    pops-in 由来のポップアップは会場が「韓国 중구」のように国名+ハングルで
    入る。ハングルを含む、または明示的に韓国と書かれた会場は出さない。
    """
    t = str(body or "")
    m = re.search(r"会場\s*([^\n]{0,40})", t)
    venue = m.group(1) if m else ""
    if re.search(r"[\uac00-\ud7a3]", venue):
        return False
    if re.search(r"(韓国|ソウル|Seoul|Korea)", venue):
        return False
    return True


def search_event_articles(limit: int = 30) -> list[dict]:
    """会場・会期を持つ記事(ポップアップ/イベント)を新しい順に返す。

    2026-08-21: トレンド連動でマッチするのはニュース記事で、会場・会期の
    構造化情報を持たない(実測 6/6 で具体抽出ゼロ)。具体ゲートを通す投稿を
    出すには、会期情報を持つこちら側をネタ元にする。
    """
    out = []
    for kw in ("ポップアップ", "POP-UP"):
        try:
            q = urllib.parse.urlencode({
                "search": kw, "per_page": limit, "status": "publish",
                "orderby": "date", "order": "desc",
                "_fields": "id,title,link,featured_media",
            })
            req = urllib.request.Request(f"{WP_SEARCH}?{q}",
                                         headers={"User-Agent": "KpopJournal-Bot/2.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except Exception:
            continue
        for d in data:
            if not d.get("featured_media"):
                continue
            pid = d.get("id")
            if any(o["post_id"] == pid for o in out):
                continue
            title = (d.get("title") or {}).get("rendered", "")
            title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
            if not title or not d.get("link"):
                continue
            out.append({"post_id": pid, "title": title, "url": d["link"]})
    return out


def pick_event_post(today: str = "") -> dict | None:
    """開催中(または直近で始まる)イベント記事から投稿を1件組み立てる。

    ニュース側と違い、この経路は会場・会期という具体が確実に取れるので
    具体ゲートを通せる。会期が終わっているものは出さない(行けない情報を
    流すと読者を裏切る)。
    """
    used = _recent_used_ids()
    for art in search_event_articles():
        if art["post_id"] in used:
            continue
        body = fetch_body(art["post_id"])
        # 2026-08-21: 実データのポップアップは大半が韓国開催(会場「韓国 중구」)。
        # 日本の読者は行けないので、行動を変える具体にならない。国内開催に絞る。
        if not _is_reachable_venue(body):
            continue
        facts = extract_concrete_facts(body)
        period = (facts.get("period") or [""])[0]
        if not (is_currently_open(period, today=today)
                or upcoming_window(period, today=today, days=7)):
            continue
        line = concrete_line(facts)
        if not line:
            continue
        opening = "開催中" if is_currently_open(period, today=today) else "まもなく開催"
        hook = f"{art['title']}\n\n{line}"
        if not has_concrete_info(hook)["ok"]:
            continue
        return {"hook": hook, "reply": f"{opening}。詳細はこちら\n{art['url']}",
                "url": art["url"], "post_id": art["post_id"],
                "artist": art.get("artist", ""), "fact": art["title"],
                "title": art["title"], "kind": "event"}
    return None


def pick_traffic_post() -> dict | None:
    """いま出せる流入投稿を1件組み立てる。出せなければ None。"""
    from lib.x_trend_topics import trending_artists, pick_trend_topic
    used = _recent_used_ids()
    for artist in trending_artists():
        topic = pick_trend_topic(artist)
        if not topic:
            continue
        # 噂・批判・体調などは流入導線に使わない。記事へ誘導する文脈で
        # デリケートな話題を使うと、便乗して稼いでいるように見える。
        if topic.get("tone") != "plain":
            continue
        art = match_article(artist, topic["fact"], used_ids=used)
        if not art:
            continue
        # owner決定(A案): 引きを作る前に記事の中身を検証する。リプに渡せる具体が
        # 無い記事で引きだけ作ると、飛んだ読者を裏切る(既往: Direct直帰65%)。
        body = fetch_body(art["post_id"])
        if not has_substance(body):
            continue
        hook = build_hook(artist, topic["fact"], art, body_text=body)
        if not hook:
            continue
        # 2026-08-21 二重ゲート。片方だけでは漏れる:
        #   型Aのみ  → 「〜楽しみ」だけの情報量ゼロが通る(伸びない)
        #   具体のみ → build_hook のフォールバック(見出し丸写し)が、見出しに
        #              日付があると通ってしまう(bot臭く、実測でも伸びない)
        if not check_hook_structure_type_a(hook)["ok"]:
            continue
        if not has_concrete_info(hook)["ok"]:
            continue
        reply = build_reply(artist, topic["fact"], art, hook=hook, body=body)
        # リプが URL 単体なら「続き」になっていないので出さない
        if not reply.replace(art["url"], "").strip():
            continue
        return {"hook": hook, "reply": reply, "url": art["url"],
                "post_id": art["post_id"], "artist": artist,
                "fact": topic["fact"], "title": art["title"]}
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="トレンドと関連記事の対応を一覧")
    args = ap.parse_args()

    if args.list:
        from lib.x_trend_topics import trending_artists, pick_trend_topic
        used = _recent_used_ids()
        for a in trending_artists():
            t = pick_trend_topic(a)
            if not t:
                continue
            art = match_article(a, t["fact"], used_ids=used)
            mark = "○" if art else "×"
            print(f"{mark} {a:14s} {t['fact'][:52]}")
            if art:
                print(f"     → {art['title'][:60]}\n       {art['url']}")
        return 0

    post = pick_traffic_post()
    if not post:
        print("(いま出せる流入投稿なし: トレンドに関連する自社記事が無い)")
        return 1
    print("=== 流入投稿 ===")
    print(f"【本文】\n{post['hook']}")
    print(f"\n【自己リプ】\n{post['reply']}")
    print(f"\n記事: {post['title']} (post_id={post['post_id']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
