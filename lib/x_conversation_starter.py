#!/usr/bin/env python3
"""x_conversation_starter.py — M10 Q-2 conversation 起点投稿生成

x-posting-rules SKILL §5 の 8 会話フォーマットを K-POP 特化で
text-only 投稿(120-180字、URL なし、ハッシュタグ 2-3個)に展開する。

X アルゴリズム最新仕様(2026/5/15)準拠:
- text-only がメディア投稿より 30% 高パフォーマンス
- URL を本文に含めない(suppression 回避)
- 返信に著者が返信 = like 150個分 → コメント誘発が最重要

使用:
    python3 lib/x_conversation_starter.py                          # ランダムで1案生成
    python3 lib/x_conversation_starter.py --id C-1                 # 指定 ID で生成
    python3 lib/x_conversation_starter.py --artist BTS --id C-2    # アーティスト指定
    python3 lib/x_conversation_starter.py --list                   # 8 テンプレ一覧
    python3 lib/x_conversation_starter.py --post                   # post_to_x.py に渡して投稿
    python3 lib/x_conversation_starter.py --dry-run                # 投稿せず生成のみ
"""
from __future__ import annotations
import argparse
import json
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# .env を読む(X_PERSONA_LLM / OPENAI_API_KEY 等)。直接 CLI 実行(cron)でも
# ペルソナ生成が有効になるよう、scheduler と同様にここで明示ロードする。
try:
    from dotenv import load_dotenv
    load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"))
except Exception:
    pass


ROOT = Path(__file__).resolve().parent.parent
# 直接実行 (python3 lib/x_conversation_starter.py) でも `lib.x_persona_voice` 等の
# `lib.` import が通るよう保険。-m / repo root からの import 時は無害。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LOG_DIR = Path.home() / ".kpop_recovery"
LOG_FILE = LOG_DIR / "x_posting_log.jsonl"


# 8 会話フォーマット(SKILL §5 と一致)
TEMPLATES = {
    "C-1": {
        "category": "意見集約",
        "title": "あなたの推しグループは?",
        "patterns": [
            "3世代と4世代、{artist} みたいなグループだとどっち推しですか?\n音楽性が違うので、好み分かれそう\n\nあなたの世代観、ぜひ教えてください #KPOP",
            "K-POP の推し、最近変わりました?\n{artist} みたいなコアなファンも増えてる気がします\n\nみなさんの推し変遷、コメントで聞きたい #KPOP",
        ],
    },
    "C-2": {
        "category": "対立喚起",
        "title": "新曲評価分かれ",
        "patterns": [
            "{artist} の新曲、評価が賛否分かれてますね\n音楽性の挑戦で読み方が変わる気がします\n\nあなたはどう聴きましたか? #KPOP #{artist}",
            "新曲のコンセプト、好き嫌い真っ二つになってる\n{artist} の路線変更、これは支持派それとも慎重派?\n\nコメントで議論しましょう #KPOP",
        ],
    },
    "C-3": {
        "category": "世代論",
        "title": "世代比較",
        "patterns": [
            "{artist} とデビュー間もない新人、音楽性どちらが好みですか?\nビートメイキングが世代で本当に違う\n\n世代別の魅力、語ってください #KPOP",
            "3世代の完成度 vs 4世代の挑戦、{artist} みたいなレジェンドとどう比べる?\n\nあなたの基準、教えてください #KPOP",
        ],
    },
    "C-4": {
        "category": "分析",
        "title": "世界進出戦略",
        "patterns": [
            "{artist} の世界進出、戦略が他と違いますね\n言語選択・MV演出・コラボ相手、すべて緻密に設計\n\nどの戦略に注目してますか? #KPOP",
            "K-POP のグローバル戦略、{artist} で変わった気がします\n進出の質が変わってきている\n\n注目戦略をコメントで #KPOP",
        ],
    },
    "C-5": {
        "category": "期待感",
        "title": "カムバ期待",
        "patterns": [
            "{artist} のカムバ予定、楽しみですか?\nティーザーから察するに、コンセプトが大胆\n\n期待ポイント、コメントで共有しよう #KPOP #{artist}",
            "カムバまであと少し、{artist} はどんな曲調で来るでしょう?\n前作との対比、議論したい\n\nあなたの予想は? #KPOP",
        ],
    },
    "C-6": {
        "category": "社会論",
        "title": "ファン層変化",
        "patterns": [
            "K-POP ファン層の年齢構成、変わってきてますね\n{artist} みたいなアーティストで新規層が広がってる\n\nあなたの周りも変わりました? #KPOP",
            "K-POP コミュニティの成熟、最近強く感じます\n{artist} のファンダム、年齢も国籍も多様\n\n変化を体感してますか? #KPOP",
        ],
    },
    "C-7": {
        "category": "データ分析",
        "title": "チャート分析",
        "patterns": [
            "韓国チャート vs グローバルチャート、傾向が違いますね\n{artist} のように両立してるアーティストが少ない\n\n注目アーティストいますか? #KPOP",
            "Hot 100 と Melon、{artist} で初めて両方一位の例があった気がします\n\nチャートの読み方、コメントで議論しよう #KPOP",
        ],
    },
    "C-8": {
        "category": "視聴行動",
        "title": "MV視聴行動",
        "patterns": [
            "{artist} のあの MV、何回見ましたか?\n見るたびに発見があって深い\n\nあなたの注目シーン、教えてください #KPOP #{artist}",
            "MV のシンメ、{artist} のパフォーマンスが完璧すぎる\nリピート視聴したくなる\n\n推しシーン、コメントで #KPOP",
        ],
    },
}

