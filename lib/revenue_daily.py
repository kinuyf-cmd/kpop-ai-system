#!/usr/bin/env python3
"""
lib/revenue_daily.py — 日次収益データ収集・サマリー生成
Phase 7 Track D-1

機能:
  - collect_daily_revenue()    : metrics_yesterday.json から日次データを収集・JSONL追記
  - get_revenue_summary()      : 直近N日の収益トレンド・平均・月次合計を返す
  - get_top_articles_by_revenue(): 推定収益上位記事を返す
"""

import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────────────────────
# パス定義
# ─────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent
METRICS_PATH = BASE / "google_metrics" / "metrics_yesterday.json"
REVENUE_DAILY_PATH = BASE / "logs" / "revenue_daily.jsonl"
FINANCE_TARGETS_PATH = BASE / "config" / "finance_targets.json"
REVENUE_CONFIG_PATH = BASE / "config" / "revenue_config.json"
ARTICLE_METRICS_PATH = BASE / "logs" / "article_metrics_latest.json"

JST = timezone(timedelta(hours=9))

# ─────────────────────────────────────────────────────────────
# ロガー
# ─────────────────────────────────────────────────────────────
logger = logging.getLogger("revenue_daily")
if not logger.handlers:
    _sh = logging.StreamHandler(sys.stderr)
    _sh.setFormatter(logging.Formatter("[revenue_daily] %(message)s"))
    _sh.setLevel(logging.INFO)
    logger.addHandler(_sh)
    logger.setLevel(logging.DEBUG)


# ─────────────────────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("JSON読み込みエラー %s: %s", path, e)
        return {}


