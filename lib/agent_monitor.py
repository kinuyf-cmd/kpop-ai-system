#!/usr/bin/env python3
"""
agent_monitor.py — AI会社 統合監視・自律改善・売上最大化システム v2.0
読み取り専用分析 → JSON/HTML出力のみ（既存pipeline・記事は変更しない）

CEO: ミュウツー / オーナー: 人間（閲覧専用）
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
LOGS = BASE / "logs"
AGENTS_DIR = BASE / "agents"
CONFIG = BASE / "config"

# 監視ログの時鮮度窓(日)。更新の止まった凍結ログ(例: gardevoir_hook.jsonl は
# 2026-04 で停止)を「現在の多発」として誤報し続けるのを防ぐため、集計は直近
# FRESHNESS_DAYS 以内のレコードに限定する(2026-07-16 誤報アラート根治)。
FRESHNESS_DAYS = 14


def _is_recent(ts_str, days: int = FRESHNESS_DAYS) -> bool:
    """ts_str(ISO8601, 末尾Z許容)が直近 days 日以内なら True。
    ts が無い/壊れているレコードは、時鮮度を判定できないため False(=集計から除外)。
    これにより凍結ログの ts 欠落行が誤って現在扱いされることを防ぐ。"""
    if not ts_str:
        return False
    try:
        s = str(ts_str).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    return dt >= datetime.now(timezone.utc) - timedelta(days=days)

# ─────────────────────────────────────────────
# エージェント完全定義テーブル（agents/定義書 + pipeline定義 + ログ実績 を統合）
# ─────────────────────────────────────────────
AGENT_MASTER = {
    # id: (カタカナ名, 役割, ROLE_CLASS, pipeline_position)
    # ─── pipeline実行ID（log上のstep名）─── 設計書と照合済み
    "mewtwo":               ("ミュウツー",      "CEO・戦略統合編集長",       "CORE",         "breaking=step0 / strategy=step7"),
    "deoxys":               ("デオキシス",      "記事生成ライター",           "CORE",         "breaking=step1,2 / strategy=step8"),
    "metamon":              ("メタモン",        "SEOリライト・タイトル生成",  "CORE",         "breaking=step2 / strategy=step9"),
    "eevee":                ("イーブイ",        "タイトル最終選定",           "CORE",         "breaking=step2.5 / strategy=step10"),
    "jirachi":              ("ジラーチ",        "ファクトチェック・予測",     "CORE",         "breaking=step3 / strategy=step5"),
    "gardevoir_hook_critic":("サーナイト",      "刺さり品質ゲート",           "CORE",         "breaking=step3.5 / strategy=step13.5"),
    "arceus":               ("アルセウス",      "最終投稿承認・総監督",       "CORE",         "breaking=step4 / strategy=step14"),
    "butterfree":           ("バタフリー",      "トレンド情報収集",           "CORE",         "strategy=step1"),
    "lapras":               ("ラプラス",        "SEOキーワード戦略",          "CORE",         "strategy=step2"),
    "mimikyu":              ("ミミッキュ",      "競合分析・差別化",           "CORE",         "strategy=step3"),
    "wobbuffet":            ("ソーナンス",      "読者ニーズ分析",             "SUPPORT",      "strategy=step4"),
    "venusaur":             ("フシギバナ",      "記事構成設計",               "CORE",         "strategy=step6"),
    # alakazam: 設計書=MANUAL_ONLY（手動専用。cronパイプライン未接続）
    # ただしlog上では alakazam_kpop の--agentをstep名「alakazam」で記録
    # → ROLE_CLASS は設計書準拠で MANUAL_ONLY。log上の実行は alakazam_kpop 経由
    "alakazam":             ("フーディン",      "ファクトチェック・時制整合（手動専用）", "MANUAL_ONLY", "手動専用 / log上はalakazam_kpop経由"),
    "gengar":               ("ゲンガー",        "SEO・品質監査",              "CORE",         "strategy=step11 / chart=step3"),
    # カイリュー: pipeline.jsonlではstep名「カイリュー」（日本語）で記録
    # kairyu_kpop が --agent 指定名。kairyu との重複カウントを防ぐためカイリューを正とする
    "カイリュー":            ("カイリュー",      "CVR・回遊最適化",            "SUPPORT",      "strategy=step13"),
    "persian":              ("ペルシアン",      "SNS拡散・X投稿戦略",         "SUPPORT",      "strategy=step15 / chart=step4"),
    "zapdos":               ("サンダー",        "チャートランキング記事生成", "CORE",         "chart=step1"),
    "wordpress_post":       ("WP投稿",          "WordPress API投稿",          "INFRA",        "breaking=final / strategy=final"),
    "x_post":               ("X投稿",           "X(Twitter)自動投稿",         "INFRA",        "breaking=final / strategy=final"),
    "x_post_b":             ("X投稿B",          "X投稿（予備）",              "INFRA",        "deprecated"),
    "dragonite":            ("カイリュー（旧）", "CVR最適化（旧版）",          "DEPRECATED",   "deprecated"),
    "pipeline":             ("パイプライン",    "パイプライン制御",           "INFRA",        "全体"),
    # ─── agents/定義あり・pipeline未接続 ───
    "porygon":              ("ポリゴン",        "週次パフォーマンス分析",     "SUPPORT",      "weekly_review=step1"),
    "porygon_z":            ("ポリゴンZ",       "SRE・インフラ監視",          "SUPPORT",      "ai_company"),
    "lugia":                ("ルギア",          "週次戦略立案",               "SUPPORT",      "weekly_review=step2"),
    "meowth":               ("ニャース",        "収益化責任者",               "SUPPORT",      "ai_company"),
    # articuno: 設計書=MANUAL_ONLY
    "articuno":             ("フリーザー",      "SNSバズコンテンツ生成",      "MANUAL_ONLY",  "手動"),
    # beautywriter: 設計書=CORE（beauty_pipeline時のみ）
    "beautywriter":         ("コスメライター",  "美容・コスメ記事生成",       "CORE",         "beauty_pipeline（master_scheduler経由）"),
    # snorlax: 設計書=MANUAL_ONLY
    "snorlax":              ("カビゴン",        "レビュー・比較記事生成",     "MANUAL_ONLY",  "手動"),
    # popupwriter: 設計書=MANUAL_ONLY
    "popupwriter":          ("ポップアップライター","ポップアップ記事生成",   "MANUAL_ONLY",  "手動"),
    # alakazam_kpop: 設計書=MERGE_CANDIDATE（strategy/chartで実際に使用）
    "alakazam_kpop":        ("フーディン",      "ファクトチェック・時制整合", "MERGE_CANDIDATE","strategy=step11 / chart=step2"),
    # mewtwo_cosme: 設計書=MANUAL_ONLY（2026-04-11時点で呼び出し実績なし）
    "mewtwo_cosme":         ("ミュウツー（コスメ）","美容戦略統合",           "MANUAL_ONLY",  "手動（cronパイプライン未接続）"),
    # mewtwo_popup: 設計書=CORE（master_schedulerのイベントトレンド検出時）
    "mewtwo_popup":         ("ミュウツー（POP）","ポップアップ戦略",          "CORE",         "popup_pipeline（master_scheduler経由）"),
    # ─── pipeline実行IDとagents/ファイルの _kpop サフィックス版 ───
    # これらは --agent 指定名。log上のstep名は suffix なし（deoxys, metamon 等）で記録される
    # ⚠️ ALIAS: 本体IDへの正規化エイリアス。agent_metrics上では本体IDに統合される（二重計上防止）
    "deoxys_kpop":          ("デオキシス",      "記事生成ライター",           "CORE",         "breaking=step1,2 / strategy=step8"),
    "metamon_kpop":         ("メタモン",        "SEOリライト・タイトル生成",  "CORE",         "breaking=step2 / strategy=step9"),
    "jirachi_kpop":         ("ジラーチ",        "ファクトチェック・予測",     "CORE",         "breaking=step3 / strategy=step5"),
    "kairyu_kpop":          ("カイリュー",      "CVR・回遊最適化",            "SUPPORT",      "strategy=step13"),
    # kairyu: kairyu_kpop のエイリアス（旧log用）。カイリュー（日本語）と統合
    "kairyu":               ("カイリュー",      "CVR・回遊最適化",            "SUPPORT",      "strategy=step13"),
}

# _kpop サフィックスエイリアス → 本体ID 正規化マップ
# agent_metrics.json 上では本体IDに統合され、エイリアス単体エントリは表示しない
KPOP_ALIAS_TO_CANONICAL = {
    "deoxys_kpop":   "deoxys",
    "metamon_kpop":  "metamon",
    "jirachi_kpop":  "jirachi",
    "kairyu_kpop":   "カイリュー",
    "kairyu":        "カイリュー",
    "alakazam_kpop": "alakazam",
}

def get_agent_ja(agent_id: str) -> str:
    info = AGENT_MASTER.get(agent_id)
    return info[0] if info else agent_id

def get_agent_role(agent_id: str) -> str:
    info = AGENT_MASTER.get(agent_id)
    return info[1] if info else "不明"

def get_agent_class(agent_id: str) -> str:
    info = AGENT_MASTER.get(agent_id)
    return info[2] if info else "UNKNOWN"

def get_agent_position(agent_id: str) -> str:
    info = AGENT_MASTER.get(agent_id)
    return info[3] if info else ""

# ─────────────────────────────────────────────
# 異常検知パターン
# ─────────────────────────────────────────────
TITLE_COLLAPSE_PATTERNS = [
    r"ウェブフェッチ(はできません|できません)",
    r"分析します",
    r"^以下に",
    r"提供してください",
    r"内部矛盾",
    r"論理的問題",
    r"以下の記事を",
    r"見当たりません",
    r"コンテンツが提供されていません",
    r"記事の元となる",
]
BODY_CONTAMINATION_PATTERNS = [
    r"申し訳ありません",
    r"修正しました",
    r"ファクトチェック済み",
    r"AI(が|は|として)",
    r"\[修正メモ\]",
    r"以下に完成記事",
    r"以下に出力します",
]
SABORI_THRESHOLD_HOURS = 48   # サボり判定: 最終実行から何時間以上（CORÉのみ）
SABORI_EMPTY_THRESHOLD = 3    # サボり判定: 空出力何回以上
CRITICAL_RATE = 0.60          # 要改善閾値
WARNING_RATE = 0.85           # 注意閾値

# サボり判定から除外するROLE_CLASS
# MANUAL_ONLY/MERGE_CANDIDATE/DEPRECATED/SUPPORT は「未実行=サボり」ではない
SABORI_EXEMPT_CLASSES = {"MANUAL_ONLY", "MERGE_CANDIDATE", "DEPRECATED", "SUPPORT"}

# 失敗連鎖を起こす「ボトルネックエージェント」として優先検知するstep
CASCADE_TRIGGER_STEPS = {
    "gardevoir_hook_critic",  # 連鎖失敗の起点29回（最多）
    "arceus",                 # 連鎖失敗の起点5回
    "butterfree",             # 空出力による下流停止
}

# ─────────────────────────────────────────────
# データ収集
# ─────────────────────────────────────────────

def parse_pipeline_jsonl() -> dict:
    """pipeline.jsonl を解析してエージェント別集計"""
    path = LOGS / "pipeline.jsonl"
    agents: dict[str, dict] = {}

    if not path.exists():
        return agents

    SUCCESS_STATUS = {"ok", "approved", "PASS"}
    FAIL_STATUS = {"error", "ERROR", "hard_fail", "HARD_FAIL", "skipped", "HARD FAIL"}

    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            step = d.get("step", "")
            if not step:
                continue
            # エイリアス正規化: KPOP_ALIAS_TO_CANONICAL で一元管理
            # kairyu/kairyu_kpop → カイリュー、alakazam_kpop → alakazam、
            # deoxys_kpop → deoxys、metamon_kpop → metamon、jirachi_kpop → jirachi
            step = KPOP_ALIAS_TO_CANONICAL.get(step, step)
            status = d.get("status", "")
            ts = d.get("timestamp", "")
            msg = d.get("message", "") or ""
            size = d.get("size_bytes", 0) or 0
            run_id = d.get("run_id", "")

            if step not in agents:
                agents[step] = {
                    "ok": 0, "fail": 0,
                    "timestamps": [], "messages": [],
                    "empty_output": 0, "contamination": 0, "retry": 0,
                    "sizes": [], "run_ids": set(),
                    "hard_fail": 0, "soft_fail": 0,
                }
            a = agents[step]

            # アルセウスは approved/rejected 両方が正常（品質ゲート動作）
            if step == "arceus":
                if status in ("approved", "ok", "PASS"):
                    a["ok"] += 1
                elif status == "rejected":
                    a["ok"] += 1  # 品質却下は正常動作
                else:
                    a["fail"] += 1
            elif status in SUCCESS_STATUS:
                a["ok"] += 1
            elif status == "rejected":
                a["fail"] += 1
            elif status in FAIL_STATUS:
                a["fail"] += 1
                if "hard_fail" in status.lower():
                    a["hard_fail"] += 1
                elif "soft" in status.lower():
                    a["soft_fail"] += 1
            else:
                a["fail"] += 1

            if ts:
                a["timestamps"].append(ts)
            a["messages"].append(msg)
            if size:
                a["sizes"].append(size)
            if run_id:
                a["run_ids"].add(run_id)

            # 空出力検知
            if "空出力" in msg or "empty" in msg.lower() or (size < 100 and status != "ok"):
                a["empty_output"] += 1
            # 汚染検知
            for pat in BODY_CONTAMINATION_PATTERNS + TITLE_COLLAPSE_PATTERNS:
                if re.search(pat, msg):
                    a["contamination"] += 1
                    break
            # リトライ検知
            if "リトライ" in msg or "retry" in msg.lower():
                a["retry"] += 1

    # run_ids を list に変換
    for a in agents.values():
        a["run_ids"] = list(a["run_ids"])

    return agents


def parse_gardevoir_jsonl() -> dict:
    """gardevoir_hook.jsonl を解析"""
    path = LOGS / "gardevoir_hook.jsonl"
    data = {
        "pass": 0, "fail": 0, "soft": 0, "error": 0,
        "scores": [], "hard_fail_titles": [], "pass_titles": [],
        "by_pipeline": {"breaking": {"pass":0,"fail":0}, "strategy": {"pass":0,"fail":0}},
    }
    if not path.exists():
        return data
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            # 凍結ログ(更新停止)の古データを現在の多発として誤報しない
            if not _is_recent(d.get("ts")):
                continue
            v = d.get("verdict", "")
            s = d.get("score", 0)
            pl = d.get("pipeline", "")
            title = d.get("title", "")
            if s:
                data["scores"].append(s)
            if v == "PASS":
                data["pass"] += 1
                if title:
                    data["pass_titles"].append(title)
                if pl in data["by_pipeline"]:
                    data["by_pipeline"][pl]["pass"] += 1
            elif v in ("HARD_FAIL", "hard_fail"):
                data["fail"] += 1
                if title:
                    data["hard_fail_titles"].append(title)
                if pl in data["by_pipeline"]:
                    data["by_pipeline"][pl]["fail"] += 1
            elif v == "SOFT_RETRY":
                data["soft"] += 1
            else:
                data["error"] += 1
    return data


def parse_kpi_posts() -> list[dict]:
    """kpi_posts.jsonl から公開記事データ"""
    path = LOGS / "kpi_posts.jsonl"
    posts = []
    if not path.exists():
        return posts
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if d.get("event") == "post_published":
                    posts.append(d)
            except json.JSONDecodeError:
                continue
    return posts


def parse_audit_feedback() -> list[dict]:
    path = LOGS / "audit_feedback.jsonl"
    data = []
    if not path.exists():
        return data
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            # 凍結ログ(更新停止)の古タイトル汚染を現在の多発として誤報しない
            if not _is_recent(d.get("ts")):
                continue
            data.append(d)
    return data


def parse_kpi_errors() -> list[dict]:
    path = LOGS / "kpi_errors.jsonl"
    errors = []
    if not path.exists():
        return errors
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                errors.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return errors


def parse_watchdog_alerts() -> list[dict]:
    path = LOGS / "watchdog_alerts.jsonl"
    alerts = []
    if not path.exists():
        return alerts
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                alerts.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return alerts


def parse_error_patterns() -> dict:
    path = CONFIG / "error_patterns.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def parse_kpi_targets() -> dict:
    path = CONFIG / "kpi_targets.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def parse_revenue_config() -> dict:
    path = CONFIG / "revenue_config.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


# ─────────────────────────────────────────────
# 計算ヘルパー
# ─────────────────────────────────────────────

def hours_since(ts_str: str) -> float:
    """タイムスタンプからの経過時間(時)"""
    if not ts_str:
        return 9999.0
    try:
        ts_str = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - dt).total_seconds() / 3600
    except Exception:
        return 9999.0


def compute_rank(rate: float) -> str:
    if rate >= WARNING_RATE:
        return "🟢"
    elif rate >= CRITICAL_RATE:
        return "🟡"
    else:
        return "🔴"


def compute_status(rate: float, last_ts: str, empty: int, role_class: str, step_id: str, total: int) -> str:
    """
    ステータス判定ルール（精度調整済み v2.1）
    - MANUAL_ONLY/SUPPORT/MERGE_CANDIDATE/DEPRECATED は「停止」表示しない（オーナー誤認防止）
    - CORÉで48h以上実行なし → 停止
    - 失敗連鎖起点エージェント（CASCADE_TRIGGER_STEPS）は低成功率でも「要改善」優先
    - 空出力が多い → 要改善（実行数に関わらず）
    """
    h = hours_since(last_ts)

    # 手動専用・サポート系・非推奨は「待機中」または「通常」
    if role_class in SABORI_EXEMPT_CLASSES:
        if total == 0:
            return "待機中"
        if rate < CRITICAL_RATE:
            return "注意"
        return "稼働中"

    # COREまたはINFRAで長期未実行
    if h > SABORI_THRESHOLD_HOURS and total == 0:
        return "停止"

    # 失敗連鎖起点エージェントは常に「要改善」で強調
    if step_id in CASCADE_TRIGGER_STEPS and rate < WARNING_RATE:
        return "要改善"

    # 成功率・空出力による判定
    if rate < CRITICAL_RATE:
        return "要改善"
    if empty >= SABORI_EMPTY_THRESHOLD:
        return "要改善"
    if rate < WARNING_RATE:
        return "注意"
    return "稼働中"


def compute_danger(rate: float, empty: int, contamination: int, hard_fail: int) -> str:
    score = 0
    if rate < 0.5:
        score += 3
    elif rate < 0.7:
        score += 1
    if empty >= 3:
        score += 2
    if contamination > 0:
        score += 2
    if hard_fail >= 5:
        score += 2
    if score >= 5:
        return "🔴 高"
    elif score >= 2:
        return "🟡 中"
    else:
        return "🟢 低"


def weekly_activity(timestamps: list[str]) -> list[int]:
    """直近7日の日別実行回数"""
    today = datetime.now(timezone.utc).date()
    counts = [0] * 7
    for ts in timestamps:
        try:
            ts = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = (today - dt.date()).days
            if 0 <= delta < 7:
                counts[6 - delta] += 1
        except Exception:
            pass
    return counts


# ─────────────────────────────────────────────
# メトリクス構築
# ─────────────────────────────────────────────

def build_agent_metrics(pipeline_data: dict, gardevoir_data: dict) -> dict:
    """エージェント別評価メトリクスを構築"""
    now_iso = datetime.now(timezone.utc).isoformat()
    metrics = {}

    # pipeline.jsonlに出現したエージェント
    for step, data in pipeline_data.items():
        ja = get_agent_ja(step)
        role = get_agent_role(step)
        cls = get_agent_class(step)
        pos = get_agent_position(step)

        total = data["ok"] + data["fail"]
        rate = round(data["ok"] / total, 3) if total > 0 else 0.0
        last_ts = max(data["timestamps"]) if data["timestamps"] else ""
        avg_size = round(sum(data["sizes"]) / len(data["sizes"])) if data["sizes"] else 0
        activity = weekly_activity(data["timestamps"])
        is_core = cls in ("CORE", "INFRA")

        entry = {
            "id": step,
            "name_ja": ja,
            "role": role,
            "role_class": cls,
            "pipeline_position": pos,
            "success_count": data["ok"],
            "fail_count": data["fail"],
            "total_count": total,
            "success_rate": rate,
            "rank": compute_rank(rate),
            "status": compute_status(rate, last_ts, data["empty_output"], cls, step, total),
            "danger": compute_danger(rate, data["empty_output"], data["contamination"], data["hard_fail"]),
            "last_run_time": last_ts,
            "hours_since_last_run": round(hours_since(last_ts), 1),
            "empty_output_count": data["empty_output"],
            "contamination_count": data["contamination"],
            "retry_count": data["retry"],
            "hard_fail_count": data["hard_fail"],
            "soft_fail_count": data["soft_fail"],
            "avg_output_size": avg_size,
            "weekly_activity": activity,
            "total_runs_participated": len(data["run_ids"]),
            "error_flag": data["contamination"] > 0 or data["empty_output"] >= 3,
            "sabori_flag": cls not in SABORI_EXEMPT_CLASSES and (
                (hours_since(last_ts) > SABORI_THRESHOLD_HOURS and total == 0)
                or data["empty_output"] >= SABORI_EMPTY_THRESHOLD
            ),
        }

        # サーナイト専用: gardevoir_hook.jsonl で補強
        if step == "gardevoir_hook_critic":
            g = gardevoir_data
            g_total = g["pass"] + g["fail"] + g["soft"] + g["error"]
            entry["gardevoir_pass"] = g["pass"]
            entry["gardevoir_fail"] = g["fail"]
            entry["gardevoir_soft"] = g["soft"]
            entry["gardevoir_error"] = g["error"]
            entry["gardevoir_total"] = g_total
            valid_scores = [s for s in g["scores"] if s > 0]
            entry["gardevoir_avg_score"] = round(sum(valid_scores) / len(valid_scores), 1) if valid_scores else 0
            entry["hard_fail_titles"] = g["hard_fail_titles"][-5:]
            entry["pass_titles"] = g["pass_titles"][-3:]
            entry["by_pipeline"] = g["by_pipeline"]
            # ERROR多発の注記
            if g["error"] > 10:
                entry["error_note"] = f"フォーマット不正によるERROR {g['error']}件（SCOREパース失敗）"
                entry["error_flag"] = True

        metrics[step] = entry

    # agents/ディレクトリに定義があるがpipelineログに未出現のエージェントを補完
    for agent_id, (ja, role, cls, pos) in AGENT_MASTER.items():
        if agent_id not in metrics:
            # _kpop エイリアスは本体IDが既に集計済みの場合スキップ（二重計上防止）
            canonical = KPOP_ALIAS_TO_CANONICAL.get(agent_id)
            if canonical and canonical in metrics:
                continue  # 本体IDに統合済み → エイリアスエントリは作らない

            agent_file = AGENTS_DIR / f"{agent_id}.md"
            agent_file2 = AGENTS_DIR / f"{agent_id}_kpop.md"
            if agent_file.exists() or agent_file2.exists():
                metrics[agent_id] = {
                    "id": agent_id,
                    "name_ja": ja,
                    "role": role,
                    "role_class": cls,
                    "pipeline_position": pos,
                    "success_count": 0,
                    "fail_count": 0,
                    "total_count": 0,
                    "success_rate": 0.0,
                    "rank": "🟡",
                    "status": "停止" if cls in ("CORE", "INFRA") else "待機中",
                    "danger": "🟢 低",
                    "last_run_time": "",
                    "hours_since_last_run": 9999,
                    "empty_output_count": 0,
                    "contamination_count": 0,
                    "retry_count": 0,
                    "hard_fail_count": 0,
                    "soft_fail_count": 0,
                    "avg_output_size": 0,
                    "weekly_activity": [0] * 7,
                    "total_runs_participated": 0,
                    "error_flag": False,
                    "sabori_flag": cls in ("CORE", "INFRA") and cls not in SABORI_EXEMPT_CLASSES,
                    "note": "定義あり・実行ログなし",
                }

    return metrics


def build_org_map(metrics: dict) -> dict:
    """AI組織マップを構築"""
    agents_list = []
    for mid, m in metrics.items():
        if mid == "pipeline":
            continue
        agents_list.append({
            "id": mid,
            "name_ja": m["name_ja"],
            "role": m["role"],
            "role_class": m["role_class"],
            "pipeline_position": m["pipeline_position"],
            "success_rate": m["success_rate"],
            "status": m["status"],
            "danger": m["danger"],
            "rank": m["rank"],
            "last_run_time": m["last_run_time"],
        })

    # 部門別分類
    core_agents = [a for a in agents_list if a["role_class"] == "CORE"]
    support_agents = [a for a in agents_list if a["role_class"] == "SUPPORT"]
    infra_agents = [a for a in agents_list if a["role_class"] == "INFRA"]
    manual_agents = [a for a in agents_list if a["role_class"] == "MANUAL_ONLY"]
    deprecated = [a for a in agents_list if a["role_class"] == "DEPRECATED"]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company": "K-POP Journal AI Company",
        "ceo": {
            "id": "mewtwo",
            "name_ja": "ミュウツー",
            "title": "CEO・編集長",
            "role": "戦略統合・最終意思決定",
        },
        "owner": {
            "name": "人間オーナー",
            "role": "経営閲覧・最終承認（実務不参加）",
        },
        "departments": {
            "core": {
                "label": "コア部隊（記事生成・品質管理）",
                "agents": core_agents,
            },
            "support": {
                "label": "サポート部隊（分析・最適化）",
                "agents": support_agents,
            },
            "infra": {
                "label": "インフラ部隊（投稿・配信）",
                "agents": infra_agents,
            },
            "manual": {
                "label": "手動発注専門（オーナー指示待ち）",
                "agents": manual_agents,
            },
        },
        "total_agents": len(agents_list),
        "active_agents": sum(1 for a in agents_list if a["status"] in ("稼働中", "注意")),
        "critical_agents": sum(1 for a in agents_list if a["status"] == "要改善"),
    }


def build_revenue_metrics(posts: list[dict], kpi_targets: dict, rev_config: dict, audit_feedback: list[dict] = None) -> dict:
    """売上最大化メトリクスを構築"""
    now = datetime.now(timezone.utc).isoformat()
    total = len(posts)
    if total == 0:
        return {"generated_at": now, "summary": {}, "articles": []}

    has_cta = sum(1 for p in posts if p.get("has_cta"))
    has_thumb = sum(1 for p in posts if p.get("has_thumbnail"))
    avg_chars = round(sum(p.get("char_count", 0) for p in posts) / total)

    # audit_feedback.jsonl からタイトル崩壊を検知（kpi_posts.jsonlより信頼性が高い）
    audit_contaminated = []
    if audit_feedback:
        for fb in audit_feedback:
            t = fb.get("title", "")
            if t and any(re.search(pat, t) for pat in TITLE_COLLAPSE_PATTERNS):
                audit_contaminated.append({"post_id": fb.get("post_id", ""), "title": t})

    # 記事別 revenue_score 計算
    # revenue_score = CTR×0.35 + SEO×0.30 + 回遊×0.20 + CVR×0.15  （v2.1調整済み）
    # 現時点はデータ代理値で算出
    article_scores = []
    contaminated_titles = []

    for p in posts:
        char = p.get("char_count", 0)
        cta = 1.0 if p.get("has_cta") else 0.0
        h2 = p.get("h2_count", 0)
        thumb = 1.0 if p.get("has_thumbnail") else 0.0
        title = p.get("title", "")

        # タイトル崩壊チェック
        is_contaminated = any(re.search(pat, title) for pat in TITLE_COLLAPSE_PATTERNS)
        if is_contaminated:
            contaminated_titles.append({"post_id": p.get("post_id",""), "title": title})

        # 代理スコア算出
        # CTR代理: タイトル文字数・数字有無・感嘆符
        ctr_proxy = 0.5
        if 20 <= len(title) <= 50:
            ctr_proxy += 0.2
        if re.search(r'\d', title):
            ctr_proxy += 0.15
        if is_contaminated:
            ctr_proxy = 0.0
        ctr_proxy = min(1.0, ctr_proxy)

        # CVR代理: CTA有無・文字数
        cvr_proxy = cta * 0.6 + min(1.0, char / 4000) * 0.4

        # SEO代理: 文字数・H2数
        seo_proxy = min(1.0, char / 3500) * 0.6 + min(1.0, h2 / 5) * 0.4

        # 回遊代理: サムネ・文字数
        navigation_proxy = thumb * 0.5 + min(1.0, char / 3000) * 0.5

        revenue_score = round(
            ctr_proxy * 0.35 + seo_proxy * 0.30 + navigation_proxy * 0.20 + cvr_proxy * 0.15,
            3,
        )

        # 鮮度スコア
        try:
            post_date = datetime.fromisoformat(p.get("timestamp", "").replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - post_date).days
            freshness = max(0.0, 1.0 - age_days / 30)
        except Exception:
            freshness = 0.5

        article_scores.append({
            "post_id": p.get("post_id", ""),
            "title": title,
            "url": p.get("url", ""),
            "pipeline": p.get("pipeline", ""),
            "date": p.get("date", ""),
            "revenue_score": revenue_score,
            "ctr_score": round(ctr_proxy, 3),
            "cvr_score": round(cvr_proxy, 3),
            "seo_score": round(seo_proxy, 3),
            "navigation_score": round(navigation_proxy, 3),
            "freshness_score": round(freshness, 3),
            "char_count": char,
            "h2_count": h2,
            "has_cta": bool(cta),
            "has_thumbnail": bool(thumb),
            "is_contaminated": is_contaminated,
        })

    article_scores.sort(key=lambda x: x["revenue_score"], reverse=True)

    # audit_feedbackで検出した汚染タイトルを統合（重複排除: post_id基準）
    known_contaminated_ids = {c["post_id"] for c in contaminated_titles if c["post_id"]}
    for ac in audit_contaminated:
        if ac["post_id"] not in known_contaminated_ids:
            contaminated_titles.append(ac)
            known_contaminated_ids.add(ac["post_id"])

    # カテゴリ別分析（pipeline別）
    pipeline_stats = defaultdict(lambda: {"count": 0, "total_score": 0.0, "cta_count": 0})
    for a in article_scores:
        pl = a.get("pipeline", "unknown")
        pipeline_stats[pl]["count"] += 1
        pipeline_stats[pl]["total_score"] += a["revenue_score"]
        if a["has_cta"]:
            pipeline_stats[pl]["cta_count"] += 1

    pipeline_analysis = {}
    for pl, v in pipeline_stats.items():
        cnt = v["count"]
        pipeline_analysis[pl] = {
            "count": cnt,
            "avg_revenue_score": round(v["total_score"] / cnt, 3) if cnt > 0 else 0,
            "cta_rate": round(v["cta_count"] / cnt, 3) if cnt > 0 else 0,
        }

    # 勝ちパターン / 負けパターン
    top25 = article_scores[:max(1, len(article_scores)//4)]
    bot25 = article_scores[-(max(1, len(article_scores)//4)):]

    winning_patterns = {
        "avg_chars": round(sum(a["char_count"] for a in top25) / len(top25)),
        "avg_h2": round(sum(a["h2_count"] for a in top25) / len(top25), 1),
        "cta_rate": round(sum(1 for a in top25 if a["has_cta"]) / len(top25), 2),
        "thumb_rate": round(sum(1 for a in top25 if a["has_thumbnail"]) / len(top25), 2),
        "avg_ctr_score": round(sum(a["ctr_score"] for a in top25) / len(top25), 3),
    }
    losing_patterns = {
        "avg_chars": round(sum(a["char_count"] for a in bot25) / len(bot25)),
        "avg_h2": round(sum(a["h2_count"] for a in bot25) / len(bot25), 1),
        "cta_rate": round(sum(1 for a in bot25 if a["has_cta"]) / len(bot25), 2),
        "thumb_rate": round(sum(1 for a in bot25 if a["has_thumbnail"]) / len(bot25), 2),
        "avg_ctr_score": round(sum(a["ctr_score"] for a in bot25) / len(bot25), 3),
    }

    daily = kpi_targets.get("daily", {})
    ultimate = kpi_targets.get("ultimate", {})

    return {
        "generated_at": now,
        "summary": {
            "total_articles": total,
            "avg_revenue_score": round(sum(a["revenue_score"] for a in article_scores) / total, 3),
            "cta_rate": round(has_cta / total, 3),
            "thumbnail_rate": round(has_thumb / total, 3),
            "avg_char_count": avg_chars,
            "contaminated_title_count": len(contaminated_titles),
            "contaminated_titles": contaminated_titles,
        },
        "kpi_targets": {
            "daily_articles": daily.get("articles_posted", {}).get("target", 5),
            "daily_revenue_jpy": daily.get("revenue_jpy", {}).get("target", 200),
            "daily_sessions": daily.get("sessions", {}).get("target", 500),
            "pipeline_uptime": daily.get("pipeline_uptime", {}).get("target", 95),
            "ultimate_monthly_revenue": ultimate.get("revenue_jpy", {}).get("target", 30000),
            "ultimate_articles": ultimate.get("articles_total", {}).get("target", 500),
        },
        "pipeline_analysis": pipeline_analysis,
        "winning_patterns": winning_patterns,
        "losing_patterns": losing_patterns,
        "top_articles": article_scores[:10],
        "bottom_articles": article_scores[-5:],
        "management_insights": _generate_management_insights(article_scores, pipeline_analysis, contaminated_titles),
    }


def _generate_management_insights(articles: list, pipeline_stats: dict, contaminated: list) -> dict:
    """経営インサイト生成"""
    avg = sum(a["revenue_score"] for a in articles) / len(articles) if articles else 0

    # 最もROIが高いpipeline
    best_pl = max(pipeline_stats.items(), key=lambda x: x[1]["avg_revenue_score"], default=(None, {}))
    worst_pl = min(pipeline_stats.items(), key=lambda x: x[1]["avg_revenue_score"], default=(None, {}))

    # 伸ばすべき記事群（score > 平均+0.1）
    grow_articles = [a for a in articles if a["revenue_score"] > avg + 0.1][:5]
    # 止めるべき記事群（score < 0.3 or 汚染）
    stop_articles = [a for a in articles if a["revenue_score"] < 0.3 or a["is_contaminated"]][:5]
    # 量産すべきパターン（score上位のタイトルパターン）
    top_titles = [a["title"] for a in articles[:5]]

    return {
        "priority_theme": "記事品質向上とCTA設置率改善（現状72%→100%目標）",
        "best_roi_pipeline": best_pl[0] if best_pl[0] else "不明",
        "worst_pipeline": worst_pl[0] if worst_pl[0] else "不明",
        "grow_articles": [{"post_id": a["post_id"], "title": a["title"][:50], "score": a["revenue_score"]} for a in grow_articles],
        "stop_articles": [{"post_id": a["post_id"], "title": a["title"][:50], "reason": "低スコア/汚染"} for a in stop_articles],
        "winning_title_patterns": top_titles,
        "urgent_actions": [
            "CTA未設置記事（約27%）にCTAを追加する",
            "サムネイル未設置記事（約3%）を修正する",
            "タイトル崩壊記事を下書き化またはリライトする",
            f"サーナイトのフォーマットERROR（{'高頻度' if contaminated else '低頻度'}）を解消する",
        ],
    }


def build_optimization_actions(
    metrics: dict,
    posts: list,
    errors: list,
    watchdog: list,
    error_patterns: dict,
) -> dict:
    """改善アクション生成（改善提案のみ・既存変更なし）"""
    actions = []
    now = datetime.now(timezone.utc).isoformat()

    for mid, m in metrics.items():
        if mid == "pipeline":
            continue
        rate = m.get("success_rate", 1.0)
        empty = m.get("empty_output_count", 0)
        cont = m.get("contamination_count", 0)
        total = m.get("total_count", 0)
        hard_fail = m.get("hard_fail_count", 0)
        name = m.get("name_ja", mid)
        h_since = m.get("hours_since_last_run", 0)
        cls = m.get("role_class", "")
        sabori = m.get("sabori_flag", False)

        if total == 0 and not sabori:
            continue

        # 成功率低下
        if total > 0 and rate < CRITICAL_RATE:
            actions.append({
                "agent_id": mid,
                "agent_name": name,
                "severity": "high",
                "reason": f"成功率 {rate:.0%} < 60%（{total}回中{m['success_count']}回成功）",
                "action_type": "prompt_hardening",
                "suggested_fix": "出力フォーマットの先頭行に必須キーを明記し、説明・謝罪・メタコメントを絶対禁止とする制約を追加する",
                "expected_effect": "pipeline停止率の低下・品質スコア向上",
            })

        # 空出力多発
        if empty >= SABORI_EMPTY_THRESHOLD:
            actions.append({
                "agent_id": mid,
                "agent_name": name,
                "severity": "high",
                "reason": f"空出力 {empty}回（サボり判定）",
                "action_type": "fallback_output_rule",
                "suggested_fix": "出力最小文字数（300字）とフォールバック出力テンプレートをプロンプトに明記する",
                "expected_effect": "空出力によるpipeline停止の削減",
            })

        # サボり（長期未実行）
        if sabori and h_since > SABORI_THRESHOLD_HOURS and cls == "CORE":
            actions.append({
                "agent_id": mid,
                "agent_name": name,
                "severity": "medium",
                "reason": f"最終実行から {h_since:.0f}時間経過（CORE担当なのに未実行）",
                "action_type": "cron_check",
                "suggested_fix": "cronスケジュール・pipeline定義を確認し、このエージェントが呼ばれているか検証する",
                "expected_effect": "担当ステップの定常実行再開",
            })

        # 汚染検知
        if cont > 0:
            actions.append({
                "agent_id": mid,
                "agent_name": name,
                "severity": "medium",
                "reason": f"出力汚染 {cont}件（AI応答文・メタコメント混入）",
                "action_type": "contamination_filter",
                "suggested_fix": "出力冒頭に「AI応答文・修正メモ・指示文・ファクトチェック文を本文に含めるな」を制約として追加する",
                "expected_effect": "タイトル・本文汚染の撲滅",
            })

        # HARD_FAIL多発
        if hard_fail >= 5:
            actions.append({
                "agent_id": mid,
                "agent_name": name,
                "severity": "high",
                "reason": f"HARD_FAIL {hard_fail}件（刺さり品質不足が多発）",
                "action_type": "quality_gate_upstream",
                "suggested_fix": "上流エージェント（デオキシス・メタモン）のタイトル生成品質を強化し、感情訴求・数字・アーティスト名を必須とする",
                "expected_effect": "HARD_FAIL率低下・pipeline完走率向上",
            })

        # サーナイト専用
        if mid == "gardevoir_hook_critic":
            g_err = m.get("gardevoir_error", 0)
            if g_err > 10:
                actions.append({
                    "agent_id": mid,
                    "agent_name": name,
                    "severity": "high",
                    "reason": f"フォーマット不正によるERROR {g_err}件（SCOREパース失敗）",
                    "action_type": "output_format_lock",
                    "suggested_fix": "SCORE:行を必ず「SCORE: [整数]」（1行・整数のみ）で出力させる。改行・分数・内訳は禁止。auto_directives.jsonへの注入で対応中。",
                    "expected_effect": "ERROR率の大幅減少・採点精度向上",
                })

    # 記事品質改善
    no_cta = [p for p in posts if not p.get("has_cta")]
    if len(no_cta) >= 3:
        actions.append({
            "agent_id": "kairyu",
            "agent_name": "カイリュー",
            "severity": "medium",
            "reason": f"CTA未設置記事 {len(no_cta)}件（CTA設置率{1 - len(no_cta)/len(posts):.0%}）",
            "action_type": "cta_injection",
            "suggested_fix": "カイリューのCTA挿入ロジックを確認し、全記事にCTAが必ず設置されるよう強化する",
            "expected_effect": "CVR向上・収益増加",
        })

    no_thumb = [p for p in posts if not p.get("has_thumbnail")]
    if len(no_thumb) >= 2:
        actions.append({
            "agent_id": "post_audit",
            "agent_name": "投稿監査",
            "severity": "low",
            "reason": f"サムネ未設置記事 {len(no_thumb)}件",
            "action_type": "thumbnail_enforce",
            "suggested_fix": "post_audit.shのサムネ自動生成を確認する",
            "expected_effect": "CTR向上",
        })

    # エラーパターン由来
    recurring = error_patterns.get("recurring_errors", [])
    for err in recurring:
        if err.get("count", 0) >= 3:
            actions.append({
                "agent_id": err.get("agent", "unknown"),
                "agent_name": get_agent_ja(err.get("agent", "unknown")),
                "severity": "medium",
                "reason": f"繰り返しエラー: {err.get('example','')[:60]}（{err.get('count')}回）",
                "action_type": "recurring_error_fix",
                "suggested_fix": err.get("fix", "エラーパターンを調査して修正する"),
                "expected_effect": "再発防止",
            })

    # watchdog由来（最新のアラート）
    recent_pipeline_errors = [w for w in watchdog[-20:] if w.get("check") == "pipeline_error"]
    if len(recent_pipeline_errors) >= 3:
        actions.append({
            "agent_id": "pipeline",
            "agent_name": "パイプライン",
            "severity": "high",
            "reason": f"Watchdogが直近 {len(recent_pipeline_errors)}回のpipelineエラーを検知",
            "action_type": "pipeline_stability",
            "suggested_fix": "サーナイトHARD_FAILと上流タイトル崩壊の連鎖を断ち切る。前段ガードを強化する。",
            "expected_effect": "pipeline完走率の向上",
        })

    # 重複除去
    seen = set()
    unique = []
    for a in actions:
        key = f"{a['agent_id']}::{a['action_type']}"
        if key not in seen:
            seen.add(key)
            unique.append(a)

    prio = {"high": 0, "medium": 1, "low": 2}
    unique.sort(key=lambda x: prio.get(x.get("severity", "low"), 2))

    return {
        "generated_at": now,
        "total_actions": len(unique),
        "high_count": sum(1 for a in unique if a["severity"] == "high"),
        "medium_count": sum(1 for a in unique if a["severity"] == "medium"),
        "low_count": sum(1 for a in unique if a["severity"] == "low"),
        "actions": unique,
        "meta": {
            "note": "改善提案のみ。既存pipeline・記事・WordPressへの変更は行いません。",
            "apply_to": "HIGH優先度を config/auto_directives.json 経由でimprovement_engine.shに反映してください。",
        },
    }


def _load_jsonl_safe(path: Path) -> list:
    """JSONLファイルを安全に読み込む（欠損・不正行は無視）"""
    if not path.exists():
        return []
    records = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return records


def build_dashboard_summary(metrics: dict, opt: dict, rev: dict, posts: list) -> dict:
    """ダッシュボードサマリー（経営向け）"""
    active = {k: v for k, v in metrics.items() if v["total_count"] > 0 and k != "pipeline"}
    sorted_active = sorted(active.items(), key=lambda x: x[1]["success_rate"], reverse=True)

    overall = (
        sum(v["success_rate"] for v in active.values()) / len(active)
        if active else 0.0
    )

    # 今日の投稿数
    today = datetime.now(timezone.utc).date().isoformat()
    today_posts = [p for p in posts if p.get("date") == today]
    week_posts = [p for p in posts if p.get("date", "") >= (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()]

    # ── 通知履歴 & キュー集計 ──
    hist_path  = BASE / "logs" / "discord_alert_history.jsonl"
    queue_path = BASE / "logs" / "alert_queue.jsonl"
    history = _load_jsonl_safe(hist_path)
    queue   = _load_jsonl_safe(queue_path)

    notif_success  = sum(1 for h in history if h.get("result") == "sent")
    notif_failure  = sum(1 for h in history if h.get("result") not in ("sent", "suppressed", "skipped"))
    notif_suppress = sum(1 for h in history if h.get("result") == "suppressed")

    queue_pending  = sum(1 for q in queue if q.get("status") == "pending")
    queue_perm_fail = sum(1 for q in queue if q.get("status") == "permanent_failed")
    unresolved_critical = sum(1 for q in queue if q.get("status") == "pending" and q.get("severity") == "CRITICAL")
    unresolved_warning  = sum(1 for q in queue if q.get("status") == "pending" and q.get("severity") == "WARNING")

    # 最終送信成功・失敗タイムスタンプ
    sent_entries = [h for h in history if h.get("result") == "sent"]
    fail_entries = [h for h in history if h.get("result") not in ("sent", "suppressed", "skipped")]
    latest_sent_at   = max((h.get("sent_at","") for h in sent_entries), default="")
    latest_failed_at = max((h.get("sent_at","") for h in fail_entries), default="")

    # 失敗理由top1
    from collections import Counter
    fail_reasons = Counter(h.get("result","") for h in fail_entries)
    top_fail_reason = fail_reasons.most_common(1)[0][0] if fail_reasons else ""

    # ── 売上阻害ボトルネック top3 ──
    REVENUE_BLOCKER_AGENTS = ["wp_poster", "sanai", "butterfree", "kairyu", "arceus"]
    revenue_blocker_top3 = []
    for aid in REVENUE_BLOCKER_AGENTS:
        v = metrics.get(aid)
        if not v:
            continue
        revenue_blocker_top3.append({
            "id": aid,
            "name": v.get("name_ja", aid),
            "rate": v.get("success_rate", 0),
            "rank": v.get("rank", "🟡"),
            "status": v.get("status", ""),
        })
        if len(revenue_blocker_top3) >= 3:
            break

    # ── 待機中エージェント top3（danger複合スコア高い順）──
    def _danger_score(v):
        r = 1.0 - v.get("success_rate", 0)
        s = 1.0 if v.get("sabori_flag") else 0.0
        e = 0.5 if v.get("error_flag") else 0.0
        return r + s + e

    idle_sorted = sorted(
        [(k, v) for k, v in active.items() if v.get("status") in ("停止", "待機中", "待機")],
        key=lambda x: _danger_score(x[1]), reverse=True
    )
    idle_agent_top3 = [
        {"id": k, "name": v.get("name_ja", k), "status": v.get("status", "")}
        for k, v in idle_sorted[:3]
    ]

    # ── 失敗率 top3 ──
    failing_sorted = sorted(
        [(k, v) for k, v in active.items() if v.get("rank") == "🔴"],
        key=lambda x: x[1]["success_rate"]
    )
    failing_agent_top3 = [
        {"id": k, "name": v.get("name_ja", k), "rate": v.get("success_rate", 0)}
        for k, v in failing_sorted[:3]
    ]

    # ── CEO判断ロジック ──
    # 売上直結エージェントID（停止・低成功率なら最優先繰り上げ）
    REVENUE_CRITICAL_IDS = {"wp_poster", "sanai", "butterfree", "kairyu", "arceus"}
    rev_critical_stopped = [
        (k, v) for k, v in metrics.items()
        if k in REVENUE_CRITICAL_IDS and (v.get("success_rate", 1) < 0.7 or v.get("status") == "停止")
        and v.get("total_count", 0) > 0
    ]
    rev_critical_stopped.sort(key=lambda x: x[1].get("success_rate", 1))

    top_fail = failing_agent_top3[0] if failing_agent_top3 else None
    top_blocker = revenue_blocker_top3[0] if revenue_blocker_top3 else None

    # 優先度判定: CRITICAL > 売上直結停止 > 売上阻害TOP > 最危険AI > WARNING > 通知失敗
    ceo_confidence = "HIGH"
    ceo_reasons = []

    if unresolved_critical > 0:
        ceo_immediate = f"CRITICAL {unresolved_critical}件がキューに滞留中 — bash run_alert_retry.sh を今すぐ実行"
        ceo_reason_parts = [f"未解決CRITICALが{unresolved_critical}件ある"]
        ceo_confidence = "HIGH"
    elif rev_critical_stopped:
        k0, v0 = rev_critical_stopped[0]
        ceo_immediate = f"{v0.get('name_ja',k0)}が{v0.get('success_rate',0):.0%}で停止 — pipeline_steps.jsonl を今すぐ確認"
        ceo_reason_parts = [f"売上直結の{v0.get('name_ja',k0)}が{v0.get('success_rate',0):.0%}で機能不全"]
        ceo_confidence = "HIGH"
    elif top_fail and top_fail.get("rate", 1) == 0.0:
        name = top_fail["name"]
        ceo_immediate = f"{name}が0%で継続停止 — agent_metrics.jsonの詳細を確認し再起動を検討"
        ceo_reason_parts = [f"{name}の成功率が0%で停止継続中"]
        ceo_confidence = "MEDIUM"
    elif queue_pending > 0:
        ceo_immediate = f"通知キューにpending {queue_pending}件 — bash run_alert_retry.sh を実行"
        ceo_reason_parts = [f"送信失敗通知が{queue_pending}件キューに滞留"]
        ceo_confidence = "MEDIUM"
    else:
        ceo_immediate = "緊急止血なし — 通常監視を継続"
        ceo_reason_parts = ["未解決CRITICAL・pipeline停止・pending通知なし"]
        ceo_confidence = "LOW"

    # 今日直す1点
    if top_blocker and top_blocker.get("rank", "🟢") in ("🔴", "🟡"):
        bname = top_blocker["name"]
        brate = top_blocker["rate"]
        ceo_today_fix = f"{bname}({brate:.0%}) — pipeline_steps.jsonlで直近3runの失敗原因を切り分け修正"
        ceo_reasons.append(f"{bname}が売上阻害TOP({brate:.0%})")
    elif top_fail and top_fail.get("rate", 1) < 0.5:
        fname = top_fail["name"]
        frate = top_fail["rate"]
        ceo_today_fix = f"{fname}({frate:.0%}) — agent_metrics.jsonの失敗ログを調査してプロンプト修正"
        ceo_reasons.append(f"{fname}の成功率が{frate:.0%}で低水準")
    elif notif_failure > 0:
        ceo_today_fix = f"通知失敗{notif_failure}件({top_fail_reason}) — discord_webhooks.jsonのURLを再確認"
        ceo_reasons.append(f"通知失敗{notif_failure}件が積算中({top_fail_reason})")
    else:
        ceo_today_fix = "収益スコア上位記事のCTA配置を確認し横展開"
        ceo_reasons.append("上位指標に異常なし")

    # 今日の売上レバー
    contaminated = rev.get("summary", {}).get("contaminated_title_count", 0)
    avg_rev = rev.get("summary", {}).get("avg_revenue_score", 0)
    if contaminated > 0:
        ceo_revenue_lever = f"タイトル汚染{contaminated}件 — audit_feedback.jsonlでサーナイト出力を修正すれば即CVR改善"
    elif avg_rev < 0.7:
        ceo_revenue_lever = f"平均収益スコア{avg_rev:.2f} — CTA未設置・文字数不足記事にCTAを追加して収益スコアを上げる"
    elif len(today_posts) < 3:
        ceo_revenue_lever = f"今日の投稿{len(today_posts)}本 — カイリュー・バタフリーの速報パイプラインを優先実行し本数を増やす"
    else:
        ceo_revenue_lever = f"収益スコア{avg_rev:.2f}・投稿{len(today_posts)}本 — 上位記事パターンを次の速報に即適用"

    # 今は触らない
    safe_agents = sum(1 for v in active.values() if v["rank"] == "🟢")
    if unresolved_warning == 0 and queue_pending == 0 and unresolved_critical == 0:
        ceo_ignore = f"WARNINGゼロ・pendingゼロ — 正常稼働中{safe_agents}名のエージェントと通知システムは放置でよい"
    elif unresolved_warning > 0:
        ceo_ignore = f"WARNING{unresolved_warning}件は本日後回し可 — CRITICAL解消後に対処"
    else:
        ceo_ignore = f"正常エージェント{safe_agents}名は放置でよい"

    # 判断理由3行以内
    ceo_reasons_all = ceo_reason_parts + ceo_reasons
    # 重複除去・最大3行
    seen = set()
    ceo_reasons_deduped = []
    for r in ceo_reasons_all:
        if r not in seen:
            seen.add(r)
            ceo_reasons_deduped.append(r)
    ceo_reason_short = " / ".join(ceo_reasons_deduped[:3])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company": "K-POP Journal AI Company",
        "ceo": "ミュウツー",
        "owner": "人間オーナー（閲覧専用）",
        "overall_success_rate": round(overall, 3),
        "active_agent_count": len(active),
        "excellent_count": sum(1 for v in active.values() if v["rank"] == "🟢"),
        "warning_count": sum(1 for v in active.values() if v["rank"] == "🟡"),
        "critical_count": sum(1 for v in active.values() if v["rank"] == "🔴"),
        "sabori_count": sum(1 for v in active.values() if v.get("sabori_flag")),
        "error_agent_count": sum(1 for v in active.values() if v.get("error_flag")),
        "today_posts": len(today_posts),
        "week_posts": len(week_posts),
        "high_priority_actions": opt.get("high_count", 0),
        "top3_agents": [
            {"name": v["name_ja"], "rate": v["success_rate"], "rank": v["rank"]}
            for _, v in sorted_active[:3]
        ],
        "worst3_agents": [
            {"name": v["name_ja"], "rate": v["success_rate"], "rank": v["rank"]}
            for _, v in sorted_active[-3:] if v["total_count"] > 0
        ],
        "avg_revenue_score": rev.get("summary", {}).get("avg_revenue_score", 0),
        "cta_rate": rev.get("summary", {}).get("cta_rate", 0),
        # ── 通知統計（新規11フィールド）──
        "notification_success_count":        notif_success,
        "notification_failure_count":        notif_failure,
        "notification_suppressed_count":     notif_suppress,
        "notification_pending_count":        queue_pending,
        "notification_permanent_failed_count": queue_perm_fail,
        "latest_notification_sent_at":       latest_sent_at,
        "latest_notification_failed_at":     latest_failed_at,
        "top_notification_failure_reason":   top_fail_reason,
        "unresolved_critical_count":         unresolved_critical,
        "unresolved_warning_count":          unresolved_warning,
        "revenue_blocker_top3":              revenue_blocker_top3,
        "idle_agent_top3":                   idle_agent_top3,
        "failing_agent_top3":               failing_agent_top3,
        # ── CEO意思決定フィールド ──
        "ceo_immediate_action":  ceo_immediate,
        "ceo_today_fix":         ceo_today_fix,
        "ceo_revenue_lever":     ceo_revenue_lever,
        "ceo_ignore_today":      ceo_ignore,
        "ceo_reason_short":      ceo_reason_short,
        "ceo_confidence":        ceo_confidence,
    }


# ─────────────────────────────────────────────
# メイン実行
# ─────────────────────────────────────────────

def main():
    print("[agent_monitor v2.0] 解析開始...", file=sys.stderr)

    pipeline_data = parse_pipeline_jsonl()
    gardevoir_data = parse_gardevoir_jsonl()
    posts = parse_kpi_posts()
    errors = parse_kpi_errors()
    watchdog = parse_watchdog_alerts()
    error_patterns = parse_error_patterns()
    kpi_targets = parse_kpi_targets()
    rev_config = parse_revenue_config()

    print(f"  pipeline: {len(pipeline_data)}エージェント / posts: {len(posts)}件", file=sys.stderr)

    metrics = build_agent_metrics(pipeline_data, gardevoir_data)
    org_map = build_org_map(metrics)
    audit_feedback = parse_audit_feedback()
    rev_metrics = build_revenue_metrics(posts, kpi_targets, rev_config, audit_feedback)
    opt_actions = build_optimization_actions(metrics, posts, errors, watchdog, error_patterns)

    # サマリー統計
    active = {k: v for k, v in metrics.items() if v["total_count"] > 0 and k != "pipeline"}
    overall = sum(v["success_rate"] for v in active.values()) / len(active) if active else 0.0

    agent_metrics_out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "system": "K-POP Journal AI Company 統合監視システム v2.0",
        "ceo": "ミュウツー",
        "owner": "人間オーナー（閲覧専用）",
        "summary": {
            "overall_success_rate": round(overall, 3),
            "total_agents_defined": len(metrics),
            "active_agents": len(active),
            "excellent_agents": sum(1 for v in active.values() if v["rank"] == "🟢"),
            "warning_agents": sum(1 for v in active.values() if v["rank"] == "🟡"),
            "critical_agents": sum(1 for v in active.values() if v["rank"] == "🔴"),
            "sabori_agents": sum(1 for v in metrics.values() if v.get("sabori_flag")),
            "error_flagged_agents": sum(1 for v in metrics.values() if v.get("error_flag")),
        },
        "agents": metrics,
    }

    dashboard_summary = build_dashboard_summary(metrics, opt_actions, rev_metrics, posts)

    # CEO実行命令エクスポート（dashboard_summary を材料に命令生成・キュー保存）
    try:
        # dashboard_summary を一時書き出しして ceo_action_export が読めるようにする
        _tmp = BASE / "dashboard_summary.json"
        _tmp.write_text(json.dumps(dashboard_summary, ensure_ascii=False, indent=2) + "\n")
        if str(BASE) not in sys.path:
            sys.path.insert(0, str(BASE))
        from lib.ceo_action_export import run as ceo_export_run
        ceo_action_fields = ceo_export_run()
        dashboard_summary.update(ceo_action_fields)
        print("  ✅ ceo_action_queue.jsonl 更新完了", file=sys.stderr)
    except Exception as e:
        print(f"  ⚠️  CEO action export スキップ: {e}", file=sys.stderr)

    # CEO実行エンジン（pending命令を安全に処理・ログ記録）
    try:
        from lib.ceo_executor import run as ceo_executor_run
        exec_result = ceo_executor_run()
        dashboard_summary["ceo_exec_processed"]     = exec_result.get("processed", 0)
        dashboard_summary["ceo_exec_done"]          = exec_result.get("done", 0)
        dashboard_summary["ceo_exec_failed"]        = exec_result.get("failed", 0)
        dashboard_summary["ceo_exec_blocked"]       = exec_result.get("blocked", 0)
        dashboard_summary["ceo_exec_skipped"]       = exec_result.get("skipped", 0)
        dashboard_summary["ceo_exec_safe_retry"]         = exec_result.get("safe_retry", 0)
        dashboard_summary["ceo_exec_safe_inspect"]        = exec_result.get("safe_inspect", 0)
        dashboard_summary["ceo_exec_improvement_queued"]  = exec_result.get("improvement_queued", 0)
        dashboard_summary["ceo_exec_action_type"]   = exec_result.get("action_type", "")
        dashboard_summary["ceo_exec_target_agent"]  = exec_result.get("target_agent", "")
        dashboard_summary["ceo_exec_result"]        = exec_result.get("result", "no_pending")
        dashboard_summary["ceo_exec_reason"]        = exec_result.get("reason", "")
        dashboard_summary["ceo_exec_summary"]       = exec_result.get("summary", "")
        dashboard_summary["ceo_exec_next"]          = exec_result.get("next_recommendation", "")
        print(
            f"  ✅ ceo_executor 完了: "
            f"処理{exec_result.get('processed',0)}件 "
            f"done={exec_result.get('done',0)} "
            f"failed={exec_result.get('failed',0)} "
            f"blocked={exec_result.get('blocked',0)}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  CEO executor スキップ: {e}", file=sys.stderr)

    # SAFE候補昇格 (ceo_ready_queue)
    try:
        from lib.ceo_improvement_queue import promote_safe_candidates, get_ready_queue_stats
        promote_result = promote_safe_candidates()
        from lib.ceo_improvement_queue import (
            promote_to_execution_ready, simulate_execution_ready, get_simulation_stats,
            rank_execution_simulations, get_ranked_queue_stats,
            promote_to_execution_packet, get_packet_queue_stats,
            promote_to_dispatch_request, get_dispatch_queue_stats,
            promote_to_executor_stub, get_stub_queue_stats,
            simulate_executor_stub, get_dry_run_queue_stats,
            promote_to_execution_candidate, get_candidate_queue_stats,
            promote_to_limited_execution, get_limited_execution_stats,
            evaluate_execution_guard, get_guard_result_stats,
            promote_to_config_patch_plan, get_patch_plan_stats,
            promote_to_config_apply_queue, get_apply_queue_stats,
        )
        from lib.ceo_config_executor import apply_config_queue, get_apply_result_stats
        from lib.ceo_performance_tracker import (
            run_full_tracking_cycle,
            get_exec_result_stats, get_perf_eval_stats, get_feedback_stats,
        )
        er_result  = promote_to_execution_ready()
        sim_result = simulate_execution_ready()
        sim_stats  = get_simulation_stats()
        dashboard_summary["simulation_pending_count"]        = sim_stats.get("pending", 0)
        dashboard_summary["simulation_high_risk_count"]      = sim_stats.get("high_risk", 0)
        dashboard_summary["simulation_medium_risk_count"]    = sim_stats.get("medium_risk", 0)
        dashboard_summary["simulation_low_risk_count"]       = sim_stats.get("low_risk", 0)
        dashboard_summary["latest_simulation_target_agent"]  = sim_stats.get("latest_agent", "")
        dashboard_summary["latest_simulation_type"]          = sim_stats.get("latest_sim_type", "")
        dashboard_summary["latest_simulation_risk"]          = sim_stats.get("latest_risk", "")
        print(
            f"  ✅ simulation 登録: simulated={sim_result.get('simulated',0)} "
            f"dup={sim_result.get('skipped_duplicate',0)} "
            f"pending={sim_stats.get('pending',0)}件",
            file=sys.stderr,
        )
        rank_result = rank_execution_simulations()
        ranked_stats = get_ranked_queue_stats()
        dashboard_summary["ranked_pending_count"]       = ranked_stats.get("pending", 0)
        dashboard_summary["ranked_hold_count"]          = ranked_stats.get("held", 0)
        dashboard_summary["ranked_high_priority_count"] = ranked_stats.get("high_priority", 0)
        dashboard_summary["ranked_medium_priority_count"] = ranked_stats.get("medium_priority", 0)
        dashboard_summary["ranked_low_priority_count"]  = ranked_stats.get("low_priority", 0)
        dashboard_summary["latest_ranked_target_agent"] = ranked_stats.get("latest_agent", "")
        dashboard_summary["latest_ranked_priority_score"] = ranked_stats.get("latest_p_score", 0.0)
        dashboard_summary["latest_ranked_execution_order"] = ranked_stats.get("latest_order", 0)
        print(
            f"  ✅ ranked 順位付け: ranked={rank_result.get('ranked',0)} "
            f"dup={rank_result.get('skipped_duplicate',0)} "
            f"pending={ranked_stats.get('pending',0)}件",
            file=sys.stderr,
        )
        packet_result = promote_to_execution_packet()
        packet_stats  = get_packet_queue_stats()
        dashboard_summary["packet_pending_count"]        = packet_stats.get("pending", 0)
        dashboard_summary["packet_high_count"]           = packet_stats.get("high", 0)
        dashboard_summary["packet_medium_count"]         = packet_stats.get("medium", 0)
        dashboard_summary["packet_low_count"]            = packet_stats.get("low", 0)
        dashboard_summary["latest_packet_target_agent"]  = packet_stats.get("latest_agent", "")
        dashboard_summary["latest_packet_priority_score"] = packet_stats.get("latest_score", 0.0)
        dashboard_summary["latest_packet_execution_order"] = packet_stats.get("latest_order", 0)
        print(
            f"  ✅ packet 生成: promoted={packet_result.get('promoted',0)} "
            f"dup={packet_result.get('skipped_duplicate',0)} "
            f"pending={packet_stats.get('pending',0)}件",
            file=sys.stderr,
        )
        dispatch_result = promote_to_dispatch_request()
        dispatch_stats  = get_dispatch_queue_stats()
        dashboard_summary["dispatch_pending_count"]         = dispatch_stats.get("pending", 0)
        dashboard_summary["dispatch_high_count"]            = dispatch_stats.get("high", 0)
        dashboard_summary["dispatch_medium_count"]          = dispatch_stats.get("medium", 0)
        dashboard_summary["dispatch_low_count"]             = dispatch_stats.get("low", 0)
        dashboard_summary["latest_dispatch_target_agent"]   = dispatch_stats.get("latest_agent", "")
        dashboard_summary["latest_dispatch_priority_score"] = dispatch_stats.get("latest_score", 0.0)
        dashboard_summary["latest_dispatch_execution_order"] = dispatch_stats.get("latest_order", 0)
        print(
            f"  ✅ dispatch 生成: promoted={dispatch_result.get('promoted',0)} "
            f"dup={dispatch_result.get('skipped_duplicate',0)} "
            f"pending={dispatch_stats.get('pending',0)}件",
            file=sys.stderr,
        )
        # フェーズ1: executor_stub
        stub_result = promote_to_executor_stub()
        stub_stats  = get_stub_queue_stats()
        dashboard_summary["stub_pending_count"]         = stub_stats.get("pending", 0)
        dashboard_summary["stub_high_count"]            = stub_stats.get("high", 0)
        dashboard_summary["stub_medium_count"]          = stub_stats.get("medium", 0)
        dashboard_summary["stub_low_count"]             = stub_stats.get("low", 0)
        dashboard_summary["latest_stub_target_agent"]   = stub_stats.get("latest_agent", "")
        dashboard_summary["latest_stub_priority_score"] = stub_stats.get("latest_score", 0.0)
        dashboard_summary["latest_stub_execution_order"] = stub_stats.get("latest_order", 0)
        print(
            f"  ✅ stub 生成: promoted={stub_result.get('promoted',0)} "
            f"dup={stub_result.get('skipped_duplicate',0)} "
            f"pending={stub_stats.get('pending',0)}件",
            file=sys.stderr,
        )
        # フェーズ2: dry_run_result
        dry_run_result = simulate_executor_stub()
        dry_run_stats  = get_dry_run_queue_stats()
        dashboard_summary["dry_run_pending_count"]         = dry_run_stats.get("pending", 0)
        dashboard_summary["dry_run_high_risk_count"]       = dry_run_stats.get("high_risk", 0)
        dashboard_summary["dry_run_medium_risk_count"]     = dry_run_stats.get("medium_risk", 0)
        dashboard_summary["dry_run_low_risk_count"]        = dry_run_stats.get("low_risk", 0)
        dashboard_summary["latest_dry_run_target_agent"]   = dry_run_stats.get("latest_agent", "")
        dashboard_summary["latest_dry_run_benefit_score"]  = dry_run_stats.get("latest_benefit", 0.0)
        dashboard_summary["latest_dry_run_execution_order"] = dry_run_stats.get("latest_order", 0)
        print(
            f"  ✅ dry_run 生成: simulated={dry_run_result.get('simulated',0)} "
            f"dup={dry_run_result.get('skipped_duplicate',0)} "
            f"pending={dry_run_stats.get('pending',0)}件",
            file=sys.stderr,
        )
        # フェーズ3: execution_candidate
        candidate_result = promote_to_execution_candidate()
        candidate_stats  = get_candidate_queue_stats()
        dashboard_summary["candidate_pending_count"]         = candidate_stats.get("pending", 0)
        dashboard_summary["candidate_high_count"]            = candidate_stats.get("high", 0)
        dashboard_summary["candidate_medium_count"]          = candidate_stats.get("medium", 0)
        dashboard_summary["candidate_low_count"]             = candidate_stats.get("low", 0)
        dashboard_summary["latest_candidate_target_agent"]   = candidate_stats.get("latest_agent", "")
        dashboard_summary["latest_candidate_priority_score"] = candidate_stats.get("latest_score", 0.0)
        dashboard_summary["latest_candidate_execution_order"] = candidate_stats.get("latest_order", 0)
        print(
            f"  ✅ candidate 生成: promoted={candidate_result.get('promoted',0)} "
            f"held={candidate_result.get('held',0)} "
            f"dup={candidate_result.get('skipped_duplicate',0)} "
            f"pending={candidate_stats.get('pending',0)}件",
            file=sys.stderr,
        )
        # フェーズ4: limited_execution_queue
        limited_result = promote_to_limited_execution()
        limited_stats  = get_limited_execution_stats()
        dashboard_summary["limited_pending_count"]              = limited_stats.get("pending", 0)
        dashboard_summary["limited_high_count"]                 = limited_stats.get("high", 0)
        dashboard_summary["limited_medium_count"]               = limited_stats.get("medium", 0)
        dashboard_summary["limited_low_count"]                  = limited_stats.get("low", 0)
        dashboard_summary["latest_limited_target_agent"]        = limited_stats.get("latest_agent", "")
        dashboard_summary["latest_limited_priority_score"]      = limited_stats.get("latest_score", 0.0)
        dashboard_summary["latest_limited_execution_order"]     = limited_stats.get("latest_order", 0)
        print(
            f"  ✅ limited_execution 生成: promoted={limited_result.get('promoted',0)} "
            f"held={limited_result.get('held',0)} "
            f"dup={limited_result.get('skipped_duplicate',0)} "
            f"pending={limited_stats.get('pending',0)}件",
            file=sys.stderr,
        )
        # フェーズ5: execution_guard_result
        guard_result = evaluate_execution_guard()
        guard_stats  = get_guard_result_stats()
        dashboard_summary["guard_allowed_count"]                = guard_stats.get("allowed", 0)
        dashboard_summary["guard_blocked_count"]                = guard_stats.get("blocked", 0)
        dashboard_summary["latest_guard_target_agent"]          = guard_stats.get("latest_agent", "")
        dashboard_summary["latest_guard_status"]                = guard_stats.get("latest_status", "")
        dashboard_summary["latest_guard_priority_score"]        = guard_stats.get("latest_score", 0.0)
        dashboard_summary["latest_guard_execution_order"]       = guard_stats.get("latest_order", 0)
        print(
            f"  ✅ execution_guard 判定: allowed={guard_result.get('allowed',0)} "
            f"blocked={guard_result.get('blocked',0)} "
            f"dup={guard_result.get('skipped_duplicate',0)}",
            file=sys.stderr,
        )
        # フェーズ6: config_patch_plan
        patch_plan_result = promote_to_config_patch_plan()
        patch_plan_stats  = get_patch_plan_stats()
        dashboard_summary["patch_plan_pending_count"]        = patch_plan_stats.get("pending", 0)
        dashboard_summary["patch_plan_held_count"]           = patch_plan_stats.get("held", 0)
        dashboard_summary["latest_patch_plan_target_agent"]  = patch_plan_stats.get("latest_agent", "")
        dashboard_summary["latest_patch_plan_priority_score"] = patch_plan_stats.get("latest_score", 0.0)
        print(
            f"  ✅ config_patch_plan 生成: promoted={patch_plan_result.get('promoted',0)} "
            f"held={patch_plan_result.get('held',0)} "
            f"dup={patch_plan_result.get('skipped_duplicate',0)} "
            f"pending={patch_plan_stats.get('pending',0)}件",
            file=sys.stderr,
        )
        # フェーズ7: config_apply_queue
        apply_queue_result = promote_to_config_apply_queue()
        apply_queue_stats  = get_apply_queue_stats()
        dashboard_summary["config_apply_pending_count"]      = apply_queue_stats.get("pending", 0)
        dashboard_summary["latest_apply_queue_target_agent"] = apply_queue_stats.get("latest_agent", "")
        print(
            f"  ✅ config_apply_queue 生成: promoted={apply_queue_result.get('promoted',0)} "
            f"dup={apply_queue_result.get('skipped_duplicate',0)} "
            f"pending={apply_queue_stats.get('pending',0)}件",
            file=sys.stderr,
        )
        # フェーズ8: config_apply 実行
        apply_exec_result = apply_config_queue()
        apply_result_stats = get_apply_result_stats()
        dashboard_summary["config_apply_applied_count"]      = apply_result_stats.get("applied", 0)
        dashboard_summary["config_apply_blocked_count"]      = apply_result_stats.get("blocked", 0)
        dashboard_summary["config_apply_failed_count"]       = apply_result_stats.get("failed", 0)
        dashboard_summary["latest_config_apply_target_agent"] = apply_result_stats.get("latest_agent", "")
        dashboard_summary["latest_config_apply_result"]      = apply_result_stats.get("latest_status", "")
        dashboard_summary["latest_config_apply_diff_path"]   = apply_result_stats.get("latest_diff_path", "")
        print(
            f"  ✅ config_apply 実行: applied={apply_exec_result.get('applied',0)} "
            f"blocked={apply_exec_result.get('blocked',0)} "
            f"failed={apply_exec_result.get('failed',0)} "
            f"dup={apply_exec_result.get('skipped_duplicate',0)}",
            file=sys.stderr,
        )
        # フェーズ9: performance tracking (実行結果→評価→フィードバック→改善loop)
        tracking_result = run_full_tracking_cycle()
        exec_stats  = get_exec_result_stats()
        perf_stats  = get_perf_eval_stats()
        fb_stats    = get_feedback_stats()
        dashboard_summary["exec_result_total"]            = exec_stats.get("total", 0)
        dashboard_summary["exec_result_success"]          = exec_stats.get("success", 0)
        dashboard_summary["exec_result_fail"]             = exec_stats.get("fail", 0)
        dashboard_summary["exec_result_latest_agent"]     = exec_stats.get("latest_agent", "")
        dashboard_summary["exec_result_latest_status"]    = exec_stats.get("latest_status", "")
        dashboard_summary["perf_eval_total"]              = perf_stats.get("total", 0)
        dashboard_summary["perf_eval_improved"]           = perf_stats.get("improved", 0)
        dashboard_summary["perf_eval_no_change"]          = perf_stats.get("no_change", 0)
        dashboard_summary["perf_eval_degraded"]           = perf_stats.get("degraded", 0)
        dashboard_summary["perf_eval_latest_agent"]       = perf_stats.get("latest_agent", "")
        dashboard_summary["perf_eval_latest_result"]      = perf_stats.get("latest_result", "")
        dashboard_summary["perf_eval_latest_delta"]       = perf_stats.get("latest_delta", "")
        dashboard_summary["feedback_total"]               = fb_stats.get("total", 0)
        dashboard_summary["feedback_keep"]                = fb_stats.get("keep", 0)
        dashboard_summary["feedback_minor_adjust"]        = fb_stats.get("minor_adjust", 0)
        dashboard_summary["feedback_urgent_fix"]          = fb_stats.get("urgent_fix", 0)
        dashboard_summary["feedback_latest_agent"]        = fb_stats.get("latest_agent", "")
        dashboard_summary["feedback_latest_type"]         = fb_stats.get("latest_type", "")
        dashboard_summary["feedback_latest_priority"]     = fb_stats.get("latest_priority", "")
        tr_er = tracking_result.get("execution_result", {})
        tr_pe = tracking_result.get("performance_eval", {})
        tr_fb = tracking_result.get("feedback_loop", {})
        tr_ri = tracking_result.get("improvement_reinject", {})
        print(
            f"  ✅ 実行結果収集: collected={tr_er.get('collected',0)} "
            f"dup={tr_er.get('skipped_duplicate',0)} "
            f"no_data={tr_er.get('skipped_no_data',0)}",
            file=sys.stderr,
        )
        print(
            f"  ✅ パフォーマンス評価: evaluated={tr_pe.get('evaluated',0)} "
            f"dup={tr_pe.get('skipped_duplicate',0)}",
            file=sys.stderr,
        )
        print(
            f"  ✅ フィードバック生成: generated={tr_fb.get('generated',0)} "
            f"dup={tr_fb.get('skipped_duplicate',0)}",
            file=sys.stderr,
        )
        print(
            f"  ✅ 改善loop再投入: enqueued={tr_ri.get('enqueued',0)} "
            f"keep_skip={tr_ri.get('skipped_keep',0)} "
            f"dup={tr_ri.get('skipped_duplicate',0)}",
            file=sys.stderr,
        )
        ready_stats = get_ready_queue_stats()
        dashboard_summary["ready_queue_pending_count"]    = ready_stats.get("pending", 0)
        dashboard_summary["ready_queue_high_count"]       = ready_stats.get("high", 0)
        dashboard_summary["ready_queue_medium_count"]     = ready_stats.get("medium", 0)
        dashboard_summary["ready_queue_duplicate_count"]  = ready_stats.get("duplicate_count", 0)
        dashboard_summary["exec_ready_pending_count"]     = ready_stats.get("exec_ready_pending", 0)
        dashboard_summary["latest_ready_target_agent"]    = ready_stats.get("latest_agent", "")
        dashboard_summary["latest_ready_improvement_type"] = ready_stats.get("latest_type", "")
        dashboard_summary["latest_ready_priority"]        = ready_stats.get("latest_priority", "")
        dashboard_summary["latest_er_target_agent"]       = ready_stats.get("latest_er_agent", "")
        dashboard_summary["latest_er_improvement_type"]   = ready_stats.get("latest_er_type", "")
        dashboard_summary["latest_er_priority"]           = ready_stats.get("latest_er_priority", "")
        print(
            f"  ✅ execution_ready 昇格: promoted={er_result.get('promoted',0)} "
            f"dup={er_result.get('skipped_duplicate',0)} "
            f"pending={ready_stats.get('exec_ready_pending',0)}件",
            file=sys.stderr,
        )
        print(
            f"  ✅ ready_queue 昇格: promoted={promote_result.get('promoted',0)} "
            f"dup={promote_result.get('skipped_duplicate',0)} "
            f"pending={ready_stats.get('pending',0)}件",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  ready_queue 昇格スキップ: {e}", file=sys.stderr)

    # フェーズ10: フィードバック再投入優先順位付け
    try:
        from lib.ceo_feedback_ranker import run_feedback_ranking_cycle, get_reinject_priority_stats
        rank_result  = run_feedback_ranking_cycle()
        rank_stats   = get_reinject_priority_stats()
        dashboard_summary["reinject_pending_count"]  = rank_stats.get("reinject_pending_count", 0)
        dashboard_summary["reinject_critical_count"] = rank_stats.get("reinject_critical_count", 0)
        dashboard_summary["reinject_high_count"]     = rank_stats.get("reinject_high_count", 0)
        dashboard_summary["reinject_medium_count"]   = rank_stats.get("reinject_medium_count", 0)
        dashboard_summary["reinject_low_count"]      = rank_stats.get("reinject_low_count", 0)
        dashboard_summary["reinject_top1_agent"]     = rank_stats.get("reinject_top1_agent", "—")
        dashboard_summary["reinject_top1_score"]     = rank_stats.get("reinject_top1_score", 0.0)
        dashboard_summary["reinject_top1_label"]     = rank_stats.get("reinject_top1_label", "—")
        dashboard_summary["reinject_latest_agent"]   = rank_stats.get("reinject_latest_agent", "—")
        dashboard_summary["reinject_latest_score"]   = rank_stats.get("reinject_latest_score", 0.0)
        dashboard_summary["reinject_latest_label"]   = rank_stats.get("reinject_latest_label", "—")
        print(
            f"  ✅ reinject 優先順位: ranked={rank_result.get('ranked',0)} "
            f"dup={rank_result.get('dup',0)} "
            f"pending={rank_result.get('pending',0)}件",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  reinject 優先順位スキップ: {e}", file=sys.stderr)

    # フェーズ11: 再投入ルーティング (dispatch → limited_return)
    try:
        from lib.ceo_reinject_router import (
            run_reinject_routing_cycle,
            get_reinject_dispatch_stats,
            get_reinject_return_stats,
        )
        routing_result = run_reinject_routing_cycle()
        disp_stats     = get_reinject_dispatch_stats()
        ret_stats      = get_reinject_return_stats()

        dashboard_summary["reinject_dispatch_pending_count"] = disp_stats.get("reinject_dispatch_pending_count", 0)
        dashboard_summary["reinject_dispatch_high_count"]    = disp_stats.get("reinject_dispatch_high_count", 0)
        dashboard_summary["reinject_dispatch_medium_count"]  = disp_stats.get("reinject_dispatch_medium_count", 0)
        dashboard_summary["reinject_dispatch_latest_agent"]  = disp_stats.get("reinject_dispatch_latest_agent", "—")
        dashboard_summary["reinject_dispatch_latest_label"]  = disp_stats.get("reinject_dispatch_latest_label", "—")
        dashboard_summary["reinject_return_pending_count"]   = ret_stats.get("reinject_return_pending_count", 0)
        dashboard_summary["reinject_return_high_count"]      = ret_stats.get("reinject_return_high_count", 0)
        dashboard_summary["reinject_return_medium_count"]    = ret_stats.get("reinject_return_medium_count", 0)
        dashboard_summary["reinject_return_latest_agent"]    = ret_stats.get("reinject_return_latest_agent", "—")
        dashboard_summary["reinject_return_latest_label"]    = ret_stats.get("reinject_return_latest_label", "—")
        dashboard_summary["reinject_return_top1_agent"]      = ret_stats.get("reinject_return_top1_agent", "—")
        dashboard_summary["reinject_return_top1_score"]      = ret_stats.get("reinject_return_top1_score", 0.0)

        dr = routing_result.get("dispatch", {})
        rr = routing_result.get("limited_return", {})
        print(
            f"  ✅ reinject dispatch: promoted={dr.get('promoted',0)} "
            f"dup={dr.get('dup',0)} "
            f"pending={dr.get('pending',0)}件",
            file=sys.stderr,
        )
        print(
            f"  ✅ reinject return: promoted={rr.get('promoted',0)} "
            f"dup={rr.get('dup',0)} "
            f"pending={rr.get('pending',0)}件",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  reinject routing スキップ: {e}", file=sys.stderr)

    # フェーズ12: 再投入ゲート + patch_ready
    try:
        from lib.ceo_reinject_gate import (
            run_reinject_gate_cycle,
            get_reinject_gate_stats,
            get_reinject_patch_ready_stats,
        )
        gate_cycle  = run_reinject_gate_cycle()
        gate_stats  = get_reinject_gate_stats()
        pr_stats    = get_reinject_patch_ready_stats()

        dashboard_summary["reinject_gate_pending_count"]        = gate_stats.get("reinject_gate_pending_count", 0)
        dashboard_summary["reinject_gate_blocked_count"]        = gate_stats.get("reinject_gate_blocked_count", 0)
        dashboard_summary["reinject_gate_latest_agent"]         = gate_stats.get("reinject_gate_latest_agent", "—")
        dashboard_summary["reinject_gate_latest_status"]        = gate_stats.get("reinject_gate_latest_status", "—")
        dashboard_summary["reinject_patch_ready_pending_count"] = pr_stats.get("reinject_patch_ready_pending_count", 0)
        dashboard_summary["reinject_patch_ready_high_count"]    = pr_stats.get("reinject_patch_ready_high_count", 0)
        dashboard_summary["reinject_patch_ready_medium_count"]  = pr_stats.get("reinject_patch_ready_medium_count", 0)
        dashboard_summary["reinject_patch_ready_latest_agent"]  = pr_stats.get("reinject_patch_ready_latest_agent", "—")
        dashboard_summary["reinject_patch_ready_latest_label"]  = pr_stats.get("reinject_patch_ready_latest_label", "—")
        dashboard_summary["reinject_patch_ready_top1_agent"]    = pr_stats.get("reinject_patch_ready_top1_agent", "—")
        dashboard_summary["reinject_patch_ready_top1_score"]    = pr_stats.get("reinject_patch_ready_top1_score", 0.0)

        gr = gate_cycle.get("gate", {})
        pr = gate_cycle.get("patch_ready", {})
        print(
            f"  ✅ reinject gate: promoted={gr.get('promoted',0)} "
            f"blocked={gr.get('blocked',0)} "
            f"dup={gr.get('dup',0)} "
            f"pending={gr.get('pending',0)}件",
            file=sys.stderr,
        )
        print(
            f"  ✅ reinject patch_ready: promoted={pr.get('promoted',0)} "
            f"dup={pr.get('dup',0)} "
            f"pending={pr.get('pending',0)}件",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  reinject gate スキップ: {e}", file=sys.stderr)

    # フェーズ13: 再接続予約
    try:
        from lib.ceo_reinject_reserve import run_reinject_reserve_cycle, get_reinject_reserve_stats
        res_result = run_reinject_reserve_cycle()
        res_stats  = get_reinject_reserve_stats()

        dashboard_summary["reinject_reserve_pending_count"]  = res_stats.get("reinject_reserve_pending_count", 0)
        dashboard_summary["reinject_reserve_critical_count"] = res_stats.get("reinject_reserve_critical_count", 0)
        dashboard_summary["reinject_reserve_high_count"]     = res_stats.get("reinject_reserve_high_count", 0)
        dashboard_summary["reinject_reserve_medium_count"]   = res_stats.get("reinject_reserve_medium_count", 0)
        dashboard_summary["reinject_reserve_low_count"]      = res_stats.get("reinject_reserve_low_count", 0)
        dashboard_summary["reinject_reserve_top1_agent"]     = res_stats.get("reinject_reserve_top1_agent", "—")
        dashboard_summary["reinject_reserve_top1_score"]     = res_stats.get("reinject_reserve_top1_score", 0.0)
        dashboard_summary["reinject_reserve_top1_label"]     = res_stats.get("reinject_reserve_top1_label", "—")
        dashboard_summary["reinject_reserve_latest_agent"]   = res_stats.get("reinject_reserve_latest_agent", "—")
        dashboard_summary["reinject_reserve_latest_label"]   = res_stats.get("reinject_reserve_latest_label", "—")
        dashboard_summary["reinject_reserve_latest_order"]   = res_stats.get("reinject_reserve_latest_order", 0)
        print(
            f"  ✅ reinject reserve: promoted={res_result.get('promoted',0)} "
            f"dup={res_result.get('dup',0)} "
            f"pending={res_result.get('pending',0)}件",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  reinject reserve スキップ: {e}", file=sys.stderr)

    # フェーズ14: 再投入コミット（patch_plan queue への実再投入）
    try:
        from lib.ceo_reinject_commit import run_reinject_commit_cycle, get_reinject_commit_stats
        commit_cycle = run_reinject_commit_cycle()
        commit_stats = get_reinject_commit_stats()

        dashboard_summary["reinject_commit_pending_count"]           = commit_stats.get("reinject_commit_pending_count", 0)
        dashboard_summary["reinject_commit_latest_agent"]            = commit_stats.get("reinject_commit_latest_agent", "—")
        dashboard_summary["reinject_commit_latest_label"]            = commit_stats.get("reinject_commit_latest_label", "—")
        dashboard_summary["reinject_commit_latest_order"]            = commit_stats.get("reinject_commit_latest_order", 0)
        dashboard_summary["reinject_commit_top1_agent"]              = commit_stats.get("reinject_commit_top1_agent", "—")
        dashboard_summary["reinject_commit_top1_score"]              = commit_stats.get("reinject_commit_top1_score", 0.0)
        dashboard_summary["reinject_commit_patch_plan_promoted_count"] = commit_stats.get("reinject_commit_patch_plan_promoted_count", 0)
        dashboard_summary["reinject_commit_duplicate_count"]         = commit_stats.get("reinject_commit_duplicate_count", 0)

        cr = commit_cycle.get("commit", {})
        pr = commit_cycle.get("patch_plan", {})
        print(
            f"  ✅ reinject commit: committed={cr.get('committed',0)} "
            f"dup={cr.get('dup',0)} "
            f"pending={cr.get('pending',0)}件",
            file=sys.stderr,
        )
        print(
            f"  ✅ patch_plan reinject: promoted={pr.get('promoted',0)} "
            f"dup={pr.get('dup',0)}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  reinject commit スキップ: {e}", file=sys.stderr)

    # フェーズ15: apply解放ゲート + apply候補レーン
    try:
        from lib.ceo_reinject_apply_gate import (
            run_reinject_apply_gate_cycle,
            get_reinject_apply_gate_stats,
            get_reinject_apply_ready_stats,
        )
        ag_cycle  = run_reinject_apply_gate_cycle()
        ag_stats  = get_reinject_apply_gate_stats()
        ar_stats  = get_reinject_apply_ready_stats()

        dashboard_summary["reinject_apply_gate_pending_count"]   = ag_stats.get("reinject_apply_gate_pending_count", 0)
        dashboard_summary["reinject_apply_gate_blocked_count"]   = ag_stats.get("reinject_apply_gate_blocked_count", 0)
        dashboard_summary["reinject_apply_gate_latest_agent"]    = ag_stats.get("reinject_apply_gate_latest_agent", "—")
        dashboard_summary["reinject_apply_gate_latest_status"]   = ag_stats.get("reinject_apply_gate_latest_status", "—")
        dashboard_summary["reinject_apply_ready_pending_count"]  = ar_stats.get("reinject_apply_ready_pending_count", 0)
        dashboard_summary["reinject_apply_ready_high_count"]     = ar_stats.get("reinject_apply_ready_high_count", 0)
        dashboard_summary["reinject_apply_ready_medium_count"]   = ar_stats.get("reinject_apply_ready_medium_count", 0)
        dashboard_summary["reinject_apply_ready_latest_agent"]   = ar_stats.get("reinject_apply_ready_latest_agent", "—")
        dashboard_summary["reinject_apply_ready_latest_priority"]= ar_stats.get("reinject_apply_ready_latest_priority", "—")
        dashboard_summary["reinject_apply_ready_top1_agent"]     = ar_stats.get("reinject_apply_ready_top1_agent", "—")
        dashboard_summary["reinject_apply_ready_top1_score"]     = ar_stats.get("reinject_apply_ready_top1_score", 0.0)

        gr = ag_cycle.get("gate", {})
        rr = ag_cycle.get("ready", {})
        print(
            f"  ✅ reinject apply_gate: promoted={gr.get('promoted',0)} "
            f"blocked={gr.get('blocked',0)} "
            f"dup={gr.get('dup',0)} "
            f"pending={gr.get('pending',0)}件",
            file=sys.stderr,
        )
        print(
            f"  ✅ reinject apply_ready: promoted={rr.get('promoted',0)} "
            f"dup={rr.get('dup',0)} "
            f"pending={rr.get('pending',0)}件",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  reinject apply_gate スキップ: {e}", file=sys.stderr)

    # フェーズ16: 最終解放候補レーン
    try:
        from lib.ceo_reinject_apply_gate import (
            run_reinject_unlock_candidate_cycle,
            get_apply_unlock_candidate_stats,
        )
        uc_cycle = run_reinject_unlock_candidate_cycle()
        uc_stats = get_apply_unlock_candidate_stats()

        dashboard_summary["apply_unlock_candidate_pending_count"]   = uc_stats.get("apply_unlock_candidate_pending_count", 0)
        dashboard_summary["apply_unlock_candidate_high_count"]      = uc_stats.get("apply_unlock_candidate_high_count", 0)
        dashboard_summary["apply_unlock_candidate_critical_count"]  = uc_stats.get("apply_unlock_candidate_critical_count", 0)
        dashboard_summary["apply_unlock_candidate_latest_agent"]    = uc_stats.get("apply_unlock_candidate_latest_agent", "—")
        dashboard_summary["apply_unlock_candidate_latest_priority"] = uc_stats.get("apply_unlock_candidate_latest_priority", "—")
        dashboard_summary["apply_unlock_candidate_latest_status"]   = uc_stats.get("apply_unlock_candidate_latest_status", "—")
        dashboard_summary["apply_unlock_candidate_top1_agent"]      = uc_stats.get("apply_unlock_candidate_top1_agent", "—")
        dashboard_summary["apply_unlock_candidate_top1_score"]      = uc_stats.get("apply_unlock_candidate_top1_score", 0.0)
        dashboard_summary["apply_unlock_candidate_blocked_count"]   = uc_stats.get("apply_unlock_candidate_blocked_count", 0)

        print(
            f"  ✅ unlock_candidate 生成: promoted={uc_cycle.get('promoted',0)} "
            f"blocked={uc_cycle.get('blocked',0)} "
            f"dup={uc_cycle.get('dup',0)} "
            f"pending={uc_cycle.get('pending',0)}件",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  unlock_candidate スキップ: {e}", file=sys.stderr)

    # フェーズ17: 最終解放判定レーン
    try:
        from lib.ceo_reinject_apply_gate import (
            run_reinject_unlock_judge_cycle,
            get_unlock_judge_stats,
        )
        uj_cycle = run_reinject_unlock_judge_cycle()
        uj_stats = get_unlock_judge_stats()

        dashboard_summary["unlock_judge_pending_count"]   = uj_stats.get("unlock_judge_pending_count", 0)
        dashboard_summary["unlock_judge_critical_count"]  = uj_stats.get("unlock_judge_critical_count", 0)
        dashboard_summary["unlock_judge_high_count"]      = uj_stats.get("unlock_judge_high_count", 0)
        dashboard_summary["unlock_judge_blocked_count"]   = uj_stats.get("unlock_judge_blocked_count", 0)
        dashboard_summary["unlock_judge_latest_agent"]    = uj_stats.get("unlock_judge_latest_agent", "—")
        dashboard_summary["unlock_judge_latest_priority"] = uj_stats.get("unlock_judge_latest_priority", "—")
        dashboard_summary["unlock_judge_latest_status"]   = uj_stats.get("unlock_judge_latest_status", "—")
        dashboard_summary["unlock_judge_top1_agent"]      = uj_stats.get("unlock_judge_top1_agent", "—")
        dashboard_summary["unlock_judge_top1_score"]      = uj_stats.get("unlock_judge_top1_score", 0.0)

        print(
            f"  ✅ unlock_judge 生成: promoted={uj_cycle.get('promoted',0)} "
            f"blocked={uj_cycle.get('blocked',0)} "
            f"dup={uj_cycle.get('dup',0)} "
            f"pending={uj_cycle.get('pending',0)}件",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  unlock_judge スキップ: {e}", file=sys.stderr)

    # フェーズ18: 解放実行待ち + apply実行待ちキュー構築
    try:
        from lib.ceo_unlock_executor import (
            run_unlock_pipeline_cycle,
            get_unlock_execute_stats,
            get_apply_execute_stats,
        )
        ul_cycle   = run_unlock_pipeline_cycle()
        ul_stats   = get_unlock_execute_stats()
        ap_x_stats = get_apply_execute_stats()

        dashboard_summary["unlock_execute_pending_count"]      = ul_stats.get("unlock_execute_pending_count", 0)
        dashboard_summary["unlock_execute_unlocked_count"]     = ul_stats.get("unlock_execute_unlocked_count", 0)
        dashboard_summary["unlock_execute_latest_agent"]       = ul_stats.get("unlock_execute_latest_agent", "—")
        dashboard_summary["apply_execute_pending_count"]       = ap_x_stats.get("apply_execute_pending_count", 0)
        dashboard_summary["apply_execute_applied_count"]       = ap_x_stats.get("apply_execute_applied_count", 0)
        dashboard_summary["apply_execute_failed_count"]        = ap_x_stats.get("apply_execute_failed_count", 0)
        dashboard_summary["apply_execute_latest_agent"]        = ap_x_stats.get("apply_execute_latest_agent", "—")
        dashboard_summary["apply_execute_latest_status"]       = ap_x_stats.get("apply_execute_latest_status", "—")
        dashboard_summary["apply_execute_latest_config_hash"]  = ap_x_stats.get("apply_execute_latest_config_hash", "—")

        ur = ul_cycle.get("unlock", {})
        aq = ul_cycle.get("apply_queue", {})
        print(
            f"  ✅ unlock_execute 構築: promoted={ur.get('promoted',0)} "
            f"dup={ur.get('dup',0)} pending={ur.get('pending',0)}件",
            file=sys.stderr,
        )
        print(
            f"  ✅ apply_execute 構築: promoted={aq.get('promoted',0)} "
            f"dup={aq.get('dup',0)} pending={aq.get('pending',0)}件",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  unlock_execute スキップ: {e}", file=sys.stderr)

    # ─── Phase 19: hardening (expiry / post-apply lock / rollback / stale) ───
    try:
        from lib.ceo_apply_hardening import (
            run_hardening_cycle,
            get_hardening_stats,
        )
        hd_cycle = run_hardening_cycle()
        hd_stats = get_hardening_stats()

        dashboard_summary["hardening_unlock_expired_count"]       = hd_stats.get("unlock_expired_count", 0)
        dashboard_summary["hardening_apply_blocked_count"]        = hd_stats.get("apply_blocked_count", 0)
        dashboard_summary["hardening_apply_applied_count"]        = hd_stats.get("apply_applied_count", 0)
        dashboard_summary["hardening_post_apply_lock_pending"]    = hd_stats.get("post_apply_lock_pending_count", 0)
        dashboard_summary["hardening_rollback_request_pending"]   = hd_stats.get("rollback_request_pending_count", 0)
        dashboard_summary["hardening_stale_operation_pending"]    = hd_stats.get("stale_operation_pending_count", 0)
        dashboard_summary["hardening_latest_rollback_agent"]      = hd_stats.get("latest_rollback_agent", "—")
        dashboard_summary["hardening_latest_stale_agent"]         = hd_stats.get("latest_stale_agent", "—")

        ex  = hd_cycle.get("expiry", {})
        pl  = hd_cycle.get("post_lock", {})
        rb  = hd_cycle.get("rollback", {})
        sta = hd_cycle.get("stale", {})
        print(
            f"  ✅ hardening: "
            f"expired={ex.get('expired',0)} "
            f"postlock={pl.get('registered',0)} "
            f"rollback={rb.get('registered',0)} "
            f"stale={sta.get('detected',0)}件",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  hardening スキップ: {e}", file=sys.stderr)

    # ─── Phase 20: 運用手順ガイド（操作ステージ決定） ───
    try:
        from lib.ceo_operation_runbook import get_operation_summary
        op_summary = get_operation_summary()
        dashboard_summary.update(op_summary)
        print(
            f"  ✅ operation_runbook: stage={op_summary.get('current_operation_stage','—')} "
            f"confidence={op_summary.get('operation_confidence','—')}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  operation_runbook スキップ: {e}", file=sys.stderr)

    # ─── Phase 21: hardening最優先アラート集約 ───
    try:
        from lib.ceo_hardening_alerts import get_hardening_alert_summary, compute_hardening_alert
        ha_summary = get_hardening_alert_summary()
        dashboard_summary.update(ha_summary)

        # hardening escalated 時は ceo_immediate_action / ceo_confidence を上書き
        ha_full = compute_hardening_alert()
        if ha_full.get("hardening_is_escalated"):
            override_action = ha_full.get("hardening_override_immediate_action")
            override_conf   = ha_full.get("hardening_override_confidence")
            if override_action:
                dashboard_summary["ceo_immediate_action"] = override_action
            if override_conf:
                dashboard_summary["ceo_confidence"] = override_conf

        print(
            f"  ✅ hardening_alerts: issue={ha_summary.get('hardening_top_issue','—')} "
            f"priority={ha_summary.get('hardening_top_priority','—')} "
            f"escalated={ha_summary.get('hardening_is_escalated',False)}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  hardening_alerts スキップ: {e}", file=sys.stderr)

    # ─── Phase 22: post-apply judge ───
    try:
        from lib.ceo_post_apply_judge import run_post_apply_judge, get_post_apply_judge_stats
        paj_result = run_post_apply_judge()
        paj_stats  = get_post_apply_judge_stats()
        dashboard_summary.update(paj_stats)
        print(
            f"  ✅ post_apply_judge: judged={paj_result.get('judged',0)} "
            f"keep={paj_result.get('keep_monitoring',0)} "
            f"readjust={paj_result.get('re_adjust_minor',0)} "
            f"rollback={paj_result.get('rollback_recommended',0)}件",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  post_apply_judge スキップ: {e}", file=sys.stderr)

    # ─── Phase 23: rollback router ───
    try:
        from lib.ceo_rollback_router import run_rollback_router, get_rollback_router_stats
        rb_result = run_rollback_router()
        rb_stats  = get_rollback_router_stats()
        dashboard_summary.update(rb_stats)
        print(
            f"  ✅ rollback_router: dispatch={rb_result.get('dispatched',0)} "
            f"watch={rb_result.get('watched',0)} "
            f"dispatch_pending={rb_result.get('dispatch_pending',0)} "
            f"watch_pending={rb_result.get('watch_pending',0)}件",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  rollback_router スキップ: {e}", file=sys.stderr)

    # ─── Phase 25: stale cleanup plan ───
    try:
        from lib.ceo_stale_cleanup import run_stale_cleanup_plan, get_stale_cleanup_stats
        sc_result = run_stale_cleanup_plan()
        sc_stats  = get_stale_cleanup_stats()
        dashboard_summary.update(sc_stats)
        print(
            f"  ✅ stale_cleanup_plan: added={sc_result.get('added',0)} "
            f"pending={sc_result.get('total_pending',0)}件",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  stale_cleanup スキップ: {e}", file=sys.stderr)

    # ─── Phase 26: lifecycle trace ───
    try:
        from lib.ceo_lifecycle_trace import get_lifecycle_trace_stats
        lt_stats = get_lifecycle_trace_stats(top_n=20)
        # traces はメモリ上のみ（大きいので top 3 情報だけ summary に入れる）
        dashboard_summary["lifecycle_trace_count"]      = lt_stats.get("lifecycle_trace_count", 0)
        dashboard_summary["lifecycle_trace_top1_agent"] = lt_stats.get("lifecycle_trace_top1_agent", "—")
        dashboard_summary["lifecycle_trace_top1_lane"]  = lt_stats.get("lifecycle_trace_top1_lane", "—")
        dashboard_summary["lifecycle_trace_top1_lanes"] = lt_stats.get("lifecycle_trace_top1_lanes", 0)
        dashboard_summary["lifecycle_trace_top2_agent"] = lt_stats.get("lifecycle_trace_top2_agent", "—")
        dashboard_summary["lifecycle_trace_top3_agent"] = lt_stats.get("lifecycle_trace_top3_agent", "—")
        # traces 全件は別ファイルに保存
        import json as _json_lt
        lt_path = BASE / "lifecycle_traces.json"
        lt_path.write_text(_json_lt.dumps(
            lt_stats.get("lifecycle_traces", []), ensure_ascii=False, indent=2
        ) + "\n")
        print(
            f"  ✅ lifecycle_trace: count={lt_stats.get('lifecycle_trace_count',0)} "
            f"top1={lt_stats.get('lifecycle_trace_top1_agent','—')}@{lt_stats.get('lifecycle_trace_top1_lane','—')}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  lifecycle_trace スキップ: {e}", file=sys.stderr)

    # ─── Phase 27: safety invariants ───
    try:
        from lib.ceo_safety_invariants import scan_invariant_violations, get_invariant_stats
        inv_result = scan_invariant_violations()
        inv_stats  = get_invariant_stats()
        dashboard_summary.update(inv_stats)
        print(
            f"  ✅ safety_invariants: detected={inv_result.get('detected',0)} "
            f"pending={inv_result.get('pending_total',0)} "
            f"critical={inv_stats.get('invariant_is_critical',False)}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  safety_invariants スキップ: {e}", file=sys.stderr)

    # ─── Phase 24: one-command summary (最後に全情報統合) ───
    try:
        from lib.ceo_operation_runbook import compute_next_command_summary
        # hardening_summary を渡してエスカレーション上書きを統合
        ha_for_next = {k: dashboard_summary.get(k) for k in (
            "hardening_is_escalated", "hardening_required_command",
            "hardening_top_target", "hardening_escalation_reason",
        )}
        next_cmd = compute_next_command_summary(ha_for_next)
        dashboard_summary.update(next_cmd)
        print(
            f"  ✅ next_command: stage={next_cmd.get('ceo_next_stage','—')} "
            f"priority={next_cmd.get('ceo_next_priority','—')} "
            f"target={next_cmd.get('ceo_next_target','—')}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  next_command スキップ: {e}", file=sys.stderr)

    # ─── Phase 29: auto executor (mode読み込み → 条件付き自動実行) ───
    try:
        from lib.ceo_auto_executor import run_auto_cycle, get_auto_exec_stats, get_runtime_mode_stats
        auto_result = run_auto_cycle()
        auto_stats  = get_auto_exec_stats()
        rt_stats    = get_runtime_mode_stats()
        dashboard_summary.update(rt_stats)
        dashboard_summary.update(auto_stats)
        dashboard_summary["auto_exec_mode"]            = auto_result.get("runtime_mode", "MANUAL")
        dashboard_summary["auto_exec_this_run_unlock"] = auto_result.get("unlock", {}).get("executed", 0)
        dashboard_summary["auto_exec_this_run_apply"]  = auto_result.get("apply",  {}).get("executed", 0)
        dashboard_summary["auto_exec_this_run_rb"]     = auto_result.get("rollback",{}).get("executed", 0)
        print(
            f"  ✅ auto_executor: mode={auto_result.get('runtime_mode','MANUAL')} "
            f"unlock={auto_result.get('unlock',{}).get('executed',0)} "
            f"apply={auto_result.get('apply',{}).get('executed',0)} "
            f"rollback={auto_result.get('rollback',{}).get('executed',0)}",
            file=sys.stderr,
        )
    except Exception as e:
        import traceback
        print(f"  ⚠️  auto_executor スキップ: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

    # ─── Phase 30: safe_auto_gate ───
    try:
        from lib.ceo_safe_auto_gate import run_safe_auto_gate, get_safe_auto_gate_stats
        sag_result = run_safe_auto_gate()
        dashboard_summary.update(sag_result)
        print(
            f"  ✅ safe_auto_gate: status={sag_result.get('safe_auto_gate_status','—')} "
            f"blocked={sag_result.get('safe_auto_blocked_count',0)} "
            f"ready={sag_result.get('safe_auto_ready',False)}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  safe_auto_gate スキップ: {e}", file=sys.stderr)

    # ─── Phase 31: stale_resolver ───
    try:
        from lib.ceo_stale_resolver import run_stale_resolver, get_stale_resolver_stats
        sr_result = run_stale_resolver()
        sr_stats  = get_stale_resolver_stats()
        dashboard_summary.update(sr_stats)
        print(
            f"  ✅ stale_resolver: added={sr_result.get('added',0)} "
            f"dup={sr_result.get('dup',0)} "
            f"pending={sr_result.get('pending',0)} "
            f"top1={sr_stats.get('stale_resolution_top1_action','—')}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  stale_resolver スキップ: {e}", file=sys.stderr)

    # ─── Phase 32: unlock_pick ───
    try:
        from lib.ceo_unlock_pick import run_unlock_pick, get_unlock_pick_stats
        up_result = run_unlock_pick()
        up_stats  = get_unlock_pick_stats()
        dashboard_summary.update(up_stats)
        print(
            f"  ✅ unlock_pick: candidates={up_result.get('candidates',0)} "
            f"added={up_result.get('added',0)} "
            f"top1={up_stats.get('unlock_pick_target_agent','—')}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  unlock_pick スキップ: {e}", file=sys.stderr)

    # ─── Phase 33: mode_transition ───
    try:
        from lib.ceo_mode_transition import run_mode_transition_check, get_mode_transition_stats
        mt_result = run_mode_transition_check()
        dashboard_summary.update(mt_result)
        print(
            f"  ✅ mode_transition: status={mt_result.get('mode_transition_status','—')} "
            f"failed={mt_result.get('mode_transition_failed_count',0)} "
            f"all_green={mt_result.get('mode_transition_ready',False)}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"  ⚠️  mode_transition スキップ: {e}", file=sys.stderr)

    # ─── Phase 28: manual explain / block check / checklist ───
    try:
        from lib.ceo_manual_explain import (
            run_all_manual_explain,
            get_unlock_explain_stats,
            get_apply_explain_stats,
            get_final_block_stats,
            get_checklist_stats,
            compute_next_manual_summary,
        )
        me_result = run_all_manual_explain()
        dashboard_summary.update(get_unlock_explain_stats())
        dashboard_summary.update(get_apply_explain_stats())
        dashboard_summary.update(get_final_block_stats())
        dashboard_summary.update(get_checklist_stats())
        nms = compute_next_manual_summary(dashboard_summary)
        dashboard_summary.update(nms)
        _ue = me_result.get("unlock_explain", {})
        _ae = me_result.get("apply_explain",  {})
        _fb = me_result.get("final_block",    {})
        _cl = me_result.get("checklist",      {})
        print(
            f"  ✅ manual_explain: unlock_explain_added={_ue.get('added',0)} dup={_ue.get('dup',0)} "
            f"apply_explain_added={_ae.get('added',0)} "
            f"final_blocked={_fb.get('total_blocked',0)} final_ready={_fb.get('total_ready',0)} "
            f"checklist={_cl.get('pending',0)}件",
            file=sys.stderr,
        )
        print(
            f"  ✅ next_manual_command: type={nms.get('next_manual_command_type','—')} "
            f"target={nms.get('next_manual_target_agent','—')}",
            file=sys.stderr,
        )
    except Exception as e:
        import traceback
        print(f"  ⚠️  manual_explain スキップ: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

    # 出力
    outputs = {
        "agent_metrics.json": agent_metrics_out,
        "optimization_actions.json": opt_actions,
        "revenue_metrics.json": rev_metrics,
        "org_map.json": org_map,
        "dashboard_summary.json": dashboard_summary,
    }

    for fname, data in outputs.items():
        path = BASE / fname
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        print(f"  ✅ {fname} 出力完了", file=sys.stderr)

    print("[agent_monitor v2.0] 完了", file=sys.stderr)
    return agent_metrics_out, opt_actions, rev_metrics, org_map, dashboard_summary


if __name__ == "__main__":
    main()
