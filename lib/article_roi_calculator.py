#!/usr/bin/env python3
"""
article_roi_calculator.py — 記事ROI自動計算（Phase 4）

品質スコア × CTR × PV で「記事ROI」を定義。
週次でTOP10/BOTTOM10レポートを自動生成し、
BOTTOM10を自動リライトキューに追加する。

ROI = quality_score × ctr_norm × pv_norm
  - quality_score: gardevoir刺さりスコア (0-100) or gengar品質スコア
  - ctr_norm: CTR ÷ サイト平均CTR (1.0が基準)
  - pv_norm: PV ÷ サイト平均PV (1.0が基準)

Usage:
  python3 lib/article_roi_calculator.py                # 週次ROI計算
  python3 lib/article_roi_calculator.py --report        # レポートのみ
  python3 lib/article_roi_calculator.py --queue-rewrite # BOTTOM10をリライトキューに追加
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"

ARTICLE_METRICS = LOGS / "article_metrics_latest.json"
ROI_REPORT = LOGS / "article_roi_report.json"
ROI_LOG = LOGS / "article_roi_weekly.jsonl"
REWRITE_QUEUE = LOGS / "rewrite_queue.jsonl"
PIPELINE_LOG = LOGS / "pipeline.jsonl"
POST_LOG = LOGS / "post_log.json"
KPI_LOG = LOGS / "kpi_posts.jsonl"

JST = timezone(timedelta(hours=9))

# 品質スコアのデフォルト（データなし時）
DEFAULT_QUALITY = 60


def _now_jst() -> str:
    return datetime.now(JST).isoformat()


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _get_quality_scores() -> dict[str, float]:
    """pipeline.jsonl から gardevoir/gengar のスコアを記事別に取得"""
    scores = {}
    entries = _load_jsonl(PIPELINE_LOG)

    for entry in entries:
        step = entry.get("step", "")
        if step not in ("gardevoir_hook_critic", "gengar"):
            continue

        # run_id からスラッグまたはタイトルを推定
        run_id = entry.get("run_id", "")
        report_file = entry.get("file", "")
        score_val = entry.get("score")

        if score_val and isinstance(score_val, (int, float)):
            # run_id をキーに（後でメトリクスとマッチ）
            scores[run_id] = max(scores.get(run_id, 0), float(score_val))

    # KPIログからもスコア取得
    kpi_entries = _load_jsonl(KPI_LOG)
    for kpi in kpi_entries:
        url = kpi.get("url", kpi.get("path", ""))
        q_score = kpi.get("quality_score", kpi.get("gardevoir_score"))
        if url and q_score:
            scores[url] = float(q_score)

    return scores


_JUNK_URL_RE = re.compile(
    r"(#rtoc-|/wp-content/|/wp-includes/|/tag/|/category/|/author/|/page/\d"
    r"|\.(jpg|jpeg|png|gif|svg|webp|css|js|xml|txt)(\?|$))",
    re.IGNORECASE,
)
_HUB_RE = re.compile(r"\.tokyo/[^/]+-hub/?$")


def _is_article_url(url: str) -> bool:
    """画像・アンカーリンク・静的ファイル・タグ/カテゴリ等のゴミURLを除外"""
    if _JUNK_URL_RE.search(url):
        return False
    if _HUB_RE.search(url):
        return False
    return True


def _get_article_metrics() -> list[dict]:
    """GSC/GA4統合メトリクスを取得"""
    if not ARTICLE_METRICS.exists():
        return []

    data = json.loads(ARTICLE_METRICS.read_text(encoding="utf-8"))

    if "merged_articles" in data:
        articles = data["merged_articles"]
    elif "gsc" in data and "articles" in data["gsc"]:
        articles = data["gsc"]["articles"]
    else:
        return []

    return [a for a in articles if _is_article_url(a.get("url", a.get("path", "")))]


def calculate_roi(articles: list[dict], quality_scores: dict) -> list[dict]:
    """記事ROIを算出"""
    if not articles:
        return []

    # サイト平均を算出
    total_ctr = sum(a.get("gsc_ctr", a.get("ctr", 0)) for a in articles)
    total_pv = sum(a.get("ga4_pageviews", a.get("pageviews", 0)) for a in articles)
    n = max(len(articles), 1)
    avg_ctr = max(total_ctr / n, 0.001)
    avg_pv = max(total_pv / n, 1)

    results = []
    for a in articles:
        url = a.get("url", a.get("path", ""))
        path = a.get("path", url)
        ctr = a.get("gsc_ctr", a.get("ctr", 0))
        pv = a.get("ga4_pageviews", a.get("pageviews", 0))
        impressions = a.get("gsc_impressions", a.get("impressions", 0))
        position = a.get("gsc_position", a.get("position", 0))

        # 品質スコアの取得（URLマッチ or デフォルト）
        quality = DEFAULT_QUALITY
        for key, score in quality_scores.items():
            if url in key or key in url or path in key:
                quality = score
                break

        # ROI計算
        ctr_norm = ctr / avg_ctr if avg_ctr > 0 else 0
        pv_norm = pv / avg_pv if avg_pv > 0 else 0
        roi = round(quality * ctr_norm * pv_norm, 2)

        results.append({
            "url": url,
            "path": path,
            "roi": roi,
            "quality_score": quality,
            "ctr": round(ctr, 4),
            "ctr_norm": round(ctr_norm, 2),
            "pv": pv,
            "pv_norm": round(pv_norm, 2),
            "impressions": impressions,
            "position": round(position, 1),
        })

    results.sort(key=lambda x: -x["roi"])
    return results


def generate_report(roi_data: list[dict]) -> dict:
    """TOP10/BOTTOM10レポート生成"""
    if not roi_data:
        return {"error": "データなし"}

    top10 = roi_data[:10]
    bottom10 = roi_data[-10:] if len(roi_data) >= 10 else roi_data
    bottom10.reverse()  # 最も低いものを先頭に

    avg_roi = sum(r["roi"] for r in roi_data) / max(len(roi_data), 1)
    median_idx = len(roi_data) // 2
    median_roi = roi_data[median_idx]["roi"] if roi_data else 0

    report = {
        "generated_at": _now_jst(),
        "period": f"直近7日間",
        "total_articles": len(roi_data),
        "avg_roi": round(avg_roi, 2),
        "median_roi": round(median_roi, 2),
        "max_roi": roi_data[0]["roi"] if roi_data else 0,
        "min_roi": roi_data[-1]["roi"] if roi_data else 0,
        "top10": [
            {
                "rank": i + 1,
                "url": r["url"],
                "roi": r["roi"],
                "quality": r["quality_score"],
                "ctr": f"{r['ctr']:.1%}",
                "pv": r["pv"],
            }
            for i, r in enumerate(top10)
        ],
        "bottom10": [
            {
                "rank": len(roi_data) - i,
                "url": r["url"],
                "roi": r["roi"],
                "quality": r["quality_score"],
                "ctr": f"{r['ctr']:.1%}",
                "pv": r["pv"],
                "diagnosis": _diagnose_low_roi(r),
            }
            for i, r in enumerate(bottom10)
        ],
    }

    return report


def _diagnose_low_roi(article: dict) -> str:
    """低ROI記事の原因診断"""
    issues = []
    if article["ctr"] < 0.01:
        issues.append("CTR極低（タイトル/メタ改善要）")
    if article["pv"] < 5:
        issues.append("PV極低（インデックス/内部リンク不足?）")
    if article["quality_score"] < 50:
        issues.append("品質スコア低（コンテンツ改善要）")
    if article["position"] > 30:
        issues.append("検索順位低（SEO強化要）")
    if article.get("impressions", 0) < 20:
        issues.append("露出不足（キーワード戦略見直し）")

    return " / ".join(issues) if issues else "総合的に改善要"


def queue_rewrites(roi_data: list[dict], bottom_n: int = 10):
    """BOTTOM N を自動リライトキューに追加"""
    if len(roi_data) < bottom_n:
        bottom_n = len(roi_data)

    bottom = roi_data[-bottom_n:]
    existing = _load_jsonl(REWRITE_QUEUE)
    existing_urls = {r.get("url") for r in existing if r.get("status") != "completed"}

    added = 0
    for article in bottom:
        if article["url"] in existing_urls:
            continue

        record = {
            "url": article["url"],
            "path": article["path"],
            "roi": article["roi"],
            "quality_score": article["quality_score"],
            "ctr": article["ctr"],
            "pv": article["pv"],
            "diagnosis": _diagnose_low_roi(article),
            "status": "queued",
            "queued_at": _now_jst(),
            "source": "roi_bottom10",
            "priority": "high" if article["roi"] < 1.0 else "medium",
        }
        with open(REWRITE_QUEUE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        added += 1

    print(f"  リライトキューに{added}件追加（既存重複{bottom_n - added}件スキップ）")
    return added


def run_roi_calculation(report_only: bool = False, queue_rewrite: bool = True):
    """ROI計算のメインフロー"""
    print(f"[{_now_jst()[:16]}] 記事ROI自動計算 開始")

    # 1. データ収集
    print("  [1/4] メトリクス読み込み...")
    articles = _get_article_metrics()
    if not articles:
        print("  ❌ メトリクスデータなし（fetch_yesterday_metrics.py を先に実行）")
        return

    print(f"    → {len(articles)} 記事のメトリクス取得")

    # 2. 品質スコア取得
    print("  [2/4] 品質スコア取得...")
    quality_scores = _get_quality_scores()
    print(f"    → {len(quality_scores)} 件の品質スコア")

    # 3. ROI計算
    print("  [3/4] ROI計算...")
    roi_data = calculate_roi(articles, quality_scores)
    print(f"    → {len(roi_data)} 記事のROI算出完了")

    # 4. レポート生成
    print("  [4/4] レポート生成...")
    report = generate_report(roi_data)

    # レポート保存
    LOGS.mkdir(parents=True, exist_ok=True)
    ROI_REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # 週次ログ追記
    log_entry = {
        "date": date.today().isoformat(),
        "total_articles": report["total_articles"],
        "avg_roi": report["avg_roi"],
        "median_roi": report["median_roi"],
        "max_roi": report["max_roi"],
        "min_roi": report["min_roi"],
    }
    with open(ROI_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    # レポート表示
    print(f"\n  === 記事ROIレポート ===")
    print(f"  総記事数: {report['total_articles']}")
    print(f"  平均ROI: {report['avg_roi']}")
    print(f"  中央値ROI: {report['median_roi']}")

    print(f"\n  --- TOP 10 ---")
    for item in report["top10"]:
        print(f"  #{item['rank']:2d} ROI={item['roi']:7.1f}  CTR={item['ctr']}  PV={item['pv']:5d}  {item['url'][-40:]}")

    print(f"\n  --- BOTTOM 10 ---")
    for item in report["bottom10"]:
        print(f"  #{item['rank']:2d} ROI={item['roi']:7.1f}  CTR={item['ctr']}  PV={item['pv']:5d}  {item['url'][-40:]}")
        print(f"       診断: {item['diagnosis']}")

    # リライトキュー追加
    if queue_rewrite and not report_only:
        print(f"\n  リライトキュー更新...")
        queue_rewrites(roi_data)

    print(f"\nROI計算完了 → {ROI_REPORT}")
    return report


def main():
    parser = argparse.ArgumentParser(description="記事ROI自動計算")
    parser.add_argument("--report", action="store_true", help="レポートのみ（キュー追加なし）")
    parser.add_argument("--queue-rewrite", action="store_true", help="BOTTOM10をリライトキューに追加")
    args = parser.parse_args()

    run_roi_calculation(
        report_only=args.report,
        queue_rewrite=args.queue_rewrite or not args.report,
    )


if __name__ == "__main__":
    main()
