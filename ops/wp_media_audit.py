#!/usr/bin/env python3
"""WordPress メディアライブラリ容量監査

ConoHa Wing 上の WP メディア数と推定容量を WP REST API 経由で監視。
507 エラーの早期検知・傾向把握に使用。

使い方:
  python3 ops/wp_media_audit.py           # 概要レポート
  python3 ops/wp_media_audit.py --detail  # 月別詳細
"""
import json, sys, urllib.request, urllib.error
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = BASE_DIR / "logs" / "wp_media_audit.jsonl"

WP_API = "https://www.kpopjournal.tokyo/wp-json/wp/v2"


def fetch_json(url):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "KPJ-MediaAudit/1.0")
    with urllib.request.urlopen(req, timeout=15) as res:
        headers = {k.lower(): v for k, v in res.getheaders()}
        return json.loads(res.read()), headers


def main():
    detail = "--detail" in sys.argv

    # メディア総数
    _, headers = fetch_json(f"{WP_API}/media?per_page=1")
    total_media = int(headers.get("x-wp-total", 0))
    total_pages = int(headers.get("x-wp-totalpages", 0))

    print(f"WordPress メディア総数: {total_media}")

    # 最新50件のサイズサンプリング
    items, _ = fetch_json(f"{WP_API}/media?per_page=50&orderby=date&order=desc")

    total_sample_bytes = 0
    monthly = defaultdict(lambda: {"count": 0, "bytes": 0})

    for item in items:
        filesize = item.get("media_details", {}).get("filesize", 0) or 0
        total_sample_bytes += filesize
        month = item.get("date", "")[:7]
        monthly[month]["count"] += 1
        monthly[month]["bytes"] += filesize

    avg_size = total_sample_bytes / len(items) if items else 0
    estimated_total_mb = (avg_size * total_media) / (1024 * 1024)

    print(f"最新50件の平均サイズ: {avg_size / 1024:.1f} KB")
    print(f"推定メディア総容量: {estimated_total_mb:.0f} MB ({estimated_total_mb / 1024:.1f} GB)")

    # WP API ヘルスチェック (507テスト)
    try:
        _, _ = fetch_json(f"{WP_API}/posts?per_page=1")
        wp_api_status = "OK"
    except urllib.error.HTTPError as e:
        wp_api_status = f"HTTP {e.code}"
    except Exception as e:
        wp_api_status = f"ERROR: {e}"

    print(f"WP API 状態: {wp_api_status}")

    if detail:
        print(f"\n--- 月別メディア (最新50件サンプル) ---")
        for month in sorted(monthly.keys(), reverse=True):
            info = monthly[month]
            mb = info["bytes"] / (1024 * 1024)
            print(f"  {month}: {info['count']}件 ({mb:.1f} MB)")

    # ログ記録
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "total_media": total_media,
        "avg_size_kb": round(avg_size / 1024, 1),
        "estimated_total_mb": round(estimated_total_mb),
        "wp_api_status": wp_api_status,
    }
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # 危険判定
    if wp_api_status != "OK":
        print(f"\n🔴 WP API異常: {wp_api_status}")
        sys.exit(1)
    elif estimated_total_mb > 3000:
        print(f"\n⚠️ メディア容量が3GB超 — ConoHa Wing容量注意")
        sys.exit(0)
    else:
        print(f"\n✅ メディア容量正常")
        sys.exit(0)


if __name__ == "__main__":
    main()
