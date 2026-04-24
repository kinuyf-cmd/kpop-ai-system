#!/usr/bin/env python3
"""
feedback_loop_orchestrator.py — Phase 2 フィードバックループ統合オーケストレーター v1.0

【責務】
  4つのフィードバックサブシステムを正しい順序で実行し、結果を統合する。

  実行順序:
    1. kpi_feedback_loop      — KPIデータ→エージェント自動注入（CTR低下分類→プロンプト改善）
    2. anomaly_auto_intervention — 異常検知→自動介入（CTR30%下落/3連続失敗→auto_repair）
    3. quality_auto_stop      — 品質スコア60未満3連続→エージェント自動停止+Discord
    4. learning_ceo_bridge    — 学習結果→CEO改善キューの自動ブリッジ（queued=0問題の解消）

【スケジュール】
  - 朝6:30  → kpi_feedback_loop + anomaly_auto_intervention（メトリクス取得後）
  - 毎2時間 → anomaly_auto_intervention + quality_auto_stop（常時監視）
  - 夜22:00 → learning_ceo_bridge（apply_learning 21:30の後）
  - full    → 全4システム実行

【安全制約】
  - 各サブシステムは独立しており、1つが失敗しても他は続行する
  - 全結果は logs/feedback_orchestrator.jsonl に記録
  - --dry-run で判定のみ（介入なし）

Usage:
  python3 lib/feedback_loop_orchestrator.py full           # 全システム実行
  python3 lib/feedback_loop_orchestrator.py morning        # 朝の実行
  python3 lib/feedback_loop_orchestrator.py monitor        # 常時監視（2時間おき）
  python3 lib/feedback_loop_orchestrator.py nightly        # 夜の実行
  python3 lib/feedback_loop_orchestrator.py --dry-run full # 判定のみ
"""
import argparse
import json
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

ORCHESTRATOR_LOG = LOGS / "feedback_orchestrator.jsonl"

# sys.path に BASE を追加（lib.xxx のインポート用）
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def _append_log(entry: dict):
    LOGS.mkdir(parents=True, exist_ok=True)
    with ORCHESTRATOR_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _run_subsystem(name: str, func, dry_run: bool) -> dict:
    """サブシステムを安全に実行する。失敗しても他に影響しない。"""
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"[orchestrator] {name} 開始...", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    try:
        result = func(dry_run=dry_run)
        print(f"[orchestrator] {name} ✅ 完了", file=sys.stderr)
        return {"status": "ok", "result": result}
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        tb = traceback.format_exc()
        print(f"[orchestrator] {name} ❌ エラー: {error_msg}", file=sys.stderr)
        print(f"  {tb}", file=sys.stderr)
        return {"status": "error", "error": error_msg, "traceback": tb[-500:]}


# ═══════════════════════════════════════════════════════════════
# 実行モード
# ═══════════════════════════════════════════════════════════════

def run_morning(dry_run: bool = False) -> dict:
    """朝の実行: KPIフィードバック + 異常検知。"""
    from lib.kpi_feedback_loop import run as kpi_run
    from lib.anomaly_auto_intervention import run as anomaly_run

    results = {}
    results["kpi_feedback"] = _run_subsystem("KPIフィードバックループ", kpi_run, dry_run)
    results["anomaly_intervention"] = _run_subsystem("異常検知→自動介入", anomaly_run, dry_run)
    return results


def run_monitor(dry_run: bool = False) -> dict:
    """常時監視: 異常検知 + 品質停止チェック。"""
    from lib.anomaly_auto_intervention import run as anomaly_run
    from lib.quality_auto_stop import run as quality_run

    results = {}
    results["anomaly_intervention"] = _run_subsystem("異常検知→自動介入", anomaly_run, dry_run)
    results["quality_auto_stop"] = _run_subsystem("品質スコア監視", quality_run, dry_run)
    return results


def run_nightly(dry_run: bool = False) -> dict:
    """夜の実行: 学習→CEOブリッジ。"""
    from lib.learning_ceo_bridge import run as bridge_run

    results = {}
    results["learning_bridge"] = _run_subsystem("学習→CEOブリッジ", bridge_run, dry_run)
    return results


def run_full(dry_run: bool = False) -> dict:
    """全4システムを実行する。"""
    from lib.kpi_feedback_loop import run as kpi_run
    from lib.anomaly_auto_intervention import run as anomaly_run
    from lib.quality_auto_stop import run as quality_run
    from lib.learning_ceo_bridge import run as bridge_run

    results = {}
    results["kpi_feedback"] = _run_subsystem("KPIフィードバックループ", kpi_run, dry_run)
    results["anomaly_intervention"] = _run_subsystem("異常検知→自動介入", anomaly_run, dry_run)
    results["quality_auto_stop"] = _run_subsystem("品質スコア監視", quality_run, dry_run)
    results["learning_bridge"] = _run_subsystem("学習→CEOブリッジ", bridge_run, dry_run)
    return results


# ═══════════════════════════════════════════════════════════════
# メイン
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Phase 2 フィードバックループ統合オーケストレーター v1.0"
    )
    parser.add_argument("mode", nargs="?", default="full",
                        choices=["full", "morning", "monitor", "nightly"],
                        help="実行モード")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"[feedback_orchestrator] {NOW.isoformat()} mode={args.mode} "
          f"dry_run={args.dry_run}", file=sys.stderr)

    mode_map = {
        "full": run_full,
        "morning": run_morning,
        "monitor": run_monitor,
        "nightly": run_nightly,
    }
    runner = mode_map[args.mode]
    results = runner(dry_run=args.dry_run)

    # 結果サマリー
    ok_count = sum(1 for v in results.values() if v.get("status") == "ok")
    err_count = sum(1 for v in results.values() if v.get("status") == "error")

    summary = {
        "timestamp": NOW.isoformat(),
        "mode": args.mode,
        "dry_run": args.dry_run,
        "subsystems_ok": ok_count,
        "subsystems_error": err_count,
        "details": {k: v.get("status", "unknown") for k, v in results.items()},
    }

    if not args.dry_run:
        _append_log(summary)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"[feedback_orchestrator] 完了: OK={ok_count} ERROR={err_count}", file=sys.stderr)
    for k, v in results.items():
        icon = "✅" if v.get("status") == "ok" else "❌"
        print(f"  {icon} {k}: {v.get('status', 'unknown')}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # stdout にJSON出力
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    # エラーがあれば exit 1
    if err_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
