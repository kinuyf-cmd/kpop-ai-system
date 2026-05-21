#!/usr/bin/env python3
"""
ceo_action_export.py — CEO判断→実行命令JSON変換モジュール
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  dashboard_summary.json の既存KPIだけを材料に、
  「最優先の1命令」を決定論的に生成し logs/ceo_action_queue.jsonl へ追記する。
  自動実行はしない。命令を保存・見える化するだけ。

【action_type 候補】
  retry_alert_queue       — 通知キュー再送が必要
  inspect_agent_failure   — エージェント停止・低成功率の調査
  inspect_revenue_blocker — 売上阻害エージェントの調査
  monitor_only            — 現在は通常監視で十分
"""

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
QUEUE_PATH = BASE / "logs" / "ceo_action_queue.jsonl"
SUMMARY_PATH = BASE / "dashboard_summary.json"

JST = timezone(timedelta(hours=9))

# 売上直結エージェントID（停止時は最優先繰り上げ対象）
REVENUE_CRITICAL_IDS = {"wp_poster", "sanai", "butterfree", "kairyu", "arceus"}

# action_type ごとの期待効果テンプレート
EXPECTED_EFFECT_TEMPLATES = {
    "retry_alert_queue": "CRITICAL通知が即時配信され、見落としリスクが解消される",
    "inspect_agent_failure": "{name}の停止原因を特定し、次回実行サイクルで復旧できる状態にする",
    "inspect_revenue_blocker": "{name}の失敗原因を排除し、{rate:.0%}→90%以上への成功率回復で売上直結効果",
    "monitor_only": "現状維持。異常発生時は次回サイクルで自動検知される",
}

# ブロッカー理由テンプレート
BLOCKER_REASON_TEMPLATES = {
    "retry_alert_queue": "未解決CRITICAL {count}件がキュー滞留中。オーナーへの通知が届いていない",
    "inspect_agent_failure": "{name}の成功率が{rate:.0%}で停止継続中。他パイプラインへの波及リスクあり",
    "inspect_revenue_blocker": "{name}が{rate:.0%}で売上阻害TOP。放置すると検索流入・CVRが継続低下",
    "monitor_only": "全クリティカル指標が正常範囲内",
}


def load_summary() -> dict:
    """dashboard_summary.json を読み込む。なければ空dict"""
    if not SUMMARY_PATH.exists():
        return {}
    try:
        return json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_recent_queue(n: int = 5) -> list:
    """ceo_action_queue.jsonl の末尾n件を読む"""
    if not QUEUE_PATH.exists():
        return []
    records = []
    try:
        with QUEUE_PATH.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    return records[-n:]


def _is_duplicate(record: dict, recent: list) -> bool:
    """
    直近1件と action_type / target_agent / target_log / reason が
    すべて一致する場合は重複とみなす
    """
    if not recent:
        return False
    last = recent[-1]
    return (
        last.get("action_type") == record.get("action_type")
        and last.get("target_agent") == record.get("target_agent")
        and last.get("target_log") == record.get("target_log")
        and last.get("reason") == record.get("reason")
    )


