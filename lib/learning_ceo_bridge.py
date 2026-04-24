#!/usr/bin/env python3
"""
learning_ceo_bridge.py — 学習結果→CEO改善キューの自動ブリッジ v1.0

【根本問題】
  apply_learning_to_agents.py → agents/*.md の更新は動いているが、
  その学習結果がCEO改善キュー（ceo_improvement_queue）に到達していなかった。
  原因: safe_action_historyへの書き込みが一部の手動実行時にしか走らず、
        enqueue_batch_from_safe_historyも__main__からしか呼ばれていなかった。

【解決策】
  このモジュールが以下を自動で行う:
  1. agent_metrics.json の最新状態を読み取り
  2. 改善が必要なエージェントを検出（成功率低下/空出力増加/HARD_FAIL多発）
  3. ceo_safe_action_history.jsonl に新規エントリを追記
  4. ceo_improvement_queue.py の enqueue_batch を呼び出してキューに積む
  5. 結果をログに記録

【パイプライン統合】
  feedback_loop_orchestrator.py から毎日22:00 JST に呼ばれる。
  apply_learning_to_agents.py（21:30）の後に走る前提。

Usage:
  python3 lib/learning_ceo_bridge.py              # 通常実行
  python3 lib/learning_ceo_bridge.py --dry-run    # 判定のみ
  python3 lib/learning_ceo_bridge.py --stats      # 統計表示
"""
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

# ── パス定義 ──
AGENT_METRICS_PATH = BASE / "agent_metrics.json"
SAFE_HISTORY_PATH = LOGS / "ceo_safe_action_history.jsonl"
BRIDGE_LOG_PATH = LOGS / "learning_ceo_bridge.jsonl"
APPLIED_LOG_PATH = LOGS / "agents_auto_applied.jsonl"
ERROR_PATTERNS_PATH = BASE / "config" / "error_patterns.json"
CTR_CLASSIFIED_PATH = LOGS / "ctr_decline_classified.json"

# ── 検出閾値 ──
SUCCESS_RATE_WARN = 0.85     # これ未満 → prompt_fix推奨
SUCCESS_RATE_CRITICAL = 0.60 # これ未満 → 即時prompt_fix（HIGH priority）
EMPTY_OUTPUT_WARN = 3        # 空出力3回以上 → timeout_fix推奨
HARD_FAIL_WARN = 5           # HARD_FAIL 5回以上 → prompt_fix推奨
CONTAMINATION_WARN = 2       # 汚染2件以上 → prompt_fix推奨

# safe_action で使う recommendation_type
REC_PROMPT_FIX = "prompt_fix"
REC_TIMEOUT_FIX = "timeout_fix"
REC_MONITOR = "monitor_continue"


def _load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    records = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


def _append_jsonl(p: Path, record: dict):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _today_str() -> str:
    return NOW.strftime("%Y-%m-%d")


# ═══════════════════════════════════════════════════════════════
# Step 1: 改善が必要なエージェントを検出
# ═══════════════════════════════════════════════════════════════

