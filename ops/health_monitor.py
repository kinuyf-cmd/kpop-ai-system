#!/usr/bin/env python3
"""サイトヘルスモニター + VPSディスク監視

cron: */30 * * * * /usr/bin/python3 /home/aiuser/kpop-ai-system/ops/health_monitor.py

チェック項目:
  1. VPSディスク使用率 (80%警告 / 90%自動掃除)
  2. WP REST API応答 (507/504/5xx検知)
  3. Next.js (PM2) プロセス状態
  4. サイトトップページ HTTP応答
"""
import json, os, shutil, subprocess, sys, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "health_monitor.jsonl"

WEBHOOKS_FILE = BASE_DIR / "config" / "discord_webhooks.json"

ENDPOINTS = [
    ("site_top", "https://www.kpopjournal.tokyo/"),
    ("wp_api", "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?per_page=1"),
    ("kpj_api", "https://www.kpopjournal.tokyo/wp-json/kpopjournal/v1/home"),
]

DISK_WARN_PCT = 80
DISK_CRIT_PCT = 90

# 自動掃除対象 (安全なもののみ)
CLEANABLE_DIRS = [
    (BASE_DIR / "logs", 7, "*.log"),          # 7日以上古いログ
    (Path("/tmp"), 1, "*"),                     # 1日以上古いtmpファイル
    (Path.home() / ".cache", 7, "*"),           # 7日以上古いキャッシュ
]


def get_webhook_url():
    try:
        with open(WEBHOOKS_FILE) as f:
            return json.load(f).get("urgent_errors", "")
    except Exception:
        return ""


def send_discord(message, webhook_url=None):
    url = webhook_url or get_webhook_url()
    if not url:
        print(f"[WARN] Discord webhook未設定: {message}")
        return
    payload = json.dumps({
        "content": message[:2000],
        "username": "HealthMonitor",
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[WARN] Discord送信失敗: {e}")


def check_disk():
    """VPSディスク使用率チェック"""
    total, used, free = shutil.disk_usage("/")
    pct = int(used / total * 100)
    free_gb = free / (1024 ** 3)
    result = {"disk_pct": pct, "free_gb": round(free_gb, 1)}

    if pct >= DISK_CRIT_PCT:
        result["level"] = "CRITICAL"
        result["action"] = "auto_clean"
    elif pct >= DISK_WARN_PCT:
        result["level"] = "WARNING"
    else:
        result["level"] = "OK"

    return result


def auto_clean_disk():
    """安全な自動掃除"""
    freed = 0
    cleaned = []

    # npmキャッシュ
    try:
        result = subprocess.run(
            ["npm", "cache", "clean", "--force"],
            capture_output=True, timeout=30,
        )
        cleaned.append("npm cache")
    except Exception:
        pass

    # 古いログ・キャッシュ
    for dir_path, max_days, pattern in CLEANABLE_DIRS:
        if not dir_path.exists():
            continue
        try:
            result = subprocess.run(
                ["find", str(dir_path), "-name", pattern,
                 "-mtime", f"+{max_days}", "-type", "f", "-delete"],
                capture_output=True, timeout=30,
            )
            cleaned.append(f"{dir_path} (+{max_days}d)")
        except Exception:
            pass

    # PM2ログローテート
    try:
        subprocess.run(["pm2", "flush"], capture_output=True, timeout=10)
        cleaned.append("pm2 logs flushed")
    except Exception:
        pass

    return cleaned


def check_endpoint(name, url):
    """HTTPエンドポイント応答チェック"""
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "KPJ-HealthMonitor/1.0")
        with urllib.request.urlopen(req, timeout=15) as res:
            return {"name": name, "status": res.status, "level": "OK"}
    except urllib.error.HTTPError as e:
        level = "CRITICAL" if e.code in (500, 502, 503, 507) else "WARNING"
        return {"name": name, "status": e.code, "level": level}
    except Exception as e:
        return {"name": name, "status": 0, "level": "CRITICAL", "error": str(e)[:100]}


def check_pm2():
    """PM2プロセス状態チェック"""
    try:
        result = subprocess.run(
            ["pm2", "jlist"], capture_output=True, text=True, timeout=10,
        )
        processes = json.loads(result.stdout)
        for proc in processes:
            if proc.get("name") == "kpopjournal":
                status = proc.get("pm2_env", {}).get("status", "unknown")
                restarts = proc.get("pm2_env", {}).get("restart_time", 0)
                return {
                    "name": "pm2_kpopjournal",
                    "status": status,
                    "restarts": restarts,
                    "level": "OK" if status == "online" else "CRITICAL",
                }
        return {"name": "pm2_kpopjournal", "status": "not_found", "level": "CRITICAL"}
    except Exception as e:
        return {"name": "pm2_kpopjournal", "status": "error", "level": "WARNING", "error": str(e)[:100]}


def main():
    now = datetime.now().isoformat(timespec="seconds")
    report = {"timestamp": now, "checks": []}
    alerts = []

    # 1. ディスクチェック
    disk = check_disk()
    report["checks"].append({"type": "disk", **disk})
    if disk["level"] == "CRITICAL":
        cleaned = auto_clean_disk()
        disk_after = check_disk()
        report["checks"].append({"type": "disk_after_clean", **disk_after, "cleaned": cleaned})
        if disk_after["disk_pct"] >= DISK_WARN_PCT:
            alerts.append(
                f"🔴 VPSディスク危険: {disk_after['disk_pct']}% (空き{disk_after['free_gb']}GB)\n"
                f"自動掃除実行済み: {', '.join(cleaned)}\n手動対応が必要です"
            )
    elif disk["level"] == "WARNING":
        alerts.append(f"⚠️ VPSディスク警告: {disk['disk_pct']}% (空き{disk['free_gb']}GB)")

    # 2. エンドポイントチェック
    for name, url in ENDPOINTS:
        result = check_endpoint(name, url)
        report["checks"].append(result)
        if result["level"] != "OK":
            status = result.get("status", "?")
            error_msg = result.get("error", "")
            alerts.append(
                f"{'🔴' if result['level'] == 'CRITICAL' else '⚠️'} "
                f"{name}: HTTP {status} {error_msg}"
            )

    # 3. PM2チェック
    pm2 = check_pm2()
    report["checks"].append(pm2)
    if pm2["level"] != "OK":
        alerts.append(f"🔴 PM2 kpopjournal: {pm2['status']}")

    # ログ記録
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(report, ensure_ascii=False) + "\n")

    # Discord通知 (異常時のみ)
    if alerts:
        msg = f"**KPJ HealthMonitor** ({now})\n" + "\n".join(alerts)
        send_discord(msg)
        print(f"ALERT: {len(alerts)} issue(s) detected")
        for a in alerts:
            print(f"  {a}")
    else:
        print(f"OK: All checks passed ({now})")

    # 終了コード (CI/cron用)
    has_critical = any(
        c.get("level") == "CRITICAL"
        for c in report["checks"]
    )
    sys.exit(1 if has_critical else 0)


if __name__ == "__main__":
    main()
