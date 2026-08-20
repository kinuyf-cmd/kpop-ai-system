#!/usr/bin/env python3
"""x_persona_voice.py — LLM ペルソナ駆動の X 投稿本文生成（テンプレ使い回しの根治）

背景:
  従来の X 投稿は2系統とも「AI 感丸出し / 同じコメントの使い回し」だった。
    - 会話起点 (lib/x_conversation_starter.py): 8テンプレ×2パターンを {artist}
      差し替えで再利用。例「{artist} のあの MV、何回見ましたか?\n見るたびに発見」が
      アーティスト名だけ変えて何度も流れる。
    - 記事誘導 (lib/x_post_templates.generate_tweet v14.0): 記事タイトルそのまま。

  本モジュールは投稿1件ごとに gpt-4o-mini で **毎回違う口調・語彙・話題** の本文を
  生成する。「K-POP 好きな等身大ライター」を複数の声 (PERSONAS) で使い分け、1人の
  人間が日々違う気分でつぶやいている感を出す。

設計:
  - generate_persona_post(context, kind, include_url) が単一の入口。
  - kind="conversation": 記事に紐づかない純粋な日常つぶやき/話題ふり (URL なし)。
  - kind="article":      記事タイトル+本文抜粋から「これ書いたよ/見て」の一言。
  - LLM 失敗・OPENAI_API_KEY 無 → used_llm=False を返し、呼出側が既存テンプレ
    /タイトルにフォールバックする (投稿は止めない)。
  - ハッシュタグは lib/x_post_templates.build_hashtags を再利用 (会話側の
    `#Stray Kids` 壊れタグ事故をここで一本化して根治)。

Anti-repeat (使い回し再発防止の肝):
  logs/x_posts.jsonl の直近本文をプロンプトに「これらと言い回しを被らせるな」と
  渡し、生成後も先頭一致/高類似なら1回だけ再生成 → なお駄目ならフォールバック。

有効化: 呼出側が環境変数 X_PERSONA_LLM=1 でゲートする (本モジュールは判定しない)。
"""
from __future__ import annotations

import json
import os
import random
import re
import urllib.request
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 直接実行 (python3 lib/x_persona_voice.py) でも `lib.` import が通るよう保険。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.x_post_templates import build_hashtags, extract_artist, sanitize_tweet
POSTS_LOG = ROOT / "logs" / "x_posts.jsonl"
COST_LOG = ROOT / "logs" / "x_tweet_llm.jsonl"
JST = timezone(timedelta(hours=9))


# ─── ライター陣 (架空ペルソナ) ──────────────────────────────────────────────
# 名前・人生・推し・口癖を持った固定キャラ。声色ランダム方式(多重人格でブレる)を捨て、
# 記事の artist/genre で担当ライターへ振り分け、各自が一貫した文体でつぶやく。
# 設定は config/x_writer_personas.json に外出し(コード改変なしで名前・口癖を調整可)。
# 設計はバイブル: .claude/plans/x-writer-personas-bible.md
WRITERS_CONFIG = ROOT / "config" / "x_writer_personas.json"


def _load_writers() -> dict:
    try:
        return json.loads(WRITERS_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"writers": {}, "genre_aliases": {}, "fallback_writer": ""}


_WRITERS_CACHE: dict | None = None


def _writers() -> dict:
    global _WRITERS_CACHE
    if _WRITERS_CACHE is None:
        _WRITERS_CACHE = _load_writers()
    return _WRITERS_CACHE


def select_writer(artist: str = "", genre: str = "") -> str:
    """記事の artist / genre から担当ライターのキーを決める。
    1) アーティスト一致(oshi リスト) 2) ジャンル一致(genres) 3) フォールバック。
    どれも無ければ全ライターからランダム(純つぶやき向け)。"""
    cfg = _writers()
    writers = cfg.get("writers", {})
    if not writers:
        return ""
    a = (artist or "").lower()
    # 1) アーティスト一致(最長一致を優先。短い名が長い名に埋もれる/dict順依存を回避)
    if a:
        best_key, best_len = "", 0
        for key, w in writers.items():
            for o in w.get("oshi", []):
                ol = (o or "").lower()
                if ol and ol in a and len(ol) > best_len:
                    best_key, best_len = key, len(ol)
        if best_key:
            return best_key
    # 2) ジャンル一致(エイリアス経由で正規化)
    g = cfg.get("genre_aliases", {}).get(genre, genre)
    if g:
        for key, w in writers.items():
            if g in w.get("genres", []):
                return key
    # 3) フォールバック(指定があれば)
    fb = cfg.get("fallback_writer", "")
    if fb in writers:
        return fb
    return random.choice(list(writers))


