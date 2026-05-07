#!/usr/bin/env python3
"""metrics_yesterday.json の鮮度・健全性チェック → 異常時にDiscord errorチャネルに通知

実行タイミング: cron `5 9 * * *` (fetch 9:00 完了の5分後)
チェック項目:
  1. metrics_yesterday.json の date が yesterday と一致するか (古ければ警告)
  2. AdSense error フィールドがあるか (token失効検知)
  3. GA4 sessions が極端に少ないか (API障害検知)

設計意図:
  - 2026-05-06 〜 5/7 の AdSense token失効事故 (5日間気付かれず) の再発防止
  - fetch_yesterday_metrics.py 自体を編集せず外部チェッカーで対応 (依存最小化)
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
METRICS_FILE = Path("/home/aiuser/kpop-ai-system/google_metrics/metrics_yesterday.json")
WEBHOOKS_FILE = Path("/home/aiuser/kpop-ai-system/config/discord_webhooks.json")
HEALTH_LOG = Path("/home/aiuser/kpop-ai-system/logs/metrics_health.jsonl")


def load_error_webhook() -> str:
    if not WEBHOOKS_FILE.exists():
        return ""
    try:
        d = json.loads(WEBHOOKS_FILE.read_text())
        return d.get("error") or d.get("morning") or ""
    except Exception:
        return ""


def send_discord(content: str) -> int:
    webhook = load_error_webhook()
    if not webhook:
        print(f"[no-webhook] {content[:100]}")
        return 0
    body = json.dumps({"content": content[:1900]}).encode()
    req = urllib.request.Request(
        webhook, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except Exception as e:
        print(f"[discord-err] {e}")
        return 0


def append_health_log(record: dict):
    HEALTH_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(HEALTH_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    now = datetime.now(JST)
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    issues = []

    if not METRICS_FILE.exists():
        issues.append({"severity": "critical", "msg": f"metrics_yesterday.json が存在しない"})
    else:
        try:
            m = json.loads(METRICS_FILE.read_text())
        except Exception as e:
            issues.append({"severity": "critical", "msg": f"metrics_yesterday.json パース失敗: {e}"})
            m = {}

        # 1. date 鮮度
        md = m.get("date")
        if md != yesterday:
            issues.append({
                "severity": "high",
                "msg": f"metrics_yesterday.json date={md} (期待: {yesterday})。fetch_yesterday_metrics.py が動いていない可能性"
            })

        # 2. AdSense error
        ads = m.get("adsense", {})
        if isinstance(ads, dict) and ads.get("error"):
            issues.append({
                "severity": "high",
                "msg": f"AdSense API エラー: {str(ads['error'])[:200]}"
            })

        # 3. GA4 異常値
        ga4_sum = m.get("ga4", {}).get("summary", {}) if isinstance(m.get("ga4"), dict) else {}
        sessions = ga4_sum.get("sessions")
        if sessions is None or str(sessions) == "":
            issues.append({"severity": "medium", "msg": "GA4 sessions 取得不可"})
        else:
            try:
                if int(sessions) < 10:
                    issues.append({"severity": "medium", "msg": f"GA4 sessions={sessions} (異常に少ない、API障害の可能性)"})
            except Exception:
                pass

    record = {
        "ts": now.isoformat(),
        "yesterday": yesterday,
        "issue_count": len(issues),
        "issues": issues,
    }
    append_health_log(record)

    if issues:
        # severityごとにアイコン
        icon_map = {"critical": "🔴", "high": "🟠", "medium": "🟡"}
        lines = [f"⚠️ **metrics_fetch_health 異常検知** ({now.strftime('%Y-%m-%d %H:%M JST')})"]
        for iss in issues:
            ic = icon_map.get(iss["severity"], "⚠️")
            lines.append(f"{ic} [{iss['severity']}] {iss['msg']}")
        lines.append("\n対応: tools/oauth_exchange.py --auth-url で再認証 / fetch_yesterday_metrics.py 手動実行")
        msg = "\n".join(lines)
        code = send_discord(msg)
        print(f"[alert] {len(issues)} issues → discord {code}")
        sys.exit(1 if any(i["severity"] in ("critical", "high") for i in issues) else 0)
    else:
        print(f"[ok] metrics_yesterday.json date={yesterday} healthy")


if __name__ == "__main__":
    main()
