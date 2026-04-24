#!/usr/bin/env python3
"""
revenue_optimizer.py — K-POP AI会社 収益最適化エンジン v1.0
CEO: ミュウツー / 収益責任者: ニャース

5つの機能:
  1. AdSense Revenue Monitor   — 週次比較で20%以上の低下を検出・原因分析
  2. Affiliate CTR Optimizer    — 高PV×低アフィリエイトCTR記事に提案
  3. Winning Pattern Learner    — 高収益記事のパターン抽出
  4. Weekly Revenue Report      — Discord webhook へ週次レポート送信
  5. Category ROI Analyzer      — カテゴリ別 収益/記事数 を算出

Usage:
  python3 lib/revenue_optimizer.py --analyze     # 全分析（1+2+5）
  python3 lib/revenue_optimizer.py --optimize    # アフィリエイト最適化提案（2）
  python3 lib/revenue_optimizer.py --report      # 週次レポート Discord送信（4）
  python3 lib/revenue_optimizer.py --learn       # 勝ちパターン学習（3）
  python3 lib/revenue_optimizer.py --dry-run     # 送信・書き込みせず結果表示のみ
  python3 lib/revenue_optimizer.py --analyze --dry-run  # 組み合わせ可
"""

import argparse
import json
import logging
import sys
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────────────────────
# パス定義
# ─────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE / "config"
REVENUE_CONFIG_PATH = CONFIG_DIR / "revenue_config.json"
DISCORD_WEBHOOKS_PATH = CONFIG_DIR / "discord_webhooks.json"
METRICS_YESTERDAY_PATH = BASE / "google_metrics" / "metrics_yesterday.json"
REVENUE_DAILY_PATH = BASE / "logs" / "revenue_daily.jsonl"
OPTIMIZATION_OUTPUT_PATH = BASE / "reports" / "revenue_optimization.json"
LOG_PATH = BASE / "logs" / "revenue_optimizer.log"

JST = timezone(timedelta(hours=9))

# ─────────────────────────────────────────────────────────────
# ロガー
# ─────────────────────────────────────────────────────────────
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("revenue_optimizer")
logger.setLevel(logging.DEBUG)
_fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_fh)
_sh = logging.StreamHandler(sys.stderr)
_sh.setFormatter(logging.Formatter("[revenue_optimizer] %(message)s"))
_sh.setLevel(logging.INFO)
logger.addHandler(_sh)


# ─────────────────────────────────────────────────────────────
# ユーティリティ
# ─────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    """JSONファイルを安全に読み込む"""
    if not path.exists():
        logger.warning("ファイルが見つかりません: %s", path)
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error("JSON読み込みエラー %s: %s", path, e)
        return {}


def load_jsonl(path: Path) -> list[dict]:
    """JSONLファイルを安全に読み込む"""
    if not path.exists():
        return []
    records: list[dict] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        logger.error("JSONL読み込みエラー %s: %s", path, e)
    return records


