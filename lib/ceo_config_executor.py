#!/usr/bin/env python3
"""
ceo_config_executor.py — CEO設定変更実行エンジン v1.0
CEO: ミュウツー / オーナー: 人間（閲覧専用）

【役割】
  config_apply_queue の pending 候補を config/agent_directives.json へ
  安全・限定・可逆で反映する。

【制約】
  - 対象ファイル: config/agent_directives.json のみ
  - improvement_type: prompt_fix のみ
  - 変更キー: 1レコード = 1キー = 単一 action フィールドのみ
  - 必ずバックアップ + unified diff を残す
  - ロールバック関数実装済み
  - LLM 判断なし / 完全決定論
"""

import difflib
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
JST  = timezone(timedelta(hours=9))

# ── パス定義 ─────────────────────────────────────────────────
APPLY_QUEUE_PATH        = BASE / "logs" / "ceo_config_apply_queue.jsonl"
APPLY_RESULT_QUEUE_PATH = BASE / "logs" / "ceo_config_apply_result_queue.jsonl"
APPLY_RESULT_HIST_PATH  = BASE / "logs" / "ceo_config_apply_result_history.jsonl"
BACKUP_HISTORY_PATH     = BASE / "logs" / "config_backup_history.jsonl"
BACKUP_DIR              = BASE / "backups" / "agent_directives"
DIFF_DIR                = BASE / "diffs" / "agent_directives"
CONFIG_TARGET           = BASE / "config" / "agent_directives.json"

_ALLOWED_TARGET_CONFIG  = "config/agent_directives.json"
_ALLOWED_WRITE_SCOPE    = "config_only"
_ALLOWED_PATCH_MODE     = "upsert_agent_directive"
_DIRECTIVE_FIELD        = "action"


# ── ユーティリティ ────────────────────────────────────────────

def _now_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST")


def _ts_compact() -> str:
    return datetime.now(JST).strftime("%Y%m%d_%H%M%S")


def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    records = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass
    return records


