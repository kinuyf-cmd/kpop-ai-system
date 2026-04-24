#!/usr/bin/env python3
"""
Human Gate - 人間介入設計
強制停止・手動承認・異常検知通知

監査本部（アブソル）管轄
"""
import json
import os
import subprocess
import sys
from datetime import datetime, date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
CONFIG_DIR = os.path.join(BASE_DIR, "config")

EMERGENCY_STOP_FILE = os.path.join(BASE_DIR, "EMERGENCY_STOP")
APPROVAL_QUEUE_FILE = os.path.join(LOGS_DIR, "approval_queue.json")


def load_safety_config():
    config_file = os.path.join(CONFIG_DIR, "safety_config.json")
    if os.path.exists(config_file):
        with open(config_file, encoding="utf-8") as f:
            return json.load(f)
    return {}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 強制停止
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def activate_emergency_stop(reason):
    """強制停止を有効化"""
    with open(EMERGENCY_STOP_FILE, "w") as f:
        f.write(json.dumps({
            "activated_at": datetime.now().isoformat(),
            "reason": reason,
        }, ensure_ascii=False))

    notify("critical", f"EMERGENCY STOP ACTIVATED: {reason}")
    return True


def deactivate_emergency_stop():
    """強制停止を解除"""
    if os.path.exists(EMERGENCY_STOP_FILE):
        os.remove(EMERGENCY_STOP_FILE)
        notify("info", "Emergency stop deactivated")
        return True
    return False


def is_emergency_stopped():
    """強制停止中かチェック"""
    if os.path.exists(EMERGENCY_STOP_FILE):
        with open(EMERGENCY_STOP_FILE) as f:
            data = json.loads(f.read())
        return {"stopped": True, **data}
    return {"stopped": False}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 手動承認
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def request_approval(post_data, reasons):
    """承認待ちキューに追加"""
    os.makedirs(LOGS_DIR, exist_ok=True)
    queue = _load_queue()

    entry = {
        "id": f"approval_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "requested_at": datetime.now().isoformat(),
        "status": "pending",
        "title": post_data.get("title", ""),
        "article_type": post_data.get("article_type", ""),
        "reasons": reasons,
        "file_path": post_data.get("file_path", ""),
    }

    queue["pending"].append(entry)
    _save_queue(queue)

    notify("warning", f"Manual approval required: {entry['title']}\nReasons: {', '.join(reasons)}")
    return entry


def approve_post(approval_id):
    """投稿を承認"""
    queue = _load_queue()
    for item in queue["pending"]:
        if item["id"] == approval_id:
            item["status"] = "approved"
            item["approved_at"] = datetime.now().isoformat()
            queue["pending"].remove(item)
            queue["approved"].append(item)
            _save_queue(queue)
            return True
    return False


def reject_post(approval_id, reason=""):
    """投稿を却下"""
    queue = _load_queue()
    for item in queue["pending"]:
        if item["id"] == approval_id:
            item["status"] = "rejected"
            item["rejected_at"] = datetime.now().isoformat()
            item["reject_reason"] = reason
            queue["pending"].remove(item)
            queue["rejected"].append(item)
            _save_queue(queue)
            return True
    return False


def get_pending_approvals():
    """承認待ちリストを取得"""
    queue = _load_queue()
    return queue["pending"]


def _load_queue():
    if os.path.exists(APPROVAL_QUEUE_FILE):
        with open(APPROVAL_QUEUE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"pending": [], "approved": [], "rejected": []}


def _save_queue(queue):
    with open(APPROVAL_QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 異常検知通知
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_and_notify_anomalies():
    """異常検知 → 通知"""
    from lib.post_guard import check_anomalies, check_emergency_stop

    # 強制停止チェック
    stop = check_emergency_stop()
    if stop["stop"]:
        notify("critical", f"System should be stopped: {stop['reason']}")
        return {"action": "stop", "reason": stop["reason"]}

    # 異常検知
    anomalies = check_anomalies()
    for alert in anomalies:
        severity = alert.get("severity", "warning")
        notify(severity, alert.get("message", "Unknown anomaly"))

    return {"action": "continue" if not anomalies else "warn", "anomalies": anomalies}


def monitor_pipeline_health():
    """パイプラインの健全性チェック"""
    checks = {
        "wp_api": _check_wp_health(),
        "post_log_integrity": _check_post_log_integrity(),
        "disk_space": _check_disk_space(),
        "recent_errors": _check_recent_errors(),
    }

    failed = [k for k, v in checks.items() if not v.get("healthy", False)]

    if failed:
        notify("warning", f"Pipeline health issues: {', '.join(failed)}")

    return {"healthy": len(failed) == 0, "checks": checks}


def _check_wp_health():
    try:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1",
             "--connect-timeout", "10", "--max-time", "15"],
            capture_output=True, text=True, timeout=20,
        )
        code = result.stdout.strip()
        return {"healthy": code == "200", "status_code": code}
    except Exception as e:
        return {"healthy": False, "error": str(e)}


