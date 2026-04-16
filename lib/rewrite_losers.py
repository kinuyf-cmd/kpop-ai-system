"""
低CTR記事のタイトル一括リライト

title_performance.jsonl から「高imp × 低CTR」の負け記事を抽出し、
勝ちワード注入したClaudeプロンプトで新タイトル生成→WordPress更新→学習データに記録。

選定基準（デフォルト）:
  - result=lose
  - ctr_score < 20  (サイト平均の40%以下)
  - 重複なし（同じpost_idは1回まで）
  - 直近30日以内に既にリライト済みでない

Usage:
  python3 lib/rewrite_losers.py --dry-run        # プレビュー
  python3 lib/rewrite_losers.py --limit 5         # 上位5件のみ実行
  python3 lib/rewrite_losers.py --max-score 15   # スコア閾値変更
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/home/aiuser/kpop-ai-system")
PERF_FILE = BASE / "logs" / "title_performance.jsonl"
WP_API = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"


def _wp_auth_header() -> str:
    """~/.wp_auth (curl config形式) から Authorization ヘッダ値を読む。
    フォールバック: WP_USER / WP_PASS 環境変数から生成。
    戻り値: 'Authorization: Basic xxxx' の文字列。
    """
    import re as _re
    wp_auth_path = os.path.expanduser("~/.wp_auth")
    if os.path.exists(wp_auth_path):
        with open(wp_auth_path) as f:
            for line in f:
                m = _re.match(r'header\s*=\s*"(Authorization:\s*Basic\s+[^"\\n]+)"?', line.strip())
                if m:
                    return m.group(1)
    # フォールバック: 環境変数
    user = os.environ.get("WP_USER", "")
    passwd = os.environ.get("WP_PASS", "")
    token = base64.b64encode(f"{user}:{passwd}".encode()).decode()
    return f"Authorization: Basic {token}"


def auth_header():
    _v = _wp_auth_header()
    return _v.split(": ", 1)[1] if ": " in _v else _v


def load_records():
    if not PERF_FILE.exists():
        return []
    out = []
    with open(PERF_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def find_loser_candidates(records, max_score=20, min_impressions=100):
    """負け記事を抽出（最悪順）"""
    seen_pids = set()
    candidates = []
    for r in records:
        if r.get("result") != "lose":
            continue
        pid = r.get("post_id")
        if not pid or pid in seen_pids:
            continue
        score = r.get("ctr_score", 100)
        if score >= max_score:
            continue
        impr = r.get("impressions", 0)
        if impr < min_impressions:
            continue
        # 既にリライト済みかチェック
        if r.get("rewritten"):
            continue
        seen_pids.add(pid)
        candidates.append({
            "post_id": pid,
            "title": r.get("title", ""),
            "score": score,
            "impressions": impr,
            "raw_ctr": r.get("raw_ctr", 0),
        })
    candidates.sort(key=lambda x: (x["score"], -x["impressions"]))
    return candidates


def fetch_post(post_id):
    req = urllib.request.Request(
        f"{WP_API}/{post_id}?context=edit",
        headers={"Authorization": auth_header()},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  WP fetch error: {e}")
        return None


def days_since_published(post):
    """投稿日からの経過日数"""
    date_str = post.get("date_gmt") or post.get("date", "")
    if not date_str:
        return 9999
    try:
        # 2026-04-08T05:43:00 形式
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return delta.days
    except Exception:
        return 9999


def get_winning_prompt():
    """title_learner.py prompt から最新の勝ちワード文を取得"""
    try:
        r = subprocess.run(
            ["python3", str(BASE / "lib" / "title_learner.py"), "prompt"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def generate_new_title(old_title, win_prompt):
    """Claudeで新タイトル生成"""
    prompt = f"""あなたはK-POPメディアのCTR改善担当です。

以下の既存タイトルは現在 **CTRが極めて低い** (要改善)。
SEOを保ちつつ、読者が思わずクリックしたくなる強いタイトルに書き換えてください。

【絶対ルール】
- 1行だけ出力（説明・前置き・記号一切なし）
- 24〜38文字
- アー名/数字/イベント名を保持
- 過度な誇張禁止（嘘・誤解は完全NG）
- カムバック・速報・衝撃・完全・ついに・神 などの強ワードを活用
- 既存タイトルと「全く同じ」は禁止

{win_prompt}

【既存タイトル】
{old_title}

