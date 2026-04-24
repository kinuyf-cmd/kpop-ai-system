#!/usr/bin/env python3
"""
cost_optimizer.py — コスト最適化エンジン（Phase 4）

月次API使用量レポートの自動生成、コスト削減提案をmewtwoに自動注入、
予算超過アラートの実装。

追跡対象:
  - Claude API（トークン消費: pipeline.jsonl + token_usage.jsonl）
  - WordPress REST API（呼び出し回数）
  - Google APIs（GSC/GA4/AdSense呼び出し回数）

Usage:
  python3 lib/cost_optimizer.py                    # 月次レポート生成
  python3 lib/cost_optimizer.py --daily            # 日次コストチェック
  python3 lib/cost_optimizer.py --inject            # mewtwoにコスト提案注入
  python3 lib/cost_optimizer.py --alert-check       # 予算超過アラートチェック
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"
AGENTS_DIR = BASE / "agents"

COST_REPORT = LOGS / "cost_report_monthly.json"
COST_LOG = LOGS / "cost_daily.jsonl"
COST_ALERT_LOG = LOGS / "cost_alerts.jsonl"
PIPELINE_LOG = LOGS / "pipeline.jsonl"
TOKEN_USAGE = LOGS / "token_usage.jsonl"
AUTO_DIRECTIVES = CONFIG / "auto_directives.json"
SAFETY_CONFIG = CONFIG / "safety_config.json"

JST = timezone(timedelta(hours=9))

# コスト定義（概算）
COST_PER_1K_INPUT_TOKENS = 0.015   # Claude Sonnet input
COST_PER_1K_OUTPUT_TOKENS = 0.075  # Claude Sonnet output
COST_PER_WP_CALL = 0.0            # WordPress API = 無料
COST_PER_GSC_CALL = 0.0           # Google APIs = 無料（quotaのみ）

# 月次予算上限（USD）
MONTHLY_BUDGET_USD = float(os.environ.get("MONTHLY_API_BUDGET", "100"))
DAILY_BUDGET_USD = MONTHLY_BUDGET_USD / 30
ALERT_THRESHOLD = 0.8  # 80%到達で警告


def _now_jst() -> str:
    return datetime.now(JST).isoformat()


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _get_month_range(target_month: date | None = None) -> tuple[str, str]:
    """月の開始日と終了日を返す"""
    if target_month is None:
        target_month = date.today()
    first = target_month.replace(day=1)
    if first.month == 12:
        last = first.replace(year=first.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        last = first.replace(month=first.month + 1, day=1) - timedelta(days=1)
    return first.isoformat(), last.isoformat()


def _count_pipeline_runs(start_date: str, end_date: str) -> dict:
    """pipeline.jsonl から期間内の実行回数を集計"""
    entries = _load_jsonl(PIPELINE_LOG)
    runs = {}
    agent_calls = {}
    total_runs = 0

    for entry in entries:
        ts = entry.get("timestamp", "")
        if not ts:
            continue
        entry_date = ts[:10]
        if entry_date < start_date or entry_date > end_date:
            continue

        run_id = entry.get("run_id", "unknown")
        step = entry.get("step", "unknown")

        if run_id not in runs:
            runs[run_id] = {"steps": 0, "date": entry_date}
            total_runs += 1
        runs[run_id]["steps"] += 1

        agent_calls[step] = agent_calls.get(step, 0) + 1

    return {
        "total_pipeline_runs": total_runs,
        "total_agent_calls": sum(agent_calls.values()),
        "agent_call_breakdown": dict(sorted(agent_calls.items(), key=lambda x: -x[1])[:20]),
        "daily_average_runs": round(total_runs / max((date.fromisoformat(end_date) - date.fromisoformat(start_date)).days, 1), 1),
    }


def _estimate_token_usage(start_date: str, end_date: str) -> dict:
    """トークン使用量を推定"""
    token_entries = _load_jsonl(TOKEN_USAGE)

    total_input = 0
    total_output = 0
    daily_usage = {}

    for entry in token_entries:
        ts = entry.get("timestamp", entry.get("date", ""))
        entry_date = ts[:10]
        if entry_date < start_date or entry_date > end_date:
            continue

        inp = entry.get("input_tokens", 0)
        out = entry.get("output_tokens", 0)
        total_input += inp
        total_output += out

        if entry_date not in daily_usage:
            daily_usage[entry_date] = {"input": 0, "output": 0}
        daily_usage[entry_date]["input"] += inp
        daily_usage[entry_date]["output"] += out

    # トークンデータがない場合、pipeline実行回数から推定
    if total_input == 0:
        pipeline_data = _count_pipeline_runs(start_date, end_date)
        agent_calls = pipeline_data["total_agent_calls"]
        # 1エージェント呼び出しあたり平均: 入力3000トークン、出力1500トークン
        total_input = agent_calls * 3000
        total_output = agent_calls * 1500

    input_cost = (total_input / 1000) * COST_PER_1K_INPUT_TOKENS
    output_cost = (total_output / 1000) * COST_PER_1K_OUTPUT_TOKENS
    total_cost = round(input_cost + output_cost, 2)

    return {
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "input_cost_usd": round(input_cost, 2),
        "output_cost_usd": round(output_cost, 2),
        "total_cost_usd": total_cost,
        "daily_usage": daily_usage,
    }


def _generate_cost_reduction_proposals(report: dict) -> list[dict]:
    """コスト削減提案を生成"""
    proposals = []
    token_data = report.get("token_usage", {})
    pipeline_data = report.get("pipeline_runs", {})
    total_cost = token_data.get("total_cost_usd", 0)

    # 1. エージェント呼び出し回数の最適化
    agent_breakdown = pipeline_data.get("agent_call_breakdown", {})
    high_call_agents = {k: v for k, v in agent_breakdown.items() if v > 100}
    if high_call_agents:
        proposals.append({
            "category": "agent_optimization",
            "title": "高頻度エージェント呼び出し最適化",
            "description": f"月間100回以上呼ばれるエージェント: {', '.join(high_call_agents.keys())}。"
                           f"キャッシュ機構やバッチ処理の導入を検討。",
            "estimated_savings_pct": 15,
            "priority": "medium",
        })

    # 2. 予算超過リスク
    budget_pct = total_cost / max(MONTHLY_BUDGET_USD, 1) * 100
    if budget_pct > 80:
        proposals.append({
            "category": "budget_alert",
            "title": "月次予算80%超過",
            "description": f"現在の使用額: ${total_cost:.2f} / ${MONTHLY_BUDGET_USD:.2f} ({budget_pct:.0f}%)。"
                           f"パイプライン実行頻度の削減またはモデルのダウングレードを検討。",
            "estimated_savings_pct": 30,
            "priority": "high",
        })

    # 3. 低ROI記事のパイプライン無駄
    daily_avg = pipeline_data.get("daily_average_runs", 0)
    if daily_avg > 10:
        proposals.append({
            "category": "pipeline_frequency",
            "title": "パイプライン実行頻度の最適化",
            "description": f"日平均{daily_avg:.1f}回実行。ピーク時間帯の統合や"
                           f"低トラフィック時間帯のスキップで20%削減可能。",
            "estimated_savings_pct": 20,
            "priority": "medium",
        })

    # 4. model_tier活用
    model_tier_file = CONFIG / "model_tier.json"
    if not model_tier_file.exists():
        proposals.append({
            "category": "model_tier",
            "title": "モデル段階分け導入",
            "description": "情報収集(butterfree)・フォーマット(alakazam)等の単純タスクに"
                           "Haikuを使用し、品質判定(gardevoir/arceus)にのみSonnetを維持。",
            "estimated_savings_pct": 40,
            "priority": "high",
        })

    # 5. 出力トークン過多
    if token_data.get("total_output_tokens", 0) > token_data.get("total_input_tokens", 0):
        proposals.append({
            "category": "output_optimization",
            "title": "出力トークン削減",
            "description": "出力が入力を上回っている。エージェントプロンプトに"
                           "max_tokens制限を設定し、不要な説明文の出力を抑制。",
            "estimated_savings_pct": 25,
            "priority": "medium",
        })

    return proposals


def _inject_to_mewtwo(proposals: list[dict]):
    """コスト削減提案をauto_directivesのmewtwoディレクティブに注入"""
    if not proposals:
        return

    ad = json.loads(AUTO_DIRECTIVES.read_text(encoding="utf-8"))

    # 高優先提案をmewtwoディレクティブに追加
    high_priority = [p for p in proposals if p["priority"] == "high"]
    if not high_priority:
        high_priority = proposals[:2]

    actions = "; ".join([p["description"][:80] for p in high_priority])

    ad["agent_directives"]["cost_optimization"] = {
        "problem": f"月次コスト最適化提案 ({len(proposals)}件)",
        "action": actions[:300],
        "proposal_count": len(proposals),
        "set_at": date.today().isoformat(),
        "source": "cost_optimizer",
    }

    ad["updated_at"] = datetime.now(JST).isoformat()
    AUTO_DIRECTIVES.write_text(
        json.dumps(ad, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"  auto_directives.json にコスト提案注入完了")


def check_budget_alert() -> bool:
    """予算超過アラートチェック"""
    today = date.today()
    start, _ = _get_month_range(today)
    token_data = _estimate_token_usage(start, today.isoformat())
    total_cost = token_data.get("total_cost_usd", 0)

    # 月の何日目か
    day_of_month = today.day
    days_in_month = 30  # 概算

    # 線形予測: 月末推定
    projected = total_cost * (days_in_month / max(day_of_month, 1))
    budget_pct = total_cost / max(MONTHLY_BUDGET_USD, 1)

    if budget_pct >= ALERT_THRESHOLD:
        alert = {
            "timestamp": _now_jst(),
            "level": "critical" if budget_pct >= 1.0 else "warning",
            "current_cost_usd": total_cost,
            "budget_usd": MONTHLY_BUDGET_USD,
            "usage_pct": round(budget_pct * 100, 1),
            "projected_monthly": round(projected, 2),
            "message": f"API予算 {budget_pct*100:.0f}% 到達 (${total_cost:.2f}/${MONTHLY_BUDGET_USD:.2f})",
        }

        LOGS.mkdir(parents=True, exist_ok=True)
        with open(COST_ALERT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(alert, ensure_ascii=False) + "\n")

        print(f"  ⚠️ {alert['message']}")
        print(f"     月末推定: ${projected:.2f}")

        if budget_pct >= 1.0:
            print(f"  🛑 予算超過 — パイプライン実行頻度の削減を検討してください")

        return True

    print(f"  ✅ 予算内: ${total_cost:.2f} / ${MONTHLY_BUDGET_USD:.2f} ({budget_pct*100:.0f}%)")
    return False


def generate_monthly_report(inject: bool = False) -> dict:
    """月次コストレポート生成"""
    today = date.today()
    start, end = _get_month_range(today)
    now_s = _now_jst()[:16]

    print(f"[{now_s}] 月次コストレポート生成 ({start} ~ {end})")

    # 1. パイプライン実行統計
    print("  [1/4] パイプライン実行統計...")
    pipeline_data = _count_pipeline_runs(start, today.isoformat())
    print(f"    → {pipeline_data['total_pipeline_runs']} runs, {pipeline_data['total_agent_calls']} agent calls")

    # 2. トークン使用量推定
    print("  [2/4] トークン使用量推定...")
    token_data = _estimate_token_usage(start, today.isoformat())
    print(f"    → 推定コスト: ${token_data['total_cost_usd']:.2f}")

    # 3. レポート構築
    report = {
        "generated_at": _now_jst(),
        "period": {"start": start, "end": today.isoformat()},
        "budget": {
            "monthly_limit_usd": MONTHLY_BUDGET_USD,
            "current_usage_usd": token_data["total_cost_usd"],
            "usage_pct": round(token_data["total_cost_usd"] / max(MONTHLY_BUDGET_USD, 1) * 100, 1),
            "remaining_usd": round(MONTHLY_BUDGET_USD - token_data["total_cost_usd"], 2),
        },
        "token_usage": token_data,
        "pipeline_runs": pipeline_data,
    }

    # 4. コスト削減提案
    print("  [3/4] コスト削減提案生成...")
    proposals = _generate_cost_reduction_proposals(report)
    report["cost_reduction_proposals"] = proposals
    print(f"    → {len(proposals)} 件の提案")

    # レポート保存
    LOGS.mkdir(parents=True, exist_ok=True)
    COST_REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # 日次ログ追記
    daily_log = {
        "date": today.isoformat(),
        "cost_usd": token_data["total_cost_usd"],
        "pipeline_runs": pipeline_data["total_pipeline_runs"],
        "agent_calls": pipeline_data["total_agent_calls"],
        "budget_pct": report["budget"]["usage_pct"],
    }
    with open(COST_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(daily_log, ensure_ascii=False) + "\n")

    # mewtwoへの注入
    if inject and proposals:
        print("  [4/4] mewtwoにコスト提案注入...")
        _inject_to_mewtwo(proposals)
    else:
        print("  [4/4] mewtwo注入スキップ")

    # レポート表示
    print(f"\n  === 月次コストレポート ===")
    print(f"  期間: {start} ~ {today.isoformat()}")
    print(f"  予算: ${MONTHLY_BUDGET_USD:.2f} / 使用: ${token_data['total_cost_usd']:.2f} ({report['budget']['usage_pct']:.0f}%)")
    print(f"  パイプライン実行: {pipeline_data['total_pipeline_runs']}回（日平均{pipeline_data['daily_average_runs']}）")
    print(f"  エージェント呼び出し: {pipeline_data['total_agent_calls']}回")

    if proposals:
        print(f"\n  --- コスト削減提案 ---")
        for i, p in enumerate(proposals, 1):
            icon = "🔴" if p["priority"] == "high" else "🟡"
            print(f"  {icon} {i}. [{p['category']}] {p['title']}")
            print(f"       推定削減: {p['estimated_savings_pct']}%")

    # 予算超過チェック
    print(f"\n  予算超過チェック...")
    check_budget_alert()

    print(f"\nレポート保存: {COST_REPORT}")
    return report


def main():
    parser = argparse.ArgumentParser(description="コスト最適化エンジン")
    parser.add_argument("--daily", action="store_true", help="日次コストチェック")
    parser.add_argument("--inject", action="store_true", help="mewtwoにコスト提案注入")
    parser.add_argument("--alert-check", action="store_true", help="予算超過アラートチェック")
    args = parser.parse_args()

    if args.alert_check:
        check_budget_alert()
    elif args.daily:
        # 日次は軽量チェックのみ
        check_budget_alert()
    else:
        generate_monthly_report(inject=args.inject)


if __name__ == "__main__":
    main()