def save_json(path: Path, data: Any, dry_run: bool = False) -> None:
    """JSONファイルに書き出す"""
    if dry_run:
        logger.info("[DRY-RUN] 書き込みスキップ: %s", path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.info("保存完了: %s", path)


def append_jsonl(path: Path, record: dict, dry_run: bool = False) -> None:
    """JSONLファイルに1行追記する"""
    if dry_run:
        logger.info("[DRY-RUN] 追記スキップ: %s", path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def today_str() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def parse_date(s: str) -> datetime:
    """YYYY-MM-DD 文字列を JST datetime に変換"""
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=JST)


# ─────────────────────────────────────────────────────────────
# 設定読み込み
# ─────────────────────────────────────────────────────────────

def load_revenue_config() -> dict:
    cfg = load_json(REVENUE_CONFIG_PATH)
    if not cfg:
        logger.warning("revenue_config.json が空または欠落。デフォルト値を使用します")
        return {
            "asp_providers": {},
            "article_type_cv_design": {},
            "adsense_optimization": {"rpm_target": 300, "measure_interval_days": 7},
            "affiliate_auto_linker": {"enabled": True, "max_links_per_article": 3},
            "daily_revenue_targets": {
                "month_1": 3000, "month_3": 6600,
                "month_6": 16600, "month_12": 33000,
            },
        }
    return cfg


def get_discord_webhook(channel: str) -> str:
    cfg = load_json(DISCORD_WEBHOOKS_PATH)
    return cfg.get(channel, "") or ""


# ─────────────────────────────────────────────────────────────
# 収益日次データ管理
# ─────────────────────────────────────────────────────────────

def ensure_today_revenue_record() -> None:
    """
    今日の metrics_yesterday.json から revenue_daily.jsonl にレコードを追記する。
    同じ日付のレコードが既にあればスキップ。
    """
    metrics = load_json(METRICS_YESTERDAY_PATH)
    if not metrics:
        return

    metrics_date = metrics.get("date", today_str())
    existing = load_jsonl(REVENUE_DAILY_PATH)
    existing_dates = {r.get("date") for r in existing}
    if metrics_date in existing_dates:
        return

    adsense = metrics.get("adsense", {})
    record = {
        "date": metrics_date,
        "adsense_revenue": _safe_float(adsense.get("ESTIMATED_EARNINGS", "0")),
        "adsense_pv": _safe_int(adsense.get("PAGE_VIEWS", "0")),
        "adsense_rpm": _safe_float(adsense.get("PAGE_VIEWS_RPM", "0")),
        "adsense_clicks": _safe_int(adsense.get("CLICKS", "0")),
        "affiliate_clicks": 0,
        "affiliate_revenue": 0,
        "total_pv": _safe_int(metrics.get("ga4", {}).get("summary", {}).get("pageviews", "0")),
    }
    append_jsonl(REVENUE_DAILY_PATH, record)
    logger.info("revenue_daily.jsonl に %s のレコードを追記", metrics_date)


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


# ═════════════════════════════════════════════════════════════
# 1. AdSense Revenue Monitor
# ═════════════════════════════════════════════════════════════

def adsense_revenue_monitor(config: dict) -> dict:
    """
    直近7日 vs 前7日の AdSense 収益を比較。
    20%以上の低下があればアラートと最適化アクションを返す。
    """
    logger.info("=== AdSense Revenue Monitor ===")
    records = load_jsonl(REVENUE_DAILY_PATH)
    if len(records) < 2:
        logger.info("データ不足（%d件）。比較にはもう少しデータが必要です", len(records))
        return {
            "status": "insufficient_data",
            "record_count": len(records),
            "message": "収益比較には最低2日分のデータが必要です",
        }

    # 日付でソートして直近14日を取得
    records.sort(key=lambda r: r.get("date", ""))
    recent_14 = records[-14:]

    midpoint = len(recent_14) // 2
    this_week = recent_14[midpoint:]
    last_week = recent_14[:midpoint]

    this_total = sum(r.get("adsense_revenue", 0) for r in this_week)
    last_total = sum(r.get("adsense_revenue", 0) for r in last_week)
    this_pv = sum(r.get("total_pv", 0) for r in this_week)
    last_pv = sum(r.get("total_pv", 0) for r in last_week)

    this_avg_rpm = (
        sum(r.get("adsense_rpm", 0) for r in this_week) / len(this_week)
        if this_week else 0
    )

    change_pct = (
        ((this_total - last_total) / last_total * 100)
        if last_total > 0 else 0.0
    )

    rpm_target = config.get("adsense_optimization", {}).get("rpm_target", 300)

    result: dict[str, Any] = {
        "status": "ok",
        "this_period": {
            "days": len(this_week),
            "total_revenue_jpy": this_total,
            "total_pv": this_pv,
            "avg_daily_revenue": round(this_total / max(len(this_week), 1), 1),
            "avg_rpm": round(this_avg_rpm, 1),
            "date_range": f"{this_week[0].get('date', '?')} ~ {this_week[-1].get('date', '?')}",
        },
        "last_period": {
            "days": len(last_week),
            "total_revenue_jpy": last_total,
            "total_pv": last_pv,
            "avg_daily_revenue": round(last_total / max(len(last_week), 1), 1),
            "date_range": f"{last_week[0].get('date', '?')} ~ {last_week[-1].get('date', '?')}",
        },
        "change_pct": round(change_pct, 1),
        "rpm_vs_target": round(this_avg_rpm - rpm_target, 1),
        "alerts": [],
        "actions": [],
    }

    # 20%以上の低下検出
    if change_pct <= -20:
        result["status"] = "decline_detected"
        result["alerts"].append(
            f"AdSense収益が前週比 {change_pct:+.1f}% 低下しています "
            f"({last_total:.0f}円 -> {this_total:.0f}円)"
        )

        # 原因分析: PV低下 or RPM低下
        pv_change = (
            ((this_pv - last_pv) / last_pv * 100) if last_pv > 0 else 0
        )
        if pv_change <= -15:
            result["actions"].append({
                "type": "pv_recovery",
                "priority": "HIGH",
                "description": f"PVが {pv_change:+.1f}% 低下。SEO記事の追加投稿・SNS拡散を強化してください",
            })
        if this_avg_rpm < rpm_target * 0.8:
            result["actions"].append({
                "type": "rpm_optimization",
                "priority": "HIGH",
                "description": (
                    f"RPMが目標の80%未満（{this_avg_rpm:.0f} vs 目標{rpm_target}）。"
                    "広告配置の見直し・記事長の調整を検討してください"
                ),
            })
        result["actions"].append({
            "type": "content_audit",
            "priority": "MEDIUM",
            "description": "低下期間の投稿記事を確認し、低品質コンテンツがないか監査してください",
        })

    # 目標達成率チェック
    targets = config.get("daily_revenue_targets", {})
    current_daily = result["this_period"]["avg_daily_revenue"]
    for phase, target_jpy in sorted(targets.items(), key=lambda x: x[1]):
        if current_daily < target_jpy:
            gap = target_jpy - current_daily
            result["actions"].append({
                "type": "target_gap",
                "priority": "INFO",
                "description": (
                    f"目標 {phase}（{target_jpy:,}円/日）まであと {gap:,.0f}円/日。"
                    f"現在の日次平均: {current_daily:,.0f}円/日"
                ),
            })
            break  # 最も近い未達目標のみ表示

    logger.info(
        "収益比較: 今週 %s円 vs 前週 %s円 (変化率 %+.1f%%)",
        this_total, last_total, change_pct,
    )
    return result


# ═════════════════════════════════════════════════════════════
# 2. Affiliate CTR Optimizer
# ═════════════════════════════════════════════════════════════

def affiliate_ctr_optimizer(config: dict) -> dict:
    """
    高PV × 低アフィリエイトCTR 記事を特定し、
    記事カテゴリに応じた ASP（amazon/a8/qoo10）でのリンク追加を提案。
    """
    logger.info("=== Affiliate CTR Optimizer ===")
    metrics = load_json(METRICS_YESTERDAY_PATH)
    if not metrics:
        return {"status": "no_metrics", "suggestions": []}

    # GSC top_pages からPVが多い記事を取得
    gsc_pages = metrics.get("gsc", {}).get("top_pages", [])
    ga4_pages = metrics.get("ga4", {}).get("top_landing_pages", [])

    # GA4のPVデータでページをランク付け
    page_pv: dict[str, int] = {}
    for p in ga4_pages:
        path = p.get("page", "")
        if path and path != "(not set)":
            page_pv[path] = _safe_int(p.get("sessions", 0))

    # アフィリエイトリンク実績を読み込み
    affiliate_log_path = BASE / "logs" / "affiliate_links.jsonl"
    affiliate_data = load_jsonl(affiliate_log_path)
    pages_with_affiliate: set[str] = set()
    for entry in affiliate_data:
        slug = entry.get("slug", "") or entry.get("page", "")
        if slug:
            pages_with_affiliate.add(slug)

    asp_providers = config.get("asp_providers", {})
    linker_cfg = config.get("affiliate_auto_linker", {})
    max_links = linker_cfg.get("max_links_per_article", 3)

    suggestions: list[dict] = []

    # PVが高い順にソート
    sorted_pages = sorted(page_pv.items(), key=lambda x: x[1], reverse=True)

    for page_path, pv in sorted_pages:
        if pv < 3:  # 最低PV閾値
            continue

        # スラッグ抽出
        slug = page_path.strip("/").split("/")[-1] if page_path else ""
        if not slug or slug == "(not set)":
            continue

        # 既にアフィリエイトリンクがある記事は優先度を下げる
        has_affiliate = any(slug in s for s in pages_with_affiliate)

        # URLのキーワードから適切なASPを推薦
        recommended_asps = _match_asps_for_slug(slug, asp_providers)

        if not recommended_asps:
            # デフォルトで全ASPを推薦（汎用記事）
            recommended_asps = [
                {"provider": "amazon", "reason": "汎用商品リンク（K-POPグッズ等）"},
            ]

        suggestion = {
            "page": page_path,
            "slug": slug,
            "sessions": pv,
            "has_existing_affiliate": has_affiliate,
            "priority": "HIGH" if (pv >= 10 and not has_affiliate) else "MEDIUM",
            "recommended_asps": recommended_asps[:max_links],
            "action": (
                "アフィリエイトリンク追加を推奨"
                if not has_affiliate
                else "リンク最適化を検討（既存リンクあり）"
            ),
        }
        suggestions.append(suggestion)

    suggestions.sort(
        key=lambda s: (0 if s["priority"] == "HIGH" else 1, -s["sessions"])
    )

    logger.info("アフィリエイト最適化提案: %d件", len(suggestions))
    return {
        "status": "ok",
        "total_pages_analyzed": len(sorted_pages),
        "suggestions": suggestions[:20],  # 上位20件
    }


def _match_asps_for_slug(slug: str, asp_providers: dict) -> list[dict]:
    """記事スラッグのキーワードからASPを推薦する"""
    recommendations: list[dict] = []
    slug_lower = slug.lower()

    keyword_asp_map = {
        "cosme": [("a8", "コスメ・ビューティ案件")],
        "beauty": [("a8", "ビューティ案件"), ("qoo10", "韓国コスメ")],
        "fashion": [("a8", "ファッション案件"), ("amazon", "ファッションアイテム")],
        "album": [("amazon", "アルバム・CD販売")],
        "goods": [("amazon", "K-POPグッズ"), ("qoo10", "韓国グッズ")],
        "food": [("amazon", "韓国食品"), ("qoo10", "韓国食品")],
        "tour": [("a8", "旅行・チケット案件")],
        "travel": [("a8", "旅行案件")],
        "ticket": [("a8", "チケット案件")],
        "skincare": [("a8", "スキンケア案件"), ("qoo10", "韓国スキンケア")],
        "guide": [("amazon", "関連書籍・グッズ")],
        "cast": [("amazon", "関連グッズ・DVD")],
        "brand": [("amazon", "ブランドアイテム"), ("qoo10", "韓国ブランド")],
    }

    seen_providers: set[str] = set()
    for keyword, asps in keyword_asp_map.items():
        if keyword in slug_lower:
            for provider_key, reason in asps:
                if provider_key not in seen_providers and provider_key in asp_providers:
                    provider_info = asp_providers[provider_key]
                    recommendations.append({
                        "provider": provider_key,
                        "provider_name": provider_info.get("name", provider_key),
                        "reason": reason,
                        "avg_commission": provider_info.get(
                            "avg_commission",
                            round(
                                provider_info.get("avg_commission_rate", 0)
                                * provider_info.get("avg_order_value", 0),
                                0,
                            ),
                        ),
                    })
                    seen_providers.add(provider_key)

    return recommendations


# ═════════════════════════════════════════════════════════════
# 3. Winning Pattern Learner
# ═════════════════════════════════════════════════════════════

def winning_pattern_learner(config: dict) -> dict:
    """
    高パフォーマンス記事（PV上位 + 高CTR）のパターンを抽出。
    タイトルスタイル、カテゴリ傾向、エンゲージメント特性を学習。
    """
    logger.info("=== Winning Pattern Learner ===")
    metrics = load_json(METRICS_YESTERDAY_PATH)
    if not metrics:
        return {"status": "no_metrics", "patterns": []}

    gsc_pages = metrics.get("gsc", {}).get("top_pages", [])
    ga4_pages = metrics.get("ga4", {}).get("top_landing_pages", [])

    # GA4 + GSC を統合
    page_data: dict[str, dict] = {}
    for p in ga4_pages:
        path = p.get("page", "")
        if path and path != "(not set)":
            page_data[path] = {
                "path": path,
                "sessions": _safe_int(p.get("sessions", 0)),
                "pageviews": _safe_int(p.get("pageviews", 0)),
                "engaged_sessions": _safe_int(p.get("engaged_sessions", 0)),
                "avg_duration": _safe_float(p.get("avg_session_duration", 0)),
            }

    for p in gsc_pages:
        url = p.get("page", "")
        # URLからパスを抽出
        path = "/" + url.split("/", 3)[-1] if "://" in url else url
        path = "/" + path.lstrip("/")
        if path in page_data:
            page_data[path]["gsc_clicks"] = p.get("clicks", 0)
            page_data[path]["gsc_impressions"] = p.get("impressions", 0)
            page_data[path]["gsc_ctr"] = p.get("ctr", 0)
            page_data[path]["gsc_position"] = p.get("position", 0)
        else:
            page_data[path] = {
                "path": path,
                "sessions": 0,
                "pageviews": 0,
                "engaged_sessions": 0,
                "avg_duration": 0,
                "gsc_clicks": p.get("clicks", 0),
                "gsc_impressions": p.get("impressions", 0),
                "gsc_ctr": p.get("ctr", 0),
                "gsc_position": p.get("position", 0),
            }

    if not page_data:
        return {"status": "no_page_data", "patterns": []}

    # スコアリング: PV × エンゲージメント率 × GSC CTR
    for path, data in page_data.items():
        pv = data.get("pageviews", 0) or data.get("sessions", 0)
        engaged = data.get("engaged_sessions", 0)
        engagement_rate = engaged / max(pv, 1)
        gsc_ctr = data.get("gsc_ctr", 0)
        duration = data.get("avg_duration", 0)

        # 総合スコア: PVで底上げ、エンゲージメントとCTRで加点
        score = (
            pv * 10
            + engagement_rate * 50
            + gsc_ctr * 30
            + min(duration / 60, 5) * 10  # 最大5分まで加点
        )
        data["performance_score"] = round(score, 1)

    # 上位記事を抽出
    top_pages = sorted(
        page_data.values(),
        key=lambda x: x["performance_score"],
        reverse=True,
    )[:10]

    # パターン分析
    patterns: list[dict] = []
    title_keywords: dict[str, int] = defaultdict(int)
    category_scores: dict[str, list[float]] = defaultdict(list)

    for page in top_pages:
        slug = page["path"].strip("/").split("/")[-1]
        if not slug:
            continue

        # スラッグからカテゴリ推定
        category = _infer_category(slug)
        category_scores[category].append(page["performance_score"])

        # キーワード抽出
        parts = slug.replace("-", " ").split()
        for part in parts:
            if len(part) >= 3 and not part.isdigit():
                title_keywords[part] += 1

        patterns.append({
            "slug": slug,
            "score": page["performance_score"],
            "sessions": page.get("sessions", 0),
            "engagement_rate": round(
                page.get("engaged_sessions", 0)
                / max(page.get("sessions", 1), 1),
                3,
            ),
            "gsc_ctr": round(page.get("gsc_ctr", 0), 4),
            "avg_duration_sec": round(page.get("avg_duration", 0), 1),
            "inferred_category": category,
        })

    # カテゴリ別の平均スコア
    category_summary = {
        cat: {
            "avg_score": round(sum(scores) / len(scores), 1),
            "count": len(scores),
        }
        for cat, scores in category_scores.items()
    }

    # 頻出キーワード上位
    top_keywords = sorted(
        title_keywords.items(), key=lambda x: x[1], reverse=True
    )[:15]

    # 記事タイプ別のCVデザイン情報
    cv_design = config.get("article_type_cv_design", {})
    winning_article_type = _identify_winning_type(patterns, cv_design)

    result = {
        "status": "ok",
        "analysis_date": today_str(),
        "top_performers": patterns,
        "category_performance": category_summary,
        "frequent_keywords": [
            {"keyword": kw, "frequency": freq} for kw, freq in top_keywords
        ],
        "recommended_article_type": winning_article_type,
        "insights": _generate_insights(patterns, category_summary, cv_design),
    }

    logger.info("勝ちパターン分析完了: 上位%d記事を解析", len(patterns))
    return result


def _infer_category(slug: str) -> str:
    """スラッグからカテゴリを推定"""
    slug_lower = slug.lower()
    category_keywords = {
        "kpop_news": ["news", "comeback", "debut", "release"],
        "kpop_events": ["event", "concert", "tour", "live", "festival", "mama"],
        "kpop_guide": ["guide", "complete", "hub", "beginner", "how"],
        "kpop_analysis": ["analysis", "review", "golden", "ranking"],
        "kpop_goods": ["goods", "album", "merch"],
        "kpop_drama": ["drama", "cast", "character", "hunters", "demon"],
        "beauty_cosme": ["cosme", "beauty", "skincare", "fashion", "brand"],
        "travel": ["travel", "food", "map", "hongdae"],
    }
    for category, keywords in category_keywords.items():
        for kw in keywords:
            if kw in slug_lower:
                return category
    return "general"


def _identify_winning_type(
    patterns: list[dict], cv_design: dict
) -> dict:
    """上位記事のパターンから推奨記事タイプを判定"""
    if not patterns:
        return {"type": "unknown", "reason": "データ不足"}

    avg_duration = sum(p["avg_duration_sec"] for p in patterns) / len(patterns)
    avg_engagement = sum(p["engagement_rate"] for p in patterns) / len(patterns)

    # 長時間滞在 + 高エンゲージメント = asset型（エバーグリーン）
    if avg_duration > 30 and avg_engagement > 0.1:
        return {
            "type": "asset",
            "reason": (
                f"上位記事は平均滞在{avg_duration:.0f}秒・エンゲージメント率{avg_engagement:.1%}。"
                "エバーグリーン型コンテンツが効果的です"
            ),
            "cv_config": cv_design.get("asset", {}),
        }
    # 高PVだが短時間 = flow型（速報・トレンド）
    elif avg_duration < 15:
        return {
            "type": "flow",
            "reason": (
                f"上位記事は速読型（平均{avg_duration:.0f}秒）。"
                "速報・トレンド記事の投入量を増やしてください"
            ),
            "cv_config": cv_design.get("flow", {}),
        }
    # バランス型
    else:
        return {
            "type": "mixed",
            "reason": (
                f"混合型（平均滞在{avg_duration:.0f}秒）。"
                "asset型とflow型をバランスよく配分してください"
            ),
        }


def _generate_insights(
    patterns: list[dict],
    category_summary: dict,
    cv_design: dict,
) -> list[str]:
    """分析結果から実行可能なインサイトを生成"""
    insights: list[str] = []

    if not patterns:
        return ["データ不足のため、インサイトを生成できませんでした"]

    # カテゴリ集中度
    if category_summary:
        best_cat = max(category_summary.items(), key=lambda x: x[1]["avg_score"])
        insights.append(
            f"最もパフォーマンスが高いカテゴリ: {best_cat[0]} "
            f"（平均スコア{best_cat[1]['avg_score']}、記事数{best_cat[1]['count']}）"
        )

    # エンゲージメント分析
    high_engage = [p for p in patterns if p["engagement_rate"] > 0.1]
    if high_engage:
        slugs = ", ".join(p["slug"][:30] for p in high_engage[:3])
        insights.append(
            f"高エンゲージメント記事（10%超）: {len(high_engage)}件 — {slugs}"
        )

    # GSC CTR分析
    high_ctr = [p for p in patterns if p["gsc_ctr"] > 0.1]
    if high_ctr:
        insights.append(
            f"GSC CTR 10%超の記事: {len(high_ctr)}件 — "
            "これらのタイトル・メタ記述のパターンを他記事に適用してください"
        )

    # revenue型記事の推奨
    revenue_design = cv_design.get("revenue", {})
    if revenue_design:
        expected_rev = revenue_design.get("expected_revenue_per_pv", 0)
        insights.append(
            f"収益特化記事（revenue型）の想定PV単価: {expected_rev}円。"
            "上位カテゴリでrevenue型記事の作成を検討してください"
        )

    return insights


# ═════════════════════════════════════════════════════════════
# 4. Weekly Revenue Report (Discord)
# ═════════════════════════════════════════════════════════════

def weekly_revenue_report(config: dict, dry_run: bool = False) -> dict:
    """
    週次収益レポートを生成し、Discord の sales_monetization チャネルに送信。
    """
    logger.info("=== Weekly Revenue Report ===")
    records = load_jsonl(REVENUE_DAILY_PATH)

    # 直近7日分を抽出
    records.sort(key=lambda r: r.get("date", ""))
    week_records = records[-7:]

    if not week_records:
        msg = "収益データがありません。レポート生成をスキップします"
        logger.warning(msg)
        return {"status": "no_data", "message": msg}

    # 集計
    total_adsense = sum(r.get("adsense_revenue", 0) for r in week_records)
    total_affiliate = sum(r.get("affiliate_revenue", 0) for r in week_records)
    total_revenue = total_adsense + total_affiliate
    total_pv = sum(r.get("total_pv", 0) for r in week_records)
    avg_daily = total_revenue / max(len(week_records), 1)
    avg_rpm = (
        sum(r.get("adsense_rpm", 0) for r in week_records) / len(week_records)
        if week_records else 0
    )

    # 目標との比較
    targets = config.get("daily_revenue_targets", {})
    target_status = []
    for phase, target_jpy in sorted(targets.items(), key=lambda x: x[1]):
        achievement = (avg_daily / target_jpy * 100) if target_jpy > 0 else 0
        status_icon = "o" if achievement >= 100 else "x"
        target_status.append(
            f"  [{status_icon}] {phase}: {target_jpy:,}円/日 "
            f"(達成率 {achievement:.0f}%)"
        )

    date_range = (
        f"{week_records[0].get('date', '?')} ~ {week_records[-1].get('date', '?')}"
    )

    # レポート本文
    report_lines = [
        f"**K-POP AI会社 週次収益レポート**",
        f"期間: {date_range} ({len(week_records)}日間)",
        "",
        "**--- 収益サマリー ---**",
        f"  AdSense収益:     {total_adsense:,.0f}円",
        f"  アフィリエイト収益: {total_affiliate:,.0f}円",
        f"  合計収益:         {total_revenue:,.0f}円",
        f"  日次平均:         {avg_daily:,.0f}円/日",
        f"  平均RPM:          {avg_rpm:,.0f}円",
        f"  総PV:             {total_pv:,}",
        "",
        "**--- 目標達成状況 ---**",
    ]
    report_lines.extend(target_status)

    # 日次推移
    report_lines.append("")
    report_lines.append("**--- 日次推移 ---**")
    for r in week_records:
        rev = r.get("adsense_revenue", 0) + r.get("affiliate_revenue", 0)
        pv = r.get("total_pv", 0)
        report_lines.append(f"  {r.get('date', '?')}: {rev:>6,.0f}円 / {pv:>5,}PV")

    report_body = "\n".join(report_lines)

    # Discord送信
    send_result = "skipped"
    if not dry_run:
        webhook_url = get_discord_webhook("sales_monetization")
        if webhook_url:
            send_result = _send_to_discord(
                webhook_url,
                title="Weekly Revenue Report",
                body=report_body,
                color=0x2ECC71,  # 緑
            )
        else:
            send_result = "webhook_not_set"
            logger.warning(
                "sales_monetization Webhook未設定。レポートはログのみに記録します"
            )
    else:
        send_result = "dry_run"
        print("\n[DRY-RUN] === Weekly Revenue Report ===")
        print(report_body)

    result = {
        "status": "ok",
        "date_range": date_range,
        "total_revenue_jpy": total_revenue,
        "total_adsense_jpy": total_adsense,
        "total_affiliate_jpy": total_affiliate,
        "avg_daily_jpy": round(avg_daily, 1),
        "avg_rpm": round(avg_rpm, 1),
        "total_pv": total_pv,
        "days": len(week_records),
        "discord_send_result": send_result,
    }

    logger.info(
        "週次レポート: 合計 %s円, 日次平均 %s円/日, PV %s, Discord=%s",
        total_revenue, round(avg_daily), total_pv, send_result,
    )
    return result


def _send_to_discord(
    webhook_url: str, title: str, body: str, color: int
) -> str:
    """
    Discord webhook にメッセージを送信する（urllib のみ使用）。
    戻り値: "sent" | エラー文字列
    """
    now_jst = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")

    # body を Discord embed の制限（4096文字）内に収める
    if len(body) > 3900:
        body = body[:3900] + "\n...(省略)"

    payload = {
        "username": "K-POP AI 収益レポート",
        "embeds": [{
            "title": title,
            "description": body,
            "color": color,
            "footer": {
                "text": f"revenue_optimizer v1.0 | {now_jst}",
            },
        }],
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 204):
                logger.info("Discord送信成功")
                return "sent"
            return f"http_{resp.status}"
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:120]
        except Exception:
            pass
        logger.error("Discord送信失敗: HTTP %s — %s", e.code, detail)
        return f"http_{e.code}"
    except Exception as e:
        logger.error("Discord送信失敗: %s", e)
        return f"network_error: {e}"


