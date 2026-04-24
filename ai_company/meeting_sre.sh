#!/bin/bash
# ============================================================
# システム運用部 日次朝会（毎日 07:30 JST）
# 部署長: ポリゴンZ
# 主旨: インフラ監視・システム安定稼働・自動修復結果共有
# ============================================================
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
source "$BASE/lib/meeting_helper.sh"
source "$BASE/env_loader.sh" 2>/dev/null || true

REPORTS="$HOME/ai_company/reports/sre/$(date '+%Y%m%d')"
mkdir -p "$REPORTS"

TODAY=$(date '+%Y年%m月%d日')
echo "=== システム運用部朝会 開始: $TODAY ==="

# 前夜の修復ログ・アラートを収集
INFRA_DATA=$(python3 - <<'PYEOF'
import json, os
from pathlib import Path
from datetime import datetime, timedelta, timezone
JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
since = now - timedelta(hours=24)
base = Path("/home/aiuser/kpop-ai-system/logs")

def count_since(path, since):
    if not path.exists(): return []
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            r = json.loads(line.strip())
            ts = r.get("ts", r.get("timestamp", ""))
            try:
                t = datetime.fromisoformat(ts).astimezone(JST)
                if t >= since: rows.append(r)
            except: pass
        except: pass
    return rows

alerts = count_since(base / "watchdog_alerts.jsonl", since)
repairs = count_since(base / "watchdog_repairs.jsonl", since)

# パイプライン稼働 — cron.log の当日マーカーで判定
# 記事パイプラインは [AUDIT] 投稿後監査開始 + タイムスタンプで時間帯判定
# インフラ系は === XXX 完了 === マーカーで直接判定
today = now.strftime("%Y-%m-%d")
cron_log = base / "cron.log"
cron_today_lines = []
if cron_log.exists():
    import re
    for line in cron_log.read_text(errors="replace").splitlines():
        if today in line:
            cron_today_lines.append(line)

# 記事投稿の監査マーカーからタイムスタンプを収集
audit_hours = set()
for line in cron_today_lines:
    if "投稿後監査開始" in line:
        ts_match = re.search(r'(\d{2}):(\d{2})', line)
        if ts_match:
            audit_hours.add(int(ts_match.group(1)))

# スケジュール定義: (表示名, 予定時刻, 検知方法)
# type="article" → audit_hours で時間帯判定
# type="marker"  → cron.log の完了キーワードで判定
pipelines = [
    {"label": "速報 07:00",          "hour": 7,  "type": "article"},
    {"label": "速報 08:00",          "hour": 8,  "type": "article"},
    {"label": "美容 11:00",          "hour": 11, "type": "article"},
    {"label": "戦略 12:00",          "hour": 12, "type": "article"},
    {"label": "速報 13:00",          "hour": 13, "type": "article"},
    {"label": "ライフスタイル 14:00","hour": 14, "type": "article"},
    {"label": "速報 15:00",          "hour": 15, "type": "article"},
    {"label": "比較 16:00",          "hour": 16, "type": "article"},
    {"label": "ダッシュボード",      "hour": -1, "type": "marker", "key": "dashboard_refresh"},
    {"label": "自動修復 06:05",      "hour": 6,  "type": "marker", "key": "auto_repair"},
    {"label": "AI会議 21:00",        "hour": 21, "type": "marker", "key": "ai_meeting"},
]

status = []
for p in pipelines:
    label = p["label"]
    hour = p["hour"]

    if p["type"] == "article":
        if hour in audit_hours:
            status.append(f"  ✅ {label}: 投稿確認済")
        elif now.hour < hour:
            status.append(f"  ⏳ {label}: 実行予定")
        else:
            status.append(f"  🔴 {label}: 未検出")
    else:
        # marker 型: cron.log から完了マーカーを検索
        key = p["key"]
        found = False
        last_time = ""
        for line in cron_today_lines:
            if key in line and "完了" in line:
                found = True
                ts_match = re.search(r'(\d{2}:\d{2})', line)
                if ts_match:
                    last_time = ts_match.group(1)
        if found:
            status.append(f"  ✅ {label}: {last_time or '確認済'}")
        elif hour >= 0 and now.hour < hour:
            status.append(f"  ⏳ {label}: 実行予定")
        elif hour < 0:
            status.append(f"  ⬜ {label}: 未検出")
        else:
            status.append(f"  🔴 {label}: 未実行")

print(f"【自動修復24h】{len(repairs)}件")
for r in repairs[:5]: print(f"  🔧 {r.get('action','')}: {r.get('message','')[:60]}")
print(f"【未解決アラート24h】{len(alerts)}件")
for r in alerts[:5]: print(f"  🚨 {r.get('check','')}: {r.get('message','')[:60]}")
print("【パイプライン稼働】")
print("\n".join(status))
PYEOF
)

safe_claude porygon_z "
あなたはポリゴンZ（CTO・システム運用部長）です。システム運用部朝会を主催し、CTO視点で前夜のインフラ状態を総括してください。

【インフラ24hデータ】
${INFRA_DATA}

出力形式：
【担当】porygon_z
【稼働サマリー】（正常/異常/要注意 を明確に）
【前夜の修復実績】
【未解決問題と根本原因】（あれば）
【今日の要注意項目】（1〜3件）
【オーナー報告事項】（なければ「なし」）
" "$REPORTS/porygon_z.md"

safe_claude illumise "
あなたはイルミーゼ（UI/UX最適化）です。
A/Bテスト結果とUI指標（直近7日）をレビューしてください。

出力形式：
【担当】illumise
【A/B結果サマリー】
【UI改善アクション】（優先度付き）
" "$REPORTS/illumise.md"

# Discord送信（alert_summary チャネル）
MSG="🛡️ システム運用部朝会 ($TODAY) — 部署長: ポリゴンZ

$(cat "$REPORTS/porygon_z.md" | head -c 1200)

$(cat "$REPORTS/illumise.md" | head -c 500)"

meeting_discord_post "alert_summary" "$MSG"

echo "✅ システム運用部朝会 完了: $REPORTS"
