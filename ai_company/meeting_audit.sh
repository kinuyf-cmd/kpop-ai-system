#!/bin/bash
# ============================================================
# 監査品質部 週次会議（毎週金曜 22:00 JST）
# 部署長: アルセウス
# 参加: アルセウス、ジラーチ、ゲンガー、サーナイト、フーディン
# 主旨: 記事品質審査・事実確認・フックゲート・コンプライアンス
# ============================================================
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
source "$BASE/lib/meeting_helper.sh"
source "$BASE/env_loader.sh" 2>/dev/null || true

REPORTS="$HOME/ai_company/reports/audit/$(date '+%Y%m%d')"
mkdir -p "$REPORTS"

TODAY=$(date '+%Y年%m月%d日')
echo "=== 監査品質部会議 開始: $TODAY ==="

# 直近7日のゲート違反・品質事故を収集
AUDIT_DATA=$(python3 - <<'PYEOF'
import json, os
from pathlib import Path
from datetime import datetime, timedelta, timezone
JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
cutoff = (now - timedelta(days=7))
base = Path("/home/aiuser/kpop-ai-system/logs")

# 品質ゲート違反ログ
gate_log = base / "pre_publish_gate.jsonl"
blocked = 0; passed = 0; block_reasons = {}
if gate_log.exists():
    for line in gate_log.read_text(errors="replace").splitlines():
        try:
            r = json.loads(line.strip())
            ts = r.get("ts","")
            try: t = datetime.fromisoformat(ts).astimezone(JST)
            except: continue
            if t < cutoff: continue
            if r.get("verdict") == "BLOCK":
                blocked += 1
                reason = r.get("reason","unknown")[:40]
                block_reasons[reason] = block_reasons.get(reason,0) + 1
            else:
                passed += 1
        except: pass

print(f"【直近7日 品質ゲート】通過 {passed}件 / BLOCK {blocked}件")
print("【BLOCK理由TOP】")
for r, n in sorted(block_reasons.items(), key=lambda x: -x[1])[:5]:
    print(f"  {n}件: {r}")

# X投稿フェイルセーフ
xf = base / "x_failsafe.jsonl"
if xf.exists():
    events = [l for l in xf.read_text(errors="replace").splitlines() if l.strip()]
    recent = 0
    for line in events:
        try:
            r = json.loads(line)
            ts = r.get("ts","")
            try: t = datetime.fromisoformat(ts).astimezone(JST)
            except: continue
            if t >= cutoff and r.get("event") == "failsafe_triggered":
                recent += 1
        except: pass
    print(f"【X投稿フェイルセーフ発動】{recent}回")
PYEOF
)

safe_claude arceus "
あなたはアルセウス（CQO・監査品質部長・総監督）です。監査品質部会議を主催し、CQO視点で週次品質監査を統括してください。

【監査データ】
${AUDIT_DATA}

出力形式：
【担当】arceus
【今週の品質評価】（A/B/C/D）
【重大インシデント】（あれば）
【プロセス遵守状況】
【再発防止策】
【オーナー報告要否】
" "$REPORTS/arceus.md"

safe_claude gengar "
あなたはゲンガー（SEO品質監査）です。直近のSEO品質違反を報告してください。

出力形式：
【担当】gengar
【SEO違反トレンド】（重複・noindex・薄記事など）
【修正優先度TOP3】
" "$REPORTS/gengar.md"

safe_claude jirachi_kpop "
あなたはジラーチ（ファクトチェック）です。直近のファクト誤り・訂正案件を報告してください。

出力形式：
【担当】jirachi
【ファクト事故件数】
【要訂正記事】（あれば）
【予防策】
" "$REPORTS/jirachi.md"

safe_claude alakazam_kpop "
あなたはフーディン（時制・整合性監査）です。直近記事の時制ズレ・矛盾を報告してください。

出力形式：
【担当】alakazam
【時制問題の発見件数】
【対処方針】
" "$REPORTS/alakazam.md"

# 統括レポート
{
  echo "# 監査部 週次レポート: ${TODAY}"
  echo "${AUDIT_DATA}"
  echo ""
  for f in arceus gengar jirachi alakazam; do
    echo "## ${f}"
    cat "$REPORTS/${f}.md" 2>/dev/null
    echo ""
  done
} > "$REPORTS/audit_summary.md"

MSG="⚖️ 監査品質部会議 ($TODAY) — 部署長: アルセウス

$(cat "$REPORTS/arceus.md" | head -c 1000)

[SEO品質]
$(cat "$REPORTS/gengar.md" | head -c 400)"

meeting_discord_post "urgent_errors" "$MSG"

echo "✅ 監査品質部会議 完了: $REPORTS"