【新タイトル】"""

    try:
        sys.path.insert(0, str(BASE / "lib"))
        from claude_retry import claude_run
        out = claude_run(prompt, max_retries=4, initial_wait=15, timeout=300)
        # 最終行のみ採用（preamble対策）
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        if not lines:
            return None
        new_title = lines[-1]
        # マークダウン記号除去
        new_title = re.sub(r"^[#\-*\s]+", "", new_title).strip()
        new_title = new_title.strip('「」『』"\'')
        return new_title
    except RuntimeError as e:
        print(f"  claude_retry failed: {e}")
        return None
    except Exception as e:
        print(f"  claude error: {e}")
        return None


def update_wp_title(post_id, new_title):
    payload = json.dumps({"title": new_title}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{WP_API}/{post_id}",
        data=payload,
        headers={
            "Authorization": auth_header(),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        return data.get("title", {}).get("rendered", "")
    except Exception as e:
        print(f"  update error: {e}")
        return None


def record_rewrite(post_id, old_title, new_title, old_score):
    """リライト履歴を title_performance.jsonl に追記（pendingとして）"""
    record = {
        "title": new_title,
        "ctr_score": 0.0,
        "pattern": "感情型",  # リライトは感情型扱い
        "result": "pending",
        "post_id": str(post_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rewritten_from": old_title,
        "old_score": old_score,
    }
    with open(PERF_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def mark_old_as_rewritten(post_id):
    """既存の lose レコードに rewritten=True フラグを立てる"""
    records = load_records()
    updated = []
    for r in records:
        if r.get("post_id") == str(post_id) and r.get("result") == "lose" and not r.get("rewritten"):
            r["rewritten"] = True
        updated.append(r)
    with open(PERF_FILE, "w", encoding="utf-8") as f:
        for r in updated:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-score", type=int, default=20, help="リライト対象スコア閾値")
    ap.add_argument("--min-impressions", type=int, default=100, help="最小インプ閾値")
    ap.add_argument("--min-age-days", type=int, default=7, help="リライト対象とする最小経過日数（新しすぎる投稿は除外）")
    ap.add_argument("--limit", type=int, default=5, help="一度に処理する最大件数")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not auth_header():
        print("ERROR: WP credentials not found (~/.wp_auth or WP_USER/WP_PASS)", file=sys.stderr)
        sys.exit(1)

    records = load_records()
    candidates = find_loser_candidates(
        records,
        max_score=args.max_score,
        min_impressions=args.min_impressions,
    )
    print(f"=== 低CTRリライト候補 (max_score={args.max_score}, min_impr={args.min_impressions}) ===")
    print(f"見つかった: {len(candidates)} 件、処理: {min(args.limit, len(candidates))} 件")
    for i, c in enumerate(candidates[:args.limit]):
        print(f"  {i+1}. ID={c['post_id']} score={c['score']} imp={c['impressions']} | {c['title'][:60]}")

    if args.dry_run:
        print("\n[DRY-RUN] 実適用なし")
        return

    win_prompt = get_winning_prompt()
    if win_prompt:
        print(f"\n=== 勝ちワード注入 ===\n{win_prompt}\n")

    success = 0
    processed = 0
    for c in candidates:
        if processed >= args.limit:
            break
        pid = c["post_id"]
        print(f"\n--- ID={pid} (score={c['score']}, imp={c['impressions']}) ---")
        post = fetch_post(pid)
        if not post:
            continue
        # 投稿日チェック（新しすぎる投稿は除外）
        age = days_since_published(post)
        if age < args.min_age_days:
            print(f"  age={age}日 < {args.min_age_days} → skip (新しすぎる)")
            continue
        current_title = post.get("title", {}).get("raw", "") or post.get("title", {}).get("rendered", "")
        if not current_title:
            print(f"  current title 取得失敗")
            continue
        print(f"  age={age}日, 旧: {current_title}")
        processed += 1

        new_title = generate_new_title(current_title, win_prompt)
        if not new_title:
            print(f"  生成失敗")
            continue
        if new_title == current_title:
            print(f"  同一→skip")
            continue
        if len(new_title) < 10 or len(new_title) > 80:
            print(f"  異常長 ({len(new_title)}文字)→skip: {new_title}")
            continue
        print(f"  新: {new_title}")

        result = update_wp_title(pid, new_title)
        if result:
            print(f"  ✅ 更新成功")
            mark_old_as_rewritten(pid)
            record_rewrite(pid, current_title, new_title, c["score"])
            success += 1
        else:
            print(f"  ❌ 更新失敗")

    print(f"\n=== Summary: {success}/{min(args.limit, len(candidates))} 成功 ===")


if __name__ == "__main__":
    main()