DEFAULT_ARTIST_POOL = [
    "BTS", "BLACKPINK", "NewJeans", "TWICE", "SEVENTEEN", "Stray Kids",
    "IVE", "aespa", "LE SSERAFIM", "ILLIT", "RIIZE", "BABYMONSTER",
    "NCT", "ENHYPEN", "ATEEZ",
]


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=9))).isoformat()


def list_templates() -> None:
    print("=== conversation starter templates ===")
    for tid, t in TEMPLATES.items():
        print(f"  {tid}  [{t['category']:8s}] {t['title']}")
    print(f"\n  total: {len(TEMPLATES)} templates")


def _load_directives() -> dict:
    """config/auto_directives.json を安全に読む(無ければ空)。
    focus_themes(時事テーマ)/ winning_words(稼ぐ語)/ stop_doing(避ける表現)を使う。"""
    path = ROOT / "config" / "auto_directives.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _weighted_artist(directives: dict) -> str:
    """focus_themes に登場するアーティスト名を優先して artist を選ぶ(時事連動)。
    該当が無ければ DEFAULT_ARTIST_POOL からランダム。"""
    themes = directives.get("focus_themes", [])
    theme_text = " ".join(
        (t.get("theme", "") if isinstance(t, dict) else str(t)) for t in themes
    )
    hits = [a for a in DEFAULT_ARTIST_POOL if a in theme_text]
    pool = hits if hits else DEFAULT_ARTIST_POOL
    return random.choice(pool)


# 2026-08-16: 会話つぶやきの種にしないトピック語。事実関係が確定していない、
# あるいは被害・係争が絡む話題を「ファンの独り言」として流すと、憶測の拡散や
# 二次加害になる。記事として扱うことは妨げないが、X の軽い投稿には載せない。
_SENSITIVE_TOPIC_WORDS = (
    '盗作', '剽窃', '流出', '訴訟', '告訴', '起訴', '逮捕', '書類送検',
    '暴行', 'ハラスメント', 'いじめ', '学暴', '薬物', '飲酒運転',
    '死去', '訃報', '事故死', '自殺', '熱愛否定', '離婚', '不倫',
    '論争', '物議', '炎上', '批判殺到', '謝罪', '契約解除', '専属契約紛争',
)


