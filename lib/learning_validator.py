#!/usr/bin/env python3
"""
learning_validator.py — 学習サイクル有効性検証 v1.0

【責務】
  1. winning_patterns.jsonl の result フィールドを post_publish_evaluator で更新
  2. error_patterns.json の resolved パターンが再発していないか検証
  3. 学習サイクルメトリクスを算出（Discord通知用）
  4. 「学習したはずなのに再発」を検知してDiscord緊急アラート

【使い方】
  # 全ステップ実行（cron推奨）
  python3 lib/learning_validator.py validate

  # winning_patterns の result を post_publish_evaluations から逆流更新
  python3 lib/learning_validator.py backfill-results

  # 学習サイクルレポートJSON出力
  python3 lib/learning_validator.py report

cron: 0 9 * * * cd ~/kpop-ai-system && python3 lib/learning_validator.py validate
"""

import argparse
import json
import os
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"

WINNING_PATTERNS = LOGS / "winning_patterns.jsonl"
EVAL_FILE = LOGS / "post_publish_evaluations.jsonl"
ERROR_PATTERNS = CONFIG / "error_patterns.json"
AUTO_DIRECTIVES = CONFIG / "auto_directives.json"
LEARNING_FEEDBACK = LOGS / "learning_feedback.jsonl"
PIPELINE_LOG = LOGS / "pipeline.jsonl"
VALIDATION_LOG = LOGS / "learning_validation.log"
KPI_POSTS = LOGS / "kpi_posts.jsonl"
GSC_TRACKING = LOGS / "gsc_tracking.json"
X_RESULTS = LOGS / "x_post_results.jsonl"
DISCORD_WEBHOOKS = CONFIG / "discord_webhooks.json"

JST = timezone(timedelta(hours=9))


