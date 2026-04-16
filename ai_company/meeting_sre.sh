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

# パイプライン稼働
today = now.strftime("%Y-%m-%d")
pipelines = [
    ("速報 07:00", "/home/aiuser/ai_kpop.log"),
    ("美容 11:00", str(base / "beauty_pipeline.log")),
    ("戦略 12:00", str(base / "strategy_pipeline.log")),
    ("AI会議 21:00", str(base / "ai_meeting.log")),
]
status = []
for label, path in pipelines:
    p = Path(path)
    if not p.exists():
        status.append(f"  ⬜ {label}: ログなし")
    else:
        m = datetime.fromtimestamp(os.path.getmtime(p), tz=JST)
        d = "✅" if m.strftime("%Y-%m-%d") == today else "🔴"
        status.append(f"  {d} {label}: {m.strftime('%m/%d %H:%M')}")

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
