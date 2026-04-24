#!/bin/bash
# ============================================================
# 人事部（横断機能）週次会議（毎週火曜 22:00 JST）
# 主管: アルセウス（監査品質部長兼務）
# 参加: アルセウス、ミュウツー（CEO）、ポリゴン、ソーナンス
# 主旨: エージェント人事評価・配置・処遇・採用監査
# ============================================================
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
source "$BASE/lib/meeting_helper.sh"
source "$BASE/env_loader.sh" 2>/dev/null || true

REPORTS="$HOME/ai_company/reports/hr/$(date '+%Y%m%d')"
mkdir -p "$REPORTS"

TODAY=$(date '+%Y年%m月%d日')
echo "=== 人事部会議 開始: $TODAY ==="

# Phase 4: 前週KPI自動注入
WEEKLY_KPI=$(weekly_kpi_brief hr)

# エージェント人事データ収集（org_map.json + agent_metrics.json + 役割監査ログ）
HR_DATA=$(python3 - <<'PYEOF'
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
base = Path("/home/aiuser/kpop-ai-system")

org_path = base / "org_map.json"
if not org_path.exists():
    print("org_map.json なし")
else:
    org = json.loads(org_path.read_text())
    total = org.get("total_agents", 0)
    active = org.get("active_agents", 0)
    critical = org.get("critical_agents", 0)
    print(f"【組織サマリー】total={total} / 稼働中={active} / 要改善={critical}")
    print()

    # 要改善 🔴 ランキング
    agents_flat = []
    for dept_k, dept in org.get("departments", {}).items():
        for a in dept.get("agents", []):
            agents_flat.append({**a, "_dept": dept_k})

    agents_flat.sort(key=lambda a: a.get("success_rate", 1.0))
    print("【パフォーマンス下位TOP5（要対応候補）】")
    for a in agents_flat[:5]:
        sr = a.get("success_rate", 0)
        last = a.get("last_run_time", "")[:10] or "未実行"
        print(f"  🔴 {a['id']:<25} 成功率={sr:.2f} / 最終={last} / 部門={a['_dept']} / {a.get('role','')}")

    print()
    # 長期未実行（14日以上）
    cutoff = now - timedelta(days=14)
    stale = []
    for a in agents_flat:
        ts = a.get("last_run_time", "")
        if not ts: continue
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(JST)
            if t < cutoff:
                stale.append((a["id"], t.strftime("%Y-%m-%d"), a.get("role", "")))
        except: pass
    if stale:
        print(f"【14日以上未実行（休眠）{len(stale)}名】")
        for aid, ts, role in stale[:10]:
            print(f"  💤 {aid:<25} 最終={ts} / {role}")

    print()
    # 役割重複チェック（同じroleを持つagent）
    from collections import defaultdict
    role_map = defaultdict(list)
    for a in agents_flat:
        role_map[a.get("role", "")].append(a["id"])
    dups = {r: ids for r, ids in role_map.items() if len(ids) > 1 and r}
    if dups:
        print("【役割重複（冗長性監査）】")
        for r, ids in dups.items():
            print(f"  ⚠ {r}: {', '.join(ids)}")

# 直近追加されたagentファイル（新規採用候補）
import os
agents_dir = base / "agents"
if agents_dir.exists():
    recent_cutoff = now.timestamp() - 14 * 86400
    new_agents = []
    for f in agents_dir.glob("*.md"):
        try:
            ct = f.stat().st_ctime
            if ct > recent_cutoff:
                new_agents.append((f.stem, datetime.fromtimestamp(ct, tz=JST).strftime("%Y-%m-%d")))
        except: pass
    if new_agents:
        print(f"\n【直近14日の新規agent候補 {len(new_agents)}件】")
        for n, d in new_agents:
            print(f"  🆕 {n} ({d})")
PYEOF
)

# ポリゴン: パフォーマンスデータ分析
safe_claude porygon "
あなたはポリゴン（データ分析）です。人事部会議でエージェント評価データを提示してください。

【人事データ】
${HR_DATA}

出力形式：
【担当】porygon
【パフォーマンス最下位3名】（定量的評価）
【休眠・サボり疑い】（14日以上未実行）
【評価改善傾向】（前週比）
" "$REPORTS/porygon.md"

# ソーナンス: 能力適性分析
safe_claude wobbuffet "
あなたはソーナンス（読者ニーズ分析）です。人事部会議で、
「どのエージェントが読者ニーズに応えられているか」という能力適性の観点で報告してください。

出力形式：
【担当】wobbuffet
【適性ミスマッチの疑い】（役割と実績がズレている agent）
【強み未活用の疑い】（能力はあるが稼働が少ない agent）
" "$REPORTS/wobbuffet.md"

# アルセウス: 人事判断
safe_claude arceus "
あなたはアルセウス（CQO・人事部長兼務）です。
ポリゴンとソーナンスの報告を踏まえ、人事判断を下してください。

【人事データ】
${HR_DATA}

【ポリゴン報告】
$(cat "$REPORTS/porygon.md")

【ソーナンス報告】
$(cat "$REPORTS/wobbuffet.md")

出力形式：
【担当】arceus（HR責任者）
【今週の人事判断】
  1. 処遇変更案：（agent ID → 再教育 / 降格 / 手動専用化 / 削除）
  2. 配置転換案：（あれば）
【低パフォーマー対応計画】（具体的アクション＋担当＋期限）
【役割重複の解消案】（冗長性があれば統合・廃止提案）
【新規agentの採用可否】（直近追加分の評価）
【オーナー承認要件】（削除・大幅降格は必ず報告）
" "$REPORTS/arceus_hr.md"

# CEO最終承認
safe_claude mewtwo "
あなたはミュウツー（CEO）です。人事部の判断を最終承認してください。

【HR責任者の判断】
$(cat "$REPORTS/arceus_hr.md")

出力形式：
【担当】mewtwo（CEO）
【承認／差し戻し】（各案件ごとに ✅承認 / ⚠条件付 / ❌差戻）
【経営判断コメント】
【実施タイミング】
【オーナー報告事項】（要承認の重大案件）
" "$REPORTS/ceo_approval.md"

# 統合レポート
{
  echo "# 人事部会議 ${TODAY}"
  echo ""
  echo "## 人事データ"
  echo "${HR_DATA}"
  echo ""
  for f in porygon wobbuffet arceus_hr ceo_approval; do
    echo "## ${f}"
    cat "$REPORTS/${f}.md" 2>/dev/null
    echo ""
  done
} > "$REPORTS/hr_summary.md"

MSG="👥 人事部会議 ($TODAY)

$(cat "$REPORTS/arceus_hr.md" | head -c 900)

[CEO最終承認]
$(cat "$REPORTS/ceo_approval.md" | head -c 500)"

meeting_discord_post "alert_summary" "$MSG"

echo "✅ 人事部会議 完了: $REPORTS"
