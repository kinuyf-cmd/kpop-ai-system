#!/usr/bin/env python3
"""
quality_auto_stop.py — 品質スコア監視→エージェント自動停止 v1.0

【責務】
  1. agent_metrics.json + pipeline.jsonl から品質スコアを追跡
  2. 品質スコア60点未満が3連続したエージェントを自動停止
  3. 停止時にDiscord urgent_errorsへアラート送信
  4. 停止されたエージェントの記録を logs/agent_auto_stopped.jsonl に保存
  5. 人間オーナーが手動復帰するまで該当エージェントをスキップ

【品質スコア算出】
  - 成功率 × 40点
  - (1 - 空出力率) × 20点
  - (1 - HARD_FAIL率) × 20点
  - (1 - 汚染率) × 20点
  合計100点満点

【安全制約】
  - arceus（最終監査官）は停止対象外（停止すると全パイプライン停止）
  - MANUAL_ONLY / DEPRECATED エージェントは対象外
  - 停止は EMERGENCY_STOP ファイルではなく agent_stopped.json で管理

Usage:
  python3 lib/quality_auto_stop.py              # 通常実行
  python3 lib/quality_auto_stop.py --dry-run    # 判定のみ
  python3 lib/quality_auto_stop.py --status     # 停止中エージェント一覧
  python3 lib/quality_auto_stop.py --restore AGENT_ID  # 手動復帰
"""
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

# ── パス定義 ──
METRICS_PATH = BASE / "agent_metrics.json"
STOPPED_PATH = CONFIG / "agent_stopped.json"
SCORE_HISTORY_PATH = LOGS / "quality_score_history.jsonl"
STOP_LOG_PATH = LOGS / "agent_auto_stopped.jsonl"

# ── 閾値 ──
QUALITY_SCORE_THRESHOLD = 60     # この点数未満が連続すると停止
CONSECUTIVE_LOW_THRESHOLD = 3    # 連続回数
QUALITY_SCORE_WEIGHTS = {
    "success_rate": 40,
    "no_empty_output": 20,
    "no_hard_fail": 20,
    "no_contamination": 20,
}

# ── 停止対象外エージェント ──
STOP_EXEMPT = {
    "arceus",         # 最終監査官（停止=全パイプライン停止）
    "pipeline",       # パイプライン制御（停止不可）
    "wordpress_post", # WP投稿（停止=収益停止）
}
STOP_EXEMPT_CLASSES = {"MANUAL_ONLY", "DEPRECATED"}


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


# ═══════════════════════════════════════════════════════════════
# 品質スコア算出
# ═══════════════════════════════════════════════════════════════

def calculate_quality_score(agent_data: dict) -> float:
    """
    エージェントの品質スコアを算出する（0-100点）。

    構成:
      success_rate      × 40点
      (1 - empty_rate)  × 20点
      (1 - hf_rate)     × 20点
      (1 - contam_rate) × 20点
    """
    total = agent_data.get("total_count", 0)
    if total == 0:
        return 100.0  # 未実行は停止しない

    sr = agent_data.get("success_rate", 1.0) or 0
    empty = agent_data.get("empty_output_count", 0) or 0
    hf = agent_data.get("hard_fail_count", 0) or 0
    contam = agent_data.get("contamination_count", 0) or 0

    empty_rate = min(empty / total, 1.0) if total > 0 else 0
    hf_rate = min(hf / total, 1.0) if total > 0 else 0
    contam_rate = min(contam / total, 1.0) if total > 0 else 0

    score = (
        sr * QUALITY_SCORE_WEIGHTS["success_rate"]
        + (1 - empty_rate) * QUALITY_SCORE_WEIGHTS["no_empty_output"]
        + (1 - hf_rate) * QUALITY_SCORE_WEIGHTS["no_hard_fail"]
        + (1 - contam_rate) * QUALITY_SCORE_WEIGHTS["no_contamination"]
    )

    return round(score, 1)


def score_all_agents() -> dict[str, dict]:
    """全エージェントの品質スコアを算出する。"""
    metrics = _load_json(METRICS_PATH)
    agents = metrics.get("agents", {})
    scores = {}

    for agent_id, data in agents.items():
        role_class = data.get("role_class", "")
        if role_class in STOP_EXEMPT_CLASSES:
            continue

        score = calculate_quality_score(data)
        scores[agent_id] = {
            "score": score,
            "name_ja": data.get("name_ja", agent_id),
            "role_class": role_class,
            "success_rate": data.get("success_rate", 0),
            "total_count": data.get("total_count", 0),
            "empty_output_count": data.get("empty_output_count", 0),
            "hard_fail_count": data.get("hard_fail_count", 0),
            "contamination_count": data.get("contamination_count", 0),
        }

    return scores