# ═════════════════════════════════════════════════════════════
# 5. Category ROI Analyzer
# ═════════════════════════════════════════════════════════════

def category_roi_analyzer(config: dict) -> dict:
    """
    カテゴリ別の 収益/記事数（ROI）を算出。
    コンテンツ戦略のリソース配分を支援する。
    """
    logger.info("=== Category ROI Analyzer ===")
    metrics = load_json(METRICS_YESTERDAY_PATH)
    if not metrics:
        return {"status": "no_metrics", "categories": {}}

    gsc_pages = metrics.get("gsc", {}).get("top_pages", [])
    ga4_pages = metrics.get("ga4", {}).get("top_landing_pages", [])
    adsense = metrics.get("adsense", {})

    # 全体RPM
    overall_rpm = _safe_float(adsense.get("PAGE_VIEWS_RPM", "0"))

    # カテゴリ別にページを集約
    category_data: dict[str, dict] = defaultdict(
        lambda: {
            "article_count": 0,
            "total_sessions": 0,
            "total_pageviews": 0,
            "total_clicks": 0,
            "total_impressions": 0,
            "total_engaged": 0,
            "slugs": [],
        }
    )

    # GA4データ
    for p in ga4_pages:
        path = p.get("page", "")
        if not path or path in ("(not set)", "/"):
            continue
        slug = path.strip("/").split("/")[-1]
        category = _infer_category(slug)
        cat = category_data[category]
        cat["article_count"] += 1
        cat["total_sessions"] += _safe_int(p.get("sessions", 0))
        cat["total_pageviews"] += _safe_int(p.get("pageviews", 0))
        cat["total_engaged"] += _safe_int(p.get("engaged_sessions", 0))
        cat["slugs"].append(slug)

    # GSCデータで補完
    for p in gsc_pages:
        url = p.get("page", "")
        path = "/" + url.split("/", 3)[-1] if "://" in url else url
        slug = path.strip("/").split("/")[-1]
        if not slug:
            continue
        category = _infer_category(slug)
        cat = category_data[category]
        cat["total_clicks"] += p.get("clicks", 0)
        cat["total_impressions"] += p.get("impressions", 0)

    # ROI算出: RPMベースでカテゴリ別推定収益
    cv_design = config.get("article_type_cv_design", {})
    categories_result: dict[str, dict] = {}

    for category, data in category_data.items():
        pv = data["total_pageviews"] or data["total_sessions"]
        estimated_revenue = pv * overall_rpm / 1000  # RPMは1000PVあたり

        engagement_rate = (
            data["total_engaged"] / max(data["total_sessions"], 1)
        )
        gsc_ctr = (
            data["total_clicks"] / max(data["total_impressions"], 1)
        )
        revenue_per_article = (
            estimated_revenue / max(data["article_count"], 1)
        )

        # 推奨記事タイプ
        if engagement_rate > 0.15 and gsc_ctr > 0.05:
            recommended_type = "revenue"
        elif engagement_rate > 0.08:
            recommended_type = "asset"
        else:
            recommended_type = "flow"

        categories_result[category] = {
            "article_count": data["article_count"],
            "total_pv": pv,
            "estimated_revenue_jpy": round(estimated_revenue, 1),
            "revenue_per_article_jpy": round(revenue_per_article, 1),
            "engagement_rate": round(engagement_rate, 3),
            "gsc_ctr": round(gsc_ctr, 4),
            "gsc_impressions": data["total_impressions"],
            "recommended_article_type": recommended_type,
            "cv_config": cv_design.get(recommended_type, {}),
            "sample_slugs": data["slugs"][:3],
        }

    # ROI順にソート
    sorted_categories = dict(
        sorted(
            categories_result.items(),
            key=lambda x: x[1]["revenue_per_article_jpy"],
            reverse=True,
        )
    )

    # 戦略提案
    strategy: list[str] = []
    if sorted_categories:
        top_cat = next(iter(sorted_categories))
        top_data = sorted_categories[top_cat]
        strategy.append(
            f"最高ROIカテゴリ: {top_cat} "
            f"({top_data['revenue_per_article_jpy']:.0f}円/記事) — "
            "このカテゴリの記事を優先的に増やしてください"
        )

        low_roi_cats = [
            cat for cat, d in sorted_categories.items()
            if d["revenue_per_article_jpy"] < 1 and d["article_count"] >= 2
        ]
        if low_roi_cats:
            strategy.append(
                f"低ROIカテゴリ: {', '.join(low_roi_cats)} — "
                "投稿頻度を減らすか、記事タイプをrevenue型に変更してください"
            )

    logger.info("カテゴリROI分析完了: %dカテゴリ", len(sorted_categories))
    return {
        "status": "ok",
        "analysis_date": today_str(),
        "overall_rpm": overall_rpm,
        "categories": sorted_categories,
        "strategy": strategy,
    }


