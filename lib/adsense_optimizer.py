#!/usr/bin/env python3
"""
AdSense配置最適化エンジン

機能:
  1. 記事別RPM計測（GA4 Data API連携）
  2. 最適広告配置ポジションの算出（ヒートマップ分析ベース）
  3. 記事本文への広告スロット自動挿入
  4. RPMレポート・改善提案出力

使い方:
  python3 lib/adsense_optimizer.py inject [--limit 50] [--dry-run]
  python3 lib/adsense_optimizer.py report
  python3 lib/adsense_optimizer.py measure [--days 7]

cron推奨: 毎日 5:00 に measure、毎日 6:00 に inject
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"
GMETRICS = BASE / "google_metrics"

RPM_LOG = LOGS / "adsense_rpm.jsonl"
AD_INJECT_LOG = LOGS / "adsense_inject.jsonl"
MAX_ADS_PER_ARTICLE = 5
METRICS_FILE = GMETRICS / "metrics_yesterday.json"
SERVICE_ACCT = GMETRICS / "service_account.json"

WP = "https://www.kpopjournal.tokyo"
WP_AUTH = str(Path.home() / ".wp_auth")
JST = timezone(timedelta(hours=9))
GA4_PROPERTY_ID = "493983919"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AdSense広告スロットHTML
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 位置別の広告ユニット（Google AdSense auto-ad互換）
AD_SLOTS = {
    "after_intro": {
        "html": """<div class="kpopj-ad kpopj-ad-after-intro" data-ad-slot="after-intro" style="margin:24px 0;text-align:center;min-height:250px;">
<ins class="adsbygoogle" style="display:block" data-ad-client="ca-pub-XXXXXXX" data-ad-slot="INTRO_SLOT" data-ad-format="rectangle" data-full-width-responsive="true"></ins>
<script>(adsbygoogle = window.adsbygoogle || []).push({});</script>
</div>""",
        "weight": 1.0,  # RPM重み（ヒートマップ分析ベース）
        "description": "導入直後（最もスクロール到達率が高い）",
    },
    "mid_article": {
        "html": """<div class="kpopj-ad kpopj-ad-mid" data-ad-slot="mid-article" style="margin:28px 0;text-align:center;min-height:250px;">
<ins class="adsbygoogle" style="display:block" data-ad-client="ca-pub-XXXXXXX" data-ad-slot="MID_SLOT" data-ad-format="rectangle" data-full-width-responsive="true"></ins>
<script>(adsbygoogle = window.adsbygoogle || []).push({});</script>
</div>""",
        "weight": 0.85,
        "description": "記事中盤（滞在時間が最も長い位置）",
    },
    "before_conclusion": {
        "html": """<div class="kpopj-ad kpopj-ad-conclusion" data-ad-slot="before-conclusion" style="margin:28px 0;text-align:center;min-height:250px;">
<ins class="adsbygoogle" style="display:block" data-ad-client="ca-pub-XXXXXXX" data-ad-slot="CONCLUSION_SLOT" data-ad-format="rectangle" data-full-width-responsive="true"></ins>
<script>(adsbygoogle = window.adsbygoogle || []).push({});</script>
</div>""",
        "weight": 0.7,
        "description": "結論直前（CVR最適位置）",
    },
    "after_article": {
        "html": """<div class="kpopj-ad kpopj-ad-bottom" data-ad-slot="after-article" style="margin:32px 0 16px;text-align:center;min-height:250px;">