def _load_json_safe(path: Path) -> dict:
    if not path.exists():
        return {"agent_directives": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if "agent_directives" not in raw:
            raw["agent_directives"] = {}
        return raw
    except Exception:
        return {"agent_directives": {}}


def _write_json_pretty(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ── バックアップ ───────────────────────────────────────────────

def _make_backup(target_agent: str, reason: str = "before_apply") -> str:
    """
    config/agent_directives.json のバックアップを作成し、パスを返す。
    存在しない場合は空構造を保存。
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts       = _ts_compact()
    safe_ag  = target_agent.replace("/", "_").replace("|", "_")
    bk_name  = f"{ts}_{safe_ag}.json"
    bk_path  = BACKUP_DIR / bk_name

    if CONFIG_TARGET.exists():
        shutil.copy2(CONFIG_TARGET, bk_path)
    else:
        _write_json_pretty(bk_path, {"agent_directives": {}})

    # バックアップ履歴に記録
    BACKUP_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with BACKUP_HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts":           _now_jst(),
            "action":       "backup",
            "target_agent": target_agent,
            "config_path":  _ALLOWED_TARGET_CONFIG,
            "backup_path":  str(bk_path.relative_to(BASE)),
            "reason":       reason,
        }, ensure_ascii=False) + "\n")

    return str(bk_path.relative_to(BASE))


# ── diff ─────────────────────────────────────────────────────

def _write_diff_file(agent_key: str, before_str: str, after_str: str) -> str:
    """
    before / after の unified diff を保存し、パスを返す。
    """
    DIFF_DIR.mkdir(parents=True, exist_ok=True)
    ts        = _ts_compact()
    diff_name = f"{ts}_{agent_key}.diff"
    diff_path = DIFF_DIR / diff_name

    before_lines = (before_str + "\n").splitlines(keepends=True)
    after_lines  = (after_str  + "\n").splitlines(keepends=True)
    diff = difflib.unified_diff(
        before_lines, after_lines,
        fromfile=f"a/agent_directives.{agent_key}.action",
        tofile=f"b/agent_directives.{agent_key}.action",
        lineterm="",
    )
    diff_path.write_text("\n".join(diff), encoding="utf-8")
    return str(diff_path.relative_to(BASE))


# ── ブロック判定 ──────────────────────────────────────────────

def _check_blocked(rec: dict) -> tuple[bool, str]:
    """
    apply 前の安全チェック。blocked なら (True, reason) を返す。
    """
    if rec.get("target_config") != _ALLOWED_TARGET_CONFIG:
        return True, f"target_config が許可外: {rec.get('target_config')}"
    if rec.get("write_scope") != _ALLOWED_WRITE_SCOPE:
        return True, f"write_scope が config_only 以外: {rec.get('write_scope')}"
    if rec.get("patch_mode") != _ALLOWED_PATCH_MODE:
        return True, f"patch_mode が upsert_agent_directive 以外: {rec.get('patch_mode')}"
    if not rec.get("target_agent", ""):
        return True, "target_agent が空"
    if not rec.get("agent_key", ""):
        return True, "agent_key が空"
    if not rec.get("after_value", ""):
        return True, "after_value が空"
    if not rec.get("duplicate_key", ""):
        return True, "duplicate_key が不正"
    # patch_path が単一キーを指していること（ドット区切り 3 parts のみ許可）
    pp = rec.get("patch_path", "")
    if pp.count(".") != 2:
        return True, f"patch_path が単一キーでない: {pp}"
    return False, ""


# ── is_result_duplicate ──────────────────────────────────────

def _is_result_duplicate(dup_key: str) -> bool:
    for r in _load_jsonl(APPLY_RESULT_QUEUE_PATH):
        if r.get("duplicate_key") == dup_key and r.get("result_status") in ("applied", "blocked", "failed"):
            return True
    return False


# ── 単一レコード apply ────────────────────────────────────────

def _apply_single_record(rec: dict) -> dict:
    """
    1レコードの apply を実行。
    戻り値: result_status, result_reason, backup_path, diff_path
    """
    now_str      = _now_jst()
    target_agent = rec.get("target_agent", "")
    agent_key    = rec.get("agent_key", "")
    after_value  = rec.get("after_value", "")
    dup_key      = rec.get("duplicate_key", "")

    # ── ブロックチェック ──
    is_blocked, block_reason = _check_blocked(rec)
    if is_blocked:
        return {
            "applied_at":    now_str,
            "target_agent":  target_agent,
            "duplicate_key": dup_key,
            "result_status": "blocked",
            "result_reason": block_reason,
            "target_config": rec.get("target_config", ""),
            "patch_path":    rec.get("patch_path", ""),
            "before_value":  rec.get("before_value", ""),
            "after_value":   after_value,
            "backup_path":   "",
            "diff_path":     "",
            "apply_from":    "ceo_config_apply_queue",
            "write_scope":   rec.get("write_scope", ""),
            "ceo_judgment":  "ミュウツーCEO設定変更結果",
        }

    backup_path = ""
    diff_path   = ""

    try:
        # 1. config 読み込み
        config_data = _load_json_safe(CONFIG_TARGET)
        ad          = config_data.setdefault("agent_directives", {})

        # 2. バックアップ
        backup_path = _make_backup(target_agent, reason="before_apply")

        # 3. before_value 取得（config 実体から）
        existing_entry = ad.get(agent_key, {})
        if isinstance(existing_entry, dict):
            before_value = existing_entry.get(_DIRECTIVE_FIELD, "")
        elif isinstance(existing_entry, str):
            before_value = existing_entry
        else:
            before_value = ""

        # 4. diff 保存
        diff_path = _write_diff_file(agent_key, before_value, after_value)

        # 5. 単一キー更新（action フィールドのみ）
        if agent_key not in ad:
            ad[agent_key] = {}
        if not isinstance(ad[agent_key], dict):
            ad[agent_key] = {"_original": ad[agent_key]}
        ad[agent_key][_DIRECTIVE_FIELD] = after_value
        ad[agent_key]["set_at"]         = datetime.now(JST).strftime("%Y-%m-%d")
        ad[agent_key]["source"]         = "ceo_config_executor"
        ad[agent_key]["target_agent"]   = target_agent

        # 6. pretty JSON で保存
        _write_json_pretty(CONFIG_TARGET, config_data)

        return {
            "applied_at":    now_str,
            "target_agent":  target_agent,
            "duplicate_key": dup_key,
            "result_status": "applied",
            "result_reason": "正常適用完了",
            "target_config": _ALLOWED_TARGET_CONFIG,
            "patch_path":    rec.get("patch_path", ""),
            "before_value":  before_value,
            "after_value":   after_value,
            "backup_path":   backup_path,
            "diff_path":     diff_path,
            "apply_from":    "ceo_config_apply_queue",
            "write_scope":   "config_only",
            "ceo_judgment":  "ミュウツーCEO設定変更結果",
        }

    except Exception as e:
        return {
            "applied_at":    now_str,
            "target_agent":  target_agent,
            "duplicate_key": dup_key,
            "result_status": "failed",
            "result_reason": f"例外: {e}",
            "target_config": _ALLOWED_TARGET_CONFIG,
            "patch_path":    rec.get("patch_path", ""),
            "before_value":  rec.get("before_value", ""),
            "after_value":   after_value,
            "backup_path":   backup_path,
            "diff_path":     diff_path,
            "apply_from":    "ceo_config_apply_queue",
            "write_scope":   "config_only",
            "ceo_judgment":  "ミュウツーCEO設定変更結果",
        }


# ── メイン apply 関数 ─────────────────────────────────────────

def apply_config_queue() -> dict:
    """
    config_apply_queue の pending を順に処理し、
    config/agent_directives.json へ反映する。
    戻り値: {"applied": int, "blocked": int, "failed": int, "skipped_duplicate": int}
    """
    pending = [r for r in _load_jsonl(APPLY_QUEUE_PATH) if r.get("apply_status") == "pending"]

    applied_count     = 0
    blocked_count     = 0
    failed_count      = 0
    skipped_duplicate = 0

    APPLY_RESULT_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    APPLY_RESULT_HIST_PATH.parent.mkdir(parents=True, exist_ok=True)

    for rec in sorted(pending, key=lambda x: x.get("queued_at", "")):
        dup_key = rec.get("duplicate_key", "")

        if _is_result_duplicate(dup_key):
            skipped_duplicate += 1
            with APPLY_RESULT_HIST_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts":            _now_jst(),
                    "duplicate_key": dup_key,
                    "status":        "result_duplicate",
                    "reason":        "既にapply_result_queueに存在",
                }, ensure_ascii=False) + "\n")
            continue

        result = _apply_single_record(rec)

        # result queue に書き出し
        with APPLY_RESULT_QUEUE_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")
        # result history にも書き出し
        with APPLY_RESULT_HIST_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

        status = result.get("result_status", "failed")
        if status == "applied":
            applied_count += 1
        elif status == "blocked":
            blocked_count += 1
        else:
            failed_count += 1

    return {
        "applied":           applied_count,
        "blocked":           blocked_count,
        "failed":            failed_count,
        "skipped_duplicate": skipped_duplicate,
    }


def get_apply_result_stats() -> dict:
    records  = _load_jsonl(APPLY_RESULT_QUEUE_PATH)
    applied  = [r for r in records if r.get("result_status") == "applied"]
    blocked  = [r for r in records if r.get("result_status") == "blocked"]
    failed   = [r for r in records if r.get("result_status") == "failed"]
    latest   = records[-1] if records else {}
    return {
        "applied":                len(applied),
        "blocked":                len(blocked),
        "failed":                 len(failed),
        "latest_agent":           latest.get("target_agent", ""),
        "latest_status":          latest.get("result_status", ""),
        "latest_diff_path":       latest.get("diff_path", ""),
        "latest_backup_path":     latest.get("backup_path", ""),
    }


# ── ロールバック ──────────────────────────────────────────────

def rollback_last_config_change(target_agent: str | None = None) -> dict:
    """
    config/agent_directives.json を直近バックアップで復元する。
    target_agent 指定時はその agent の直近、None の場合は全体直近。

    戻り値:
      {"status": "rolled_back"|"no_backup"|"failed", "backup_path": str, "reason": str}
    """
    now_str = _now_jst()
    history = _load_jsonl(BACKUP_HISTORY_PATH)

    # backup アクションのみ対象
    backups = [r for r in history if r.get("action") == "backup"]
    if target_agent:
        backups = [r for r in backups if r.get("target_agent") == target_agent]

    if not backups:
        return {"status": "no_backup", "backup_path": "", "reason": "バックアップ履歴なし"}

    # 最新バックアップ
    latest_bk = backups[-1]
    bk_rel    = latest_bk.get("backup_path", "")
    bk_path   = BASE / bk_rel

    if not bk_path.exists():
        return {"status": "no_backup", "backup_path": bk_rel, "reason": f"バックアップファイル不在: {bk_rel}"}

    try:
        shutil.copy2(bk_path, CONFIG_TARGET)

        # ロールバック履歴記録
        rb_agent = target_agent or latest_bk.get("target_agent", "全体")
        with BACKUP_HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts":           now_str,
                "action":       "rollback",
                "target_agent": rb_agent,
                "config_path":  _ALLOWED_TARGET_CONFIG,
                "backup_path":  bk_rel,
                "reason":       "manual_rollback",
            }, ensure_ascii=False) + "\n")

        return {"status": "rolled_back", "backup_path": bk_rel, "reason": f"{rb_agent} の直近バックアップで復元完了"}

    except Exception as e:
        return {"status": "failed", "backup_path": bk_rel, "reason": f"復元失敗: {e}"}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        agent = sys.argv[2] if len(sys.argv) > 2 else None
        result = rollback_last_config_change(agent)
        print(f"rollback: {result}")
    else:
        result = apply_config_queue()
        print(f"apply: {result}")
        stats  = get_apply_result_stats()
        print(f"stats: {stats}")
