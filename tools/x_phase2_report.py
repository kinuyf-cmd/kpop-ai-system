#!/usr/bin/env python3
"""X Phase 2 移行可否の判定レポート(2026-08-12 Phase 1再開の検証用)。

Phase 1(cap=3・会話型text-only・URLゼロ)で積んだ投稿の実測impを集計し、
Phase 2(ARTICLE_HOURS復活+プロフィール誘導)へ進めるかを判定して Discord に通知する。

判定GO条件(全て満たす場合のみ):
  1. Phase 1再開時刻(X_PHASE1_START)以降のトップレベル投稿のみを対象
     ※停止期間中の残存impを混入させない。これを外すと8.4のような幻を掴む
  2. avg imp >= X_PHASE2_AVG (default 8.0) かつ median >= X_PHASE2_MEDIAN (default 6.0)
     ※中央値を併用するのは、1本の当たりで平均が持ち上がる誤判定を防ぐため
  3. n >= X_PHASE2_MIN_N (default 6) …24h以上経過した投稿数

判定は報告のみで、cron変更などの副作用は持たない(Phase 2移行はowner判断)。
結果は logs/x_phase2_report.jsonl に追記。

usage:
  python3 tools/x_phase2_report.py            # 集計してDiscord通知
  python3 tools/x_phase2_report.py --dry-run  # 通知せず標準出力のみ
"""
import json
import os
import statistics
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path("/home/aiuser/kpop-ai-system")
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "google_metrics"))

POSTS_LOG = BASE / "logs" / "x_posts.jsonl"
REPORT_LOG = BASE / "logs" / "x_phase2_report.jsonl"

# Phase 1 再開時刻(cron再開は 2026-08-12 12:17)
PHASE1_START = os.environ.get("X_PHASE1_START", "2026-08-12T12:00:00")
AVG_GATE = float(os.environ.get("X_PHASE2_AVG", "8.0"))
MEDIAN_GATE = float(os.environ.get("X_PHASE2_MEDIAN", "6.0"))
MIN_N = int(os.environ.get("X_PHASE2_MIN_N", "6"))
AGE_H = int(os.environ.get("X_PHASE2_AGE_H", "24"))
# バン期の崩壊水準(レポートの参照値)
BAN_ERA_AVG = 6.0


def _phase1_post_ids() -> list[tuple[str, str]]:
    """Phase 1再開以降・AGE_H以上経過・status ok のトップレベル投稿 (tweet_id, ts)。"""
    if not POSTS_LOG.exists():
        return []
    lo = datetime.fromisoformat(PHASE1_START)
    hi = datetime.now() - timedelta(hours=AGE_H)
    out = []
    for line in POSTS_LOG.read_text().splitlines():
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("status") != "ok" or not d.get("tweet_id"):
            continue
        if d.get("reply_to"):  # リプライのimpは親に含まれるため除外
            continue
        try:
            ts = datetime.fromisoformat(d["ts"])
        except (KeyError, ValueError):
            continue
        if lo <= ts <= hi:
            out.append((str(d["tweet_id"]), d["ts"]))
    return out


def _metrics(ids: list[str]) -> dict[str, dict]:
    from post_to_x import get_public_metrics

    merged = {}
    for i in range(0, len(ids), 100):
        merged.update(get_public_metrics(ids[i : i + 100]) or {})
    return merged


def _followers() -> int | None:
    """x_metrics.jsonl の最新スナップショットからフォロワー数を読む(API追加コールなし)。"""
    path = BASE / "logs" / "x_metrics.jsonl"
    if not path.exists():
        return None
    for line in reversed(path.read_text().splitlines()):
        try:
            return json.loads(line).get("account", {}).get("followers")
        except json.JSONDecodeError:
            continue
    return None


def _notify_discord(msg: str) -> None:
    try:
        from lib.resolve_discord_webhook import resolve

        url = resolve("urgent_errors")
        if not url:
            return
        req = urllib.request.Request(
            url,
            data=json.dumps({"content": msg}).encode(),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "KpopJournal-Bot/2.0 (x-phase2-report)",
            },
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:  # 通知失敗でレポート生成は止めない
        print(f"discord notify failed: {e}", file=sys.stderr)


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    rec: dict = {"ts": datetime.now().isoformat(), "phase1_start": PHASE1_START}

    posts = _phase1_post_ids()
    if len(posts) < MIN_N:
        rec.update({"verdict": "WAIT", "reason": "insufficient_data", "n": len(posts)})
        _log(rec)
        msg = (
            f"⏳ [X Phase2判定] データ不足のため判定保留。"
            f"Phase 1以降で24h経過した投稿は {len(posts)}本(必要 {MIN_N}本)。"
            f"cap=3運用のため、あと数日積んでから再判定してください。"
        )
        print(msg)
        if not dry_run:
            _notify_discord(msg)
        return 0

    data = _metrics([p for p, _ in posts])
    imps = sorted(int(m.get("impression_count", 0)) for m in data.values())
    if not imps:
        rec.update({"verdict": "WAIT", "reason": "no_metrics", "n": len(posts)})
        _log(rec)
        print("metrics取得に失敗(APIレスポンス空)。再実行してください。")
        return 1

    avg = sum(imps) / len(imps)
    med = statistics.median(imps)
    n = len(imps)
    followers = _followers()

    go = avg >= AVG_GATE and med >= MEDIAN_GATE and n >= MIN_N
    rec.update(
        {
            "verdict": "GO" if go else "HOLD",
            "n": n,
            "avg_impression": round(avg, 2),
            "median_impression": med,
            "max_impression": imps[-1],
            "min_impression": imps[0],
            "followers": followers,
            "gates": {"avg": AVG_GATE, "median": MEDIAN_GATE, "min_n": MIN_N},
        }
    )
    _log(rec)

    head = "✅ [X Phase2判定] GO" if go else "🟡 [X Phase2判定] HOLD(Phase 1継続)"
    lines = [
        head,
        f"Phase 1({PHASE1_START[:10]}〜)の実測 n={n}本",
        f"・平均imp {avg:.2f}(GATE {AVG_GATE}) / 中央値 {med:.1f}(GATE {MEDIAN_GATE})",
        f"・レンジ {imps[0]}〜{imps[-1]} / フォロワー {followers}",
        f"・参照: バン期の崩壊水準は平均{BAN_ERA_AVG}以下",
    ]
    if go:
        lines.append(
            "→ Phase 2へ移行可。ただしURLは本文に戻さずプロフィール誘導化すること"
            "(リプライURLは再発トリガー)。ARTICLE_HOURS復活は段階的に。"
        )
    else:
        fails = []
        if avg < AVG_GATE:
            fails.append(f"平均{avg:.2f}<{AVG_GATE}")
        if med < MEDIAN_GATE:
            fails.append(f"中央値{med:.1f}<{MEDIAN_GATE}")
        lines.append(f"→ 未達({' / '.join(fails)})。Phase 1のまま継続し再判定。")
        if avg >= AVG_GATE > med:
            lines.append(
                "※平均だけGATE超え=1本の当たりが平均を持ち上げている状態。"
                "リーチ回復ではないので移行不可。"
            )
    msg = "\n".join(lines)
    print(msg)
    if not dry_run:
        _notify_discord(msg)
    return 0


def _log(record: dict) -> None:
    with REPORT_LOG.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    sys.exit(main())