def _load_jsonl(path: Path, max_records: int = 500) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        logger.warning("JSONL読み込みエラー %s: %s", path, e)
    return records[-max_records:]


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(v: Any) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _today_str() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def _trend_label(values: list[float]) -> str:
    """値リストからトレンドを判定: 上昇/横ばい/下降"""
    if len(values) < 2:
        return "データ不足"
    first_half = values[: len(values) // 2]
    second_half = values[len(values) // 2 :]
    avg_first = sum(first_half) / max(len(first_half), 1)
    avg_second = sum(second_half) / max(len(second_half), 1)
    if avg_first == 0:
        return "横ばい" if avg_second == 0 else "上昇"
    change_pct = (avg_second - avg_first) / avg_first * 100
    if change_pct > 10:
        return "上昇"
    elif change_pct < -10:
        return "下降"
    return "横ばい"


# ─────────────────────────────────────────────────────────────
# メイン関数
# ─────────────────────────────────────────────────────────────

def collect_daily_revenue() -> dict:
    """
    metrics_yesterday.json から日次収益データを収集し、
    revenue_daily.jsonl に追記。サマリーdictを返す。
    同じ日付が既に存在する場合はスキップ。
    """
    metrics = _load_json(METRICS_PATH)
    if not metrics:
        logger.warning("metrics_yesterday.json が見つかりません")
        return {"status": "no_metrics"}

    metrics_date = metrics.get("date", _today_str())
    adsense = metrics.get("adsense", {})
    ga4_summary = metrics.get("ga4", {}).get("summary", {})

    # 既存レコードチェック
    existing = _load_jsonl(REVENUE_DAILY_PATH)
    existing_dates = {r.get("date") for r in existing}

    revenue = _safe_float(adsense.get("ESTIMATED_EARNINGS", "0"))
    pv = _safe_int(adsense.get("PAGE_VIEWS", "0"))
    impressions = _safe_int(adsense.get("IMPRESSIONS", "0"))
    clicks = _safe_int(adsense.get("CLICKS", "0"))
    rpm = _safe_float(adsense.get("PAGE_VIEWS_RPM", "0"))
    sessions = _safe_int(ga4_summary.get("sessions", "0"))
    total_pv = _safe_int(ga4_summary.get("pageviews", "0"))

    # CPM計算 (1000インプレッションあたりの収益)
    cpm = (revenue / impressions * 1000) if impressions > 0 else 0.0

    record = {
        "date": metrics_date,
        "adsense_revenue": revenue,
        "adsense_pv": pv,
        "adsense_impressions": impressions,
        "adsense_clicks": clicks,
        "adsense_rpm": rpm,
        "adsense_cpm": round(cpm, 1),
        "sessions": sessions,
        "total_pv": total_pv,
        "affiliate_revenue": 0,
        "total_revenue": revenue,
    }

    # 追記（重複チェック）
    if metrics_date not in existing_dates:
        _append_jsonl(REVENUE_DAILY_PATH, record)
        logger.info("revenue_daily.jsonl に %s のレコードを追記", metrics_date)
    else:
        logger.info("%s のレコードは既に存在。スキップ", metrics_date)

    return {
        "status": "ok",
        "date": metrics_date,
        "revenue_jpy": revenue,
        "sessions": sessions,
        "total_pv": total_pv,
        "rpm": rpm,
        "cpm": round(cpm, 1),
    }


def get_revenue_summary(days: int = 30) -> dict:
    """
    直近N日の収益サマリーを生成。
    トレンド・平均・月次合計を含むdictを返す。
    """
    records = _load_jsonl(REVENUE_DAILY_PATH)
    if not records:
        return {
            "status": "no_data",
            "message": "収益データがありません",
        }

    # 日付でソート、直近N日を取得
    records.sort(key=lambda r: r.get("date", ""))
    recent = records[-days:]

    # 基本集計
    revenues = [r.get("adsense_revenue", 0) + r.get("affiliate_revenue", 0)
                for r in recent]
    rpms = [r.get("adsense_rpm", 0) for r in recent]
    cpms = [r.get("adsense_cpm", r.get("adsense_revenue", 0) /
            max(r.get("adsense_impressions", 1), 1) * 1000)
            for r in recent]
    pvs = [r.get("total_pv", 0) for r in recent]

    total_revenue = sum(revenues)
    avg_daily = total_revenue / max(len(recent), 1)

    # 7日平均
    last_7 = recent[-7:] if len(recent) >= 7 else recent
    rev_7 = [r.get("adsense_revenue", 0) + r.get("affiliate_revenue", 0)
             for r in last_7]
    avg_7d = sum(rev_7) / max(len(rev_7), 1)

    # 30日平均
    last_30 = recent[-30:] if len(recent) >= 30 else recent
    rev_30 = [r.get("adsense_revenue", 0) + r.get("affiliate_revenue", 0)
              for r in last_30]
    avg_30d = sum(rev_30) / max(len(rev_30), 1)

    # 月次合計（今月）
    now = datetime.now(JST)
    current_month = now.strftime("%Y-%m")
    mtd_records = [r for r in records if (r.get("date", ""))[:7] == current_month]
    mtd_revenue = sum(r.get("adsense_revenue", 0) + r.get("affiliate_revenue", 0)
                      for r in mtd_records)
    mtd_days = len(mtd_records)

    # 月末予測
    days_in_month = (now.replace(month=now.month % 12 + 1, day=1) - timedelta(days=1)).day \
        if now.month < 12 else 31
    projected_monthly = (mtd_revenue / max(mtd_days, 1)) * days_in_month if mtd_days > 0 else 0

    # トレンド判定
    weekly_trend = _trend_label(rev_7)
    monthly_trend = _trend_label(rev_30)

    # RPM/CPMトレンド
    rpm_trend = _trend_label(rpms[-7:])

    # 目標読み込み
    targets = _load_json(FINANCE_TARGETS_PATH)
    daily_target = targets.get("daily", {}).get("revenue_jpy", {}).get("target", 200)
    monthly_target = targets.get("monthly", {}).get("revenue_jpy", {}).get("target", 6000)

    # 目標達成率
    daily_achievement = (avg_daily / daily_target * 100) if daily_target > 0 else 0
    monthly_achievement = (mtd_revenue / monthly_target * 100) if monthly_target > 0 else 0

    # 昨日のデータ
    yesterday = recent[-1] if recent else {}
    yesterday_revenue = yesterday.get("adsense_revenue", 0) + yesterday.get("affiliate_revenue", 0)

    return {
        "status": "ok",
        "data_days": len(recent),
        "yesterday": {
            "date": yesterday.get("date", ""),
            "revenue_jpy": yesterday_revenue,
            "sessions": yesterday.get("sessions", 0),
            "rpm": yesterday.get("adsense_rpm", 0),
            "cpm": yesterday.get("adsense_cpm", 0),
        },
        "avg_7d_jpy": round(avg_7d, 1),
        "avg_30d_jpy": round(avg_30d, 1),
        "mtd_revenue_jpy": round(mtd_revenue, 1),
        "mtd_days": mtd_days,
        "projected_monthly_jpy": round(projected_monthly, 1),
        "weekly_trend": weekly_trend,
        "monthly_trend": monthly_trend,
        "rpm_trend": rpm_trend,
        "avg_rpm": round(sum(rpms) / max(len(rpms), 1), 1),
        "avg_cpm": round(sum(cpms) / max(len(cpms), 1), 1),
        "daily_revenues": [{"date": r.get("date", ""), "revenue": r.get("adsense_revenue", 0) + r.get("affiliate_revenue", 0)}
                           for r in recent[-14:]],  # 直近14日分（スパークライン用）
        "targets": {
            "daily_target_jpy": daily_target,
            "monthly_target_jpy": monthly_target,
            "daily_achievement_pct": round(daily_achievement, 1),
            "monthly_achievement_pct": round(monthly_achievement, 1),
        },
    }


def get_top_articles_by_revenue(n: int = 10) -> list[dict]:
    """
    記事別の推定収益上位N件を返す。
    article_metrics_latest.json + metrics_yesterday.json から算出。
    """
    metrics = _load_json(METRICS_PATH)
    article_metrics = _load_json(ARTICLE_METRICS_PATH)
    rev_config = _load_json(REVENUE_CONFIG_PATH)

    adsense = metrics.get("adsense", {})
    overall_rpm = _safe_float(adsense.get("PAGE_VIEWS_RPM", "0"))

    # 記事データソース: merged > gsc > ga4
    articles = (
        article_metrics.get("merged_articles", [])
        or article_metrics.get("gsc", {}).get("articles", [])
        or []
    )

    # GA4のランディングページも統合
    ga4_pages = metrics.get("ga4", {}).get("top_landing_pages", [])
    gsc_pages = metrics.get("gsc", {}).get("top_pages", [])

    page_data: dict[str, dict] = {}

    for p in ga4_pages:
        path = p.get("page", "")
        if path and path != "(not set)":
            page_data[path] = {
                "url": path,
                "sessions": _safe_int(p.get("sessions", 0)),
                "pageviews": _safe_int(p.get("pageviews", 0)),
            }

    for p in gsc_pages:
        url = p.get("page", "")
        path = "/" + url.split("/", 3)[-1] if "://" in url else url
        path = "/" + path.lstrip("/")
        if path in page_data:
            page_data[path]["clicks"] = p.get("clicks", 0)
            page_data[path]["impressions"] = p.get("impressions", 0)
            page_data[path]["ctr"] = p.get("ctr", 0)
        else:
            page_data[path] = {
                "url": path,
                "sessions": 0,
                "pageviews": 0,
                "clicks": p.get("clicks", 0),
                "impressions": p.get("impressions", 0),
                "ctr": p.get("ctr", 0),
            }

    # 推定収益を計算
    result = []
    for path, data in page_data.items():
        pv = data.get("pageviews", 0) or data.get("sessions", 0)
        est_revenue = pv * overall_rpm / 1000 if overall_rpm > 0 else pv * 2.0
        result.append({
            "url": data.get("url", path),
            "pageviews": pv,
            "sessions": data.get("sessions", 0),
            "clicks": data.get("clicks", 0),
            "impressions": data.get("impressions", 0),
            "est_revenue_jpy": round(est_revenue, 1),
        })

    result.sort(key=lambda x: x["est_revenue_jpy"], reverse=True)
    return result[:n]


# ─────────────────────────────────────────────────────────────
# CLI実行
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="日次収益データ収集")
    parser.add_argument("--collect", action="store_true", help="日次データ収集・追記")
    parser.add_argument("--summary", action="store_true", help="収益サマリー表示")
    parser.add_argument("--top", type=int, default=10, help="上位記事数")
    parser.add_argument("--days", type=int, default=30, help="サマリー対象日数")
    args = parser.parse_args()

    if args.collect or not any([args.summary]):
        result = collect_daily_revenue()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.summary:
        summary = get_revenue_summary(days=args.days)
        print(json.dumps(summary, ensure_ascii=False, indent=2))

        top = get_top_articles_by_revenue(n=args.top)
        print("\n--- 推定収益上位記事 ---")
        for i, a in enumerate(top, 1):
            print(f"  {i}. {a['url']} — ¥{a['est_revenue_jpy']:.0f}")