def _random_writer() -> str:
    writers = _writers().get("writers", {})
    return random.choice(list(writers)) if writers else ""


# 禁止フレーズ: 既存テンプレ語 + AI 煽り定型 + meta 表現 + 「わざとらしい」オチ定型。
# (lib/x_post_templates._llm_tweet_body の forbidden を継承・拡張)
FORBIDDEN = [
    # 既存テンプレ語 (使い回しの正体) — 完全撲滅対象
    "何回見ましたか", "見るたびに発見", "賛否は分かれそう", "賛否分かれ",
    "推し変遷", "音楽性が違う", "世代観", "戦略が他と違い",
    # AI 煽り定型
    "まさかの展開", "衝撃の事実", "ファン反応続出", "話題沸騰", "驚愕の事実",
    # engagement bait
    "みんなはどう思う", "私はアリだと思う", "どう思う?", "どう思う？",
    "コメントで議論", "教えてください", "聞きたい",
    # meta 表現
    "本記事では", "この記事は", "まとめている", "まとめました",
    # 抽象 AI 臭
    "動向", "あらまし", "ポイント",
]

# オタク語の soft 制限: forbidden ではないが「毎回はくどい」語。直近ログに出ていたら
# 当該語を含む生成を再試行で避ける(連発防止)。たまに出る分には自然。
OTAKU_SOFT = ["沼", "尊い", "課金", "涙腺", "エモい", "尊さ", "限界オタク", "勝ち"]

RECENT_WINDOW = 20      # anti-repeat で見る直近本文数
PREFIX_MATCH_LEN = 12   # 先頭一致で重複とみなす文字数

# 2026-08-17: 投稿ごとに1つ選んで「今回の書き方」として渡す文型。
# 「毎回ちがう構文で」という抽象指示ではモデルが一つの型(「〇〇、〜けど、〜だろう」)に
# 収束し、実測126本で「けど、」62% となった。型を外から指定して散らす。
_POST_FORMS = (
    "事実を短く言い切るだけ。感想は付けない。20〜35字。",
    "体言止めで終える。文末に『だ・である・です』を置かない。",
    "驚きを先に置き、そのあと何が起きたかを書く。",
    "自分の行動や状況の報告から入る(見てた/知らなかった/今知った など)。",
    "一つだけ素朴な疑問を書く。答えや推測は書かない。",
    "誰かに話しかけるでもない、途中で切れた独り言。文を完結させない。",
    "数字への反応だけを書く。その数字が何を意味するかは書かない。",
    "淡々と事実を並べる。感情語(すごい/やばい/嬉しい)を一切使わない。",
    "『〜らしい』『〜って』と伝聞で受けて、そこで終える。",
    "以前との比較を一言だけ。良し悪しの判断は付けない。",
)


def _recent_post_bodies(n: int = RECENT_WINDOW) -> list[str]:
    """logs/x_posts.jsonl の直近 n 件のフック/会話本文を返す (URL リプ等は除く)。"""
    if not POSTS_LOG.exists():
        return []
    try:
        lines = POSTS_LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    bodies: list[str] = []
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("mode") == "url_reply":
            continue
        text = (d.get("text") or "").strip()
        if not text:
            continue
        # ハッシュタグ/URL 行を落として本文だけ比較対象にする
        body = re.sub(r"https?://\S+", "", text)
        body = re.sub(r"#\S+", "", body).strip()
        if body:
            bodies.append(body)
        if len(bodies) >= n:
            break
    return bodies


def _strip_decorations(text: str) -> str:
    """本文から URL/ハッシュタグ/絵文字残骸/改行を除去して1行に正規化。"""
    out = text.replace("\n", " ").replace("\r", " ").strip()
    out = re.sub(r"https?://\S+", "", out).strip()
    out = re.sub(r"#\S+", "", out).strip()
    return out


