#!/usr/bin/env python3
"""
x_post_audit.py - X投稿品質監査

Usage:
  python3 lib/x_post_audit.py [--hours 72]

読み込み:
  logs/tweet_id_db.tsv   - 投稿済みツイートDB（post_id\ttweet_id\ttitle\tposted_at）
  logs/x_post.log        - X投稿詳細ログ
  logs/x_post_audit.jsonl - 既存の監査ログ（あれば）

分類: posted / failed / skipped / plan_only / unknown
チェック項目: hook有無、URL in reply、ハッシュタグ数2-3、長さ≤130文字
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.parent
LOGS = SCRIPT_DIR / "logs"
JST = timezone(timedelta(hours=9))

# ── フックパターン ───────────────────────────────────────────────────────────
HOOK_PATTERNS = [
    r"？$",          # 疑問形
    r"\?$",
    r"^\d+",         # 数字始まり
    r"！$|!$",       # 感嘆符
    r"…$|\.\.\.$",  # 「...」で始まる
    r"速報",
    r"衝撃",
    r"電撃",
    r"判明",
    r"ついに",
    r"まさか",
    r"記録",
    r"驚愕",
    r"神",
    r"レベチ",
    r"解禁",
    r"完全",
    r"必見",
]
_HOOK_RE = re.compile("|".join(HOOK_PATTERNS))

# コメント誘導パターン
COMMENT_TRIGGER_RE = re.compile(
    r"どう思う|どっち派|賛否|泣いた|超えられる|RT|シェア|教えて|感動した|あなたは"
)


def _now_jst():
    return datetime.now(JST)


def _parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(s[:19], fmt[:len(fmt)])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)
            return dt
        except Exception:
            pass
    return None


def _cutoff(hours):
    return _now_jst() - timedelta(hours=hours)


def _load_jsonl(path):
    recs = []
    p = Path(path)
    if not p.exists():
        return recs
    with p.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except Exception:
                pass
    return recs


def _check_tweet_quality(tweet_text: str, reply_text: str = "") -> list:
    """ツイート品質チェック: 問題リストを返す"""
    issues = []

    if not tweet_text:
        return ["ツイートテキストなし"]

    lines = [l for l in tweet_text.strip().split("\n") if l.strip()]
    hook = lines[0] if lines else ""

    # フックチェック
    if not _HOOK_RE.search(hook):
        issues.append("フックに強ワード・疑問形なし")

    # フック長
    if len(hook) > 20:
        issues.append(f"フック{len(hook)}文字（20文字超）")

    # 全体長
    if len(tweet_text) > 130:
        issues.append(f"本文{len(tweet_text)}文字（130文字超）")

    # ハッシュタグ数
    hashtags = re.findall(r"#\S+", tweet_text)
    if len(hashtags) < 2:
        issues.append(f"ハッシュタグ{len(hashtags)}個（2個未満）")
    elif len(hashtags) > 3:
        issues.append(f"ハッシュタグ{len(hashtags)}個（3個超）")

    # URLはリプライに含まれているか
    has_url_in_main = bool(re.search(r"https?://", tweet_text))
    has_url_in_reply = bool(re.search(r"https?://", reply_text))
    if has_url_in_main:
        issues.append("本文にURL含まれている（URLペナルティ懸念）")
    elif not has_url_in_reply:
        issues.append("リプライにURLなし（記事URLが確認できない）")

    # コメント誘導
    if not COMMENT_TRIGGER_RE.search(tweet_text):
        issues.append("コメント誘導フレーズなし")

    return issues


def parse_x_log(hours=72) -> dict:
    """x_post.logを解析してセッションごとのデータを返す"""
    x_log = LOGS / "x_post.log"
    cutoff = _cutoff(hours)

    sessions = []
    current = {}

    if not x_log.exists():
        return {"sessions": []}

    with x_log.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip()

            # タイムスタンプ抽出
            m_ts = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (.+)", line)
            if not m_ts:
                continue

            ts_str, content = m_ts.group(1), m_ts.group(2)
            ts = _parse_dt(ts_str)
            if not ts or ts < cutoff:
                continue

            if content.startswith("=== X/Twitter 自動投稿開始 ==="):
                if current:
                    sessions.append(current)
                current = {
                    "started_at": ts_str,
                    "title": "",
                    "url": "",
                    "tweet_text": "",
                    "tweet_length": 0,
                    "reply_text": "",
                    "tweet_id": "",
                    "tweet_url": "",
                    "reply_url": "",
                    "status": "unknown",
                    "pre_score": 0,
                    "v12_check": "",
                    "mode": "dry_run",
                }
            elif current:
                if content.startswith("TITLE: "):
                    current["title"] = content[7:]
                elif content.startswith("URL: "):
                    current["url"] = content[5:]
                elif content.startswith("TWEET_TEXT: "):
                    current["tweet_text"] = content[12:]
                elif content.startswith("TWEET_LENGTH: "):
                    try:
                        current["tweet_length"] = int(content[14:])
                    except Exception:
                        pass
                elif content.startswith("PRE_SCORE: ") or content.startswith("RE-SCORE: "):
                    m_score = re.search(r"([\d.]+)/100", content)
                    if m_score:
                        current["pre_score"] = float(m_score.group(1))
                elif content.startswith("V12_FORMAT: "):
                    current["v12_check"] = content[12:]
                elif content.startswith("DRY_RUN: false"):
                    current["mode"] = "live"
                elif content.startswith("DRY_RUN: true") or "DRY-RUN" in content:
                    current["mode"] = "dry_run"
                    if "DRY-RUN" in content:
                        current["status"] = "plan_only"
                elif "RESULT: フェイルセーフ" in content or "フェイルセーフによりスキップ" in content:
                    current["status"] = "skipped"
                elif "RESULT: プレフライト不合格" in content:
                    current["status"] = "skipped"
                elif "RESULT: フック投稿成功" in content or "投稿成功" in content:
                    current["status"] = "posted"
                    m_url = re.search(r"https://x\.com/\S+", content)
                    if m_url:
                        current["tweet_url"] = m_url.group(0)
                    m_tid = re.search(r"tweet_id=(\d+)", content)
                    if m_tid:
                        current["tweet_id"] = m_tid.group(1)
                elif "RESULT: X投稿失敗" in content:
                    current["status"] = "failed"
                elif "URL_REPLY: 成功" in content:
                    m_url = re.search(r"https://x\.com/\S+", content)
                    if m_url:
                        current["reply_url"] = m_url.group(0)
                elif "TITLE_CRASH" in content:
                    current["status"] = "skipped"

    if current:
        sessions.append(current)

    return {"sessions": sessions}


def load_tweet_db(hours=72) -> list:
    """tweet_id_db.tsvから投稿済みレコードを読む"""
    tweet_db = LOGS / "tweet_id_db.tsv"
    cutoff = _cutoff(hours)
    records = []

    if not tweet_db.exists():
        return records

    with tweet_db.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 4:
                dt = _parse_dt(parts[3])
                if dt and dt >= cutoff:
                    records.append({
                        "post_id": parts[0],
                        "tweet_id": parts[1],
                        "title": parts[2] if len(parts) > 2 else "",
                        "posted_at": parts[3] if len(parts) > 3 else "",
                    })

    return records


def audit_x_posts(hours=72) -> list:
    """記事ごとのX投稿監査結果リスト"""
    log_data = parse_x_log(hours)
    tweet_db = load_tweet_db(hours)

    # tweet_dbからpost_id→tweet_idマッピングを作成
    db_map = {r["post_id"]: r for r in tweet_db}

    results = []
    for session in log_data["sessions"]:
        tweet_text = session.get("tweet_text", "")
        reply_text = session.get("reply_text", "")
        issues = _check_tweet_quality(tweet_text, reply_text)

        # V12チェック結果があれば問題を追加
        v12 = session.get("v12_check", "")
        if v12.startswith("NG:"):
            for v12_issue in v12[3:].split("/"):
                v12_issue = v12_issue.strip()
                if v12_issue and v12_issue not in issues:
                    issues.append(f"[V12] {v12_issue}")

        tweet_url = session.get("tweet_url", "")
        tweet_id = session.get("tweet_id", "")

        # tweet_urlからtweet_idを抽出
        if not tweet_id and tweet_url:
            m = re.search(r"/status/(\d+)", tweet_url)
            if m:
                tweet_id = m.group(1)

        results.append({
            "article_url": session.get("url", ""),
            "title": session.get("title", ""),
            "main_post_text": tweet_text,
            "reply_text": reply_text,
            "tweet_status": session.get("status", "unknown"),
            "tweet_id": tweet_id,
            "tweet_url": tweet_url or (f"https://x.com/i/status/{tweet_id}" if tweet_id else ""),
            "reply_url": session.get("reply_url", ""),
            "posted_at": session.get("started_at", ""),
            "mode": session.get("mode", "unknown"),
            "pre_score": session.get("pre_score", 0),
            "issues": issues,
        })

    return results


def main():
    hours = 72
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--hours" and i + 1 < len(sys.argv) - 1:
            try:
                hours = int(sys.argv[i + 2])
            except Exception:
                pass

    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    print(f"\n{'='*60}")
    print(f"  X投稿監査レポート  ({now_str})  直近{hours}時間")
    print(f"{'='*60}")

    results = audit_x_posts(hours)
    tweet_db = load_tweet_db(hours)

    # 集計
    status_counts = {}
    for r in results:
        s = r["tweet_status"]
        status_counts[s] = status_counts.get(s, 0) + 1

    print(f"\n  投稿ログ解析: {len(results)}セッション")
    for status, count in sorted(status_counts.items()):
        print(f"    {status}: {count}件")
    print(f"  ツイートDB（直近{hours}h）: {len(tweet_db)}件")

    print(f"\n{'─'*60}")
    print("  記事別X投稿監査")
    print(f"{'─'*60}")

    for r in results:
        status_icon = {
            "posted": "✅",
            "failed": "❌",
            "skipped": "⚠️",
            "plan_only": "📋",
            "unknown": "❓",
        }.get(r["tweet_status"], "❓")

        print(f"\n  {status_icon} [{r['tweet_status'].upper()}]  {r['title'][:50]}")
        print(f"     URL: {r['article_url']}")
        if r["tweet_url"]:
            print(f"     ツイート: {r['tweet_url']}")
        print(f"     投稿日時: {r['posted_at']}  mode={r['mode']}  score={r['pre_score']}")
        if r["main_post_text"]:
            preview = r["main_post_text"][:80].replace("\n", "↵")
            print(f"     本文: {preview}...")
        if r["issues"]:
            print(f"     問題:")
            for issue in r["issues"]:
                print(f"       • {issue}")

    print(f"\n{'─'*60}")
    print("  tweet_id_db.tsv（直近{}h）".format(hours))
    print(f"{'─'*60}")
    for rec in tweet_db[-10:]:
        print(f"  post_id={rec['post_id']}  tweet_id={rec['tweet_id']}  [{rec['posted_at'][:16]}]  {rec['title'][:40]}")

    print(f"\n{'='*60}")
    print("  X投稿監査完了")
    print(f"{'='*60}\n")

    # JSON出力
    print("\n=== JSON ===")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
