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


def _fixed_reply_candidates(reply_text: str, artist: str = "") -> list[str]:
    """固定テンプレ候補(LLM未使用/失敗時のfallback)。質問返し・共感のみ、事実主張なし。"""
    rt = (reply_text or "").strip()[:80]
    candidates = [
        "そうなんです、特にあのパートが印象的でした。\nあなたはどのシーンが一番好みでしたか?",
        "そう感じる人多いみたいですね。\n他のリスナーはどう聴いてるんだろう、共有してもらえると嬉しいです",
        "そのご意見、面白い視点ですね。\n他の楽曲との比較で語ると、また違う発見がありそう",
    ]
    if rt and any(neg in rt for neg in ["悪い", "嫌い", "酷い", "ダメ", "微妙"]):
        candidates = [
            "そう感じる方もいますよね。\n好みの分かれる作品ほど議論が活発になる気がします、どこが気になりました?",
            "率直なご感想ありがとうございます。\n他のリスナーの反応も気になります、コメントで共有してもらえると嬉しいです",
            "異なる視点、参考になります。\n音楽の楽しみ方は人それぞれですね、好きなアーティストは誰ですか?",
        ]
    return candidates


def _llm_reply_candidates(reply_text: str, artist: str = "") -> list[str]:
    """gpt-4o-mini で返信候補3案を生成(X_REPLY_LLM=1 のとき)。
    ハルシネーション対策で『相手への質問・共感のみ。事実主張・固有データ・断定は禁止』を厳守。
    失敗時は呼び出し側で固定テンプレにフォールバック。"""
    try:
        from openai import OpenAI
    except ImportError:
        return []
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return []
    sys_prompt = (
        "あなたはK-POPメディアのSNS運用担当。フォロワーの返信に対する『返信候補』を3案作る。"
        "目的は会話を続けて相手にもう一度返信してもらうこと。厳守事項:"
        "①事実主張・数値・固有のニュースを書かない(ハルシネーション厳禁)"
        "②相手の意見への共感+質問返しのみ。③各60〜120字、改行1回まで。"
        "④ハッシュタグ・URLなし。⑤否定や論争を煽らずポジティブに。"
        "出力はJSON配列(文字列3個)のみ。"
    )
    user = f"フォロワーの返信:「{(reply_text or '').strip()[:200]}」\nアーティスト文脈: {artist or '不明'}"
    try:
        client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": sys_prompt},
                      {"role": "user", "content": user}],
            temperature=0.7, max_tokens=400,
        )
        raw = resp.choices[0].message.content.strip()
        raw = raw[raw.find("["):raw.rfind("]") + 1] if "[" in raw else raw
        cands = json.loads(raw)
        cands = [str(c).strip() for c in cands if str(c).strip()][:3]
        return cands if len(cands) == 3 else []
    except Exception:  # noqa: BLE001 — LLM失敗は fallback に委ねる
        return []


def generate_reply_candidates(reply_text: str, artist: str = "") -> list[str]:
    """返信候補3案を生成。X_REPLY_LLM=1 なら gpt-4o-mini、失敗/未設定は固定テンプレ。
    候補は短め(60-120字)・質問/共感形・ハッシュタグ/URLなし(返信内タグはalgo効果低)。
    事実主張を含めないことでハルシネーション源を断つ(owner承認は別途必須)。"""
    if os.environ.get("X_REPLY_LLM") == "1":
        llm = _llm_reply_candidates(reply_text, artist)
        if llm:
            return llm
    return _fixed_reply_candidates(reply_text, artist)


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


WATCH_FILE = LOG_DIR / "x_engagement_watch.jsonl"
X_LOGIN = ROOT / "google_metrics" / "x_login.json"


def fetch_replies(tweet_id: str) -> list[dict]:
    """元ツイートへの返信を取得して [{author, text, reply_id}] を返す。
    Playwright + 保存済みログイン(x_login.json)を再利用。未整備・失敗時は空配列(致命でない)。
    API tier では reply 取得が重い/不可のため Playwright 経路を既定とする。"""
    if not X_LOGIN.exists():
        print(f"  fetch_replies: {X_LOGIN.name} 無し → 空(返信収集はログイン整備後)", file=sys.stderr)
        return []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  fetch_replies: playwright未導入 → 空", file=sys.stderr)
        return []
    replies = []
    try:
        state = json.loads(X_LOGIN.read_text())
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx = b.new_context(storage_state=state)
            pg = ctx.new_page()
            pg.goto(f"https://x.com/i/status/{tweet_id}", wait_until="networkidle", timeout=45000)
            pg.wait_for_timeout(3000)
            # 会話ツリーのツイート要素。元ツイート以外を返信とみなす(簡易)。
            arts = pg.query_selector_all('article[data-testid="tweet"]')
            for a in arts[1:11]:  # 元ツイートを除く最大10件
                txt_el = a.query_selector('div[data-testid="tweetText"]')
                if not txt_el:
                    continue
                replies.append({"author": "", "text": txt_el.inner_text().strip()[:280], "reply_id": ""})
            b.close()
    except Exception as e:  # noqa: BLE001
        print(f"  fetch_replies err: {e}", file=sys.stderr)
        return []
    return replies