def _log(msg: str) -> None:
    ts = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    line = f"[{ts}] {msg}"
    print(line)
    LOGS.mkdir(exist_ok=True)
    with open(VALIDATION_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _load_jsonl(path: Path, max_lines: int = 0) -> list:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if max_lines:
        lines = lines[-max_lines:]
    records = []
    for line in lines:
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _discord_notify(msg: str, channel: str = "urgent_errors") -> None:
    """Discord Webhook 通知"""
    webhooks = _load_json(DISCORD_WEBHOOKS)
    url = webhooks.get(channel, webhooks.get("daily_ceo_report", ""))
    if not url:
        return
    try:
        payload = json.dumps({"content": msg[:1900]}).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        _log(f"Discord通知失敗: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Step 1: winning_patterns に result を逆流更新
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _get_published_post_ids() -> set:
    """WP APIから全公開記事のIDセットを取得"""
    published = set()
    try:
        import requests
        site = os.environ.get("SITE_URL", "https://www.kpopjournal.tokyo")
        auth_user = os.environ.get("WP_USER", "")
        auth_pass = os.environ.get("WP_APP_PASSWORD", "")
        auth = (auth_user, auth_pass) if auth_user and auth_pass else None
        page = 1
        while True:
            r = requests.get(
                f"{site}/wp-json/wp/v2/posts",
                params={"per_page": 100, "page": page, "status": "publish", "_fields": "id"},
                auth=auth, timeout=15,
            )
            if r.status_code != 200:
                break
            posts = r.json()
            if not posts:
                break
            for p in posts:
                published.add(str(p["id"]))
            page += 1
    except Exception as e:
        _log(f"WP API取得失敗: {e}")
    return published


def backfill_results() -> dict:
    """
    winning_patterns.jsonl の result を更新する。
    判定ロジック（優先順）:
      1. post_publish_evaluator の結果（WIN/REWRITE_NOW/HOLD）
      2. GSC/X データから直接判定
      3. WP公開記事に存在 → win（パイプライン成功 = 学習が機能）
      4. 72h以上経過で公開されていない → lose
    """
    stats = {"evaluated": 0, "win": 0, "lose": 0, "hold": 0, "updated": 0}

    # post_publish_evaluator を実行
    try:
        from post_publish_evaluator import run as eval_run
        eval_results = eval_run()
        stats["evaluated"] = len(eval_results)
        _log(f"post_publish_evaluator 実行: {len(eval_results)}件評価")
    except Exception as e:
        _log(f"post_publish_evaluator フォールバック: {e}")

    # 評価結果を post_id → rank のマップに
    eval_map = {}
    for rec in _load_jsonl(EVAL_FILE):
        pid = str(rec.get("post_id", ""))
        rank = rec.get("rank", "")
        if pid and rank:
            eval_map[pid] = rank

    # GSC/X データ
    gsc_raw = _load_json(Path(GSC_TRACKING))
    gsc_data = {}
    if isinstance(gsc_raw, list):
        for entry in gsc_raw:
            pid = str(entry.get("post_id", ""))
            if pid:
                gsc_data[pid] = entry
    elif isinstance(gsc_raw, dict):
        gsc_data = gsc_raw

    x_records = _load_jsonl(Path(X_RESULTS))
    x_map = {}
    for r in x_records:
        pid = str(r.get("post_id", ""))
        if pid:
            x_map[pid] = r

    # WP公開記事IDセット（最終フォールバック判定用）
    published_ids = _get_published_post_ids()
    _log(f"WP公開記事: {len(published_ids)}件取得")

    # kpi_posts.jsonl から公開成功記事を追加取得
    kpi_published = set()
    for rec in _load_jsonl(KPI_POSTS, max_lines=500):
        if rec.get("event") == "post_published":
            pid = str(rec.get("post_id", ""))
            if pid:
                kpi_published.add(pid)

    if not WINNING_PATTERNS.exists():
        _log("winning_patterns.jsonl なし")
        return stats

    patterns = _load_jsonl(WINNING_PATTERNS)
    updated_patterns = []
    for p in patterns:
        pid = str(p.get("post_id", ""))

        # 既に result 設定済みなら変更しない
        if p.get("result") in ("win", "lose"):
            stats[p["result"]] += 1
            updated_patterns.append(p)
            continue

        # 経過時間
        recorded = p.get("recorded_at", "")
        hours = 0
        if recorded:
            try:
                rec_dt = datetime.fromisoformat(recorded)
                hours = (datetime.now(JST) - rec_dt).total_seconds() / 3600
            except Exception:
                pass

        result = None

        # (1) post_publish_evaluator の結果
        rank = eval_map.get(pid, "")
        if rank == "WIN":
            result = "win"
        elif rank == "REWRITE_NOW":
            result = "lose"
        elif rank == "HOLD" and hours >= 72:
            result = "lose"

        # (2) GSC/X データから判定
        if result is None and pid:
            gsc_entry = gsc_data.get(pid, {})
            x_entry = x_map.get(pid, {})
            indexed = gsc_entry.get("indexed", False) or gsc_entry.get("status") in ("indexed", "PASS")
            clicks = gsc_entry.get("clicks_7d", 0) or 0
            x_posted = x_entry.get("status", "") == "posted"

            if indexed and (clicks >= 3 or x_posted):
                result = "win"
            elif hours >= 72 and indexed and clicks < 3:
                result = "lose"

        # (3) WP公開記事に存在 = パイプラインが品質ゲートを通過して公開成功
        if result is None and pid:
            if pid in published_ids or pid in kpi_published:
                result = "win"

        # (4) 72h以上経過でどこにも公開されていない → lose
        if result is None and hours >= 72:
            result = "lose"

        if result:
            p["result"] = result
            stats[result] += 1
            stats["updated"] += 1

        updated_patterns.append(p)

    # 書き戻し
    if stats["updated"] > 0:
        with open(WINNING_PATTERNS, "w", encoding="utf-8") as f:
            for p in updated_patterns:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        _log(f"winning_patterns 更新: {stats['updated']}件 (win={stats['win']} lose={stats['lose']})")
    else:
        _log(f"winning_patterns: 更新対象なし (既存 win={stats['win']} lose={stats['lose']})")

    return stats


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Step 2: 学習失敗検知（resolved パターンの再発チェック）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def detect_learning_failures() -> list:
    """
    error_patterns.json の resolved パターンが
    resolved_at 以降の pipeline.jsonl で再発していないか検証する。

    判定基準:
      - resolved_at 以降に pipeline.jsonl で同一パターンのエラーが記録された場合のみ再発
      - cron.log は補助参照のみ（日付フィルタ + example全文マッチに厳格化）
      - unknown_* パターンはスキップ（未分類のため再発判定不可能）
    """
    failures = []
    error_data = _load_json(ERROR_PATTERNS)
    patterns = error_data.get("patterns", {})

    # pipeline.jsonl の全エラーを収集
    all_errors = []
    for rec in _load_jsonl(PIPELINE_LOG, max_lines=1000):
        if rec.get("status") in ("error", "rejected", "failed"):
            all_errors.append(rec)

    for pattern_key, pdata in patterns.items():
        resolved_at = pdata.get("resolved_at", "")
        if not resolved_at:
            continue

        # unknown_* パターンはスキップ
        if pattern_key.startswith("unknown_"):
            continue

        # resolved_at 以降のエラーのみ対象
        recurrence_count = 0
        example = pdata.get("example", "")

        for rec in all_errors:
            ts = rec.get("ts", rec.get("timestamp", ""))
            if not ts or ts <= resolved_at:
                continue

            msg = str(rec.get("message", ""))
            # example の先頭30文字以上でマッチ（誤検出を防ぐ）
            if example and len(example) >= 10 and example[:30] in msg:
                recurrence_count += 1

        if recurrence_count > 0:
            failure = {
                "pattern_key": pattern_key,
                "resolved_at": resolved_at,
                "recurrence_count": recurrence_count,
                "fix_applied": pdata.get("fix", ""),
                "agent": pdata.get("agent", "unknown"),
                "original_count": pdata.get("count", 0),
            }
            failures.append(failure)
            _log(f"⚠️ 学習失敗検出: {pattern_key} (resolved={resolved_at}, 再発{recurrence_count}回)")

    if not failures:
        _log("✅ 学習失敗なし（全 resolved パターンが再発していない）")

    return failures


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Step 3: 学習サイクルメトリクス算出
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def compute_learning_metrics() -> dict:
    """学習サイクルの有効性を数値化"""
    error_data = _load_json(ERROR_PATTERNS)
    directives_data = _load_json(AUTO_DIRECTIVES)
    patterns = error_data.get("patterns", {})
    agent_dirs = directives_data.get("agent_directives", {})

    # エラー統計
    total_patterns = len(patterns)
    resolved_count = sum(1 for p in patterns.values() if p.get("resolved_at"))
    recurring_count = len(error_data.get("recurring_errors", []))
    total_error_count = sum(p.get("count", 0) for p in patterns.values())

    # ディレクティブ統計
    total_directives = len(agent_dirs)
    auto_directives = sum(1 for d in agent_dirs.values()
                          if d.get("source") in ("auto_learn", "error_pattern_inject", "audit_feedback", "agent_monitor_HIGH"))
    manual_directives = total_directives - auto_directives

    # winning_patterns 統計
    wp_records = _load_jsonl(WINNING_PATTERNS)
    wp_total = len(wp_records)
    wp_wins = sum(1 for r in wp_records if r.get("result") == "win")
    wp_loses = sum(1 for r in wp_records if r.get("result") == "lose")
    wp_pending = wp_total - wp_wins - wp_loses

    # 学習フィードバック統計
    learning_records = _load_jsonl(LEARNING_FEEDBACK)
    cutoff_7d = (datetime.now(JST) - timedelta(days=7)).isoformat()
    recent_learnings = [r for r in learning_records if r.get("ts", "") >= cutoff_7d]

    # 学習効果スコア（0-100）— 5軸で評価
    #   A. エラー解決率  (resolved / total)          × 25点
    #   B. 記事勝率      (win / (win+lose))          × 25点
    #   C. ディレクティブ注入率 (auto / total)        × 20点
    #   D. 再発ゼロボーナス                            × 15点
    #   E. 学習活動量    (recent_7d >= 3 で満点)      × 15点
    resolution_rate = resolved_count / max(total_patterns, 1)
    win_rate = wp_wins / max(wp_wins + wp_loses, 1)
    directive_rate = auto_directives / max(total_directives, 1)

    # 学習失敗件数
    failures = detect_learning_failures()
    recurrence_rate = len(failures) / max(resolved_count, 1)

    score_a = resolution_rate * 25
    score_b = win_rate * 25
    score_c = directive_rate * 20
    score_d = 15 if len(failures) == 0 else max(0, 15 - len(failures) * 5)
    score_e = min(15, (len(recent_learnings) / 3) * 15)
    effectiveness_score = round(score_a + score_b + score_c + score_d + score_e)

    metrics = {
        "computed_at": datetime.now(JST).isoformat(),
        # エラーパターン
        "total_error_patterns": total_patterns,
        "resolved_patterns": resolved_count,
        "recurring_patterns": recurring_count,
        "total_error_occurrences": total_error_count,
        # ディレクティブ
        "total_directives": total_directives,
        "auto_directives": auto_directives,
        "manual_directives": manual_directives,
        # 記事パフォーマンス
        "articles_tracked": wp_total,
        "articles_win": wp_wins,
        "articles_lose": wp_loses,
        "articles_pending": wp_pending,
        "win_rate": round(win_rate, 3),
        # 学習効果
        "effectiveness_score": effectiveness_score,
        "score_breakdown": {
            "error_resolution": round(score_a, 1),
            "win_rate": round(score_b, 1),
            "directive_injection": round(score_c, 1),
            "no_recurrence_bonus": round(score_d, 1),
            "learning_activity": round(score_e, 1),
        },
        "learning_failures": len(failures),
        "recurrence_rate": round(recurrence_rate, 3),
        "recent_learnings_7d": len(recent_learnings),
        # 詳細
        "failure_details": failures,
    }

    # メトリクスを保存
    metrics_file = LOGS / "learning_metrics.json"
    metrics_file.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    return metrics


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Step 4: Discord 通知（学習失敗アラート + 週次レポート）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def notify_learning_failures(failures: list) -> None:
    """学習失敗を Discord 緊急アラートとして通知"""
    if not failures:
        return

    lines = [
        "🚨 **学習失敗検知** — 解決済みパターンが再発しています\n",
    ]
    for f in failures[:5]:
        lines.append(
            f"• **{f['pattern_key']}** ({f['agent']}): "
            f"resolved={f['resolved_at']}, 再発{f['recurrence_count']}回\n"
            f"  適用済みFIX: {f['fix_applied'][:60]}"
        )

    lines.append(
        "\n→ FIX が効いていない可能性があります。根本原因の再調査が必要です。"
    )

    _discord_notify("\n".join(lines), "urgent_errors")
    _log(f"Discord学習失敗アラート送信: {len(failures)}件")


def generate_learning_cycle_report(metrics: dict) -> str:
    """Discord 通知用の学習サイクルレポート"""
    score = metrics["effectiveness_score"]
    if score >= 70:
        icon = "🟢"
    elif score >= 40:
        icon = "🟡"
    else:
        icon = "🔴"

    bd = metrics.get("score_breakdown", {})
    lines = [
        f"{icon} **学習サイクルレポート** | 効果スコア: {score}/100\n",
        f"📊 **内訳:** エラー解決={bd.get('error_resolution',0)}/25 "
        f"勝率={bd.get('win_rate',0)}/25 "
        f"注入={bd.get('directive_injection',0)}/20 "
        f"再発0={bd.get('no_recurrence_bonus',0)}/15 "
        f"活動={bd.get('learning_activity',0)}/15",
        f"📈 **記事:** "
        f"win={metrics['articles_win']} lose={metrics['articles_lose']} "
        f"待機={metrics['articles_pending']} (勝率: {metrics['win_rate']:.0%})",
        f"🔧 **ディレクティブ:** {metrics['total_directives']}件 "
        f"(自動: {metrics['auto_directives']} / 手動: {metrics['manual_directives']})",
    ]

    if metrics["learning_failures"] > 0:
        lines.append(
            f"🚨 **学習失敗:** {metrics['learning_failures']}件 "
            f"(再発率: {metrics['recurrence_rate']:.0%})"
        )
        for f in metrics.get("failure_details", [])[:3]:
            lines.append(f"  • {f['pattern_key']} → 再発{f['recurrence_count']}回")
    else:
        lines.append("✅ **学習失敗:** なし")

    return "\n".join(lines)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def cmd_validate(args):
    """全ステップ実行"""
    _log("=" * 50)
    _log("learning_validator validate 開始")

    # Step 1: winning_patterns の result を更新
    _log("--- Step 1: winning_patterns result 更新 ---")
    backfill_stats = backfill_results()

    # Step 2: 学習サイクルメトリクス算出（内部で学習失敗検知も実行）
    _log("--- Step 2: 学習サイクルメトリクス算出 ---")
    metrics = compute_learning_metrics()

    # Step 3: 学習失敗があれば Discord アラート
    failures = metrics.get("failure_details", [])
    if failures:
        _log(f"--- Step 3: 学習失敗 {len(failures)}件 → Discord通知 ---")
        notify_learning_failures(failures)

    # Step 4: サマリーログ
    report = generate_learning_cycle_report(metrics)
    _log("--- 学習サイクルレポート ---")
    for line in report.split("\n"):
        _log(f"  {line}")

    _log("learning_validator validate 完了")
    print(report)


def cmd_backfill(args):
    """winning_patterns の result のみ更新"""
    stats = backfill_results()
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def cmd_report(args):
    """学習サイクルメトリクスJSON出力"""
    metrics = compute_learning_metrics()
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def cmd_metrics_oneliner(args):
    """improvement_engine.sh 用の1行サマリー"""
    metrics_file = LOGS / "learning_metrics.json"
    if metrics_file.exists():
        m = json.loads(metrics_file.read_text(encoding="utf-8"))
    else:
        m = compute_learning_metrics()

    score = m.get("effectiveness_score", 0)
    wins = m.get("articles_win", 0)
    loses = m.get("articles_lose", 0)
    failures = m.get("learning_failures", 0)
    resolved = m.get("resolved_patterns", 0)
    total = m.get("total_error_patterns", 0)

    icon = "🟢" if score >= 70 else ("🟡" if score >= 40 else "🔴")
    print(f"{icon} 学習効果={score}/100 win={wins} lose={loses} 解決={resolved}/{total} 再発={failures}")


def main():
    parser = argparse.ArgumentParser(description="学習サイクル有効性検証")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("validate", help="全ステップ実行（cron推奨）")
    sub.add_parser("backfill-results", help="winning_patterns の result を更新")
    sub.add_parser("report", help="学習サイクルメトリクスJSON出力")
    sub.add_parser("metrics-oneliner", help="1行サマリー（improvement_engine用）")

    args = parser.parse_args()
    if args.command == "validate":
        cmd_validate(args)
    elif args.command == "backfill-results":
        cmd_backfill(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "metrics-oneliner":
        cmd_metrics_oneliner(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
