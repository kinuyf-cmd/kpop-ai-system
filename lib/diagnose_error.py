#!/usr/bin/env python3
"""
diagnose_error.py — Pipeline error pattern diagnosis and auto-remedy.

Reads pipeline.jsonl + pipeline_learning.log to classify errors,
propose fixes, and tag each with a safety_class (SAFE/REVIEW).
"""

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PIPELINE_LOG = BASE / "logs" / "pipeline.jsonl"
LEARNING_LOG = BASE / "logs" / "pipeline_learning.log"
ERROR_PATTERNS = BASE / "config" / "error_patterns.json"
AUTONOMY_MATRIX = BASE / "config" / "autonomy_matrix.json"

JST = timezone(timedelta(hours=9))


# Known error categories and their remedies
ERROR_TAXONOMY = {
    "empty_output": {
        "patterns": ["出力が空", "空出力", "empty output"],
        "safety_class": "SAFE",
        "remedy": "agent directive に min_output_chars=300 + fallback_template を追加",
        "category": "agent_quality",
    },
    "tiny_output": {
        "patterns": ["出力極小", "出力が極小", "bytes（エラー応答"],
        "safety_class": "SAFE",
        "remedy": "agent directive に min_output_chars=500 を設定、check_output 閾値以上を保証",
        "category": "agent_quality",
    },
    "boilerplate_response": {
        "patterns": ["エラー応答検出", "boilerplate", "申し訳ありません", "お手伝いできますか"],
        "safety_class": "SAFE",
        "remedy": "agent prompt に '質問しない・前置きしない・必ず出力する' を追記",
        "category": "agent_quality",
    },
    "score_fail": {
        "patterns": ["score=0", "score=?", "公開停止 score="],
        "safety_class": "REVIEW",
        "remedy": "gardevoir/arceus の評価基準見直し、または記事品質の根本改善",
        "category": "quality_gate",
    },
    "sanitize_empty": {
        "patterns": ["sanitize後極小", "定型文のみだった疑い"],
        "safety_class": "SAFE",
        "remedy": "post_write_sanitize の閾値調整、またはエージェントへの禁止フレーズ通知",
        "category": "sanitizer",
    },
    "x_post_fail": {
        "patterns": ["x_post", "X投稿"],
        "safety_class": "REVIEW",
        "remedy": "X API credential 確認、rate limit 待機ロジック追加",
        "category": "external_api",
    },
    "wp_post_fail": {
        "patterns": ["wordpress_post", "WP投稿"],
        "safety_class": "REVIEW",
        "remedy": "WP REST API 認証トークン更新、タイムアウト延長",
        "category": "external_api",
    },
    "archive_exit": {
        "patterns": ["archive_and_exit code=1"],
        "safety_class": "SAFE",
        "remedy": "上流ステップの出力品質改善（check_output 拒否が原因）",
        "category": "pipeline_flow",
    },
}


# Step-based classification when error text is empty
STEP_TAXONOMY = {
    "pipeline": {
        "type": "pipeline_flow_fail",
        "safety_class": "SAFE",
        "remedy": "上流エージェント出力の品質改善。check_output拒否（空出力/極小/boilerplate）が主因",
        "category": "pipeline_flow",
    },
    "gardevoir_hook_critic": {
        "type": "quality_gate_reject",
        "safety_class": "REVIEW",
        "remedy": "gardevoir評価基準の見直し。スコア閾値・must_fix条件の緩和を検討",
        "category": "quality_gate",
    },
    "butterfree": {
        "type": "agent_output_fail",
        "safety_class": "SAFE",
        "remedy": "butterfree directive に min_output_chars=300 + 3段階リトライ + fallback_template を適用",
        "category": "agent_quality",
    },
    "x_post": {
        "type": "x_post_fail",
        "safety_class": "REVIEW",
        "remedy": "X API credential 確認、rate limit 待機ロジック追加",
        "category": "external_api",
    },
    "wordpress_post": {
        "type": "wp_post_fail",
        "safety_class": "REVIEW",
        "remedy": "WP REST API 認証トークン更新、タイムアウト延長",
        "category": "external_api",
    },
    "snorlax": {
        "type": "agent_output_fail",
        "safety_class": "SAFE",
        "remedy": "snorlax directive の出力形式・最低文字数を明確化",
        "category": "agent_quality",
    },
    "mewtwo_strategy": {
        "type": "strategy_fail",
        "safety_class": "SAFE",
        "remedy": "mewtwo_strategy のプロンプト簡素化、出力フォーマット厳格化",
        "category": "agent_quality",
    },
}