<ins class="adsbygoogle" style="display:block" data-ad-client="ca-pub-XXXXXXX" data-ad-slot="BOTTOM_SLOT" data-ad-format="rectangle" data-full-width-responsive="true"></ins>
<script>(adsbygoogle = window.adsbygoogle || []).push({});</script>
</div>""",
        "weight": 0.5,
        "description": "記事末尾（離脱防止）",
    },
}

# ヒートマップ分析ベースの最適配置ルール
# Phase6: 広告は最大3箇所に制限（UX改善）
PLACEMENT_RULES = {
    "short": {  # < 2000文字
        "max_ads": 2,
        "positions": ["after_intro", "after_article"],
    },
    "medium": {  # 2000-4000文字
        "max_ads": 3,
        "positions": ["after_intro", "mid_article", "after_article"],
    },
    "long": {  # > 4000文字 — 以前は4箇所→3箇所に削減
        "max_ads": 3,
        "positions": ["after_intro", "mid_article", "after_article"],
    },
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RPM計測
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def measure_rpm(days: int = 7) -> list[dict]:
    """GA4 Data APIから記事別RPMを計測"""
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange, Dimension, Metric, RunReportRequest,
        )
        import os
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(SERVICE_ACCT))

        client = BetaAnalyticsDataClient()
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=days - 1)

        request = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            date_ranges=[DateRange(start_date=start_date.isoformat(), end_date=end_date.isoformat())],
            dimensions=[
                Dimension(name="pagePath"),
                Dimension(name="pageTitle"),
            ],
            metrics=[
                Metric(name="screenPageViews"),
                Metric(name="averageSessionDuration"),
                Metric(name="bounceRate"),
                Metric(name="totalAdRevenue"),
            ],
            limit=200,
            order_bys=[{"metric": {"metric_name": "screenPageViews"}, "desc": True}],
        )

        response = client.run_report(request)
        results = []
        for row in response.rows:
            path = row.dimension_values[0].value
            title = row.dimension_values[1].value
            pv = int(row.metric_values[0].value or 0)
            avg_duration = float(row.metric_values[1].value or 0)
            bounce_rate = float(row.metric_values[2].value or 0)
            ad_revenue = float(row.metric_values[3].value or 0)

            if pv < 5:
                continue

            rpm = (ad_revenue / pv * 1000) if pv > 0 else 0

            results.append({
                "path": path,
                "title": title[:60],
                "pv": pv,
                "rpm": round(rpm, 2),
                "avg_duration": round(avg_duration, 1),
                "bounce_rate": round(bounce_rate, 3),
                "ad_revenue": round(ad_revenue, 2),
            })

        # ログに記録
        ts = datetime.now(JST).isoformat()
        LOGS.mkdir(exist_ok=True)
        with open(RPM_LOG, "a") as f:
            f.write(json.dumps({
                "date": ts,
                "period_days": days,
                "articles": len(results),
                "avg_rpm": round(sum(r["rpm"] for r in results) / max(len(results), 1), 2),
                "top_rpm": results[:5] if results else [],
            }, ensure_ascii=False) + "\n")

        return results

    except ImportError:
        print("  ⚠️ google-analytics-data パッケージ未インストール → フォールバック計測")
        return _fallback_measure()
    except Exception as e:
        print(f"  ⚠️ GA4 API エラー: {e} → フォールバック計測")
        return _fallback_measure()


def _fallback_measure() -> list[dict]:
    """GA4 APIが使えない場合のフォールバック（metrics_yesterday.jsonから推計）"""
    if not METRICS_FILE.exists():
        return []
    try:
        data = json.loads(METRICS_FILE.read_text())
        pages = data.get("pages", [])
        results = []
        for p in pages[:100]:
            pv = p.get("clicks", 0) + p.get("impressions", 0) // 10
            # RPM推計: CTRベース (高CTR記事はエンゲージメント高→RPM高い傾向)
            ctr = p.get("ctr", 0)
            estimated_rpm = 150 + ctr * 5000  # ベース150円 + CTR加算
            results.append({
                "path": p.get("page", ""),
                "title": p.get("page", "")[:60],
                "pv": pv,
                "rpm": round(estimated_rpm, 2),
                "avg_duration": 0,
                "bounce_rate": 0,
                "ad_revenue": round(estimated_rpm * pv / 1000, 2),
            })
        return results
    except Exception:
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 広告スロット自動挿入
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def classify_length(content: str) -> str:
    """本文長さを分類"""
    plain = re.sub(r"<[^>]+>", "", content)
    char_count = len(plain)
    if char_count < 2000:
        return "short"
    elif char_count < 4000:
        return "medium"
    else:
        return "long"


def has_ad_slots(content: str) -> bool:
    """既にAdSenseスロットが挿入済みか"""
    return "kpopj-ad" in content or "adsbygoogle" in content


def find_h2_positions(content: str) -> list[int]:
    """H2タグの開始位置一覧"""
    return [m.start() for m in re.finditer(r"<h2\b", content, re.IGNORECASE)]


def inject_ad_slots(content: str, positions: list[str]) -> str:
    """指定ポジションに広告スロットを挿入"""
    if has_ad_slots(content):
        return content

    # 既存の広告ブロック数をカウントし、上限を超えないよう制限
    existing_ad_count = len(re.findall(r'class="kpopj-ad\b|adsbygoogle', content))
    remaining_budget = MAX_ADS_PER_ARTICLE - existing_ad_count
    if remaining_budget <= 0:
        return content
    positions = positions[:remaining_budget]

    h2_positions = find_h2_positions(content)
    p_positions = [m.start() for m in re.finditer(r"</p>", content)]

    result = content

    # 後ろから挿入（位置がずれないように）
    insertions = []

    for pos_name in positions:
        slot = AD_SLOTS.get(pos_name)
        if not slot:
            continue

        if pos_name == "after_intro" and h2_positions:
            # 最初のH2の直後の</p>の後
            first_h2 = h2_positions[0]
            after_h2_ps = [p for p in p_positions if p > first_h2]
            if after_h2_ps:
                insert_at = after_h2_ps[0] + len("</p>")
                insertions.append((insert_at, slot["html"]))

        elif pos_name == "mid_article" and len(h2_positions) >= 3:
            # 中間のH2の直前
            mid_idx = len(h2_positions) // 2
            insertions.append((h2_positions[mid_idx], slot["html"]))

        elif pos_name == "before_conclusion" and len(h2_positions) >= 2:
            # 最後のH2の直前
            insertions.append((h2_positions[-1], slot["html"]))

        elif pos_name == "after_article":
            # 記事末尾
            insertions.append((len(result), "\n" + slot["html"]))

    # 後ろから挿入
    for pos, html in sorted(insertions, key=lambda x: x[0], reverse=True):
        result = result[:pos] + "\n" + html + "\n" + result[pos:]

    return result


def inject_posts(limit: int = 50, dry_run: bool = False) -> int:
    """WP記事に広告スロットを自動挿入"""
    print(f"=== AdSense広告スロット自動挿入 (limit={limit}, dry_run={dry_run}) ===")

    # 直近記事を取得
    cmd = ["curl", "-s", f"{WP}/wp-json/wp/v2/posts?per_page={limit}&orderby=date&order=desc&_fields=id,title,content,categories",
           "-K", WP_AUTH]
    try:
        posts = json.loads(subprocess.check_output(cmd, timeout=30))
    except Exception as e:
        print(f"  ❌ WP API エラー: {e}")
        return 0

    injected = 0
    LOGS.mkdir(exist_ok=True)

    for post in posts:
        pid = post["id"]
        title = post.get("title", {}).get("rendered", "")
        content = post.get("content", {}).get("rendered", "")

        if has_ad_slots(content):
            continue

        length_class = classify_length(content)
        rule = PLACEMENT_RULES[length_class]

        new_content = inject_ad_slots(content, rule["positions"])

        if new_content == content:
            continue

        if dry_run:
            print(f"  [DRY-RUN] #{pid} ({length_class}): {title[:40]}... → {len(rule['positions'])}スロット挿入予定")
            injected += 1
            continue

        # WP更新
        update_cmd = [
            "curl", "-s", "-X", "POST",
            f"{WP}/wp-json/wp/v2/posts/{pid}",
            "-K", WP_AUTH,
            "-H", "Content-Type: application/json",
            "-d", json.dumps({"content": new_content}, ensure_ascii=False),
        ]
        try:
            resp = json.loads(subprocess.check_output(update_cmd, timeout=30))
            if resp.get("id"):
                injected += 1
                print(f"  ✅ #{pid} ({length_class}): {title[:40]}... → {len(rule['positions'])}スロット挿入完了")
                with open(AD_INJECT_LOG, "a") as f:
                    f.write(json.dumps({
                        "ts": datetime.now(JST).isoformat(),
                        "post_id": pid,
                        "title": title[:60],
                        "length_class": length_class,
                        "slots": rule["positions"],
                    }, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"  ⚠️ #{pid} 更新失敗: {e}")

    print(f"\n  合計: {injected}件に広告スロット挿入{'予定' if dry_run else '完了'}")
    return injected


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RPMレポート
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def report():
    """RPMレポート出力"""
    print("=== AdSense RPMレポート ===")

    if not RPM_LOG.exists():
        print("  ⚠️ RPMログなし → まず measure を実行してください")
        return

    entries = []
    with open(RPM_LOG) as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))

    if not entries:
        print("  ⚠️ RPMデータなし")
        return

    latest = entries[-1]
    print(f"  計測日: {latest['date']}")
    print(f"  対象記事: {latest['articles']}件")
    print(f"  平均RPM: ¥{latest['avg_rpm']}")
    print()
    print("  TOP5 RPM記事:")
    for i, a in enumerate(latest.get("top_rpm", [])[:5], 1):
        print(f"    {i}. ¥{a['rpm']:,.0f} RPM | {a['pv']} PV | {a['title'][:50]}")

    # 改善提案
    print()
    print("  💡 改善提案:")
    if latest["avg_rpm"] < 200:
        print("    - 記事内広告配置を最適化（after_intro + mid_article が最もRPM高い傾向）")
        print("    - 記事平均滞在時間を伸ばす（目標30秒以上）→ RPM向上に直結")
    print("    - 高RPM記事のパターンを分析し、類似記事を量産")
    print("    - アンカー広告・固定フッター広告の併用を検討")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# メイン
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    parser = argparse.ArgumentParser(description="AdSense配置最適化エンジン")
    sub = parser.add_subparsers(dest="command")

    p_inject = sub.add_parser("inject", help="広告スロット自動挿入")
    p_inject.add_argument("--limit", type=int, default=50)
    p_inject.add_argument("--dry-run", action="store_true")

    p_measure = sub.add_parser("measure", help="記事別RPM計測")
    p_measure.add_argument("--days", type=int, default=7)

    sub.add_parser("report", help="RPMレポート出力")

    args = parser.parse_args()

    if args.command == "inject":
        inject_posts(limit=args.limit, dry_run=args.dry_run)
    elif args.command == "measure":
        results = measure_rpm(days=args.days)
        print(f"  計測完了: {len(results)}件")
    elif args.command == "report":
        report()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