def _pick_theme_for(artist: str, themes: list) -> str:
    """投稿対象アーティストに関係する focus_theme を1件選び、事実部分だけを返す。

    2026-08-16 追加。LLM に「何について書くか」を渡さないと、どのアーティストにも
    当てはまる空虚なつぶやきしか生成されない(実測: Phase1の8投稿すべて)。
    topic は「<artist>速報の深掘り: <実際の見出し>」形式なので、コロン以降の
    見出し部分=具体的事実だけを取り出す。該当が無ければ空文字(=話題を渡さない)。
    """
    if not artist or not themes:
        return ""
    key = str(artist).replace(" ", "").lower()
    cands = []
    for t in themes:
        topic = (t.get("topic", "") if isinstance(t, dict) else str(t)).strip()
        if not topic:
            continue
        # 2026-08-16: 係争・被害・訴訟系は「個人の独り言」として軽く触れると
        # 加害・誤情報の拡散になりうるため、つぶやきの種にしない。
        # (実際に「盗作指摘」「個人情報流出」を種にした生成が確認された)
        if any(w in topic for w in _SENSITIVE_TOPIC_WORDS):
            continue
        if key and key in topic.replace(" ", "").lower():
            # 「〜速報の深掘り: 見出し」→ 見出しだけ
            fact = topic.split(":", 1)[1].strip() if ":" in topic else topic
            if fact:
                cands.append(fact)
    if not cands:
        return ""
    return random.choice(cands)[:120]


def _persona_generate(artist: str, directives: dict) -> dict | None:
    """X_PERSONA_LLM=1 のとき LLM ペルソナで純つぶやきを生成 (URLなし)。
    成功時は generate() と同形の dict、失敗時は None (呼出側でテンプレ退避)。
    2026-05-26: テンプレ使い回し(8テンプレ×{artist}差し替え)の根治。"""
    if os.getenv("X_PERSONA_LLM", "") != "1":
        return None
    try:
        from lib.x_persona_voice import generate_persona_post
    except ImportError:
        return None
    # focus_themes をきっかけ語として渡す(時事連動)
    # 2026-08-16 真因修理: 要素は {'topic': ..., 'hint': ...} なのに .get("theme") を
    # 読んでおり、**theme_text が空白80文字**になっていた。つまり LLM には artist 名しか
    # 届いておらず、具体的事実ゼロで書かせていたため「なんか〜な気がする」「どうなってん
    # だろう」といった、どのアーティストにも当てはまる空虚な投稿しか出てこなかった
    # (Phase1の8投稿すべてがこの型。owner指摘「ペルソナ型も的外れ」の正体)。
    # 加えて全290件を連結して80字で切っていたため、仮にキーが正しくても先頭数件の
    # 断片しか渡らない。**投稿対象アーティストに関係するテーマだけ**を選んで渡す。
    themes = directives.get("focus_themes", [])
    theme_text = _pick_theme_for(artist, themes)
    payload = {"artist": artist}
    if theme_text:
        payload["theme"] = theme_text
    out = generate_persona_post(
        payload,
        kind="conversation", genre="default",
    )
    if not out.get("used_llm") or not out.get("text"):
        return None
    text = out["text"]
    return {
        "template_id": f"LLM-{out['persona']}",
        "category": "persona",
        "title": "ペルソナつぶやき",
        "artist": artist,
        "text": text,
        "char_count": len(text),
        "in_range": 20 <= len(text) <= 200,
        "has_url": bool(re.search(r"https?://", text)),
        "hashtag_count": len(re.findall(r"#\S+", text)),
    }


def generate(template_id: str | None, artist: str | None) -> dict:
    directives = _load_directives()
    if not artist:
        # 2026-05-26(施策1-a): focus_themes の時事アーティストを重み付け選択
        artist = _weighted_artist(directives)
    # 2026-05-26: テンプレより先に LLM ペルソナを試す(成功すれば使い回し回避)。
    # template_id を明示指定された場合(--id)は従来テンプレを尊重しスキップ。
    if not template_id:
        persona = _persona_generate(artist, directives)
        if persona is not None:
            return persona
    if not template_id:
        template_id = random.choice(list(TEMPLATES.keys()))
    if template_id not in TEMPLATES:
        raise SystemExit(f"unknown template id: {template_id}")
    tmpl = TEMPLATES[template_id]
    pattern = random.choice(tmpl["patterns"])
    # 2026-05-26: テンプレ内の `#{artist}` がスペースを残し `#Stray Kids` 等の
    # 壊れたハッシュタグを生む事故を修正。本文中の {artist} はそのまま(スペース可)、
    # ハッシュタグ位置のみスペース除去する。
    artist_tag = artist.replace(" ", "")
    pattern = pattern.replace("#{artist}", f"#{artist_tag}")
    text = pattern.format(artist=artist)
    char_count = len(text)
    # 文字数チェック(120-180字推奨、超過時は warn)
    in_range = 100 <= char_count <= 200  # 緩めの範囲(改行・絵文字含む)
    return {
        "template_id": template_id,
        "category": tmpl["category"],
        "title": tmpl["title"],
        "artist": artist,
        "text": text,
        "char_count": char_count,
        "in_range": in_range,
        "has_url": bool(re.search(r"https?://", text)),
        "hashtag_count": len(re.findall(r"#\S+", text)),
    }