def _check_post_log_integrity():
    if not os.path.exists(POST_LOG_FILE):
        return {"healthy": True, "note": "No post log yet"}
    try:
        with open(POST_LOG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {"healthy": isinstance(data, dict) and "posts" in data, "entries": len(data.get("posts", []))}
    except (json.JSONDecodeError, IOError):
        return {"healthy": False, "error": "post_log.json corrupted"}


def _check_disk_space():
    try:
        result = subprocess.run(["df", "-h", "/home"], capture_output=True, text=True, timeout=5)
        lines = result.stdout.strip().split("\n")
        if len(lines) >= 2:
            parts = lines[1].split()
            use_pct = int(parts[4].rstrip("%")) if len(parts) >= 5 else 0
            return {"healthy": use_pct < 90, "usage_percent": use_pct}
    except Exception:
        pass
    return {"healthy": True, "note": "Could not check"}


def _check_recent_errors():
    error_log = os.path.join(LOGS_DIR, "kpi_errors.jsonl")
    if not os.path.exists(error_log):
        return {"healthy": True, "error_count": 0}

    today = date.today().isoformat()
    count = 0
    with open(error_log, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                if entry.get("date") == today:
                    count += 1
            except (json.JSONDecodeError, KeyError):
                continue

    config = load_safety_config()
    threshold = config.get("emergency_stop", {}).get("daily_error_threshold", 15)
    return {"healthy": count < threshold, "error_count": count, "threshold": threshold}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 通知
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def notify(severity, message):
    """重要度に応じた通知"""
    config = load_safety_config()
    channels = config.get("notification_channels", {})
    targets = channels.get(severity, channels.get("warning", ["discord"]))

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    icons = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}
    icon = icons.get(severity, "📝")

    full_message = f"{icon} [{severity.upper()}] {timestamp}\n{message}"

    if "discord" in targets:
        _send_discord(full_message, severity)

    if "line" in targets:
        _send_line(full_message)

    # ログにも記録
    os.makedirs(LOGS_DIR, exist_ok=True)
    log_file = os.path.join(LOGS_DIR, "notifications.jsonl")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": timestamp,
            "severity": severity,
            "message": message,
        }, ensure_ascii=False) + "\n")


def _send_discord(message, severity="info"):
    """Discord Webhook送信"""
    webhook = os.environ.get("DISCORD_WEBHOOK", "")
    if not webhook:
        webhook_file = os.path.expanduser("~/.kpop_discord_webhook")
        if os.path.exists(webhook_file):
            with open(webhook_file) as f:
                webhook = f.read().strip()

    if not webhook:
        return

    colors = {"critical": 15158332, "warning": 16776960, "info": 3066993}
    color = colors.get(severity, 3066993)

    try:
        import requests
        requests.post(webhook, json={
            "embeds": [{
                "title": f"KPOP JOURNAL - {severity.upper()}",
                "description": message[:2000],
                "color": color,
            }]
        }, timeout=10)
    except Exception:
        pass


def _send_line(message):
    """LINE Notify送信"""
    token_file = os.path.expanduser("~/.kpop_line_token")
    if not os.path.exists(token_file):
        return

    with open(token_file) as f:
        token = f.read().strip()

    if not token:
        return

    try:
        import requests
        requests.post("https://notify-api.line.me/api/notify",
                       headers={"Authorization": f"Bearer {token}"},
                       data={"message": message[:1000]},
                       timeout=10)
    except Exception:
        pass


# ── CLI ──

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: human_gate.py <stop|resume|status|pending|health|check>")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "stop":
        reason = sys.argv[2] if len(sys.argv) > 2 else "Manual stop"
        activate_emergency_stop(reason)
        print("Emergency stop activated")

    elif cmd == "resume":
        deactivate_emergency_stop()
        print("Emergency stop deactivated")

    elif cmd == "status":
        result = is_emergency_stopped()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "pending":
        result = get_pending_approvals()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "health":
        result = monitor_pipeline_health()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "check":
        sys.path.insert(0, BASE_DIR)
        result = check_and_notify_anomalies()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        print(f"Unknown: {cmd}")
