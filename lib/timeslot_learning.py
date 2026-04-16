#!/usr/bin/env python3
"""
timeslot_learning.py — 投稿時間帯×パフォーマンスの相関分析

データ: logs/initial_performance.jsonl（post_date + initial_24h_pv/search_clicks/search_impressions）
出力:
  - logs/timeslot_learning.log: 時間帯別 PV / CTR / 投稿数の集計
  - logs/timeslot_ranking.json: 時間帯×ジャンルのCTR順位表（determine_content()が将来参照可能）

用途:
  - 15時ライフスタイル枠のPVが伸びないなら18時ファッション枠と入れ替え検討
  - ゴールデンタイム(7/8/17-19時)の真の強さを数値で確認
  - kpop_master_scheduler.sh の determine_content() が近い将来この結果を参照
"""
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SRC = BASE / "logs" / "initial_performance.jsonl"
KPI = BASE / "logs" / "kpi_posts.jsonl"
LOG_OUT = BASE / "logs" / "timeslot_learning.log"
RANK_OUT = BASE / "logs" / "timeslot_ranking.json"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
SINCE = NOW - timedelta(days=30)  # 30日分で十分なサンプル


def _load_kpi_post_times() -> dict:
    """kpi_posts.jsonl から post_id → 投稿時刻(JST) のmapを作る。
    初動計測にはpost_date（日付のみ）しかないため、ここで時刻を引く。"""
    result = {}
    if not KPI.exists():
        return result
    for line in KPI.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        pid = str(d.get("post_id") or "")
        ts_str = d.get("timestamp") or ""
        if not pid or not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=JST)
        # 同じpost_idが複数回記録されていれば最初の"event":"post_success"を優先
        if pid not in result:
            result[pid] = ts
    return result


def load_entries():
    if not SRC.exists():
        return []
    post_times = _load_kpi_post_times()
    out = []
    for line in SRC.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        pid = str(d.get("post_id") or "")
        # 投稿時刻の優先順位: kpi_posts → post_date（日付のみ・時刻不明） → skip
        ts = post_times.get(pid)
        if ts is None:
            pd = d.get("post_date") or d.get("measurement_date")
            if not pd:
                continue
            try:
                if "T" in pd:
                    ts = datetime.fromisoformat(pd.replace("Z", "+00:00"))
                else:
                    # 時刻不明は学習対象外（全て00時に集まって歪む）
                    continue
            except Exception:
                continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=JST)
        if ts < SINCE:
            continue
        d["_ts"] = ts
        out.append(d)
    return out


def main():
    entries = load_entries()
    if not entries:
        msg = f"[{NOW.isoformat()}] initial_performance.jsonl に過去30日データなし"
        LOG_OUT.parent.mkdir(parents=True, exist_ok=True)
        with LOG_OUT.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
        print(msg)
        RANK_OUT.write_text(json.dumps({"generated_at": NOW.isoformat(), "note": "insufficient_data"},
                                        ensure_ascii=False, indent=2), encoding="utf-8")
        return

    # 時間帯×pipeline別に集計
    slot = defaultdict(lambda: {"count": 0, "pv_sum": 0, "click_sum": 0, "imp_sum": 0})
    for e in entries:
        hour = e["_ts"].astimezone(JST).hour
        pipeline = e.get("pipeline", "unknown") or "unknown"
        key = (hour, pipeline)
        slot[key]["count"] += 1
        slot[key]["pv_sum"] += int(e.get("initial_24h_pv", 0) or 0)
        slot[key]["click_sum"] += int(e.get("initial_24h_search_clicks", 0) or 0)
        slot[key]["imp_sum"] += int(e.get("initial_24h_search_impressions", 0) or 0)

    rows = []
    for (hour, pipeline), v in sorted(slot.items()):
        if v["count"] == 0:
            continue
        avg_pv = v["pv_sum"] / v["count"]
        ctr = (v["click_sum"] / v["imp_sum"]) if v["imp_sum"] > 0 else 0.0
        rows.append({
            "hour": hour,
            "pipeline": pipeline,
            "posts": v["count"],
            "avg_pv": round(avg_pv, 2),
            "total_clicks": v["click_sum"],
            "total_impressions": v["imp_sum"],
            "ctr": round(ctr, 4),
        })

    rows.sort(key=lambda r: -r["avg_pv"])

    lines = [f"[timeslot_learning] 期間 {SINCE.date()}〜{NOW.date()} / 総投稿: {len(entries)}件"]
    lines.append(f"  (時,pipeline) → 投稿数/平均PV/合計クリック/合計表示/CTR")
    for r in rows[:15]:
        lines.append(
            f"    {r['hour']:02d}時 [{r['pipeline']}] "
            f"{r['posts']}投稿 avg_pv={r['avg_pv']} clicks={r['total_clicks']} "
            f"imp={r['total_impressions']} ctr={r['ctr']*100:.2f}%"
        )

    # 時間帯単独（pipeline合算）の順位
    hour_agg = defaultdict(lambda: {"posts": 0, "pv": 0, "clicks": 0, "imp": 0})
    for r in rows:
        hour_agg[r["hour"]]["posts"] += r["posts"]
        hour_agg[r["hour"]]["pv"] += r["avg_pv"] * r["posts"]
        hour_agg[r["hour"]]["clicks"] += r["total_clicks"]
        hour_agg[r["hour"]]["imp"] += r["total_impressions"]
    hour_ranking = sorted([
        {
            "hour": h,
            "posts": v["posts"],
            "avg_pv": round(v["pv"] / max(1, v["posts"]), 2),
            "ctr": round(v["clicks"] / max(1, v["imp"]), 4),
        }
        for h, v in hour_agg.items()
    ], key=lambda x: -x["avg_pv"])

    lines.append("")
    lines.append("  時間帯別 平均PV ランキング:")
    for r in hour_ranking[:10]:
        lines.append(f"    {r['hour']:02d}時: avg_pv={r['avg_pv']} ctr={r['ctr']*100:.2f}% ({r['posts']}投稿)")

    out = "\n".join(lines)
    LOG_OUT.parent.mkdir(parents=True, exist_ok=True)
    with LOG_OUT.open("a", encoding="utf-8") as f:
        f.write(f"[{NOW.isoformat()}]\n{out}\n")

    RANK_OUT.write_text(json.dumps({
        "generated_at": NOW.isoformat(),
        "period_days": 30,
        "total_samples": len(entries),
        "slot_pipeline": rows,
        "hour_ranking": hour_ranking,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