def validate(post: dict) -> list[str]:
    """投稿前バリデーション。x-posting-rules SKILL §3 §4 準拠。"""
    issues = []
    if post["char_count"] > 200:
        issues.append(f"too long ({post['char_count']} chars, 200 max)")
    if post["has_url"]:
        issues.append("contains URL (suppression risk, move to self-reply)")
    if post["hashtag_count"] > 3:
        issues.append(f"too many hashtags ({post['hashtag_count']}, 3 max)")
    # 2026-05-26(施策1-a): auto_directives.stop_doing の語を含む投稿は弾く
    stop = _load_directives().get("stop_doing", [])
    stop_terms = [s.get("term", "") if isinstance(s, dict) else str(s) for s in stop]
    for term in stop_terms:
        t = (term or "").strip()
        if len(t) >= 3 and t in post["text"]:
            issues.append(f"stop_doing 語を含む: {t[:20]}")
    return issues


# ─── engagement watch(施策1-b): 投稿後の返信収集ウィンドウ管理 ──────────
WATCH_FILE = LOG_DIR / "x_engagement_watch.jsonl"
WATCH_MARKS_MIN = [10, 30, 60]  # 投稿後この分数で返信をスキャン(最初30分が勝負)


def register_watch(tweet_id: str, text: str) -> None:
    """投稿直後に呼ぶ。返信スキャンの予定(due時刻)を記録。
    x_engagement_responder --scan-watch が due を処理する。"""
    if not tweet_id or str(tweet_id).startswith("DRYRUN"):
        return
    LOG_DIR.mkdir(exist_ok=True)
    now = datetime.now(timezone(timedelta(hours=9)))
    entry = {
        "tweet_id": str(tweet_id),
        "text": text,
        "posted_at": now.isoformat(),
        "marks_min": WATCH_MARKS_MIN,
        "done_marks": [],          # 処理済みのmark(分)
        "status": "watching",
    }
    with WATCH_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_event(post: dict, action: str, detail: str = "") -> None:
    LOG_DIR.mkdir(exist_ok=True)
    entry = {
        "timestamp": now_iso(),
        "source": "x_conversation_starter",
        "action": action,
        "template_id": post.get("template_id"),
        "artist": post.get("artist"),
        "char_count": post.get("char_count"),
        "detail": detail,
    }
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_webhook() -> str:
    """.env から URGENT_ERRORS webhook を取得(無ければ汎用 DISCORD_WEBHOOK)。
    値の生読み(メモリ: discord-notify-placeholder-not-expanded)を避け、必ず実 URL を返す。"""
    url = os.environ.get("DISCORD_WEBHOOK_URGENT_ERRORS") or os.environ.get("DISCORD_WEBHOOK") or ""
    if url.startswith("http"):
        return url
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            for key in ("DISCORD_WEBHOOK_URGENT_ERRORS", "DISCORD_WEBHOOK"):
                if line.startswith(key + "="):
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if v.startswith("http"):
                        return v
    return ""


# 連続失敗 N 件で通知。同じ失敗で毎回鳴らさないよう sentinel ファイルで抑制。
_CONSEC_FAIL_THRESHOLD = 3
_ALERT_SENTINEL = LOG_DIR / ".x_consecutive_fail_alerted"


def _recent_consecutive_fails(n: int) -> int:
    """LOG_FILE 末尾を見て、直近から連続している post_fail の件数を数える。"""
    if not LOG_FILE.exists():
        return 0
    try:
        lines = LOG_FILE.read_text().splitlines()
    except OSError:
        return 0
    count = 0
    for line in reversed(lines):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        act = d.get("action", "")
        if act == "post_fail":
            count += 1
        elif act in ("post_live", "post_dry"):
            break  # 成功でリセット
        # generated 等はスキップ(投稿成否に無関係)
        if count >= n:
            break
    return count


