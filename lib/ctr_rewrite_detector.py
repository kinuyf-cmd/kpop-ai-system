#!/usr/bin/env python3
"""
CTRリライト候補検出スクリプト (ctr_rewrite_detector.py)

条件:
  - 公開後24h経過
  - Xインプレッション < 500 または X_SCORE < 60
  - サムネスコア 60〜75（含む）

出力: logs/rewrite_targets.json
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.parent
LOGS = SCRIPT_DIR / "logs"
JST = timezone(timedelta(hours=9))


def _now_jst():
    return datetime.now(JST)


def _parse_dt(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(s[:19], fmt[:len(fmt)])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)
            return dt
        except Exception:
            continue
    return None


def _load_jsonl(path):
    recs = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        recs.append(json.loads(line))
                    except Exception:
                        pass
    except FileNotFoundError:
        pass
    return recs


def get_thumbnail_score(title: str) -> int:
    """score_thumbnail_text.pyを使ってスコアを取得"""
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable,
             str(SCRIPT_DIR / "google_metrics" / "score_thumbnail_text.py"),
             title],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            data = json.loads(result.stdout.strip())
            return data.get("score", 0)
    except Exception:
        pass
    return 0


def detect_rewrite_candidates():
    pipeline_log = LOGS / "pipeline.jsonl"
    x_results_log = LOGS / "x_post_results.jsonl"

    pipeline_recs = _load_jsonl(pipeline_log)
    x_recs = _load_jsonl(x_results_log)

    # X投稿結果をpost_idでインデックス化
    x_by_post = {}
    for r in x_recs:
        pid = str(r.get("post_id", ""))
        if pid:
            x_by_post[pid] = r

    now = _now_jst()
    cutoff = now - timedelta(hours=24)

    candidates = []

    for rec in pipeline_recs:
        pid = str(rec.get("post_id", rec.get("id", "")))
        if not pid:
            continue

        published_str = rec.get("published_at", rec.get("posted_at", ""))
        published_dt = _parse_dt(published_str)
        if not published_dt:
            continue

        # 24時間経過チェック
        if published_dt > cutoff:
            continue

        # X投稿データ取得
        x_data = x_by_post.get(pid)
        if x_data is None:
            continue  # X投稿データがなければスキップ

        x_impressions = x_data.get("impressions", x_data.get("x_impressions", 9999))
        x_score = x_data.get("x_score", x_data.get("score", 100))

        # Xスコア/インプレッション条件
        x_low = (x_impressions < 500) or (x_score < 60)
        if not x_low:
            continue

        # サムネスコア取得
        title = rec.get("title", rec.get("post_title", ""))
        if not title:
            continue

        thumbnail_score = get_thumbnail_score(title)

        # サムネスコア 60〜75 条件
        if not (60 <= thumbnail_score <= 75):
            continue

        url = rec.get("url", rec.get("post_url", ""))
        reason = f"サムネスコア{thumbnail_score}・Xスコア{x_score}"

        candidates.append({
            "post_id": int(pid) if pid.isdigit() else pid,
            "title": title,
            "url": url,
            "reason": reason,
            "thumbnail_score": thumbnail_score,
            "x_score": x_score,
            "detected_at": now.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        })

    return candidates


def main():
    candidates = detect_rewrite_candidates()

    output_path = LOGS / "rewrite_targets.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "status": "ok",
        "candidates": len(candidates),
        "output": str(output_path),
        "items": candidates,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