def classify_error(error_text: str, step: str = "") -> dict:
    """Classify an error string into a known category."""
    error_lower = error_text.lower()

    # First try error text patterns
    if error_lower.strip():
        for etype, info in ERROR_TAXONOMY.items():
            for pattern in info["patterns"]:
                if pattern.lower() in error_lower:
                    return {
                        "type": etype,
                        "safety_class": info["safety_class"],
                        "remedy": info["remedy"],
                        "category": info["category"],
                    }

    # Fall back to step-based classification
    step_lower = step.lower()
    for step_key, info in STEP_TAXONOMY.items():
        if step_key in step_lower:
            return dict(info)

    # Default for unknown agents
    return {
        "type": "agent_output_fail",
        "safety_class": "SAFE",
        "remedy": f"{step} の出力品質改善。directive に最低出力要件を追加",
        "category": "agent_quality",
    }


def analyze_recent_errors(hours: int = 48) -> list[dict]:
    """Analyze recent pipeline errors and return diagnosed list."""
    if not PIPELINE_LOG.exists():
        return []

    cutoff = datetime.now(JST) - timedelta(hours=hours)
    errors = []

    for line in PIPELINE_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue

        status = rec.get("status", rec.get("result", ""))
        if status not in ("failed", "error", "hard_fail", "HARD_FAIL"):
            continue

        ts_str = rec.get("timestamp", "")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(JST)
        except ValueError:
            continue
        if ts < cutoff:
            continue

        error_text = rec.get("error", rec.get("reason", ""))
        step = rec.get("step", rec.get("agent", "unknown"))
        diagnosis = classify_error(error_text, step=step)

        errors.append({
            "timestamp": ts.isoformat(),
            "step": step,
            "error": error_text[:200],
            "diagnosis": diagnosis,
            "run_id": rec.get("run_id", ""),
        })

    return errors


def analyze_learning_log() -> dict:
    """Parse pipeline_learning.log for the latest failure distribution."""
    if not LEARNING_LOG.exists():
        return {}

    text = LEARNING_LOG.read_text(encoding="utf-8")
    # Get the last block (latest analysis)
    blocks = text.split("[pipeline_learning]")
    if len(blocks) < 2:
        return {}

    last_block = blocks[-1]
    result = {}

    # Extract completion rate
    m = re.search(r"完走率:\s*([\d.]+)%", last_block)
    if m:
        result["completion_rate"] = float(m.group(1))

    # Extract failure distribution
    m = re.search(r"最終失敗ステップ分布:\s*(\{.*?\})", last_block)
    if m:
        try:
            result["failure_distribution"] = eval(m.group(1))
        except Exception:
            pass

    # Extract top errors
    errors = []
    for m in re.finditer(r"-\s*\((\d+)回\)\s*(.+)", last_block):
        errors.append({"count": int(m.group(1)), "error": m.group(2).strip()})
    result["top_errors"] = errors[:10]

    return result


def generate_remedies(errors: list[dict]) -> list[dict]:
    """Generate actionable remedies grouped by category."""
    by_category = defaultdict(list)
    for e in errors:
        cat = e["diagnosis"]["category"]
        by_category[cat].append(e)

    remedies = []
    for cat, errs in sorted(by_category.items(), key=lambda x: -len(x[1])):
        safety_classes = set(e["diagnosis"]["safety_class"] for e in errs)
        overall_safety = "REVIEW" if "REVIEW" in safety_classes else "SAFE"

        remedy_texts = list(set(e["diagnosis"]["remedy"] for e in errs))
        affected_steps = list(set(e["step"] for e in errs))

        remedies.append({
            "category": cat,
            "count": len(errs),
            "safety_class": overall_safety,
            "affected_steps": affected_steps,
            "remedies": remedy_texts,
            "auto_applicable": overall_safety == "SAFE",
        })

    return remedies


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Pipeline Error Diagnosis")
    parser.add_argument("--hours", type=int, default=48, help="Hours to look back")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    print(f"=== Pipeline Error Diagnosis (直近{args.hours}h) ===\n")

    # 1. Recent errors
    errors = analyze_recent_errors(args.hours)
    print(f"検出エラー数: {len(errors)}")

    # 2. Learning log analysis
    learning = analyze_learning_log()
    if learning:
        print(f"完走率 (7日ローリング): {learning.get('completion_rate', '?')}%")
        dist = learning.get("failure_distribution", {})
        if dist:
            print(f"失敗ステップ分布: {json.dumps(dist, ensure_ascii=False)}")

    # 3. Generate remedies
    remedies = generate_remedies(errors)
    print(f"\n=== 対処提案 ({len(remedies)}カテゴリ) ===")
    for r in remedies:
        safety_icon = "🟢" if r["auto_applicable"] else "🔴"
        print(f"\n{safety_icon} [{r['category']}] {r['count']}件")
        print(f"   影響ステップ: {', '.join(r['affected_steps'])}")
        print(f"   安全クラス: {r['safety_class']}")
        for remedy in r["remedies"]:
            print(f"   → {remedy}")

    if args.json:
        output = {
            "analyzed_at": datetime.now(JST).isoformat(),
            "hours": args.hours,
            "error_count": len(errors),
            "learning_summary": learning,
            "remedies": remedies,
            "errors": errors,
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
