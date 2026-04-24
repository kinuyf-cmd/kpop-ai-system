#!/usr/bin/env python3
"""
trend_predictor.py — トレンド予測AI（Phase 4）
Google Trends + X(Twitter)トレンド + GSCクエリ急上昇を組み合わせ、
3日後にバズる記事トピックを予測しauto_directivesに自動注入する。

管轄: ジラーチ（予測担当）→ ミュウツー（戦略注入）

Usage:
  python3 lib/trend_predictor.py                   # 予測実行＋注入
  python3 lib/trend_predictor.py --dry-run          # 予測のみ（注入なし）
  python3 lib/trend_predictor.py --top 10           # 上位10トピック
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"
GMETRICS = BASE / "google_metrics"

AUTO_DIRECTIVES = CONFIG / "auto_directives.json"
TREND_LOG = LOGS / "trend_predictions.jsonl"
GSC_METRICS = LOGS / "gsc_metrics_latest.json"
ARTICLE_METRICS = LOGS / "article_metrics_latest.json"

JST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------------------
# Signal collectors
# ---------------------------------------------------------------------------

def _collect_gsc_rising_queries(days_recent=3, days_baseline=14) -> list[dict]:
    """GSCクエリの直近3日 vs 過去14日の急上昇を検出"""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        return []

    sa_file = GMETRICS / "service_account.json"
    if not sa_file.exists():
        return []

    creds = service_account.Credentials.from_service_account_file(
        str(sa_file),
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
    )
    service = build("searchconsole", "v1", credentials=creds)
    site_url = os.environ.get("GSC_SITE_URL", "https://www.kpopjournal.tokyo/")

    end = date.today() - timedelta(days=1)

    def _fetch(start_d, end_d, limit=200):
        body = {
            "startDate": start_d.isoformat(),
            "endDate": end_d.isoformat(),
            "dimensions": ["query"],
            "rowLimit": limit,
        }
        try:
            res = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
            return {
                row["keys"][0]: {
                    "clicks": row.get("clicks", 0),
                    "impressions": row.get("impressions", 0),
                    "ctr": row.get("ctr", 0),
                    "position": row.get("position", 0),
                }
                for row in res.get("rows", [])
            }
        except Exception:
            return {}

    recent = _fetch(end - timedelta(days=days_recent - 1), end, 200)
    baseline = _fetch(end - timedelta(days=days_baseline - 1),
                      end - timedelta(days=days_recent), 200)

    rising = []
    for q, r_data in recent.items():
        b_data = baseline.get(q)
        if not b_data:
            # 新出クエリ（baseline にない）= 急上昇候補
            if r_data["impressions"] >= 20:
                rising.append({
                    "query": q,
                    "signal": "new_query",
                    "recent_impressions": r_data["impressions"],
                    "recent_clicks": r_data["clicks"],
                    "growth_ratio": 999.0,
                })
        else:
            # 既存クエリの表示回数増加率
            b_impr = max(b_data["impressions"], 1)
            r_impr = r_data["impressions"]
            ratio = r_impr / b_impr
            if ratio >= 2.0 and r_impr >= 20:
                rising.append({
                    "query": q,
                    "signal": "rising",
                    "recent_impressions": r_impr,
                    "recent_clicks": r_data["clicks"],
                    "baseline_impressions": b_data["impressions"],
                    "growth_ratio": round(ratio, 2),
                })

    rising.sort(key=lambda x: -x["growth_ratio"])
    return rising[:30]


def _collect_x_trends() -> list[dict]:
    """X(Twitter)トレンドをClaude WebSearchで取得"""
    prompt = """以下の条件でX(Twitter)の日本のK-POPトレンドを調査し、JSON配列で返せ。

【条件】
- 現在X(Twitter)の日本で話題のK-POP関連トピック
- 直近24-72時間でツイート数が急増しているもの
- アーティスト名・イベント名・楽曲名など具体的なもの

【出力形式（JSON配列のみ、説明不要）】
[
  {"topic": "トピック名", "artist": "関連アーティスト", "reason": "話題の理由", "heat": 1-10},
  ...
]