def _has_forbidden(text: str) -> bool:
    return any(kw in text for kw in FORBIDDEN)


# 韓国語ソースの見出しをそのまま種にすると、人名や曲名がハングルのまま本文に
# 残ることがある(実測: 「NCT 런쥔が…「위로와 힐링」について語った」)。
# 読者は日本語話者なので、残っていたら生成し直す。
_HANGUL = re.compile(r'[가-힣ᄀ-ᇿ]')


def _has_hangul(text: str) -> bool:
    return bool(_HANGUL.search(str(text or '')))


def _too_similar(text: str, recent: list[str]) -> bool:
    """直近本文と先頭 PREFIX_MATCH_LEN 字が一致したら使い回しとみなす。"""
    head = text[:PREFIX_MATCH_LEN]
    if len(head) < PREFIX_MATCH_LEN:
        return False
    return any(b.startswith(head) or text == b for b in recent)


def _log_cost(res: dict, persona: str) -> None:
    """gpt-4o-mini の usage を logs/x_tweet_llm.jsonl に追記 (kpi_dashboard 集計用)。
    既存 _llm_tweet_body と同形式 (caller のみ x_persona_voice に変える)。"""
    try:
        usage = res.get("usage", {})
        in_tok = int(usage.get("prompt_tokens", 0))
        out_tok = int(usage.get("completion_tokens", 0))
        # gpt-4o-mini pricing: input $0.00015 / output $0.0006 per 1K
        cost = in_tok / 1000 * 0.00015 + out_tok / 1000 * 0.0006
        now = datetime.now(JST)
        entry = {
            "ts": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "caller": "x_persona_voice",
            "persona": persona,
            "model": "gpt-4o-mini",
            "input": in_tok,
            "output": out_tok,
            "cost_usd": round(cost, 6),
        }
        COST_LOG.parent.mkdir(parents=True, exist_ok=True)
        with COST_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _build_prompt(kind: str, context: dict, writer_key: str,
                  recent: list[str]) -> tuple[str, str]:
    """(system, user) を組み立てる。writer_key の人物像で語らせ、雑談トーンを徹底する。"""
    w = _writers().get("writers", {}).get(writer_key, {})
    name = w.get("name", "")
    age = w.get("age")
    stance = w.get("stance", "")
    bio = w.get("bio", "")
    voice = w.get("voice", "")
    tics = "、".join(w.get("tics", []))
    dislikes = "、".join(w.get("dislikes", []))
    artist = context.get("artist", "")
    title = context.get("title", "")
    source = (context.get("source_text", "") or "")[:1200]

    avoid = ""
    if recent:
        sample = "\n".join(f"・{b[:40]}" for b in recent[:10])
        avoid = (
            "\n\n【直近の投稿(言い回し・構文・話題を絶対に被らせない)】\n"
            f"{sample}"
        )

    # 2026-08-17: 投稿1件ごとに「書き方」を1つ指定して、構文の収束を防ぐ。
    form = random.choice(_POST_FORMS)

    # 具体年齢でなく「◯代」表記。age は内部データとして数値のまま使う。
    age_s = f"{(int(age) // 10) * 10}代・" if age else ""
    system = (
        f"あなたは「{name}」({age_s}{stance})という日本語の K-POP ファン/ライターです。"
        f"\nプロフィール: {bio}"
        f"\n文体の癖: {voice} よく使う言い回し例: {tics}。"
        + (f"\n苦手: {dislikes}。" if dislikes else "")
        + "\n\nいま X(Twitter)に、本当に思ったことをそのまま、ひとことつぶやきます。"
        "\n\n【絶対ルール — これを破ると不自然になる】"
        "\n- 生身の人間の独り言。AI/まとめサイト/広報/宣伝の口調は厳禁"
        "\n- ★オチを付けない。きれいな感想でまとめない。言い切らない。途中で終わってもいい"
        "\n- ★毎回キレイに感情で締めるのをやめる。素っ気なくていい。疑問・つっこみ・"
        "どうでもいい報告・愚痴・実況・脱線、なんでもいい"
        "\n- ★「いいことを言おう」としない。目的(宣伝・拡散)を絶対に匂わせない"
        "\n- オタク語(沼/尊い/課金/涙腺/エモい)を毎回使わない。素朴な普通の言葉で"
        "\n- 毎回ちがう語彙・構文・入り。テンプレ的な型を作らない"
        # 2026-08-17: 抽象的に「テンプレを作るな」と書いても効かず、実測126本で
        # 「けど、」62%・「〜だろう」33%・「なんか」27% と癖が固定化した。
        # 実際に出た型を名指しで禁じる。
        "\n【実測で多すぎた型 — 使うな】"
        "\n- ★「〇〇、〜な気がするけど、〜なんだろう」の形。これが最頻の型で最もAIっぽい"
        "\n- ★逆接『けど』でつないで問いかけで締める形(全体の6割がこれだった)"
        "\n- ★「やっぱり」「ほんとに」「なんか」で始める/強調する癖"
        "\n- ★文末を「〜だろう」「〜のかな」「〜んだろう」で毎回締めること"
        "\n代わりに: 体言止め、言い切り、短い実況、独り言の途中で切る、"
        "素朴な事実確認、順序を入れ替える(感想を先に置く)など、形自体を毎回変える"
        # 2026-08-17: 「毎回変えろ」と言うだけでは、モデルは結局いちばん書きやすい
        # 一つの型に収束した(禁止型を塞ぐたび、締めの語だけ変えて同じ構文が残った)。
        # 毎回ひとつ「書き方」を指定して回すことで、型自体を強制的に散らす。
        f"\n\n【今回の書き方 — これに従うこと】\n{form}"
        "\n- 出力は本文のみ1行。ハッシュタグ・URL・絵文字・署名は付けない(別途付与する)"
        "\n- engagement bait(「どう思う?」「教えてください」)・煽り(「衝撃の」)・"
        "meta(「本記事では」)は禁止"
        "\n- 短くていい。20〜90字目安。長い感想文にしない"
        + avoid
    )

    if kind == "article":
        user = (
            f"次の話題について、{name}が思わずこぼす一言を書いて。"
            "記事の紹介や要約ではなく、見聞きして個人的に浮かんだ独り言。\n"
            f"話題(タイトル): {title}\n参考(本文抜粋): {source}\n"
            "\n注意: ソースに無い固有名詞・数値・事実は創作しない。"
            "感想を述べきらず、ひっかかった一点や素朴な反応でいい。"
            "\nつぶやき(1行のみ、オチ無しでよい):"
        )
    else:  # conversation — 記事に紐づかない純粋なつぶやき
        # トピックの手掛かりが無ければ、そのライター自身の推し/関心から1つ選んで種にする。
        # (種が無いと直近の avoid 例を話題と誤認して全員同じ話になる事故を防ぐ)
        # 2026-08-16 修理: 従来は `topic = artist or theme` で、artist があると
        # theme(具体的な出来事)が捨てられていた。結果ヒントが「頭にあるのは
        # 『TWICE』のこと」だけになり、LLM は書くべき中身を知らないまま
        # 「なんか〜な気がする」「どうなってんだろう」と曖昧語で埋めるしかなかった
        # (owner指摘「ペルソナ型も的外れ」の直接原因)。両方を渡す。
        fact = (context.get("theme") or "").strip()
        topic = artist or fact
        if not topic:
            seeds = list(w.get("topics", [])) or list(w.get("oshi", []))
            topic = random.choice(seeds) if seeds else ""
        if artist and fact:
            # 2026-08-17: 渡した事実を「必ず具体的に書かせる」。実測で、事実を
            # 渡しても「〜って、なんかすごい気がする」と抽象化して逃げる生成が
            # 残っていた。数字・固有名は落とさせない(反応が付いた投稿は例外なく
            # 数字か固有の出来事を含んでいた)。
            hint = (f"今ちょうど頭にあるのは「{artist}」の話で、きっかけはこの出来事:"
                    f"「{fact}」。この出来事に触れた独り言にすること。"
                    "出来事の具体(数字・作品名・何が起きたか)を必ず一つは書くこと。"
                    "ぼかして『すごい』『やばい』だけで済ませない。"
                    # 2026-08-17: 実測で「Takes 2nd Win(2回目の1位)」を「2位獲得」と
                    # 書き換える誤りが出た。数字と順位の意味は原文のまま扱わせる。
                    "\n重要: 出来事に書かれた数字・順位・回数は、意味を変えずにそのまま扱うこと。"
                    # 例示に固有の語(旧: 「2nd Win」)を使うと、それ自体が出来事と
                    # 無関係に投稿本文へ紛れ込む事故が実測で出た。一般形で説明する。
                    "英語の「Nth Win」は『N回目の1位』の意味で、『N位』ではない。"
                    # 2026-08-17: 実測で「LALISAのMVが1億回再生突破」のような、出来事に
                    # 一切書かれていない記録を創作する生成が出た。曲名・数字・記録は
                    # 出来事に書かれているものしか使えない、と明示で縛る。
                    "\n絶対禁止: 出来事に書かれていない曲名・数字・記録・再生回数・順位を出すこと。"
                    "自分の記憶から補ってはいけない。書かれている範囲だけで書く。"
                    "他の曲や過去の実績に言及したくなっても、出来事に無ければ書かない。")
            # 2026-08-17: 噂・疑惑・移籍・体調などは扱ってよいが、断定させない。
            # ニュースを扱う以上こうした話題は避けられないが、独り言の体裁で
            # 言い切ると噂の拡散・決めつけになる。伝聞であることを口調で示す。
            if str(context.get("tone") or "") == "hedged":
                hint += (
                    "\nこの話題は未確定・デリケートな内容を含む。次を厳守すること:"
                    "\n- 報道・発表を受けての受け止めとして書き、事実として断定しない"
                    "(『〜らしい』『と報じられてる』『という話が出てる』のように伝聞で書く)"
                    "\n- 原因・背景・今後を勝手に推測しない。決めつけない"
                    "\n- 面白がらない。茶化さない。他者や事務所を非難しない"
                    "\n- 当事者が読んでも失礼にならない範囲にとどめる"
                )
            # 捏造禁止は最後に置く。hedge の指示より後ろに置かないと、伝聞口調へ
            # 寄せる過程で「原文に無い曲名・記録」を補う生成が実測で復活した。
            hint += ("\n【最優先】出来事に書かれていない固有名詞・曲名・数字・記録は"
                     "一切書かないこと。これは他のどの指示よりも優先する。"
                     # 2026-08-17: 「300 Million Streams」を「300万回再生」と書く
                     # 誤変換が実測で出た(正しくは3億)。英語の桁は間違えやすいので明示。
                     "\n英語の数値を日本語にするときの桁に注意: million=100万、"
                     "billion=10億。『300 million』は『3億』、『1.9 billion』は『19億』。"
                     "『1.9 billion』のように英語のまま書かず、必ず日本語の桁に直すこと。"
                     "桁に自信が持てないときは、数字に触れず出来事だけを書くこと。"
                     # 出来事が韓国語ソースだと人名・曲名がハングルのまま残る。
                     "\n出来事が韓国語で書かれていても、本文は必ず日本語で書くこと。"
                     "人名・曲名も日本語(またはアルファベット)表記に直し、"
                     "ハングルをそのまま残さない。")
        elif topic:
            hint = f"今ちょうど頭にあるのは「{topic}」のこと。"
        else:
            hint = ""
        user = (
            f"{name} が、いま日常でふともらした K-POP まわりの独り言を一言。"
            f"{hint}"
            "自分の推しや関心ごとについての、独り言・疑問・あるある・どうでもいい報告・"
            "ぼやき・思いつきでいい。ニュースの要約や紹介ではない。"
            "直前の投稿リストはあくまで『被らせない為』の参照で、その話題を続ける必要はない。"
            # 2026-08-17: 「事実を断定しない」は、渡した出来事まで曖昧にさせる副作用が
            # あった。断定を避けるべきなのは**自分の解釈・憶測**であって、出来事そのもの
            # ではない。出来事は与えられたとおり書き、感想の側を言い切らない。
            "出来事そのものは与えられたとおり書いてよい。断定を避けるのは自分の解釈の側。"
            "きれいにまとめない。"
            # 2026-08-17: 反応(返信)を生む引っかかりを1つ残す。実測で ER が付いた
            # 投稿は、読み手が「自分もそう思う/いや違う」と言いたくなる一点を持っていた。
            # ただし「どう思う?」等の露骨な engagement bait は system 側で禁止済みなので、
            # あくまで独り言の中に自然な余白として置く。
            "\n読んだ人が思わず口を挟みたくなる余白を一つ残すこと。"
            "例: 自分だけの偏った感想、意外だった点、他と比べたときの引っかかり。"
            "ただし質問形で締めたり『みんなはどう?』と呼びかけたりはしない。"
            # 2026-08-16: 中身のない一般論を禁止(実測でこの型が8/8を占めた)
            "\n禁止: 「なんか〜な気がする」「どうなってるんだろう」「謎すぎ」のような、"
            "対象を差し替えても成立してしまう空虚な感想。何について言っているのかが"
            "読み手に伝わる、具体的な一点に触れること。"
            "\nつぶやき(1行のみ、オチ無しでよい):"
        )
    return system, user


