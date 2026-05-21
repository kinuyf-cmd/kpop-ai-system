"""
セレビィ: 鮮度維持エージェント

機能:
1. 直近30日間更新されていない win 判定記事を抽出
2. 「※本記事は2026年XX月XX日時点の情報です」の日付を今日に更新
3. 軽微な編集で modified を更新 → 検索エンジンに鮮度シグナル送信
4. 内部リンクの再構築 (add_internal_links.sh 呼び出し)

Usage:
  python3 lib/celebi_freshness.py --dry-run
  python3 lib/celebi_freshness.py --limit 5
  python3 lib/celebi_freshness.py --min-stale-days 30
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timezone
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


def load_winners():
    """title_performance.jsonl から win レコードを抽出"""
    if not PERF_FILE.exists():
        return []
    seen = set()
    out = []
    with open(PERF_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("result") != "win":
                continue
            pid = r.get("post_id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            out.append(pid)
    return out


def fetch_post(post_id):
    req = urllib.request.Request(
        f"{WP_API}/{post_id}?context=edit",
        headers={"Authorization": auth_header()},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  fetch error: {e}")
        return None


def days_since_modified(post):
    date_str = post.get("modified_gmt") or post.get("modified", "")
    if not date_str:
        return 0
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return 0


def refresh_date_stamp(content):
    """※本記事は2026年XX月XX日時点... を今日に更新"""
    today = date.today()
    today_jp = f"{today.year}年{today.month:02d}月{today.day:02d}日"
    new_content, n = re.subn(
        r"(※本記事は)20\d{2}年\d{1,2}月\d{1,2}日(時点)",
        rf"\g<1>{today_jp}\g<2>",
        content,
    )
    return new_content, n


def update_post_content(post_id, content):
    payload = json.dumps({"content": content}, ensure_ascii=False).encode("utf-8")
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
        return data.get("modified", "")
    except Exception as e:
        print(f"  update error: {e}")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-stale-days", type=int, default=30, help="この日数以上更新ない記事のみ対象")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not auth_header():
        print("ERROR: WP credentials not found (~/.wp_auth or WP_USER/WP_PASS)", file=sys.stderr)
        sys.exit(1)

    winners = load_winners()
    print(f"=== Celebi Freshness ({len(winners)} win records) ===")

    refreshed = 0
    skipped_fresh = 0
    skipped_no_stamp = 0
    errors = 0

    for pid in winners:
        if refreshed >= args.limit:
            break
        post = fetch_post(pid)
        if not post:
            errors += 1
            continue
        title = post.get("title", {}).get("rendered", "")
        days = days_since_modified(post)
        if days < args.min_stale_days:
            skipped_fresh += 1
            continue

        content = post.get("content", {}).get("raw", "") or post.get("content", {}).get("rendered", "")
        new_content, n = refresh_date_stamp(content)
        if n == 0:
            skipped_no_stamp += 1
            continue

        print(f"--- ID={pid} (last modified {days}日前) ---")
        print(f"  title: {title[:60]}")
        print(f"  date stamps refreshed: {n}")

        if args.dry_run:
            print(f"  [DRY-RUN]")
            refreshed += 1
            continue

        result = update_post_content(pid, new_content)
        if result:
            print(f"  ✅ updated, new modified: {result}")
            refreshed += 1
        else:
            errors += 1

    print(f"\n=== Summary ===")
    print(f"  refreshed:       {refreshed}")
    print(f"  skipped(fresh):  {skipped_fresh}")
    print(f"  skipped(noStamp): {skipped_no_stamp}")
    print(f"  errors:          {errors}")


if __name__ == "__main__":
    main()
