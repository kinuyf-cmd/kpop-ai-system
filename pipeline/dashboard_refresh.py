#!/usr/bin/env python3
"""経営ダッシュボード更新パイプライン (v4)

1. dashboard.json を build_dashboard_json.py で生成
2. dashboard/v3/render.py で軽量HTML (12KB) を生成
3. deploy_dashboard.py で WPページにデプロイ

cron: 毎2時間 (9,11,13,15,17,19,21時)
"""
import os
import subprocess
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(BASE, "logs", "dashboard_refresh.log")


def _log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S JST")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _run(label, cmd):
    _log(f"{label}...")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=BASE, timeout=120)
    if r.returncode != 0:
        _log(f"ERROR {label}: exit={r.returncode}")
        if r.stderr:
            _log(f"  stderr: {r.stderr[:300]}")
        return False
    if r.stdout:
        for line in r.stdout.strip().split("\n")[-3:]:
            _log(f"  {line}")
    return True


def main():
    _log("=== dashboard_refresh v4 開始 ===")

    # Step 1: dashboard.json 生成
    ok1 = _run("Step1: build_dashboard_json",
               [sys.executable, os.path.join(BASE, "tools", "build_dashboard_json.py")])
    if not ok1:
        _log("Step1失敗 — 中断")
        return False

    # Step 2: v4 HTML render
    ok2 = _run("Step2: render v4 HTML",
               [sys.executable, os.path.join(BASE, "dashboard", "v3", "render.py")])
    if not ok2:
        _log("Step2失敗 — 中断")
        return False

    # Step 3: dashboard.html にコピー + デプロイ
    src = "/home/aiuser/kpopjournal-frontend/public/dash-kx7m2p-v2/index.html"
    dst = os.path.join(BASE, "dashboard.html")
    if os.path.exists(src):
        import shutil
        shutil.copy2(src, dst)
        size = os.path.getsize(dst)
        _log(f"  dashboard.html updated: {size:,} bytes")
        if size > 500_000:
            _log(f"  WARN: HTMLが500KBを超えています ({size:,}B) — nginx 413リスク")
    else:
        _log(f"  WARN: {src} not found, skipping deploy")
        return False

    ok3 = _run("Step3: deploy to WP",
               [sys.executable, "-c",
                "import sys; sys.path.insert(0,'lib'); from deploy_dashboard import run; run()"])
    if not ok3:
        _log("Step3失敗 — デプロイ未完了")
        return False

    _log("=== dashboard_refresh v4 完了 ===")
    return True


if __name__ == "__main__":
    main()