# ─── 数値の整合チェック(捏造・桁違いの検出) ──────────────────────────────
# プロンプトで「原文に無い数字を書くな」と指示しても、実測で以下が残った:
#   「300 Million Streams」→「300万回再生」(正: 3億) / 「1.9 Billion」→「1.9億」(正: 19億)
# 桁違いは最も分かりやすい誤情報なので、生成後にコードで検査して弾く。

# 日付・時刻として書かれた数値は検査から外す(誤情報になりにくく表記ゆれも大きい)。
# 「2年半」のような経過年数は日付ではないので除外しない — 出来事に無ければ創作。
_DATE_LIKE = re.compile(r'\d+\s*(?:月\d+\s*日|月|日|時|分|年代|/|:)')


def _fact_number_set(fact: str) -> set[float]:
    """出来事に現れる数値を、日本語表記に換算した集合として返す。

    「300 Million」なら 3億(=300000000)と、素の 300 の両方を許容する。
    どちらの言い回しで書かれても弾かないため。
    """
    out: set[float] = set()
    text = str(fact or '')
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*(million|billion|thousand)?', text, re.IGNORECASE):
        try:
            n = float(m.group(1))
        except ValueError:
            continue
        out.add(n)
        unit = (m.group(2) or '').lower()
        if unit == 'million':
            out.add(n * 1_000_000)
        elif unit == 'billion':
            out.add(n * 1_000_000_000)
        elif unit == 'thousand':
            out.add(n * 1_000)
    return out


