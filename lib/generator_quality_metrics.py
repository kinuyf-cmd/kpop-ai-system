#!/usr/bin/env python3
"""generator_quality_metrics.py — generator/source 別の月次品質メトリクス

目的: GENERATOR_DEPRECATION_PLAN.md Phase 4 で deprecated にした
seo_longtail / stock_topic と同じ silent rot を未然検出する。

計測対象は auto_directives.json の focus_themes に注入する全 source:
  - search_driven_expansion
  - pv_kpi_winner_expansion_YYYYMMDD
  - gsc_unmet_demand_YYYYMMDD
  - breaking_followup
  - youtube_show_monitor / music_show_monitor / tiktok_trend_collector
  - winning_pattern / trend_predictor / auto_improve / seo_longtail_generator (廃止済)

silent rot 判定:
  - 該当 source の最終 added_date が 30 日以上前
  - かつ expires_at が全て過去 (＝新規投入が止まっている)

出力: logs/generator_quality_monthly.json
cron: 月初 06:00 JST 推奨
"""
from __future__ import annotations
import json
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
AUTO_DIRECTIVES = BASE / "config" / "auto_directives.json"
OUT = BASE / "logs" / "generator_quality_monthly.json"
JST = timezone(timedelta(hours=9))

SILENT_ROT_DAYS = 30
DATE_SUFFIX = re.compile(r"_(\d{8})$")


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            return None


def _normalize_source(raw: str) -> tuple[str, str | None]:
    """source 名末尾の _YYYYMMDD を分離。返り値は (正規名, 日付suffix or None)"""
    m = DATE_SUFFIX.search(raw or "")
    if not m:
        return raw or "unknown", None
    return raw[: m.start()], m.group(1)


def collect_focus_theme_metrics(today: datetime) -> dict:
    if not AUTO_DIRECTIVES.exists():
        return {"error": "auto_directives.json not found"}
    data = json.loads(AUTO_DIRECTIVES.read_text())
    themes = data.get("focus_themes", [])

    today_d = today.date()
    by_source: dict[str, dict] = defaultdict(lambda: {
        "count": 0,
        "newest_signal": None,
        "oldest_signal": None,
        "expired_count": 0,
        "active_count": 0,
    })

    stale_total = 0
    for t in themes:
        src_raw = t.get("source") or "unknown"
        src, suffix = _normalize_source(src_raw)

        added = _parse_date(t.get("added_date")) or _parse_date(suffix and f"{suffix[:4]}-{suffix[4:6]}-{suffix[6:8]}")
        expires = _parse_date(t.get("expires_at"))

        s = by_source[src]
        s["count"] += 1

        signal = added or expires
        if signal:
            sd = signal.date()
            if s["newest_signal"] is None or sd > s["newest_signal"]:
                s["newest_signal"] = sd
            if s["oldest_signal"] is None or sd < s["oldest_signal"]:
                s["oldest_signal"] = sd

        if expires and expires.date() < today_d:
            s["expired_count"] += 1
            stale_total += 1
        else:
            s["active_count"] += 1

    silent_rot = []
    threshold = today_d - timedelta(days=SILENT_ROT_DAYS)
    for src, s in by_source.items():
        latest = s["newest_signal"]
        s["newest_signal"] = latest.isoformat() if latest else None
        s["oldest_signal"] = s["oldest_signal"].isoformat() if s["oldest_signal"] else None
        if latest is None or latest < threshold:
            if s["active_count"] == 0:
                silent_rot.append(src)
                s["silent_rot"] = True
            else:
                s["silent_rot"] = False
        else:
            s["silent_rot"] = False

    return {
        "total_focus_themes": len(themes),
        "active_themes": len(themes) - stale_total,
        "stale_themes": stale_total,
        "by_source": dict(sorted(by_source.items(), key=lambda x: -x[1]["count"])),
        "silent_rot_sources": silent_rot,
    }


def main():
    now = datetime.now(JST).replace(tzinfo=None)
    metrics = collect_focus_theme_metrics(now)
    report = {
        "generated_at": datetime.now(JST).isoformat(),
        "auto_directives_health": metrics,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    health = metrics if "error" not in metrics else {}
    print(f"[generator_quality] focus_themes={health.get('total_focus_themes', '?')} "
          f"active={health.get('active_themes', '?')} stale={health.get('stale_themes', '?')}")
    rot = health.get("silent_rot_sources", [])
    if rot:
        print(f"[generator_quality] ⚠ silent rot detected: {', '.join(rot)}")
    else:
        print(f"[generator_quality] ✅ no silent rot")
    print(f"[generator_quality] report: {OUT}")


if __name__ == "__main__":
    main()