# ═══════════════════════════════════════════════════════════════
# 品質スコア履歴管理
# ═══════════════════════════════════════════════════════════════

def record_scores(scores: dict[str, dict]):
    """品質スコアを履歴に記録する。"""
    LOGS.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": NOW.isoformat(),
        "scores": {aid: s["score"] for aid, s in scores.items()},
    }
    with SCORE_HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_consecutive_low_scores(agent_id: str) -> int:
    """指定エージェントの連続低スコア回数を取得する。"""
    records = _load_jsonl(SCORE_HISTORY_PATH)
    consecutive = 0

    for rec in reversed(records):
        agent_scores = rec.get("scores", {})
        score = agent_scores.get(agent_id)
        if score is None:
            continue
        if score < QUALITY_SCORE_THRESHOLD:
            consecutive += 1
        else:
            break

    return consecutive


# ═══════════════════════════════════════════════════════════════
# エージェント自動停止
# ═══════════════════════════════════════════════════════════════

def load_stopped_agents() -> dict:
    """停止中エージェント一覧を読み込む。"""
    return _load_json(STOPPED_PATH)


def save_stopped_agents(stopped: dict):
    """停止中エージェント一覧を保存する。"""
    CONFIG.mkdir(parents=True, exist_ok=True)
    STOPPED_PATH.write_text(
        json.dumps(stopped, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def stop_agent(agent_id: str, score_data: dict, consecutive: int,
               dry_run: bool = False) -> dict:
    """エージェントを自動停止する。"""
    if agent_id in STOP_EXEMPT:
        return {"stopped": False, "reason": f"{agent_id} is exempt from auto-stop"}

    if dry_run:
        print(f"[DRY-RUN] 自動停止: {agent_id} "
              f"(スコア={score_data['score']}, 連続{consecutive}回)")
        return {"stopped": False, "reason": "dry_run"}

    stopped = load_stopped_agents()
    if agent_id in stopped:
        return {"stopped": False, "reason": "already_stopped"}

    # 停止記録
    stop_entry = {
        "agent_id": agent_id,
        "name_ja": score_data.get("name_ja", agent_id),
        "stopped_at": NOW.isoformat(),
        "quality_score": score_data["score"],
        "consecutive_low_count": consecutive,
        "reason": f"品質スコア{score_data['score']}点が{consecutive}回連続でしきい値{QUALITY_SCORE_THRESHOLD}点未満",
        "auto_stopped": True,
    }

    stopped[agent_id] = stop_entry
    save_stopped_agents(stopped)

    # ログ記録
    LOGS.mkdir(parents=True, exist_ok=True)
    with STOP_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(stop_entry, ensure_ascii=False) + "\n")

    return {"stopped": True, "entry": stop_entry}


def restore_agent(agent_id: str) -> dict:
    """停止中のエージェントを手動復帰させる。"""
    stopped = load_stopped_agents()
    if agent_id not in stopped:
        return {"restored": False, "reason": f"{agent_id} is not stopped"}

    entry = stopped.pop(agent_id)
    save_stopped_agents(stopped)

    # 復帰ログ
    restore_entry = {
        "agent_id": agent_id,
        "name_ja": entry.get("name_ja", agent_id),
        "restored_at": NOW.isoformat(),
        "was_stopped_at": entry.get("stopped_at", ""),
        "action": "manual_restore",
    }
    with STOP_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(restore_entry, ensure_ascii=False) + "\n")

    return {"restored": True, "entry": restore_entry}


# ═══════════════════════════════════════════════════════════════
# Discord通知
# ═══════════════════════════════════════════════════════════════