def _body_numbers(text: str) -> list[float]:
    """本文中の数値を、単位(万/億)を掛けた実数として返す。日付類は除く。"""
    out = []
    body = _DATE_LIKE.sub(' ', str(text or ''))
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*(億|万)?', body):
        raw = m.group(1)
        try:
            n = float(raw)
        except ValueError:
            continue
        unit = m.group(2) or ''
        if unit == '億':
            out.append(n * 100_000_000)
        elif unit == '万':
            out.append(n * 10_000)
        else:
            out.append(n)
    return out


def _numbers_consistent(text: str, fact: str) -> bool:
    """本文の数値がすべて出来事の数値で説明できるか。

    出来事に無い数字を出した場合(捏造)と、桁を取り違えた場合の両方を弾く。
    出来事が空なら検査しない(呼出側が事実を渡していないケース)。
    """
    if not str(fact or '').strip():
        return True
    allowed = _fact_number_set(fact)
    for n in _body_numbers(text):
        if not any(abs(n - a) < max(1e-6, abs(a) * 1e-9) for a in allowed):
            return False
    return True


def _norm_title(s: str) -> str:
    """作品名比較用の正規化(記号・空白を落として小文字化)。"""
    return re.sub(r"[\s'’\"“”,.\-!?&:]", '', str(s or '')).lower()