# ═════════════════════════════════════════════════════════════
# メイン実行
# ═════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="K-POP AI会社 収益最適化エンジン v1.0"
    )
    parser.add_argument(
        "--analyze", action="store_true",
        help="全分析を実行（AdSense監視 + アフィリエイト最適化 + カテゴリROI）",
    )
    parser.add_argument(
        "--optimize", action="store_true",
        help="アフィリエイトCTR最適化提案を生成",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="週次収益レポートをDiscordに送信",
    )
    parser.add_argument(
        "--learn", action="store_true",
        help="勝ちパターン学習を実行",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="結果表示のみ（書き込み・送信しない）",
    )
    args = parser.parse_args()

    # 引数なしの場合はヘルプを表示
    if not any([args.analyze, args.optimize, args.report, args.learn]):
        parser.print_help()
        sys.exit(0)

    config = load_revenue_config()
    dry_run = args.dry_run

    # 最新のメトリクスをrevenue_daily.jsonlに取り込み
    if not dry_run:
        ensure_today_revenue_record()

    output: dict[str, Any] = {
        "generated_at": datetime.now(JST).isoformat(),
        "dry_run": dry_run,
    }

    if args.analyze:
        logger.info("全分析モードを実行します")
        output["adsense_monitor"] = adsense_revenue_monitor(config)
        output["affiliate_optimizer"] = affiliate_ctr_optimizer(config)
        output["category_roi"] = category_roi_analyzer(config)

    if args.optimize:
        if "affiliate_optimizer" not in output:
            output["affiliate_optimizer"] = affiliate_ctr_optimizer(config)

    if args.learn:
        output["winning_patterns"] = winning_pattern_learner(config)

    if args.report:
        output["weekly_report"] = weekly_revenue_report(config, dry_run=dry_run)

    # 結果保存
    save_json(OPTIMIZATION_OUTPUT_PATH, output, dry_run=dry_run)

    # stdout にサマリー出力（他スクリプトからの読み取り用）
    summary = {
        "revenue_optimizer": "v1.0",
        "dry_run": dry_run,
        "sections": list(output.keys()),
    }
    if "adsense_monitor" in output:
        mon = output["adsense_monitor"]
        summary["adsense_status"] = mon.get("status", "unknown")
        summary["adsense_change_pct"] = mon.get("change_pct", 0)
    if "affiliate_optimizer" in output:
        opt = output["affiliate_optimizer"]
        summary["affiliate_suggestions"] = len(opt.get("suggestions", []))
    if "category_roi" in output:
        roi = output["category_roi"]
        summary["categories_analyzed"] = len(roi.get("categories", {}))
    if "weekly_report" in output:
        rep = output["weekly_report"]
        summary["report_discord"] = rep.get("discord_send_result", "n/a")
    if "winning_patterns" in output:
        wp = output["winning_patterns"]
        summary["patterns_found"] = len(wp.get("top_performers", []))

    print(json.dumps(summary, ensure_ascii=False))
    logger.info("完了: %s", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