def detect_agents_needing_improvement() -> list[dict]:
    """agent_metrics.json から改善が必要なエージェントを検出する。"""
    metrics = _load_json(AGENT_METRICS_PATH)
    agents = metrics.get("agents", {})
    needs = []

    for agent_id, data in agents.items():
        role_class = data.get("role_class", "")
        if role_class in ("MANUAL_ONLY", "DEPRECATED"):
            continue

        total = data.get("total_count", 0)
        if total < 3:  # 実行回数が少なすぎるものは判定しない
            continue

        sr = data.get("success_rate", 1.0) or 1.0
        empty = data.get("empty_output_count", 0) or 0
        hf = data.get("hard_fail_count", 0) or 0
        contam = data.get("contamination_count", 0) or 0
        name_ja = data.get("name_ja", agent_id)

        recommendations = []

        # 成功率チェック
        if sr < SUCCESS_RATE_CRITICAL:
            recommendations.append({
                "type": REC_PROMPT_FIX,
                "priority": "HIGH",
                "reason": f"成功率{sr:.0%}がCRITICAL閾値{SUCCESS_RATE_CRITICAL:.0%}未満",
                "detail": f"成功{data.get('success_count',0)}/失敗{data.get('fail_count',0)}/計{total}",
            })
        elif sr < SUCCESS_RATE_WARN:
            recommendations.append({
                "type": REC_PROMPT_FIX,
                "priority": "MEDIUM",
                "reason": f"成功率{sr:.0%}がWARN閾値{SUCCESS_RATE_WARN:.0%}未満",
                "detail": f"成功{data.get('success_count',0)}/失敗{data.get('fail_count',0)}/計{total}",
            })

        # 空出力チェック
        if empty >= EMPTY_OUTPUT_WARN:
            recommendations.append({
                "type": REC_TIMEOUT_FIX,
                "priority": "HIGH" if empty >= EMPTY_OUTPUT_WARN * 2 else "MEDIUM",
                "reason": f"空出力{empty}回（閾値{EMPTY_OUTPUT_WARN}回以上）",
                "detail": f"タイムアウトまたはプロンプト不備が疑われる",
            })

        # HARD_FAIL チェック
        if hf >= HARD_FAIL_WARN:
            recommendations.append({
                "type": REC_PROMPT_FIX,
                "priority": "HIGH",
                "reason": f"HARD_FAIL {hf}回（閾値{HARD_FAIL_WARN}回以上）",
                "detail": f"出力品質ゲートで繰り返し弾かれている",
            })

        # 汚染チェック
        if contam >= CONTAMINATION_WARN:
            recommendations.append({
                "type": REC_PROMPT_FIX,
                "priority": "HIGH",
                "reason": f"AI応答汚染{contam}回検出（閾値{CONTAMINATION_WARN}回以上）",
                "detail": f"タイトル/本文にAI内部応答が混入している",
            })

        if recommendations:
            needs.append({
                "agent_id": agent_id,
                "name_ja": name_ja,
                "role_class": role_class,
                "metrics": {"sr": sr, "empty": empty, "hf": hf, "contam": contam, "total": total},
                "recommendations": recommendations,
            })

    return needs


# ═══════════════════════════════════════════════════════════════
# Step 2: safe_action_history に新規エントリを追記
# ═══════════════════════════════════════════════════════════════

def _is_today_already_processed(agent_id: str, rec_type: str) -> bool:
    """本日既に同じエージェント+タイプの処理が済んでいるかチェック。"""
    today = _today_str()
    for rec in reversed(_load_jsonl(SAFE_HISTORY_PATH)):
        ts = rec.get("executed_at", "")
        if not ts.startswith(today):
            break  # 今日以外に到達したら終了
        if (rec.get("target_agent") == agent_id
                and rec.get("recommendation_type") == rec_type):
            return True
    return False


def generate_safe_action_entries(needs: list[dict]) -> list[dict]:
    """検出結果からsafe_action_historyエントリを生成する。"""
    entries = []

    for agent_info in needs:
        agent_id = agent_info["agent_id"]
        name_ja = agent_info["name_ja"]
        metrics = agent_info["metrics"]

        for rec in agent_info["recommendations"]:
            rec_type = rec["type"]

            # 本日既に処理済みならスキップ
            if _is_today_already_processed(name_ja, rec_type):
                continue

            action_type = "inspect_agent_failure" if rec_type == REC_PROMPT_FIX else "inspect_timeout"

            entry = {
                "executed_at": NOW.isoformat(),
                "action_type": action_type,
                "target_agent": name_ja,
                "result": "done",
                "summary": (
                    f"{name_ja} — 全{metrics['total']}回 "
                    f"成功率{metrics['sr']:.1%}、"
                    f"空出力{metrics['empty']}回・HARD_FAIL{metrics['hf']}回・"
                    f"汚染{metrics['contam']}回。{rec['reason']}"
                ),
                "recommendation_type": rec_type,
                "proposed_next_step": (
                    f"{name_ja}のプロンプト修正で改善余地あり。"
                    f"config/agent_directives.jsonまたはagents/{agent_id}.mdを修正する"
                    if rec_type == REC_PROMPT_FIX else
                    f"{name_ja}のタイムアウト設定を見直す。空出力時のfallbackを強化する"
                ),
                "source_log": "agent_metrics.json",
                "bridge_generated": True,  # ブリッジが自動生成したことを示すフラグ
            }
            entries.append(entry)

    # 全体が正常な場合はmonitor_continueを1件追加
    if not entries:
        if not _is_today_already_processed("", REC_MONITOR):
            overall = _load_json(AGENT_METRICS_PATH).get("summary", {})
            entries.append({
                "executed_at": NOW.isoformat(),
                "action_type": "monitor_only",
                "target_agent": "",
                "result": "done",
                "summary": (
                    f"全体成功率{overall.get('overall_success_rate', 0):.1%}・"
                    f"アクティブ{overall.get('active_agents', 0)}エージェント・"
                    f"CRITICAL{overall.get('critical_agents', 0)}件。"
                    f"learning_ceo_bridge自動検出: 改善必要エージェント0件。"
                ),
                "recommendation_type": REC_MONITOR,
                "proposed_next_step": "全指標正常範囲内。次回サイクルまで監視継続でよい",
                "source_log": "dashboard_summary.json",
                "bridge_generated": True,
            })

    return entries


