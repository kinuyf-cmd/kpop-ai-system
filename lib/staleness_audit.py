#!/usr/bin/env python3
"""staleness_audit.py — 本番に出ている「定期更新されるはずの表示」の鮮度監査

背景 (2026-08-23):
  トップの MUSIC CHART が Playwright ブラウザ消失で8日間止まっていた。
  cron は登録済みで、スクリプトは非破壊フォールバック(失敗時は既存維持)の
  ため exit 0。エラー通知も出ず、古い順位を出し続けていた。

  cron の有無は「動いている証拠」にならない。本番の実データが「いつのものか」
  を測り、想定更新間隔を超えたら鳴らす。取得できなかったものを ok 扱いしない
  ことが肝(それが今回の事故の本質)。

Usage:
  python3 lib/staleness_audit.py            # 人が読む形式
  python3 lib/staleness_audit.py --json
  python3 lib/staleness_audit.py --notify   # stale/unknown があれば Discord 通知
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

SITE = "https://www.kpopjournal.tokyo"
WP_RO = "/usr/local/sbin/kpop/kpop-wp-ro"
UA = {"User-Agent": "KpopJournal-Bot/2.0"}


def evaluate(name: str, age_days, max_age_days: float) -> dict:
    """鮮度を判定する。age_days が None(取得不能)は ok にしない。"""
    if age_days is None:
        return {"name": name, "ok": False, "level": "unknown", "age_days": None,
                "message": f"{name}: 更新時刻を取得できなかった(要確認)"}
    if age_days <= max_age_days:
        return {"name": name, "ok": True, "level": "ok", "age_days": age_days,
                "message": f"{name}: {age_days:.1f}日前(閾値{max_age_days}日)"}
    return {"name": name, "ok": False, "level": "stale", "age_days": age_days,
            "message": f"{name}: {age_days:.1f}日前で停止の疑い(閾値{max_age_days}日)"}


def _db(sql: str) -> str:
    try:
        return subprocess.run(["sudo", "-n", WP_RO, "db", "query", sql],
                              capture_output=True, text=True, timeout=90).stdout
    except Exception:
        return ""


def _age_from_sql(sql: str):
    """SQL の1列目に DATETIME を返させ、経過日数を返す。取れなければ None。"""
    out = _db(sql).splitlines()
    if len(out) < 2:
        return None
    m = re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", out[1])
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(0).replace("T", " "), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return (datetime.now() - dt).total_seconds() / 86400


def probe_soompi_chart():
    """WP option の週タイトルでなく、取り込んだ JSON の更新時刻で測る。"""
    f = BASE / "data" / "soompi_chart_top10.json"
    if not f.exists():
        return None
    return (datetime.now().timestamp() - f.stat().st_mtime) / 86400


def probe_latest_post():
    return _age_from_sql(
        "SELECT post_date FROM wp_posts WHERE post_type='post' "
        "AND post_status='publish' ORDER BY post_date DESC LIMIT 1")


def probe_latest_popup():
    return _age_from_sql(
        "SELECT post_date FROM wp_posts WHERE post_type='post' "
        "AND post_status='publish' AND (post_title LIKE '%ポップアップ%' "
        "OR post_name LIKE 'popup-%') ORDER BY post_date DESC LIMIT 1")


def probe_future_event():
    """未来のイベントが登録されているか。0件なら「カレンダーが空」= 異常。"""
    out = _db("SELECT COUNT(*) FROM wp_posts p JOIN wp_postmeta m "
              "ON m.post_id=p.ID AND m.meta_key='_EventStartDate' "
              "WHERE p.post_type='tribe_events' AND p.post_status='publish' "
              "AND m.meta_value>=NOW()").splitlines()
    if len(out) < 2:
        return None
    try:
        return 0.0 if int(out[1].strip()) > 0 else 999.0
    except ValueError:
        return None


def probe_idol_wiki():
    return _age_from_sql(
        "SELECT post_modified FROM wp_posts WHERE post_type='idol_artist' "
        "AND post_status='publish' ORDER BY post_modified DESC LIMIT 1")


def probe_home_render():
    """本番トップが引けるか。引けなければ他の判定も信用できない。"""
    try:
        req = urllib.request.Request(SITE + "/", headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            return 0.0 if r.status == 200 and len(r.read()) > 10000 else 999.0
    except Exception:
        return None


# 2026-08-23: ルートパーティション100%で PHP-FPM が書き込めず本番が502になった。
# ディスクは静かに埋まり、埋まった瞬間にサイトが落ちる。90%で警告する。
DISK_WARN_PCT = 90


def _disk_used_pct():
    try:
        st = os.statvfs("/")
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        if not total:
            return None
        return round((total - free) / total * 100, 1)
    except Exception:
        return None


def evaluate_disk(used_pct=None) -> dict:
    """ディスク使用率を判定する。取得不能は ok にしない。"""
    if used_pct is None:
        return {"name": "ディスク空き", "ok": False, "level": "unknown",
                "age_days": None, "message": "ディスク使用率を取得できなかった"}
    if used_pct >= DISK_WARN_PCT:
        return {"name": "ディスク空き", "ok": False, "level": "stale",
                "age_days": used_pct,
                "message": f"ディスク使用率 {used_pct}% (警告{DISK_WARN_PCT}%)"
                           f" — 満杯になるとPHP-FPMが落ちて502になる"}
    return {"name": "ディスク空き", "ok": True, "level": "ok", "age_days": used_pct,
            "message": f"ディスク使用率 {used_pct}%"}


def probe_disk():
    """0.0=正常 / 999.0=逼迫。evaluate() の枠に合わせるための変換。"""
    p = _disk_used_pct()
    if p is None:
        return None
    return 0.0 if p < DISK_WARN_PCT else 999.0


CHECKS = [
    {"key": "soompi_chart", "label": "ミュージックチャート",
     # 週次更新なので「1週スキップ」で気づけるよう7.5日。2026-08-23の実事故は
     # 8日停止で、閾値9日だと見逃していた。
     "max_age_days": 7.5, "probe": probe_soompi_chart,
     "hint": "tools/chart/cron_update_soompi_chart.sh / Playwrightブラウザ消失が定番"},
    {"key": "latest_post", "label": "記事の公開",
     "max_age_days": 2, "probe": probe_latest_post,
     "hint": "pipeline/breaking_news_detector.py"},
    {"key": "popup_article", "label": "ポップアップ記事",
     "max_age_days": 10, "probe": probe_latest_popup,
     "hint": "popup_event_weekly.sh"},
    {"key": "future_event", "label": "イベントカレンダー(未来分)",
     "max_age_days": 1, "probe": probe_future_event,
     "hint": "未来イベント0件ならカレンダーが空。event収集を確認"},
    {"key": "idol_wiki", "label": "Idol Wiki 更新",
     "max_age_days": 14, "probe": probe_idol_wiki,
     "hint": "idol_wiki_release_daily.sh"},
    {"key": "disk_free", "label": "ディスク空き",
     "max_age_days": 1, "probe": probe_disk,
     "hint": "df -h / で確認。満杯だとPHP-FPMが書けず本番が502になる"},
    {"key": "home_render", "label": "本番トップの表示",
     "max_age_days": 1, "probe": probe_home_render,
     "hint": "200が返らない/極端に小さい"},
]


def run() -> list[dict]:
    out = []
    for c in CHECKS:
        try:
            age = c["probe"]()
        except Exception:
            age = None
        if c["key"] == "disk_free":
            r = evaluate_disk(_disk_used_pct())
        else:
            r = evaluate(c["label"], age, c["max_age_days"])
        r["key"] = c["key"]
        r["hint"] = c["hint"]
        out.append(r)
    return out


def notify(msg: str) -> None:
    try:
        hook = subprocess.run(
            [sys.executable, str(BASE / "lib" / "resolve_discord_webhook.py"),
             "publishing_log"], capture_output=True, text=True, timeout=30
        ).stdout.strip()
        if not hook:
            return
        data = json.dumps({"content": msg}).encode()
        req = urllib.request.Request(hook, data=data, headers={
            "Content-Type": "application/json", **UA})
        urllib.request.urlopen(req, timeout=20).read()
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--notify", action="store_true")
    a = ap.parse_args()

    res = run()
    bad = [r for r in res if not r["ok"]]

    if a.json:
        print(json.dumps({"checked": len(res), "bad": len(bad), "items": res},
                         ensure_ascii=False, indent=1))
    else:
        print("=== 表示鮮度の点検(cronの有無でなく本番データの新しさで判定) ===")
        for r in res:
            mark = {"ok": "✓", "stale": "✗", "unknown": "?"}[r["level"]]
            print(f"  {mark} {r['message']}")
            if not r["ok"]:
                print(f"      → {r['hint']}")
        print(f"\n  異常 {len(bad)}/{len(res)}件")

    if a.notify and bad:
        lines = "\n".join(f"・{r['message']}" for r in bad)
        notify(f"⚠️ 表示鮮度の点検で{len(bad)}件の異常\n{lines}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