最大10件。JSON配列のみ出力。"""

    try:
        result = subprocess.run(
            ["claude", "--no-session-persistence", "-p", prompt],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            return []
        text = result.stdout.strip()
        # JSON配列を抽出
        m = re.search(r"\[[\s\S]*?\]", text)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    return []


def _collect_google_trends_kpop() -> list[dict]:
    """Google TrendsのK-POP関連急上昇をClaude WebSearchで取得"""
    prompt = """Google Trendsの日本における直近のK-POP関連の急上昇キーワードを調査し、JSON配列で返せ。

【条件】
- Google Trendsで過去7日間に急上昇している日本のK-POP関連検索
- 「急上昇」「注目」のキーワードを優先
- アーティスト名、イベント、新曲、カムバック、来日等

【出力形式（JSON配列のみ、説明不要）】
[
  {"keyword": "検索キーワード", "trend_score": 1-100, "category": "カテゴリ", "context": "背景"},
  ...
]

最大10件。JSON配列のみ出力。"""

    try:
        result = subprocess.run(
            ["claude", "--no-session-persistence", "-p", prompt],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            return []
        text = result.stdout.strip()
        m = re.search(r"\[[\s\S]*?\]", text)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------

def _compute_buzz_score(topic: dict) -> float:
    """3つのシグナルを統合してバズ予測スコア（0-100）を算出"""
    score = 0.0

    # GSCシグナル（急上昇クエリとの一致）
    gsc_weight = topic.get("gsc_growth_ratio", 0)
    if gsc_weight >= 5.0:
        score += 35
    elif gsc_weight >= 3.0:
        score += 25
    elif gsc_weight >= 2.0:
        score += 15

    # Xトレンドheat
    x_heat = topic.get("x_heat", 0)
    score += min(x_heat * 3, 30)  # max 30

    # Google Trendsスコア
    gt_score = topic.get("google_trend_score", 0)
    score += min(gt_score * 0.25, 25)  # max 25

    # ボーナス: 複数シグナルの重複
    signals = sum([
        1 if gsc_weight >= 2.0 else 0,
        1 if x_heat >= 5 else 0,
        1 if gt_score >= 30 else 0,
    ])
    if signals >= 3:
        score += 10  # トリプルシグナルボーナス
    elif signals >= 2:
        score += 5   # ダブルシグナルボーナス

    return min(round(score, 1), 100)


def _merge_signals(gsc_rising: list, x_trends: list, gt_trends: list) -> list[dict]:
    """3つのシグナルソースをトピック単位でマージ"""
    topics = {}

    # GSC急上昇クエリ
    for q in gsc_rising:
        key = q["query"].lower()
        topics[key] = {
            "topic": q["query"],
            "source_signals": ["gsc"],
            "gsc_growth_ratio": q["growth_ratio"],
            "gsc_impressions": q["recent_impressions"],
            "x_heat": 0,
            "google_trend_score": 0,
        }

    # Xトレンド
    for t in x_trends:
        topic_name = t.get("topic", "")
        key = topic_name.lower()
        heat = t.get("heat", 0)
        if key in topics:
            topics[key]["x_heat"] = heat
            topics[key]["source_signals"].append("x")
        else:
            topics[key] = {
                "topic": topic_name,
                "artist": t.get("artist", ""),
                "reason": t.get("reason", ""),
                "source_signals": ["x"],
                "gsc_growth_ratio": 0,
                "gsc_impressions": 0,
                "x_heat": heat,
                "google_trend_score": 0,
            }

    # Google Trends
    for g in gt_trends:
        kw = g.get("keyword", "")
        key = kw.lower()
        gt_s = g.get("trend_score", 0)
        if key in topics:
            topics[key]["google_trend_score"] = gt_s
            topics[key]["source_signals"].append("google_trends")
            if not topics[key].get("category"):
                topics[key]["category"] = g.get("category", "")
        else:
            topics[key] = {
                "topic": kw,
                "category": g.get("category", ""),
                "context": g.get("context", ""),
                "source_signals": ["google_trends"],
                "gsc_growth_ratio": 0,
                "gsc_impressions": 0,
                "x_heat": 0,
                "google_trend_score": gt_s,
            }

    # スコア算出
    result = []
    for key, t in topics.items():
        t["buzz_score"] = _compute_buzz_score(t)
        result.append(t)

    result.sort(key=lambda x: -x["buzz_score"])
    return result


# ---------------------------------------------------------------------------
# auto_directives injection
# ---------------------------------------------------------------------------

def _inject_to_auto_directives(predictions: list[dict]):
    """予測結果をauto_directives.jsonのfocus_themesに注入"""
    if not predictions:
        return

    ad = json.loads(AUTO_DIRECTIVES.read_text(encoding="utf-8"))

    # 既存のtrend_prediction由来のテーマを除去
    existing_themes = [
        t for t in ad.get("focus_themes", [])
        if t.get("source") != "trend_prediction"
    ]

    # 上位5件を注入
    today = date.today().isoformat()
    for pred in predictions[:5]:
        signals = "+".join(pred.get("source_signals", []))
        hint_parts = []
        if pred.get("reason"):
            hint_parts.append(pred["reason"])
        if pred.get("context"):
            hint_parts.append(pred["context"])
        if pred.get("artist"):
            hint_parts.append(f"関連: {pred['artist']}")
        hint_parts.append(f"バズ予測スコア: {pred['buzz_score']}")
        hint_parts.append(f"シグナル: {signals}")

        existing_themes.append({
            "topic": pred["topic"],
            "hint": "。".join(hint_parts),
            "category_suggest": pred.get("category", "速報"),
            "added_at": today,
            "source": "trend_prediction",
            "buzz_score": pred["buzz_score"],
            "expires_at": (date.today() + timedelta(days=3)).isoformat(),
        })

    ad["focus_themes"] = existing_themes
    ad["updated_at"] = datetime.now(JST).isoformat()

    AUTO_DIRECTIVES.write_text(
        json.dumps(ad, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"  auto_directives.json に {min(len(predictions), 5)} 件注入完了")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_prediction(top: int = 5, dry_run: bool = False) -> list[dict]:
    """トレンド予測のメインフロー"""
    now_s = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    print(f"[{now_s}] トレンド予測AI 開始 (top={top})")

    # 1. シグナル収集
    print("  [1/4] GSC急上昇クエリ収集...")
    gsc_rising = _collect_gsc_rising_queries()
    print(f"    → {len(gsc_rising)} 件の急上昇クエリ検出")

    print("  [2/4] X(Twitter)トレンド収集...")
    x_trends = _collect_x_trends()
    print(f"    → {len(x_trends)} 件のXトレンド検出")

    print("  [3/4] Google Trends収集...")
    gt_trends = _collect_google_trends_kpop()
    print(f"    → {len(gt_trends)} 件のGTトレンド検出")

    # 2. マージ＋スコアリング
    print("  [4/4] シグナル統合・バズ予測スコア算出...")
    predictions = _merge_signals(gsc_rising, x_trends, gt_trends)

    # 上位表示
    top_predictions = predictions[:top]
    print(f"\n  === バズ予測 TOP {min(top, len(top_predictions))} ===")
    for i, p in enumerate(top_predictions, 1):
        signals = "+".join(p.get("source_signals", []))
        print(f"  {i}. [{p['buzz_score']:5.1f}] {p['topic']}  ({signals})")

    # 3. ログ記録
    LOGS.mkdir(parents=True, exist_ok=True)
    log_record = {
        "timestamp": datetime.now(JST).isoformat(),
        "predictions_count": len(predictions),
        "top_predictions": top_predictions,
        "signal_counts": {
            "gsc_rising": len(gsc_rising),
            "x_trends": len(x_trends),
            "google_trends": len(gt_trends),
        },
    }
    with open(TREND_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_record, ensure_ascii=False) + "\n")

    # 4. auto_directives注入
    if not dry_run and top_predictions:
        _inject_to_auto_directives(top_predictions)
    elif dry_run:
        print("\n  [dry-run] auto_directives注入スキップ")

    print(f"\n予測完了: {len(predictions)}トピック分析 → TOP{min(top, len(top_predictions))}選定")
    return top_predictions


def main():
    parser = argparse.ArgumentParser(description="トレンド予測AI")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run_prediction(top=args.top, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