def write_safe_action_entries(entries: list[dict], dry_run: bool = False) -> int:
    """safe_action_historyにエントリを書き込む。"""
    if dry_run:
        for e in entries:
            print(f"[DRY-RUN] safe_action: {e['target_agent']} → {e['recommendation_type']}")
        return 0

    written = 0
    for entry in entries:
        _append_jsonl(SAFE_HISTORY_PATH, entry)
        written += 1

    return written


# ═══════════════════════════════════════════════════════════════
# Step 3: improvement_queue に積む
# ═══════════════════════════════════════════════════════════════

def enqueue_to_improvement(entries: list[dict], dry_run: bool = False) -> dict:
    """safe_action_historyのエントリをimprovement_queueに積む。"""
    if dry_run:
        return {"queued": 0, "skipped_dup": 0, "skipped_na": 0, "dry_run": True}

    sys.path.insert(0, str(BASE))
    from lib.ceo_improvement_queue import enqueue_batch_from_safe_history
    return enqueue_batch_from_safe_history(entries)


# ═══════════════════════════════════════════════════════════════
# メイン実行
# ═══════════════════════════════════════════════════════════════

def run(dry_run: bool = False) -> dict:
    """学習結果→CEO改善キューの完全ブリッジを実行する。"""
    print(f"[learning_ceo_bridge] {NOW.isoformat()} 開始", file=sys.stderr)

    # Step 1: 改善が必要なエージェントを検出
    needs = detect_agents_needing_improvement()
    print(f"  検出: {len(needs)}エージェントに改善推奨", file=sys.stderr)
    for n in needs:
        for r in n["recommendations"]:
            print(f"    {n['name_ja']}: {r['type']} ({r['priority']}) — {r['reason']}", file=sys.stderr)

    # Step 2: safe_action_historyエントリを生成・書き込み
    entries = generate_safe_action_entries(needs)
    written = write_safe_action_entries(entries, dry_run)
    print(f"  safe_action_history: {written}件追記", file=sys.stderr)

    # Step 3: improvement_queueに積む
    queue_result = enqueue_to_improvement(entries, dry_run)
    print(f"  improvement_queue: queued={queue_result.get('queued', 0)} "
          f"skipped_dup={queue_result.get('skipped_dup', 0)} "
          f"skipped_na={queue_result.get('skipped_na', 0)}", file=sys.stderr)

    result = {
        "agents_needing_improvement": len(needs),
        "safe_actions_written": written,
        "queue_result": queue_result,
        "dry_run": dry_run,
    }

    # ブリッジ実行ログ
    if not dry_run:
        _append_jsonl(BRIDGE_LOG_PATH, {
            "timestamp": NOW.isoformat(),
            "agents_detected": len(needs),
            "entries_written": written,
            "queued": queue_result.get("queued", 0),
            "skipped_dup": queue_result.get("skipped_dup", 0),
        })

    print(f"[learning_ceo_bridge] 完了: {json.dumps(result, ensure_ascii=False)}", file=sys.stderr)
    return result


def print_stats():
    records = _load_jsonl(BRIDGE_LOG_PATH)
    if not records:
        print("ブリッジ実行ログなし")
        return

    print(f"\n=== Learning→CEO ブリッジ統計 ===")
    print(f"  実行回数: {len(records)}")
    latest = records[-1]
    print(f"  最終実行: {latest.get('timestamp', '-')}")
    print(f"  検出エージェント: {latest.get('agents_detected', 0)}")
    print(f"  書き込み: {latest.get('entries_written', 0)}")
    print(f"  キュー追加: {latest.get('queued', 0)}")
    print(f"  重複スキップ: {latest.get('skipped_dup', 0)}")

    # 全期間の合計
    total_queued = sum(r.get("queued", 0) for r in records)
    total_detected = sum(r.get("agents_detected", 0) for r in records)
    print(f"\n  累計:")
    print(f"    検出: {total_detected}件")
    print(f"    キュー追加: {total_queued}件")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="学習→CEOブリッジ v1.0")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    if args.stats:
        print_stats()
    else:
        result = run(dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
