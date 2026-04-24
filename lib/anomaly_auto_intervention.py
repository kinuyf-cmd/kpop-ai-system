#!/usr/bin/env python3
"""
anomaly_auto_intervention.py — 異常検知→自動介入システム v1.0

【責務】
  1. CTR 30%下落検知 → mewtwoに緊急議題を自動注入
  2. パイプライン3連続失敗 → 即時auto_repair起動
  3. PV 50%下落検知 → mewtwoに緊急レポート注入
  4. 全異常をDiscord urgent_errors チャネルに即時通知

【安全制約】
  - auto_repair は1日最大3回まで（暴走防止）
  - mewtwo議題注入は既存の人間管理セクションに触れない（AUTO-LEARNED内のみ）
  - 全介入はログに記録（logs/anomaly_interventions.jsonl）

Usage:
  python3 lib/anomaly_auto_intervention.py              # 通常実行
  python3 lib/anomaly_auto_intervention.py --dry-run    # 判定のみ
  python3 lib/anomaly_auto_intervention.py --stats      # 統計表示
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
AGENTS = BASE / "agents"
CONFIG = BASE / "config"
GOOGLE_METRICS = BASE / "google_metrics"

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)

# ── パス定義 ──
INTERVENTION_LOG = LOGS / "anomaly_interventions.jsonl"
PIPELINE_LOG = LOGS / "pipeline.jsonl"
KPI_ERROR_LOG = LOGS / "kpi_errors.jsonl"
SAFETY_CONFIG_PATH = CONFIG / "safety_config.json"
METRICS_PATH = GOOGLE_METRICS / "metrics_yesterday.json"
METRICS_HISTORY_DIR = GOOGLE_METRICS  # metrics_yesterday.json の履歴
MEWTWO_PATH = AGENTS / "mewtwo.md"

# ── 閾値 ──
CTR_DROP_THRESHOLD = 0.30        # 30%下落
PV_DROP_THRESHOLD = 0.50         # 50%下落
CONSECUTIVE_FAILURE_THRESHOLD = 3  # 連続失敗回数
MAX_AUTO_REPAIR_PER_DAY = 3      # 1日あたりのauto_repair上限
EMERGENCY_AGENDA_COOLDOWN_HOURS = 6  # 同種の緊急議題の再注入間隔
DISCORD_COOLDOWN_HOURS = 6           # 同一エラーのDiscord再通知間隔

# ── Discord通知クールダウン ──
DISCORD_COOLDOWN_FILE = LOGS / "discord_cooldown.json"


def _load_discord_cooldown() -> dict:
    if not DISCORD_COOLDOWN_FILE.exists():
        return {}
    try:
        return json.loads(DISCORD_COOLDOWN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_discord_cooldown(state: dict) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    DISCORD_COOLDOWN_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _is_discord_cooled(event_key: str) -> bool:
    """同一エラーが DISCORD_COOLDOWN_HOURS 以内に通知済みか"""
    state = _load_discord_cooldown()
    last_str = state.get(event_key)
    if not last_str:
        return False
    try:
        last_dt = datetime.fromisoformat(last_str)
        elapsed = (NOW - last_dt).total_seconds()
        if elapsed < DISCORD_COOLDOWN_HOURS * 3600:
            return True
    except Exception:
        pass
    return False


def _mark_discord_sent(event_key: str) -> None:
    state = _load_discord_cooldown()
    state[event_key] = NOW.isoformat()
    # 古いエントリを掃除（7日超）
    cutoff = (NOW - timedelta(days=7)).isoformat()
    state = {k: v for k, v in state.items() if v >= cutoff}
    _save_discord_cooldown(state)


def _load_json(p: Path) -> dict | list:
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


def _append_log(entry: dict):
    LOGS.mkdir(parents=True, exist_ok=True)
    with INTERVENTION_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _today_interventions() -> list[dict]:
    """本日の介入ログを取得する。"""
    today = date.today().isoformat()
    return [r for r in _load_jsonl(INTERVENTION_LOG)
            if r.get("timestamp", "").startswith(today)]


def _recent_intervention(intervention_type: str, hours: int = 6) -> bool:
    """指定時間内に同種の介入があったかチェック（クールダウン）。"""
    cutoff = (NOW - timedelta(hours=hours)).isoformat()
    for r in reversed(_load_jsonl(INTERVENTION_LOG)):
        if r.get("intervention_type") == intervention_type and r.get("timestamp", "") >= cutoff:
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# 検知1: CTR下落検知
# ═══════════════════════════════════════════════════════════════

def detect_ctr_drop() -> dict | None:
    """GSCデータからCTR 30%下落を検知する。"""
    metrics = _load_json(METRICS_PATH)
    gsc = metrics.get("gsc", {})
    top_pages = gsc.get("top_pages", [])

    if not top_pages:
        return None

    # 全体の平均CTR
    total_clicks = sum(p.get("clicks", 0) for p in top_pages)
    total_impressions = sum(p.get("impressions", 0) for p in top_pages)
    if total_impressions == 0:
        return None

    current_ctr = total_clicks / total_impressions

    # 前回のメトリクスと比較（metrics_history.jsonl）
    history_path = LOGS / "metrics_history.jsonl"
    previous_records = _load_jsonl(history_path)

    # 直近7日間のCTRの平均を取得
    recent_ctrs = []
    for rec in previous_records[-7:]:
        prev_gsc = rec.get("gsc", {})
        prev_pages = prev_gsc.get("top_pages", [])
        if prev_pages:
            pc = sum(p.get("clicks", 0) for p in prev_pages)
            pi = sum(p.get("impressions", 0) for p in prev_pages)
            if pi > 0:
                recent_ctrs.append(pc / pi)

    if not recent_ctrs:
        # 履歴がない場合は、safety_configの閾値と比較
        config = _load_json(SAFETY_CONFIG_PATH)
        threshold = config.get("anomaly_detection", {}).get("ctr_drop_threshold", 0.3)
        # 初回は検知しない（比較対象なし）
        return None

    avg_ctr = sum(recent_ctrs) / len(recent_ctrs)
    if avg_ctr == 0:
        return None

    drop_rate = (avg_ctr - current_ctr) / avg_ctr

    if drop_rate >= CTR_DROP_THRESHOLD:
        return {
            "type": "ctr_drop",
            "current_ctr": current_ctr,
            "avg_ctr_7d": avg_ctr,
            "drop_rate": drop_rate,
            "severity": "critical" if drop_rate >= 0.5 else "warning",
        }

    return None


# ═══════════════════════════════════════════════════════════════
# 検知2: パイプライン連続失敗
# ═══════════════════════════════════════════════════════════════

def detect_consecutive_pipeline_failures() -> dict | None:
    """パイプラインの3連続失敗を検知する。"""
    pipeline_records = _load_jsonl(PIPELINE_LOG)
    if not pipeline_records:
        # pipeline.jsonlがなければ kpi_errors.jsonl を参照
        error_records = _load_jsonl(KPI_ERROR_LOG)
        today = date.today().isoformat()
        today_errors = [e for e in error_records
                        if e.get("date") == today and not e.get("recoverable", True)]
        if len(today_errors) >= CONSECUTIVE_FAILURE_THRESHOLD:
            return {
                "type": "consecutive_failures",
                "count": len(today_errors),
                "last_errors": [e.get("message", "")[:100] for e in today_errors[-3:]],
                "severity": "critical",
            }
        return None

    # 直近のパイプライン結果から連続失敗を検出
    recent = pipeline_records[-10:]
    consecutive_fails = 0
    fail_details = []

    for rec in reversed(recent):
        status = rec.get("status", rec.get("result", ""))
        if status in ("failed", "error", "timeout", "BLOCK"):
            consecutive_fails += 1
            fail_details.append({
                "step": rec.get("step", "unknown"),
                "error": str(rec.get("error", rec.get("message", "")))[:100],
                "timestamp": rec.get("timestamp", rec.get("ts", "")),
            })
        else:
            break

    if consecutive_fails >= CONSECUTIVE_FAILURE_THRESHOLD:
        return {
            "type": "consecutive_failures",
            "count": consecutive_fails,
            "details": fail_details[:5],
            "severity": "critical",
        }

    return None


# ═══════════════════════════════════════════════════════════════
# 検知3: PV急落
# ═══════════════════════════════════════════════════════════════

def detect_pv_drop() -> dict | None:
    """GA4データからPV 50%下落を検知する。"""
    metrics = _load_json(METRICS_PATH)
    ga4 = metrics.get("ga4", {})
    summary = ga4.get("summary", {})
    current_pv = int(summary.get("pageviews", 0))

    if current_pv == 0:
        return None

    # 履歴から7日平均PVを取得
    history = _load_jsonl(LOGS / "metrics_history.jsonl")
    recent_pvs = []
    for rec in history[-7:]:
        pv = int(rec.get("ga4", {}).get("summary", {}).get("pageviews", 0))
        if pv > 0:
            recent_pvs.append(pv)

    if not recent_pvs:
        return None

    avg_pv = sum(recent_pvs) / len(recent_pvs)
    if avg_pv == 0:
        return None

    drop_rate = (avg_pv - current_pv) / avg_pv

    if drop_rate >= PV_DROP_THRESHOLD:
        return {
            "type": "pv_drop",
            "current_pv": current_pv,
            "avg_pv_7d": avg_pv,
            "drop_rate": drop_rate,
            "severity": "critical",
        }

    return None


# ═══════════════════════════════════════════════════════════════
# 介入1: mewtwo緊急議題注入
# ═══════════════════════════════════════════════════════════════

def inject_emergency_agenda_to_mewtwo(anomalies: list[dict], dry_run: bool = False) -> dict:
    """検知した異常をmewtwoのAUTO-LEARNEDセクションに緊急議題として注入する。"""
    if not anomalies:
        return {"injected": False, "reason": "no anomalies"}

    if _recent_intervention("mewtwo_emergency_agenda", EMERGENCY_AGENDA_COOLDOWN_HOURS):
        return {"injected": False, "reason": "cooldown active"}

    # 緊急議題テキスト生成
    agenda_lines = [
        "",
        "---",
        "",
        f"## 🚨 緊急議題（自動検知: {NOW.strftime('%Y-%m-%d %H:%M JST')}）",
        "",
        "**以下の異常が自動検知されました。CEO判断で優先対応を指示してください。**",
        "",
    ]

    for anomaly in anomalies:
        atype = anomaly["type"]
        severity = anomaly.get("severity", "warning")
        icon = "🔴" if severity == "critical" else "🟡"

        if atype == "ctr_drop":
            agenda_lines.extend([
                f"{icon} **CTR急落検知**",
                f"  - 現在CTR: {anomaly['current_ctr']:.2%} (7日平均: {anomaly['avg_ctr_7d']:.2%})",
                f"  - 下落率: **{anomaly['drop_rate']:.0%}**",
                f"  - 推奨: metamon/deoxysにタイトルリライト緊急指示、laprasにSEO分析を依頼",
                "",
            ])
        elif atype == "consecutive_failures":
            details = anomaly.get("details", anomaly.get("last_errors", []))
            agenda_lines.extend([
                f"{icon} **パイプライン{anomaly['count']}連続失敗**",
                f"  - 直近エラー: {details[0] if details else '不明'}",
                f"  - 推奨: auto_repairを起動し、失敗ステップのconfig/promptを修正",
                "",
            ])
        elif atype == "pv_drop":
            agenda_lines.extend([
                f"{icon} **PV急落検知**",
                f"  - 現在PV: {anomaly['current_pv']} (7日平均: {anomaly['avg_pv_7d']:.0f})",
                f"  - 下落率: **{anomaly['drop_rate']:.0%}**",
                f"  - 推奨: SEOペナルティ・サーバー障害・季節変動を切り分けて調査",
                "",
            ])

    agenda_lines.append("**対応後はこのセクションが次回更新時に上書きされます。**")

    agenda_body = "\n".join(agenda_lines)

    if dry_run:
        print(f"[DRY-RUN] mewtwo緊急議題注入: {len(anomalies)}件")
        print(agenda_body[:500])
        return {"injected": False, "reason": "dry_run", "anomaly_count": len(anomalies)}

    # mewtwo.mdのAUTO-LEARNEDセクションに注入
    if not MEWTWO_PATH.exists():
        return {"injected": False, "reason": "mewtwo.md not found"}

    sys.path.insert(0, str(BASE / "lib"))
    from apply_learning_to_agents import _rewrite_auto_section, START_MARK, END_MARK

    content = MEWTWO_PATH.read_text(encoding="utf-8")
    # 既存のAUTO-LEARNEDブロックを取得
    pattern = re.compile(
        re.escape(START_MARK) + r"(.*?)" + re.escape(END_MARK),
        re.DOTALL,
    )
    m = pattern.search(content)
    existing = m.group(1) if m else ""

    # 既存の緊急議題セクションを置換
    emergency_marker = "## 🚨 緊急議題"
    if emergency_marker in existing:
        parts = existing.split(emergency_marker)
        before = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        next_section = re.search(r'\n## ', rest)
        after = rest[next_section.start():] if next_section else ""
        new_block = before.rstrip() + agenda_body + after
    else:
        new_block = existing.rstrip() + agenda_body

    changed, reason = _rewrite_auto_section(MEWTWO_PATH, new_block)

    _append_log({
        "timestamp": NOW.isoformat(),
        "intervention_type": "mewtwo_emergency_agenda",
        "anomaly_count": len(anomalies),
        "anomaly_types": [a["type"] for a in anomalies],
        "result": "injected" if changed else reason,
    })

    return {"injected": changed, "anomaly_count": len(anomalies)}


# ═══════════════════════════════════════════════════════════════
# 介入2: auto_repair起動
# ═══════════════════════════════════════════════════════════════

def trigger_auto_repair(failure_info: dict, dry_run: bool = False) -> dict:
    """パイプライン連続失敗時にauto_repairを起動する。"""
    # 本日のauto_repair回数チェック
    today_interventions = _today_interventions()
    repair_count = sum(1 for r in today_interventions
                       if r.get("intervention_type") == "auto_repair")

    if repair_count >= MAX_AUTO_REPAIR_PER_DAY:
        msg = f"auto_repair上限到達 ({repair_count}/{MAX_AUTO_REPAIR_PER_DAY})"
        _append_log({
            "timestamp": NOW.isoformat(),
            "intervention_type": "auto_repair",
            "result": "blocked",
            "reason": msg,
        })
        return {"triggered": False, "reason": msg}

    if _recent_intervention("auto_repair", hours=1):
        return {"triggered": False, "reason": "cooldown_1h"}

    if dry_run:
        print(f"[DRY-RUN] auto_repair起動: {failure_info.get('count', 0)}連続失敗")
        return {"triggered": False, "reason": "dry_run"}

    # ceo_auto_executor のrun_auto_cycleを呼び出す
    try:
        sys.path.insert(0, str(BASE / "lib"))
        from ceo_auto_executor import run_auto_cycle
        result = run_auto_cycle()

        _append_log({
            "timestamp": NOW.isoformat(),
            "intervention_type": "auto_repair",
            "failure_count": failure_info.get("count", 0),
            "result": "triggered",
            "auto_cycle_result": {
                "rollback": result.get("rollback", {}).get("executed", 0),
                "unlock": result.get("unlock", {}).get("executed", 0),
            },
        })

        return {"triggered": True, "cycle_result": result}

    except Exception as e:
        _append_log({
            "timestamp": NOW.isoformat(),
            "intervention_type": "auto_repair",
            "result": "error",
            "error": str(e)[:200],
        })
        return {"triggered": False, "reason": f"error: {e}"}


# ═══════════════════════════════════════════════════════════════
# 介入3: Discord緊急通知
# ═══════════════════════════════════════════════════════════════

def send_anomaly_alerts(anomalies: list[dict], dry_run: bool = False) -> dict:
    """検知した異常をDiscord urgent_errorsに送信する。"""
    if not anomalies:
        return {"sent": 0}

    try:
        sys.path.insert(0, str(BASE / "lib"))
        from discord_notifier import send_discord, CHANNEL_CRITICAL, COLOR_CRITICAL
    except ImportError:
        return {"sent": 0, "error": "discord_notifier import failed"}

    sent = 0
    skipped = 0
    for anomaly in anomalies:
        atype = anomaly["type"]
        severity = anomaly.get("severity", "warning")

        # クールダウンチェック: 同一エラーは6時間以内に再通知しない
        cooldown_key = f"anomaly_{atype}"
        if _is_discord_cooled(cooldown_key):
            print(f"  ℹ️ [{atype}] Discord通知クールダウン中 → スキップ", file=sys.stderr)
            skipped += 1
            continue

        if atype == "ctr_drop":
            title = f"🚨 CTR急落検知: {anomaly['drop_rate']:.0%}下落"
            body = (
                f"**CTRが7日平均から{anomaly['drop_rate']:.0%}下落しました。**\n\n"
                f"- 現在CTR: {anomaly['current_ctr']:.2%}\n"
                f"- 7日平均: {anomaly['avg_ctr_7d']:.2%}\n\n"
                f"**対応**: mewtwoに緊急議題を注入済み。"
                f"metamon/deoxysにタイトルリライトを優先指示中。"
            )
        elif atype == "consecutive_failures":
            title = f"🚨 パイプライン{anomaly['count']}連続失敗"
            body = (
                f"**パイプラインが{anomaly['count']}回連続で失敗しています。**\n\n"
                f"auto_repairを自動起動しました。\n"
                f"**確認ログ**: `logs/pipeline.jsonl` を確認してください。"
            )
        elif atype == "pv_drop":
            title = f"🚨 PV急落検知: {anomaly['drop_rate']:.0%}下落"
            body = (
                f"**PVが7日平均から{anomaly['drop_rate']:.0%}下落しました。**\n\n"
                f"- 現在PV: {anomaly['current_pv']}\n"
                f"- 7日平均: {anomaly['avg_pv_7d']:.0f}\n\n"
                f"**確認**: SEOペナルティ・サーバー障害・季節変動を調査してください。"
            )
        else:
            continue

        event_key = f"ANOMALY_{atype}__{NOW.strftime('%Y%m%d')}"

        if dry_run:
            print(f"[DRY-RUN] Discord通知: {title}")
            sent += 1
            continue

        result = send_discord(
            CHANNEL_CRITICAL, title, body, COLOR_CRITICAL,
            event_key, "CRITICAL", dry_run=False,
        )
        if result == "sent":
            sent += 1
            _mark_discord_sent(cooldown_key)

    return {"sent": sent, "skipped_cooldown": skipped}


# ═══════════════════════════════════════════════════════════════
# メイン実行
# ═══════════════════════════════════════════════════════════════

def run(dry_run: bool = False) -> dict:
    """全異常検知を実行し、必要な介入を行う。"""
    print(f"[anomaly_auto_intervention] {NOW.isoformat()} 開始", file=sys.stderr)

    anomalies = []
    result = {
        "ctr_drop": None,
        "consecutive_failures": None,
        "pv_drop": None,
        "interventions": [],
    }

    # 検知1: CTR下落
    ctr_drop = detect_ctr_drop()
    if ctr_drop:
        anomalies.append(ctr_drop)
        result["ctr_drop"] = ctr_drop
        print(f"  🔴 CTR急落検知: {ctr_drop['drop_rate']:.0%}下落", file=sys.stderr)

    # 検知2: パイプライン連続失敗
    pipeline_fail = detect_consecutive_pipeline_failures()
    if pipeline_fail:
        anomalies.append(pipeline_fail)
        result["consecutive_failures"] = pipeline_fail
        print(f"  🔴 パイプライン{pipeline_fail['count']}連続失敗検知", file=sys.stderr)

    # 検知3: PV急落
    pv_drop = detect_pv_drop()
    if pv_drop:
        anomalies.append(pv_drop)
        result["pv_drop"] = pv_drop
        print(f"  🔴 PV急落検知: {pv_drop['drop_rate']:.0%}下落", file=sys.stderr)

    if not anomalies:
        print("  ✅ 異常なし", file=sys.stderr)
        return result

    # 介入1: mewtwo緊急議題注入
    agenda_result = inject_emergency_agenda_to_mewtwo(anomalies, dry_run)
    result["interventions"].append({"type": "mewtwo_agenda", **agenda_result})

    # 介入2: パイプライン連続失敗時のauto_repair
    if pipeline_fail:
        repair_result = trigger_auto_repair(pipeline_fail, dry_run)
        result["interventions"].append({"type": "auto_repair", **repair_result})

    # 介入3: Discord通知
    alert_result = send_anomaly_alerts(anomalies, dry_run)
    result["interventions"].append({"type": "discord_alert", **alert_result})

    print(f"[anomaly_auto_intervention] 完了: 異常{len(anomalies)}件、"
          f"介入{len(result['interventions'])}件", file=sys.stderr)
    return result


def print_stats():
    records = _load_jsonl(INTERVENTION_LOG)
    if not records:
        print("介入ログなし")
        return

    from collections import Counter
    types = Counter(r.get("intervention_type", "") for r in records)
    results = Counter(r.get("result", "") for r in records)

    print(f"\n=== 異常介入統計 ===")
    print(f"  総介入回数: {len(records)}")
    print(f"\n  介入タイプ別:")
    for t, c in types.most_common():
        print(f"    {t}: {c}回")
    print(f"\n  結果別:")
    for r, c in results.most_common():
        print(f"    {r}: {c}回")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="異常検知→自動介入システム v1.0")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    if args.stats:
        print_stats()
    else:
        result = run(dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
