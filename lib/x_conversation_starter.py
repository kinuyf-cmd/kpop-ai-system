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


ROOT = Path(__file__).resolve().parent.parent
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


def generate(template_id: str | None, artist: str | None) -> dict:
    if not template_id:
        template_id = random.choice(list(TEMPLATES.keys()))
    if template_id not in TEMPLATES:
        raise SystemExit(f"unknown template id: {template_id}")
    if not artist:
        artist = random.choice(DEFAULT_ARTIST_POOL)
    tmpl = TEMPLATES[template_id]
    pattern = random.choice(tmpl["patterns"])
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
    return issues


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
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
        _ALERT_SENTINEL.touch()
    except Exception:
        pass  # 通知失敗で投稿処理を止めない


def post_via_api(text: str, dry_run: bool) -> tuple[bool, str]:
    """既存 google_metrics/post_to_x.py に委譲"""
    poster = ROOT / "google_metrics" / "post_to_x.py"
    if not poster.exists():
        return False, "post_to_x.py not found"
    if dry_run:
        return True, "DRY_RUN (not actually posted)"
    try:
        result = subprocess.run(
            ["python3", str(poster), text],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0, (result.stdout + result.stderr)[:200]
    except subprocess.TimeoutExpired:
        return False, "timeout"


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
        ok, detail = post_via_api(post["text"], args.dry_run)
        action = "post_dry" if args.dry_run else ("post_live" if ok else "post_fail")
        log_event(post, action, detail)
        print(f"  post result: {ok}  {detail}")
        # エラー可視化: 連続失敗で Discord 通知。成功したら sentinel 解除(次の連続で再通知可)。
        if action == "post_live":
            _ALERT_SENTINEL.unlink(missing_ok=True)
        elif action == "post_fail":
            maybe_alert_consecutive_failures()
    else:
        log_event(post, "generated", "no post requested")
    return 0 if post["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