def _notify_discord_candidates(tweet_id: str, reply_text: str, qid: str, candidates: list[str]) -> None:
    """返信候補をDiscordに通知(owner承認導線)。UA必須(Cloudflare 1010対策)。"""
    url = os.environ.get("DISCORD_WEBHOOK_URGENT_ERRORS") or os.environ.get("DISCORD_WEBHOOK") or ""
    if not url.startswith("http"):
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("DISCORD_WEBHOOK="):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not url.startswith("http"):
        return
    body = "\n".join(f"  [{i+1}] {c}" for i, c in enumerate(candidates))
    msg = (f"💬 **X返信候補(owner承認待ち)** queue=`{qid}`\n"
           f"元tweet: https://x.com/i/status/{tweet_id}\n"
           f"受信返信: {reply_text[:80]}\n候補:\n{body}\n"
           f"→ {qid}.json に selected_candidate を設定し --process-queue で投稿")
    try:
        import urllib.request
        req = urllib.request.Request(url, data=json.dumps({"content": msg[:1900]}).encode(),
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "KpopJournal-Bot/2.0"})
        urllib.request.urlopen(req, timeout=10)
    except Exception:  # noqa: BLE001
        pass


def scan_watch(dry_run: bool) -> int:
    """x_engagement_watch.jsonl の due な mark を処理: fetch_replies→候補→queue→Discord。
    owner承認フローは不変(ここでは候補投入とDiscord通知まで。実返信は --process-queue)。"""
    if not WATCH_FILE.exists():
        print("scan-watch: watch無し")
        return 0
    now = datetime.now(timezone(timedelta(hours=9)))
    lines = [l for l in WATCH_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    out, processed = [], 0
    for line in lines:
        try:
            w = json.loads(line)
        except json.JSONDecodeError:
            out.append(line); continue
        if w.get("status") != "watching":
            out.append(line); continue
        try:
            posted = datetime.fromisoformat(w["posted_at"])
        except (KeyError, ValueError):
            out.append(line); continue
        elapsed_min = (now - posted).total_seconds() / 60
        done = set(w.get("done_marks", []))
        due = [m for m in w.get("marks_min", []) if m <= elapsed_min and m not in done]
        for m in due:
            replies = fetch_replies(w["tweet_id"])
            for r in replies:
                cands = generate_reply_candidates(r["text"], "")
                if dry_run:
                    print(f"  [scan-watch DRY] tweet={w['tweet_id']} mark={m}分 返信='{r['text'][:40]}' 候補3案生成")
                else:
                    qf = queue_reply(w["tweet_id"], r["text"], "", cands)
                    _notify_discord_candidates(w["tweet_id"], r["text"], qf.stem, cands)
                    log_event("watch_queued", {"tweet_id": w["tweet_id"], "mark": m, "queue_id": qf.stem})
                processed += 1
            done.add(m)
        w["done_marks"] = sorted(done)
        # 全mark消化 or 90分経過で watch 終了
        if set(w["done_marks"]) >= set(w.get("marks_min", [])) or elapsed_min > 90:
            w["status"] = "done"
        out.append(json.dumps(w, ensure_ascii=False))
    if not dry_run:
        WATCH_FILE.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")
    print(f"scan-watch: {processed}件の返信を処理")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tweet-id", help="target tweet id to check replies on")
    ap.add_argument("--reply-text", help="(mock) the reply text received")
    ap.add_argument("--artist", default="", help="artist context (for hashtag)")
    ap.add_argument("--mock", action="store_true", help="mock mode (no actual X API call)")
    ap.add_argument("--process-queue", help="process an approved queue entry by id")
    ap.add_argument("--scan-watch", action="store_true",
                    help="due な engagement watch を処理(返信収集→候補→queue→Discord)")
    ap.add_argument("--dry-run", action="store_true", help="do not call X API")
    args = ap.parse_args()

    if args.scan_watch:
        return scan_watch(args.dry_run or args.mock)

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