def send_stop_alert(agent_id: str, score_data: dict, consecutive: int,
                    dry_run: bool = False) -> str:
    """エージェント停止をDiscordに通知する。"""
    if dry_run:
        return "dry_run"

    try:
        sys.path.insert(0, str(BASE / "lib"))
        from discord_notifier import send_discord, CHANNEL_CRITICAL, COLOR_CRITICAL

        name_ja = score_data.get("name_ja", agent_id)
        title = f"🛑 エージェント自動停止: {name_ja}"
        body = (
            f"**{name_ja}（{agent_id}）が品質基準を満たさず自動停止されました。**\n\n"
            f"- 品質スコア: **{score_data['score']}点** / 100点\n"
            f"- 連続低スコア: **{consecutive}回** (しきい値: {CONSECUTIVE_LOW_THRESHOLD}回)\n"
            f"- 成功率: {score_data.get('success_rate', 0):.0%}\n"
            f"- 空出力: {score_data.get('empty_output_count', 0)}回\n"
            f"- HARD_FAIL: {score_data.get('hard_fail_count', 0)}回\n"
            f"- 汚染: {score_data.get('contamination_count', 0)}回\n\n"
            f"**復帰方法**: `python3 lib/quality_auto_stop.py --restore {agent_id}`\n"
            f"**確認ログ**: `logs/agent_auto_stopped.jsonl`"
        )
        event_key = f"AGENT_STOP__{agent_id}__{NOW.strftime('%Y%m%d')}"

        return send_discord(
            CHANNEL_CRITICAL, title, body, COLOR_CRITICAL,
            event_key, "CRITICAL", dry_run=False,
        )
    except Exception as e:
        print(f"  [quality_auto_stop] Discord通知エラー: {e}", file=sys.stderr)
        return f"error: {e}"


# ═══════════════════════════════════════════════════════════════
# 停止チェック関数（パイプラインから呼ばれる）
# ═══════════════════════════════════════════════════════════════

def is_agent_stopped(agent_id: str) -> bool:
    """エージェントが自動停止中かどうかを返す。パイプラインのステップ実行前に呼ぶ。"""
    stopped = load_stopped_agents()
    return agent_id in stopped


# ═══════════════════════════════════════════════════════════════
# メイン実行
# ═══════════════════════════════════════════════════════════════

def run(dry_run: bool = False) -> dict:
    """全エージェントの品質スコアを確認し、必要なら停止する。"""
    print(f"[quality_auto_stop] {NOW.isoformat()} 開始", file=sys.stderr)

    # 1. 全エージェントのスコアを算出
    scores = score_all_agents()
    print(f"  スコア算出: {len(scores)}エージェント", file=sys.stderr)

    # 2. スコアを記録
    record_scores(scores)

    # 3. 低スコアエージェントを検出
    result = {
        "total_scored": len(scores),
        "below_threshold": 0,
        "newly_stopped": [],
        "already_stopped": [],
    }

    for agent_id, score_data in scores.items():
        if score_data["score"] >= QUALITY_SCORE_THRESHOLD:
            continue

        result["below_threshold"] += 1
        consecutive = get_consecutive_low_scores(agent_id)

        print(f"  ⚠️ {score_data['name_ja']}({agent_id}): "
              f"スコア={score_data['score']}点, 連続{consecutive}回", file=sys.stderr)

        if consecutive >= CONSECUTIVE_LOW_THRESHOLD:
            # 自動停止実行
            stop_result = stop_agent(agent_id, score_data, consecutive, dry_run)
            if stop_result.get("stopped"):
                result["newly_stopped"].append(agent_id)
                # Discord通知
                send_stop_alert(agent_id, score_data, consecutive, dry_run)
                print(f"  🛑 {agent_id} を自動停止しました", file=sys.stderr)
            elif stop_result.get("reason") == "already_stopped":
                result["already_stopped"].append(agent_id)

    if not result["newly_stopped"]:
        print("  ✅ 新規停止なし", file=sys.stderr)

    print(f"[quality_auto_stop] 完了: below_threshold={result['below_threshold']}, "
          f"newly_stopped={len(result['newly_stopped'])}", file=sys.stderr)
    return result


def print_status():
    """停止中エージェントの一覧を表示する。"""
    stopped = load_stopped_agents()
    if not stopped:
        print("停止中のエージェントはありません。")
        return

    print(f"\n=== 停止中エージェント ({len(stopped)}件) ===\n")
    for agent_id, entry in stopped.items():
        print(f"  🛑 {entry.get('name_ja', agent_id)} ({agent_id})")
        print(f"     停止日時: {entry.get('stopped_at', '-')}")
        print(f"     スコア: {entry.get('quality_score', '-')}点")
        print(f"     理由: {entry.get('reason', '-')}")
        print()

    print(f"復帰方法: python3 lib/quality_auto_stop.py --restore <agent_id>")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="品質スコア監視→エージェント自動停止 v1.0")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true", help="停止中エージェント一覧")
    parser.add_argument("--restore", type=str, help="エージェントを手動復帰")
    args = parser.parse_args()

    if args.status:
        print_status()
    elif args.restore:
        result = restore_agent(args.restore)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        result = run(dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
