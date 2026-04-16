"""
週次CTR更新スクリプト

title_performance.jsonl の pending レコードを GSC 実CTR で win/lose 確定する。

フロー:
1. pending な post_id を抽出
2. 各 post_id の URL を WordPress REST から取得
3. GSC API で過去N日のCTR/impressions取得
4. impressions が閾値以上ならスコア化 (0-100) → title_learner.py update

スコアリング (サイト平均ベース):
  - サイト平均の2倍以上 → 100 (圧倒的勝ち)
  - サイト平均同等 → 50
  - サイト平均の半分 → 25
  - 0% → 0

  formula: score = min(100, round((ctr / site_avg_ctr) * 50))

Usage:
  python3 lib/ctr_updater.py                # 通常実行
  python3 lib/ctr_updater.py --dry-run      # 実更新せずプレビュー
  python3 lib/ctr_updater.py --days 14      # 集計期間指定
  python3 lib/ctr_updater.py --min-impr 30  # 最小imp閾値
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

# GSC認証
from google.oauth2 import service_account
from googleapiclient.discovery import build

BASE = Path("/home/aiuser/kpop-ai-system")
PERF_FILE = BASE / "logs" / "title_performance.jsonl"
SERVICE_ACCOUNT = BASE / "google_metrics" / "service_account.json"
GSC_SITE = os.environ.get("GSC_SITE_URL", "https://www.kpopjournal.tokyo/")
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


def load_pending_post_ids():
    """pending状態のpost_idを抽出"""
    if not PERF_FILE.exists():
        return []
    seen = set()
    pending = []
    with open(PERF_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("result") != "pending":
                continue
            pid = r.get("post_id")
            if pid and pid not in seen:
                seen.add(pid)
                pending.append(pid)
    return pending


def fetch_post_url(post_id):
    """WP REST から投稿URLを取得"""
    _auth = _wp_auth_header()
    _auth_value = _auth.split(": ", 1)[1] if ": " in _auth else ""
    if not _auth_value:
        return None
    req = urllib.request.Request(
        f"{WP_API}/{post_id}",
        headers={"Authorization": _auth_value},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return data.get("link", "")
    except Exception as e:
        print(f"  WP fetch error for {post_id}: {e}", file=sys.stderr)
        return None


def fetch_gsc_ctr(service, page_url, start_date, end_date):
    """指定URLのGSC CTR/imp/clicks を取得"""
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["page"],
        "dimensionFilterGroups": [{
            "filters": [{
                "dimension": "page",
                "operator": "equals",
                "expression": page_url,
            }]
        }],
        "rowLimit": 1,
    }
    try:
        res = service.searchanalytics().query(siteUrl=GSC_SITE, body=body).execute()
    except Exception as e:
        print(f"  GSC error: {e}", file=sys.stderr)
        return None
    rows = res.get("rows", [])
    if not rows:
        return None
    row = rows[0]
    return {
        "clicks": int(row.get("clicks", 0)),
        "impressions": int(row.get("impressions", 0)),
        "ctr": float(row.get("ctr", 0.0)),
        "position": float(row.get("position", 0.0)),
    }


def fetch_site_avg_ctr(service, start_date, end_date):
    """サイト全体の平均CTRを取得（基準値）"""
    body = {
        "startDate": start_date,
        "endDate": end_date,
    }
    try:
        res = service.searchanalytics().query(siteUrl=GSC_SITE, body=body).execute()
    except Exception as e:
        print(f"site avg fetch error: {e}", file=sys.stderr)
        return 0.05  # フォールバック: 5%
    rows = res.get("rows", [])
    if not rows:
        return 0.05
    return float(rows[0].get("ctr", 0.05))


def ctr_to_score(ctr, site_avg):
    """CTR (0-1) をサイト平均比較で 0-100 のスコアに"""
    if site_avg <= 0:
        return 50  # 比較不能、中立
    score = (ctr / site_avg) * 50
    return min(100, max(0, round(score)))


def call_title_learner_update(post_id, score, dry_run=False):
    """title_learner.py update を呼ぶ"""
    cmd = [
        "python3",
        str(BASE / "lib" / "title_learner.py"),
        "update",
        "--post-id", str(post_id),
        "--score", str(score),
    ]
    if dry_run:
        print(f"  [DRY-RUN] would run: {' '.join(cmd)}")
        return True
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  update failed: {e.stderr}", file=sys.stderr)
        return False


def call_thumbnail_learner_update(post_id, score, dry_run=False):
    """thumbnail_learner.py update を呼ぶ（同じスコアで同期更新）"""
    cmd = [
        "python3",
        str(BASE / "lib" / "thumbnail_learner.py"),
        "update",
        "--post-id", str(post_id),
        "--score", str(score),
    ]
    if dry_run:
        return True
    try:
        subprocess.run(cmd, check=False, capture_output=True, text=True)
        return True
    except Exception:
        return False


def backfill_from_gsc(days=14, min_impr=30, dry_run=False):
    """過去投稿をGSCから取得して title_performance.jsonl にバックフィル"""
    end_date = (date.today() - timedelta(days=1)).isoformat()
    start_date = (date.today() - timedelta(days=days)).isoformat()
    creds = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT),
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    )
    service = build("searchconsole", "v1", credentials=creds)

    site_avg = fetch_site_avg_ctr(service, start_date, end_date)
    print(f"backfill: {start_date} 〜 {end_date}, site_avg={site_avg*100:.2f}%")

    body = {
        "startDate": start_date, "endDate": end_date,
        "dimensions": ["page"], "rowLimit": 200,
    }
    res = service.searchanalytics().query(siteUrl=GSC_SITE, body=body).execute()
    rows = res.get("rows", [])
    print(f"GSC pages: {len(rows)}")

    # 既存pendingの post_id を取得
    existing_pids = set()
    if PERF_FILE.exists():
        with open(PERF_FILE) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    existing_pids.add(str(r.get("post_id", "")))
                except: pass

    _auth = _wp_auth_header()
    auth = _auth.split(": ", 1)[1] if ": " in _auth else ""
    new_records = []
    for row in rows:
        url = row["keys"][0]
        if row.get("impressions", 0) < min_impr:
            continue
        # URL→slug→post_id
        slug = url.rstrip("/").split("/")[-1]
        try:
            req = urllib.request.Request(
                f"{WP_API}?slug={slug}",
                headers={"Authorization": auth},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                posts = json.loads(r.read())
            if not posts:
                continue
            pid = str(posts[0]["id"])
            title = posts[0].get("title", {}).get("rendered", "")
        except Exception:
            continue
        if pid in existing_pids:
            continue
        score = ctr_to_score(row["ctr"], site_avg)
        result = "win" if score >= 50 else "lose"
        record = {
            "title": title,
            "ctr_score": score,
            "pattern": "情報型",  # 不明な場合のデフォルト
            "result": result,
            "post_id": pid,
            "timestamp": f"{date.today().isoformat()}T00:00:00",
            "backfilled_from_gsc": True,
            "raw_ctr": round(row["ctr"], 4),
            "impressions": int(row["impressions"]),
        }
        new_records.append(record)
        print(f"  +{pid}: imp={int(row['impressions'])}, ctr={row['ctr']*100:.2f}%, score={score} → {result} | {title[:40]}")

    if not new_records:
        print("nothing to backfill")
        return

    if dry_run:
        print(f"[DRY-RUN] would add {len(new_records)} records")
        return

    PERF_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PERF_FILE, "a", encoding="utf-8") as f:
        for r in new_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"✅ backfilled {len(new_records)} records")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14, help="集計期間（日）")
    ap.add_argument("--min-impr", type=int, default=30, help="最小impressions閾値")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backfill", action="store_true", help="過去投稿をGSCから取得してバックフィル")
    args = ap.parse_args()

    if args.backfill:
        backfill_from_gsc(days=args.days, min_impr=args.min_impr, dry_run=args.dry_run)
        return

    _auth = _wp_auth_header()
    _auth_value = _auth.split(": ", 1)[1] if ": " in _auth else ""
    if not _auth_value:
        print("ERROR: WP credentials not found (~/.wp_auth or WP_USER/WP_PASS)", file=sys.stderr)
        sys.exit(1)

    end_date = (date.today() - timedelta(days=1)).isoformat()
    start_date = (date.today() - timedelta(days=args.days)).isoformat()

    print(f"=== CTR Updater ({start_date} 〜 {end_date}) ===")

    # GSC初期化
    creds = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT),
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    )
    service = build("searchconsole", "v1", credentials=creds)

    # サイト平均
    site_avg = fetch_site_avg_ctr(service, start_date, end_date)
    print(f"サイト平均CTR: {site_avg:.4f} ({site_avg*100:.2f}%)")

    # pending抽出
    pending_ids = load_pending_post_ids()
    print(f"pending records: {len(pending_ids)} unique post_ids")
    if not pending_ids:
        print("nothing to update")
        return

    stats = {"updated": 0, "skipped_no_url": 0, "skipped_no_data": 0, "skipped_low_impr": 0, "errors": 0}

    for pid in pending_ids:
        print(f"--- post_id={pid} ---")
        url = fetch_post_url(pid)
        if not url:
            print(f"  URL取得失敗 → skip")
            stats["skipped_no_url"] += 1
            continue
        print(f"  URL: {url}")

        gsc = fetch_gsc_ctr(service, url, start_date, end_date)
        if not gsc:
            print(f"  GSC データなし → skip (impressions未達)")
            stats["skipped_no_data"] += 1
            continue

        if gsc["impressions"] < args.min_impr:
            print(f"  imp={gsc['impressions']} < {args.min_impr} → skip (継続pending)")
            stats["skipped_low_impr"] += 1
            continue

        score = ctr_to_score(gsc["ctr"], site_avg)
        result = "win" if score >= 50 else "lose"
        print(f"  imp={gsc['impressions']}, clicks={gsc['clicks']}, ctr={gsc['ctr']*100:.2f}%, score={score} → {result}")

        if call_title_learner_update(pid, score, dry_run=args.dry_run):
            stats["updated"] += 1
            # サムネ側も同じスコアで同期更新
            call_thumbnail_learner_update(pid, score, dry_run=args.dry_run)
        else:
            stats["errors"] += 1

    print(f"\n=== Summary ===")
    print(f"  updated:        {stats['updated']}")
    print(f"  skipped(noURL): {stats['skipped_no_url']}")
    print(f"  skipped(noGSC): {stats['skipped_no_data']}")
    print(f"  skipped(lowImp): {stats['skipped_low_impr']}")
    print(f"  errors:         {stats['errors']}")

    # 学習結果のwinning-words更新を促す
    if stats["updated"] > 0 and not args.dry_run:
        print(f"\n=== Refreshed winning-words ===")
        try:
            r = subprocess.run(
                ["python3", str(BASE / "lib" / "title_learner.py"), "winning-words"],
                capture_output=True, text=True, check=True,
            )
            print(r.stdout)
        except Exception as e:
            print(f"winning-words error: {e}")


if __name__ == "__main__":
    main()