def _titles_consistent(text: str, fact: str) -> bool:
    """本文が挙げる曲名・番組名が、出来事に出てくるものだけかを検査する。

    実測(2026-08-17)で、退所報道の独り言に「『Next Level』の頃が懐かしい」と
    出来事に無い別曲を差し込む生成が出た。読者には事実の一部に見えるため弾く。
    """
    if not str(fact or '').strip():
        return True
    fact_norm = _norm_title(fact)
    for m in re.finditer(r'[「『"“]([^」』"”]{2,60})[」』"”]', str(text or '')):
        if _norm_title(m.group(1)) not in fact_norm:
            return False
    return True


# ─── AI感の検出(実測した癖を名指しで弾く) ────────────────────────────────
# 2026-08-17 実測 (conversation 126本): 「けど、」62% /「〜だろう」33% /
# 「なんか」27%。直近12本はほぼ全てが「主題、感想〜けど、疑問…」の同一構文だった。
# system プロンプトには既に「毎回ちがう構文で」と書いてあるが効かなかったため、
# 具体的な型を検出して作り直させる。

# 逆接からの問いかけで締める、最頻の型。
_AI_PATTERNS = (
    # 「〜けど、〜だろう/のかな/なんだろう」で締める
    r'けど[、,].{0,40}(?:だろう|のかな|なんだろ|んだろ|かなあ|かなぁ)',
    # 「気がする」+ 逆接(実測10%、どの話題でも成立してしまう)
    r'気がするけど',
    r'気がする[、,]',
    # 「〜なんだろう…」で終わる
    r'(?:なんだろう|んだろう|のだろう)[。.．…]*$',
    # 「やっぱり」+「ほんとに/すごい」の感嘆セット
    r'やっぱり.{0,30}(?:ほんとに|本当に).{0,20}すご',
    r'ほんとに.{0,20}すごすぎ',
    # 2026-08-17 第2波: 上の型を塞いだ直後、生成8本中7本が「〜けど/〜って、
    # …気になる」に流れた。締めの語を変えただけで構文は同じなので、これも弾く。
    r'(?:けど|って)[、,].{0,40}気になる',
    r'どうなるのか.{0,10}気になる',
    r'気になる(?:部分が多い|ところ|な[ぁあ]?)[。.．…]*$',
    # 中身のない強調(「本当にすごい/マジで〜すぎる」)
    r'(?:本当に|ほんとに|マジで).{0,10}(?:すごい|すご[すぎ]|意味深)',
    r'すごい.{0,8}(?:展開|ニュース|こと)だ',
)

