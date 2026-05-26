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
        topic = artist or context.get("theme", "")
        if not topic:
            seeds = list(w.get("topics", [])) or list(w.get("oshi", []))
            topic = random.choice(seeds) if seeds else ""
        hint = f"今ちょうど頭にあるのは「{topic}」のこと。" if topic else ""
        user = (
            f"{name} が、いま日常でふともらした K-POP まわりの独り言を一言。"
            f"{hint}"
            "自分の推しや関心ごとについての、独り言・疑問・あるある・どうでもいい報告・"
            "ぼやき・思いつきでいい。ニュースの要約や紹介ではない。"
            "直前の投稿リストはあくまで『被らせない為』の参照で、その話題を続ける必要はない。"
            "事実を断定しない。きれいにまとめない。"
            "\nつぶやき(1行のみ、オチ無しでよい):"
        )
    return system, user


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
        if _has_forbidden(cand) or _too_similar(cand, recent):
            continue
        # オタク語の連発は最終試行では許容(無限ループ回避)
        if attempt < 2 and _has_otaku_overlap(cand, recent):
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
    signature = w.get("signature", "")

    # レイアウト: 本文 → 署名 → (URL) → ハッシュタグ
    parts = [body]
    if signature:
        parts.append(signature)
    block1 = "\n".join(parts)
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
