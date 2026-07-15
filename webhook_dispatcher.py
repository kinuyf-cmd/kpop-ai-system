#!/usr/bin/env python3
"""webhook_dispatcher.py — M10 P-3 Webhook 通知統合

orchestration-leader SKILL §4 通信プロトコル: Webhook
の汎用ディスパッチャ。orchestration_run.sh / red_team_scan.sh /
blue_team_repair.sh / qa_test_run.sh から呼び出される統一窓口。

既存 lib/discord_notifier.py が WordPress/記事系の精緻通知を担うのに対し、
本スクリプトは「エージェント完了イベント」の Webhook 通知に特化する。

用途:
    python3 webhook_dispatcher.py --event orchestration_complete --suite morning --success 4 --failed 0
    python3 webhook_dispatcher.py --event qa_test_failed --suite all --failed 3
    python3 webhook_dispatcher.py --dry-run --event test

設定:
    config/discord_webhooks.json から webhook URL を読む。
    失効中なら exit 0(ロバスト動作、M8 で実証済の安全設計を踏襲)。
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = Path.home() / ".kpop_recovery"
LOG_FILE = LOG_DIR / "webhook_dispatcher_log.jsonl"

WEBHOOK_CONFIG = ROOT / "config" / "discord_webhooks.json"

# Discord 送信用 UA は lib/resolve_discord_webhook.py に集約(DRY)。
sys.path.insert(0, str(ROOT / "lib"))
from resolve_discord_webhook import DISCORD_USER_AGENT  # noqa: E402


def now_iso() -> str:
    return datetime.now(timezone(timedelta(hours=9))).isoformat()


_DOTENV_LOADED = False


def _load_dotenv_once() -> None:
    """M11.5.B: .env を一度だけ os.environ に読み込む(既存値は上書きしない)。"""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    _DOTENV_LOADED = True
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k and k not in os.environ:
            os.environ[k] = v.strip().strip('"').strip("'")


def _expand(value):
    """config 値が "${DISCORD_WEBHOOK_*}" なら .env/環境変数から展開。
    未解決のプレースホルダーは空文字にして誤送信を防ぐ。"""
    if not isinstance(value, str):
        return value
    v = value.strip()
    expanded = os.path.expandvars(v)
    if expanded.startswith("${") and expanded.endswith("}"):
        _load_dotenv_once()
        expanded = os.path.expandvars(v)
    return "" if expanded.startswith("${") else expanded


def load_webhooks() -> dict:
    if not WEBHOOK_CONFIG.exists():
        return {}
    try:
        raw = json.loads(WEBHOOK_CONFIG.read_text())
    except json.JSONDecodeError:
        return {}
    # M11.5.B: メタキー(_ 始まり)を除外し、値を環境変数展開する。
    return {k: _expand(v) for k, v in raw.items() if not k.startswith("_")}


def select_webhook(event: str, hooks: dict) -> str | None:
    """イベント種別から適切な webhook channel を選ぶ"""
    # 2026-07-15: 旧候補キー (qa/red_team/blue_team/orchestration/kpop_general/default)
    # は config/discord_webhooks.json に1つも存在せず、常にフォールバック依存だった。
    # QA/RED/BLUE/orchestration の完了イベントは weekly_board_report へ集約 (RED/BLUE
    # スキャンの通知先と同じ枠)。最終フォールバックは daily_ceo_report。
    candidates = ["weekly_board_report", "daily_ceo_report"]
    for key in candidates:
        url = hooks.get(key)
        if url and url.startswith("http"):
            return url
    # 最終フォールバック: 最初の有効 URL
    for v in hooks.values():
        if isinstance(v, str) and v.startswith("http"):
            return v
    return None


def color_for_event(event: str, failed: int) -> int:
    if failed > 0:
        return 0xE91E63  # red(KPOP brand AA-compliant)
    if "complete" in event:
        return 0x4CAF50  # green
    return 0x2196F3  # blue


def build_payload(event: str, args) -> dict:
    fields = []
    if args.suite:
        fields.append({"name": "suite", "value": args.suite, "inline": True})
    if args.success is not None:
        fields.append({"name": "success", "value": str(args.success), "inline": True})
    if args.failed is not None:
        fields.append({"name": "failed", "value": str(args.failed), "inline": True})
    if args.note:
        fields.append({"name": "note", "value": args.note[:200], "inline": False})
    return {
        "embeds": [{
            "title": f"[KPOP] {event}",
            "description": f"timestamp: `{now_iso()}`",
            "color": color_for_event(event, args.failed or 0),
            "fields": fields,
        }]
    }


def send_webhook(url: str, payload: dict, timeout: int = 10) -> tuple[bool, str]:
    data = json.dumps(payload).encode("utf-8")
    # User-Agent 必須: 既定の python-urllib UA は Discord/Cloudflare に
    # error code 1010(HTTP 403)でブロックされる。明示 UA で 204 成功。
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": DISCORD_USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (200 <= resp.status < 300, f"HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        return (False, f"HTTPError {e.code}")
    except urllib.error.URLError as e:
        return (False, f"URLError {e.reason}")
    except TimeoutError:
        return (False, "timeout")


def log_event(event: str, success: bool, detail: str, args) -> None:
    LOG_DIR.mkdir(exist_ok=True)
    entry = {
        "timestamp": now_iso(),
        "event": event,
        "suite": args.suite,
        "delivered": success,
        "detail": detail,
        "success_count": args.success,
        "failed_count": args.failed,
        "dry_run": args.dry_run,
    }
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", required=True, help="event name (e.g. orchestration_complete)")
    ap.add_argument("--suite", default=None)
    ap.add_argument("--success", type=int, default=None)
    ap.add_argument("--failed", type=int, default=None)
    ap.add_argument("--note", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    hooks = load_webhooks()
    url = select_webhook(args.event, hooks)
    payload = build_payload(args.event, args)

    if args.dry_run or not url:
        reason = "dry-run" if args.dry_run else "no webhook URL configured (suppressed)"
        print(f"WEBHOOK DISPATCH ({reason})")
        print(f"  event   : {args.event}")
        print(f"  payload : {json.dumps(payload, ensure_ascii=False)[:200]}")
        log_event(args.event, False, reason, args)
        # webhook 失効中でもロバスト動作(M8 で確立した方針)
        return 0

    ok, detail = send_webhook(url, payload)
    print(f"WEBHOOK DISPATCH")
    print(f"  event     : {args.event}")
    print(f"  delivered : {ok}  {detail}")
    log_event(args.event, ok, detail, args)
    return 0  # 配送失敗でも 0(ロバスト動作)


if __name__ == "__main__":
    sys.exit(main())
