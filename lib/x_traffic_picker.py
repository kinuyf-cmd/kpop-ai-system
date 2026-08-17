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
import re
import sys
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
            return text
    except Exception:
        pass
    # フォールバック: 出来事をそのまま短く提示する(URLは付けない)
    return str(fact or article.get("title", ""))[:100]


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