def maybe_alert_consecutive_failures() -> None:
    """直近が _CONSEC_FAIL_THRESHOLD 件連続失敗なら Discord に1度だけ通知。
    成功すると sentinel を消し、次の連続失敗で再通知できる(post_via_api 成功時に解除)。"""
    fails = _recent_consecutive_fails(_CONSEC_FAIL_THRESHOLD)
    if fails < _CONSEC_FAIL_THRESHOLD:
        return
    if _ALERT_SENTINEL.exists():
        return  # 既に通知済み(復旧=成功まで再通知しない)
    webhook = _load_webhook()
    if not webhook:
        return
    msg = (
        f"⚠️ **X自動投稿が{fails}回連続で失敗しています**\n"
        f"直近ログ: `{LOG_FILE}`\n"
        f"`~/.x_credentials` の失効(HTTP 401)や API 制限の可能性。"
        f"認証を確認してください。"
    )
    try:
        import urllib.request
        req = urllib.request.Request(
            webhook, data=json.dumps({"content": msg}).encode("utf-8"),
            # User-Agent 必須: 既定の Python-urllib は Discord/Cloudflare に 403(1010)で
            # 拒否される(lib/discord_channel_router.py / lib/alert_queue.py と同方針)。
            headers={"Content-Type": "application/json", "User-Agent": "KpopJournal-Bot/2.0"},
        )
        urllib.request.urlopen(req, timeout=10)
        _ALERT_SENTINEL.touch()
    except Exception:
        pass  # 通知失敗で投稿処理を止めない


def post_via_api(text: str, dry_run: bool) -> tuple[bool, str, str]:
    """既存 google_metrics/post_to_x.py に委譲。(ok, detail, tweet_id) を返す。"""
    poster = ROOT / "google_metrics" / "post_to_x.py"
    if not poster.exists():
        return False, "post_to_x.py not found", ""
    if dry_run:
        return True, "DRY_RUN (not actually posted)", ""
    try:
        result = subprocess.run(
            ["python3", str(poster), text],
            capture_output=True, text=True, timeout=30,
        )
        out = result.stdout + result.stderr
        m = re.search(r"^TWEET_ID=(\S+)", out, re.M)
        return result.returncode == 0, out[:200], (m.group(1) if m else "")
    except subprocess.TimeoutExpired:
        return False, "timeout", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="template id (e.g. C-1)")
    ap.add_argument("--artist", help="artist name")
    ap.add_argument("--list", action="store_true", help="list templates")
    ap.add_argument("--post", action="store_true", help="post via post_to_x.py")
    ap.add_argument("--dry-run", action="store_true", help="generate only, no post")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    if args.list:
        list_templates()
        return 0

    post = generate(args.id, args.artist)
    issues = validate(post)
    post["issues"] = issues
    post["valid"] = len(issues) == 0

    if args.json:
        print(json.dumps(post, ensure_ascii=False, indent=2))
    else:
        print(f"=== conversation post ({post['template_id']} {post['category']}) ===")
        print(f"  artist     : {post['artist']}")
        print(f"  chars      : {post['char_count']} (target 100-200)")
        print(f"  hashtags   : {post['hashtag_count']} (max 3)")
        print(f"  has URL    : {post['has_url']}")
        if issues:
            print(f"  ⚠ issues  : {issues}")
        else:
            print(f"  ✓ valid")
        print(f"--- text ({post['char_count']} chars) ---")
        print(post["text"])
        print("---")

    if args.post or args.dry_run:
        ok, detail, tweet_id = post_via_api(post["text"], args.dry_run)
        action = "post_dry" if args.dry_run else ("post_live" if ok else "post_fail")
        log_event(post, action, detail)
        print(f"  post result: {ok}  {detail}")
        # エラー可視化: 連続失敗で Discord 通知。成功したら sentinel 解除(次の連続で再通知可)。
        if action == "post_live":
            _ALERT_SENTINEL.unlink(missing_ok=True)
            # 施策1-b: 投稿成功なら返信収集ウィンドウを登録(著者返信+75を取りに行く)
            if tweet_id:
                register_watch(tweet_id, post["text"])
        elif action == "post_fail":
            maybe_alert_consecutive_failures()
    else:
        log_event(post, "generated", "no post requested")
    return 0 if post["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