def build_action(summary: dict) -> dict:
    """
    既存KPIから最優先の1命令を決定論的に生成する。
    優先順位:
      1. unresolved_critical_count > 0  → retry_alert_queue
      2. 売上直結AIが低成功率/停止       → inspect_revenue_blocker (HIGH)
      3. revenue_blocker_top3[0] 異常    → inspect_revenue_blocker
      4. failing_agent_top3[0] rate==0% → inspect_agent_failure
      5. notification_pending_count > 0 → retry_alert_queue (MEDIUM)
      6. それ以外                        → monitor_only
    """
    unres_crit    = summary.get("unresolved_critical_count", 0)
    queue_pending = summary.get("notification_pending_count", 0)
    blockers      = summary.get("revenue_blocker_top3", [])
    failing       = summary.get("failing_agent_top3", [])

    top_blocker = blockers[0] if blockers else None
    top_fail    = failing[0]  if failing  else None

    now_jst = datetime.now(JST).isoformat()

    # ─── 優先度1: 未解決CRITICAL ───
    if unres_crit > 0:
        reason = BLOCKER_REASON_TEMPLATES["retry_alert_queue"].format(count=unres_crit)
        effect = EXPECTED_EFFECT_TEMPLATES["retry_alert_queue"]
        return {
            "generated_at":       now_jst,
            "priority":           "HIGH",
            "action_type":        "retry_alert_queue",
            "target_agent":       "",
            "target_log":         "logs/alert_queue.jsonl",
            "target_metric":      f"unresolved_critical={unres_crit}",
            "reason":             reason,
            "expected_effect":    effect,
            "execute_recommended": True,
            "status":             "pending",
        }

    # ─── 優先度2: 売上直結AIが低成功率（<70%）または停止 ───
    if top_blocker and top_blocker.get("rank", "🟢") in ("🔴", "🟡"):
        bid   = top_blocker.get("id", "")
        bname = top_blocker.get("name", bid)
        brate = top_blocker.get("rate", 0)
        # 売上直結ID かつ低成功率なら HIGH
        priority = "HIGH" if bid in REVENUE_CRITICAL_IDS and brate < 0.7 else "MEDIUM"
        log_hint = "logs/pipeline_steps.jsonl"
        reason = BLOCKER_REASON_TEMPLATES["inspect_revenue_blocker"].format(name=bname, rate=brate)
        effect = EXPECTED_EFFECT_TEMPLATES["inspect_revenue_blocker"].format(name=bname, rate=brate)
        return {
            "generated_at":       now_jst,
            "priority":           priority,
            "action_type":        "inspect_revenue_blocker",
            "target_agent":       bname,
            "target_log":         log_hint,
            "target_metric":      f"success_rate={brate:.3f}",
            "reason":             reason,
            "expected_effect":    effect,
            "execute_recommended": True,
            "status":             "pending",
        }

    # ─── 優先度3: 最危険AIが0%停止 ───
    if top_fail and top_fail.get("rate", 1) == 0.0:
        fname = top_fail.get("name", top_fail.get("id", ""))
        reason = BLOCKER_REASON_TEMPLATES["inspect_agent_failure"].format(name=fname, rate=0.0)
        effect = EXPECTED_EFFECT_TEMPLATES["inspect_agent_failure"].format(name=fname)
        return {
            "generated_at":       now_jst,
            "priority":           "MEDIUM",
            "action_type":        "inspect_agent_failure",
            "target_agent":       fname,
            "target_log":         "logs/agent_metrics.json",
            "target_metric":      "success_rate=0.000",
            "reason":             reason,
            "expected_effect":    effect,
            "execute_recommended": True,
            "status":             "pending",
        }

    # ─── 優先度4: 通知キューpending ───
    if queue_pending > 0:
        reason = f"送信失敗通知が{queue_pending}件キューに滞留。再送実行が必要"
        effect = EXPECTED_EFFECT_TEMPLATES["retry_alert_queue"]
        return {
            "generated_at":       now_jst,
            "priority":           "MEDIUM",
            "action_type":        "retry_alert_queue",
            "target_agent":       "",
            "target_log":         "logs/alert_queue.jsonl",
            "target_metric":      f"pending={queue_pending}",
            "reason":             reason,
            "expected_effect":    effect,
            "execute_recommended": True,
            "status":             "pending",
        }

    # ─── 優先度5: monitor_only ───
    reason = BLOCKER_REASON_TEMPLATES["monitor_only"]
    effect = EXPECTED_EFFECT_TEMPLATES["monitor_only"]
    return {
        "generated_at":       now_jst,
        "priority":           "LOW",
        "action_type":        "monitor_only",
        "target_agent":       "",
        "target_log":         "",
        "target_metric":      "",
        "reason":             reason,
        "expected_effect":    effect,
        "execute_recommended": False,
        "status":             "pending",
    }


def enqueue_action(record: dict) -> bool:
    """
    record を ceo_action_queue.jsonl に追記する。
    重複の場合は追記せず False を返す。
    """
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    recent = load_recent_queue(n=5)
    if _is_duplicate(record, recent):
        print(
            f"  [ceo_action] スキップ（重複）: {record['action_type']} / {record.get('target_agent','')}",
            file=sys.stderr,
        )
        return False
    with QUEUE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(
        f"  [ceo_action] 追記: priority={record['priority']} "
        f"type={record['action_type']} agent={record.get('target_agent','—')}",
        file=sys.stderr,
    )
    return True


def run() -> dict:
    """
    メイン実行。summary を読んで命令を生成・保存し、結果を返す。
    戻り値は dashboard_summary への追加フィールド用dict。
    """
    summary = load_summary()
    record  = build_action(summary)
    enqueue_action(record)

    return {
        "ceo_action_version":        "1.0",
        "ceo_action_generated_at":   record["generated_at"],
        "ceo_action_priority":       record["priority"],
        "ceo_action_type":           record["action_type"],
        "ceo_target_agent":          record.get("target_agent", ""),
        "ceo_target_log":            record.get("target_log", ""),
        "ceo_target_metric":         record.get("target_metric", ""),
        "ceo_expected_effect":       record.get("expected_effect", ""),
        "ceo_execute_recommended":   record.get("execute_recommended", False),
        "ceo_blocker_reason":        record.get("reason", ""),
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