# 名乗り・署名。個人の独り言に毎回名前が入るのは不自然(owner指摘)。
_SIGNATURE_LIKE = re.compile(r'[🌙💐💜⚡👗🎧🌸🔥✨][ぁ-んァ-ヶ一-龠ーA-Za-z]{1,8}[🌙💐💜⚡👗🎧🌸🔥✨]')


def _is_ai_ish(text: str) -> bool:
    """実測した「AI感の型」に当てはまるか。当てはまれば生成し直す。"""
    t = str(text or '')
    if _SIGNATURE_LIKE.search(t):
        return True
    return any(re.search(p, t) for p in _AI_PATTERNS)


def _has_otaku_overlap(text: str, recent: list[str]) -> bool:
    """text にオタク語が含まれ、かつ直近ログにも同じ語が出ているなら True(連発防止)。"""
    recent_blob = " ".join(recent)
    for kw in OTAKU_SOFT:
        if kw in text and kw in recent_blob:
            return True
    return False


def _call_llm(system: str, user: str, writer_key: str) -> str:
    """gpt-4o-mini を1回叩いて本文(1行)を返す。失敗/キー無は空文字。
    多様性が目的なので temperature は高め(0.85)。"""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return ""
    body = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.85,
        "max_tokens": 200,
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read())
        out = res["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""
    _log_cost(res, writer_key)
    return _strip_decorations(out)


def generate_persona_post(context: dict, *, kind: str = "conversation",
                          include_url: bool = False, url: str = "",
                          genre: str = "default",
                          persona: str | None = None) -> dict:
    """名前付きライターの声で X 投稿1件を生成する(雑談トーン+署名)。

    Args:
      context: {"title", "source_text", "artist", "theme"} のうち持つものを渡す。
      kind:    "conversation" (純つぶやき・URLなし) | "article" (記事フック)。
      include_url: True かつ url 指定時、本文末尾に URL を付ける(通常は False=自己リプ運用)。
      url:     include_url=True のときの記事 URL。
      genre:   担当ライター選定 + ハッシュタグ生成に使うジャンル。
      persona: ライターキーを固定したい場合 (省略時は artist/genre から自動選定。
               conversation で何も手掛かりが無ければ全ライターからランダム)。

    Returns:
      {"text", "writer", "name", "signature", "char_count", "hashtags", "used_llm"}。
      ("persona" は writer キーの別名として後方互換のため併記)
      used_llm=False のとき text は空 → 呼出側が既存テンプレ/タイトルにフォールバック。
    """
    artist = context.get("artist") or (
        extract_artist(context.get("title", "")) if context.get("title") else ""
    )

    # 担当ライター選定: 明示指定 > artist/genre 自動 > (純つぶやきは)ランダム。
    writers = _writers().get("writers", {})
    if persona in writers:
        writer_key = persona
    elif artist or (genre and genre != "default") or kind == "article":
        writer_key = select_writer(artist, genre)
    else:
        writer_key = _random_writer()
    if writer_key not in writers:
        writer_key = _random_writer()

    w = writers.get(writer_key, {})
    recent = _recent_post_bodies()

    system, user = _build_prompt(kind, {**context, "artist": artist},
                                 writer_key, recent)

    # 生成 → forbidden/重複/オタク語連発なら最大2回まで再生成 → 駄目ならフォールバック
    body = ""
    for attempt in range(3):
        cand = _call_llm(system, user, writer_key)
        if not cand:
            break  # キー無/API 失敗 → フォールバック
        if _has_forbidden(cand) or _too_similar(cand, recent) or _has_hangul(cand):
            continue
        # 2026-08-17: 出来事に無い数字・桁違いの数字は誤情報として最も目立つ。
        # プロンプト指示だけでは実測で漏れたため、ここで検査して作り直させる。
        _fact = str(context.get("theme") or "")
        if not _numbers_consistent(cand, _fact) or not _titles_consistent(cand, _fact):
            continue
        # オタク語の連発・AI感の定型は最終試行では許容(無限ループ回避)
        if attempt < 2 and (_has_otaku_overlap(cand, recent) or _is_ai_ish(cand)):
            continue
        body = cand
        break

    if not body:
        return {"text": "", "writer": writer_key, "persona": writer_key,
                "name": w.get("name", ""), "signature": w.get("signature", ""),
                "char_count": 0, "hashtags": "", "used_llm": False}

    body = sanitize_tweet(body)
    if len(body) > 130:
        body = body[:128] + "…"

    hashtags = build_hashtags(artist, genre)
    # 署名 = 絵文字で名前を両側から挟む(💐ももか💐)。sign_emoji があればそれで生成し、
    # 無ければ config の signature 文字列にフォールバック(後方互換)。
    _emoji = w.get("sign_emoji", "")
    _name = w.get("name", "")
    signature = f"{_emoji}{_name}{_emoji}" if (_emoji and _name) else w.get("signature", "")

    # レイアウト: 本文 → (URL) → ハッシュタグ
    # 2026-08-17: 署名(💐ももか💐)を本文から外した。個人アカウントの独り言に
    # 毎回名乗りが入るのは不自然で、AI/bot感の直接の原因になっていた(owner指摘)。
    # signature 自体は戻り値に残す(呼出側の互換とログ用)。
    block1 = body
    tail = [block1]
    if include_url and url:
        tail.append(url)
    if hashtags:
        tail.append(hashtags)
    text = "\n\n".join(tail).strip()

    return {
        "text": text,
        "writer": writer_key,
        "persona": writer_key,   # 後方互換
        "name": w.get("name", ""),
        "signature": signature,
        "char_count": len(text),
        "hashtags": hashtags,
        "used_llm": True,
    }


# ─── CLI (動作確認用) ───────────────────────────────────────────────────────
def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="persona voice tweet generator (dry)")
    ap.add_argument("--kind", default="conversation",
                    choices=["conversation", "article"])
    ap.add_argument("--artist", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--genre", default="default")
    ap.add_argument("--writer", "--persona", dest="persona", default=None,
                    help="ライターキーを固定 (mina/yui/nono/saki/haruka/aya/rika/editorial)")
    ap.add_argument("-n", type=int, default=1, help="生成回数")
    args = ap.parse_args()

    ctx = {"artist": args.artist, "title": args.title}
    for i in range(args.n):
        out = generate_persona_post(ctx, kind=args.kind, genre=args.genre,
                                    persona=args.persona)
        tag = f"{out['name']}({out['writer']})" if out["used_llm"] else "FALLBACK"
        print(f"--- #{i+1} [{tag}] {out['char_count']}字 ---")
        print(out["text"] or "(LLM 不可 → 呼出側でテンプレ退避)")
        print()
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
