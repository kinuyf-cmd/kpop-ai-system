#!/usr/bin/env python3
"""x_engagement_responder.py — M10 Q-3 active engagement フロー

x-posting-rules SKILL §6 のオーナー承認型返信フローを実装。
X アルゴリズム上「返信に著者が返信 = like 150 個分」のため、
返信検出 → AI 候補3案生成 → owner_decision_queue 投入 → オーナー承認 → X 返信投稿
の流れを管理する。

X API の実呼び出しは Day 9 以降(Premium 取得 + token 有効性確認後)。
Day 8 は **モック実装中心** で構造とフローを確立する。

使用:
    # モックモード(返信を仮想生成して候補3案を作る)
    python3 lib/x_engagement_responder.py --mock --tweet-id 12345 --reply-text "新曲最高でした"

    # 既存ツイートをチェックしてキュー投入(本実装、Day 9 以降)
    python3 lib/x_engagement_responder.py --tweet-id 12345

    # キューを処理(オーナー承認後の投稿)
    python3 lib/x_engagement_responder.py --process-queue X-REPLY-20260520-001
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path.home() / ".kpop_recovery"
QUEUE_DIR = LOG_DIR / "owner_decision_queue"
LOG_FILE = LOG_DIR / "x_posting_log.jsonl"


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=9))).isoformat()


def generate_reply_candidates(reply_text: str, artist: str = "") -> list[str]:
    """返信候補3案生成(モック実装)

    本実装(Day 9 以降)では Claude API に渡して 3 案生成する。
    Day 8 は固定テンプレベースの簡易版で構造を確立する。

    candidates は X アルゴリズムに最適化:
    - 短め(60-120字、返信なので元投稿より短く)
    - 質問形 or 同意形(さらに返信を引き出す)
    - ハッシュタグなし(返信内のハッシュタグは algo 効果低)
    - URL なし
    """
    rt = (reply_text or "").strip()[:80]
    a = artist or ""
    suffix = f" #{a}" if a else ""

    candidates = [
        # 同意 + 深掘り
        f"そうなんです、特にあのパートが印象的でした。\nあなたはどのシーンが一番好みでしたか?",
        # 質問返し
        f"そう感じる人多いみたいですね。\n他のリスナーはどう聴いてるんだろう、共有してもらえると嬉しいです",
        # 観点拡張
        f"そのご意見、面白い視点ですね。\n他の楽曲との比較で語ると、また違う発見がありそう",
    ]

    if rt and any(neg in rt for neg in ["悪い", "嫌い", "酷い", "ダメ", "微妙"]):
        # ネガティブ返信にはセンチメント配慮で ポジティブ転換 候補
        candidates = [
            f"そう感じる方もいますよね。\n好みの分かれる作品ほど議論が活発になる気がします、どこが気になりました?",
            f"率直なご感想ありがとうございます。\n他のリスナーの反応も気になります、コメントで共有してもらえると嬉しいです",
            f"異なる視点、参考になります。\n音楽の楽しみ方は人それぞれですね、好きなアーティストは誰ですか?",
        ]

    return candidates


def queue_reply(tweet_id: str, reply_text: str, artist: str, candidates: list[str]) -> Path:
    """owner_decision_queue に X-REPLY-{timestamp}.json として投入"""
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    qid = f"X-REPLY-{ts}"
    qfile = QUEUE_DIR / f"{qid}.json"
    entry = {
        "id": qid,
        "type": "x_reply",
        "created_at": now_iso(),
        "original_tweet_id": tweet_id,
        "reply_text": reply_text,
        "artist_context": artist,
        "candidates": [
            {"index": i + 1, "text": c, "chars": len(c)} for i, c in enumerate(candidates)
        ],
        "selected_candidate": None,  # オーナーが選択する
        "status": "pending_approval",
        "expires_at": (datetime.now(timezone(timedelta(hours=9))) + timedelta(hours=6)).isoformat(),
    }
    qfile.write_text(json.dumps(entry, ensure_ascii=False, indent=2))
    return qfile


def log_event(action: str, detail: dict) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    entry = {"timestamp": now_iso(), "source": "x_engagement_responder", "action": action, **detail}
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def process_queue(queue_id: str, dry_run: bool) -> int:
    """承認済 queue エントリを X API に投稿(モック中心、Day 9 で本実装)"""
    qfile = QUEUE_DIR / f"{queue_id}.json"
    if not qfile.exists():
        print(f"  queue entry not found: {qfile}", file=sys.stderr)
        return 2
    entry = json.loads(qfile.read_text())
    selected = entry.get("selected_candidate")
    if not selected:
        print(f"  no candidate selected, awaiting owner approval", file=sys.stderr)
        return 3
    # 選択候補のテキスト
    cand_text = next((c["text"] for c in entry["candidates"] if c["index"] == selected), None)
    if not cand_text:
        print(f"  selected candidate index {selected} not found", file=sys.stderr)
        return 4

    poster = ROOT / "google_metrics" / "post_to_x.py"
    if dry_run or not poster.exists():
        print(f"  DRY_RUN reply (queue={queue_id}, tweet_id={entry['original_tweet_id']}):")
        print(f"    {cand_text}")
        log_event("reply_dry", {"queue_id": queue_id, "tweet_id": entry["original_tweet_id"]})
        return 0

    # 本投稿(Day 9 以降)
    result = subprocess.run(
        ["python3", str(poster), cand_text, "--reply-to", entry["original_tweet_id"]],
        capture_output=True, text=True, timeout=30,
    )
    ok = result.returncode == 0
    print(f"  reply posted: {ok}")
    entry["status"] = "posted" if ok else "post_failed"
    entry["posted_at"] = now_iso()
    qfile.write_text(json.dumps(entry, ensure_ascii=False, indent=2))
    log_event("reply_live" if ok else "reply_fail", {
        "queue_id": queue_id, "tweet_id": entry["original_tweet_id"],
        "detail": (result.stdout + result.stderr)[:200],
    })
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tweet-id", help="target tweet id to check replies on")
    ap.add_argument("--reply-text", help="(mock) the reply text received")
    ap.add_argument("--artist", default="", help="artist context (for hashtag)")
    ap.add_argument("--mock", action="store_true", help="mock mode (no actual X API call)")
    ap.add_argument("--process-queue", help="process an approved queue entry by id")
    ap.add_argument("--dry-run", action="store_true", help="do not call X API")
    args = ap.parse_args()

    if args.process_queue:
        return process_queue(args.process_queue, args.dry_run or args.mock)

    if not args.tweet_id:
        ap.error("--tweet-id required (or use --process-queue)")

    reply_text = args.reply_text or "(no reply text given, mock mode)"
    candidates = generate_reply_candidates(reply_text, args.artist)
    qfile = queue_reply(args.tweet_id, reply_text, args.artist, candidates)

    print(f"=== X-REPLY queue entry ===")
    print(f"  queue file : {qfile.name}")
    print(f"  tweet id   : {args.tweet_id}")
    print(f"  reply text : {reply_text[:60]}")
    print(f"  candidates :")
    for i, c in enumerate(candidates, 1):
        print(f"    [{i}] ({len(c)} chars) {c[:80]}")
    print(f"  next       : owner reviews queue and sets selected_candidate, then run --process-queue")

    log_event("queue_created", {"queue_id": qfile.stem, "tweet_id": args.tweet_id, "candidate_count": len(candidates)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
