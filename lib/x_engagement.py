#!/usr/bin/env python3
"""X投稿のエンゲージ率を算出する。

既存メモリ「Phase3ゲートはimpでなくエンゲージ率」の通り、判定の主指標は
エンゲージ率。x_phase2_report は impression しか見ていなかったため、
ここに算出を切り出して両方を並べて追えるようにする(2026-08-20)。

設計上の要点:
  imp=0 の投稿は「率が定義できない」ので None を返し、集計の母数からも除く。
  0.0% として混ぜると、まだ配信されていない投稿が平均を不当に押し下げる。
"""
from __future__ import annotations

_REACTION_KEYS = ("like_count", "reply_count", "retweet_count", "quote_count")


def engagement_rate(metrics: dict) -> float | None:
    """1投稿のエンゲージ率(%)を返す。imp が 0/欠損なら None。"""
    m = metrics or {}
    try:
        imp = int(m.get("impression_count", 0) or 0)
    except (TypeError, ValueError):
        return None
    if imp <= 0:
        return None
    total = 0
    for k in _REACTION_KEYS:
        try:
            total += int(m.get(k, 0) or 0)
        except (TypeError, ValueError):
            continue
    return round(total / imp * 100, 2)


def summarize_engagement(data: dict[str, dict]) -> dict:
    """複数投稿のエンゲージ率をまとめる。

    Returns:
      {"n", "avg_engagement_rate", "median_engagement_rate",
       "max_engagement_rate", "min_engagement_rate", "skipped"}
      n は率が定義できた投稿数。skipped は imp=0 等で除外した数。
    """
    rates = []
    skipped = 0
    for m in (data or {}).values():
        r = engagement_rate(m)
        if r is None:
            skipped += 1
            continue
        rates.append(r)
    if not rates:
        return {"n": 0, "avg_engagement_rate": None, "median_engagement_rate": None,
                "max_engagement_rate": None, "min_engagement_rate": None,
                "skipped": skipped}
    rates.sort()
    mid = len(rates) // 2
    med = rates[mid] if len(rates) % 2 else round((rates[mid - 1] + rates[mid]) / 2, 2)
    return {
        "n": len(rates),
        "avg_engagement_rate": round(sum(rates) / len(rates), 2),
        "median_engagement_rate": med,
        "max_engagement_rate": rates[-1],
        "min_engagement_rate": rates[0],
        "skipped": skipped,
    }
