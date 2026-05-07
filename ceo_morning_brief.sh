#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CEO Morning Brief - 毎朝 9:00 JST
# 担当: ミュウツー（CFO/Data）| 監視: ポリゴンZ（SRE）
#
# 出力: KPIダッシュボード（デイリー/月次/最終目標進捗）
#       + パイプライン稼働状況 + SRE監査 + X投稿実績
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/env_loader.sh"

TODAY=$(date '+%Y年%m月%d日')
TODAY_KEY=$(date '+%Y-%m-%d')
YESTERDAY_KEY=$(date -d 'yesterday' '+%Y-%m-%d' 2>/dev/null || date -v-1d '+%Y-%m-%d' 2>/dev/null || echo "")
YESTERDAY_LABEL=$(date -d 'yesterday' '+%Y年%m月%d日' 2>/dev/null || date -v-1d '+%Y年%m月%d日' 2>/dev/null || echo "前日")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [SECTION 1] KPI ダッシュボード
# （lib/kpi_dashboard.py が目標値・実績・達成率・進捗バーを生成）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KPI_DASHBOARD=$(python3 "$SCRIPT_DIR/lib/kpi_dashboard.py" 2>/dev/null || echo "⚠ KPIダッシュボード生成失敗")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [SECTION 2] パイプライン稼働状況
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PIPELINE_STATUS=$(python3 - << 'PYPIPE'
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
today = now.strftime("%Y-%m-%d")
yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
base = Path("/home/aiuser/kpop-ai-system/logs")

PIPELINES = [
    (Path("/home/aiuser/ai_kpop.log"),                "07:00 速報パイプライン"),
    (base / "beauty_pipeline.log",                    "11:00 美容・コスメ"),
    (base / "strategy_pipeline.log",                  "12:00 戦略・資産記事"),
    (base / "morning_brief.log",                      "09:00 CEOブリーフ"),
    (base / "post_publish_enricher.log",              "記事公開エンリッチャー"),
    (base / "post_audit_feedback_loop.log",           "記事監査フィードバックループ"),
    (base / "breaking_news.log",                      "速報ニュース検知"),
    (base / "x_scheduled.log",                        "X投稿スケジューラー"),
]
# 廃止 (2026-05時点でcron無し): lifestyle_pipeline / fashion_pipeline /
# ai_meeting / chart_pipeline (月曜) / weekly_review (月曜) — 母数から除外

lines = []
ok = ng = 0
for log_path, label in PIPELINES:
    if not log_path.exists():
        lines.append(f"  ⬜ {label:<24} ログなし")
        continue
    mtime = datetime.fromtimestamp(os.path.getmtime(log_path), tz=JST)
    mtime_str = mtime.strftime("%m/%d %H:%M")
    if mtime.strftime("%Y-%m-%d") == today:
        lines.append(f"  ✅ {label:<24} 本日 {mtime.strftime('%H:%M')} 更新")
        ok += 1
    elif mtime.strftime("%Y-%m-%d") == yesterday:
        lines.append(f"  🟡 {label:<24} 昨日 {mtime.strftime('%H:%M')} 更新")
        ok += 1
    else:
        lines.append(f"  🔴 {label:<24} 最終: {mtime_str}")
        ng += 1

uptime = ok/(ok+ng)*100 if (ok+ng) > 0 else 0
icon = "✅" if uptime >= 95 else ("🟡" if uptime >= 70 else "🔴")
print(f"  {icon} 稼働率: {uptime:.0f}% ({ok}本稼働 / {ng}本停止)\n")
print("\n".join(lines))
PYPIPE
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [SECTION 3] X投稿実績（前日）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
X_POST_SUMMARY=$(python3 - << 'PYXPOST'
# 真ソース: x_posts.jsonl (status='ok'/'error'/'ogp_warn')。x_post.log は旧/部分ログのため使わない。
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")

xj = Path("/home/aiuser/kpop-ai-system/logs/x_posts.jsonl")
if not xj.exists():
    print("  ⬜ x_posts.jsonl なし")
    exit()

ok = ng = warn = 0
tweet_urls = []
for line in xj.read_text(errors="replace").splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        r = json.loads(line)
    except Exception:
        continue
    if not str(r.get("ts","")).startswith(yesterday):
        continue
    st = r.get("status")
    if st == "ok":
        ok += 1
        if r.get("url"):
            tweet_urls.append(r["url"])
    elif st == "error":
        ng += 1
    elif st == "ogp_warn":
        warn += 1

icon = "✅" if ok > 0 else ("🟡" if warn > 0 else "🔴")
print(f"  {icon} 投稿成功: {ok}件  失敗: {ng}件  ogp_warn: {warn}件")
for u in tweet_urls[:3]:
    print(f"      ↳ {u}")
if ok == 0 and warn == 0 and ng == 0:
    print("  ⬜ 前日のX投稿記録なし")
PYXPOST
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [SECTION 4] 前日投稿記事一覧
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ARTICLE_LIST=$(python3 - << 'PYART'
import json, re, os
from pathlib import Path
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")

# pipeline logから昨日投稿された記事を検出
base = Path("/home/aiuser/kpop-ai-system/logs")
PIPELINE_LOGS = [
    (Path("/home/aiuser/ai_kpop.log"), "速報"),
    (base / "beauty_pipeline.log", "美容"),
    (base / "strategy_pipeline.log", "戦略"),
    (base / "lifestyle_pipeline.log", "ライフスタイル"),
    (base / "fashion_pipeline.log", "ファッション"),
    (base / "chart_pipeline.log", "チャート"),
]

articles = []
for log_path, label in PIPELINE_LOGS:
    if not log_path.exists():
        continue
    mtime = datetime.fromtimestamp(os.path.getmtime(log_path), tz=JST)
    if mtime.strftime("%Y-%m-%d") != yesterday:
        continue
    txt = log_path.read_text(errors="replace")
    # POST_ID= で投稿IDを取得
    pids = re.findall(r'POST_ID=(\d+)', txt)
    # TITLE行を取得
    titles = re.findall(r'TITLE[:=]\s*(.+)', txt)
    # スコアを取得
    scores = re.findall(r'SCORE[:=]\s*([\d.]+)', txt)
    if pids:
        for i, pid in enumerate(pids[:5]):  # 最大5本
            title = titles[i] if i < len(titles) else "不明"
            score = scores[i] if i < len(scores) else "?"
            articles.append(f"  ✅ [{label}] ID:{pid} | {title[:35]} | スコア:{score}")
    elif mtime.strftime("%Y-%m-%d") == yesterday:
        articles.append(f"  🟡 [{label}] 実行済み（記事ID取得不可）")

if not articles:
    print("  ⬜ 前日の投稿記事データなし")
else:
    print("\n".join(articles))
PYART
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [SECTION 5] 自動修復ログ（前日）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REPAIR_SUMMARY=$(python3 - << 'PYREPAIR'
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
yesterday = (datetime.now(JST) - timedelta(days=1)).strftime("%Y-%m-%d")
base = Path("/home/aiuser/kpop-ai-system/logs")

repairs, alerts = [], []
for path, lst in [(base/"watchdog_repairs.jsonl", repairs), (base/"watchdog_alerts.jsonl", alerts)]:
    if path.exists():
        for line in path.read_text(errors="replace").splitlines():
            try:
                r = json.loads(line.strip())
                if yesterday in r.get("ts",""):
                    lst.append(r)
            except: pass

if not repairs and not alerts:
    print("  ✅ 自動修復なし・未解決アラートなし（正常稼働）")
else:
    if repairs:
        print(f"  🔧 自動修復: {len(repairs)}件")
        for r in repairs[:3]:
            print(f"      [{r.get('action','')}] {r.get('message','')[:70]}")
    if alerts:
        print(f"  🚨 未解決アラート: {len(alerts)}件")
        for r in alerts[:3]:
            print(f"      [{r.get('check','')}] {r.get('message','')[:70]}")
PYREPAIR
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [SECTION 6] 当日方針（ルールベース）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
POLICY=$(python3 - << 'PYPOLICY'
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
base = Path("/home/aiuser/kpop-ai-system/logs")

# 前日のx_post状況 (真ソース: x_posts.jsonl)
x_ok = 0
xj = base / "x_posts.jsonl"
if xj.exists():
    for line in xj.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("status") == "ok" and str(r.get("ts","")).startswith(yesterday):
            x_ok += 1

# failsafe状態
failsafe_active = False
fs_path = base / "x_failsafe.jsonl"
if fs_path.exists():
    lines = [l for l in fs_path.read_text(errors="replace").splitlines() if l.strip()]
    if lines:
        try:
            last = json.loads(lines[-1])
            if last.get("event") == "failsafe_triggered":
                failsafe_active = True
        except: pass

actions = []

if failsafe_active:
    actions.append("  🚨 【緊急】X投稿フェイルセーフが発動中 → CTR低下の原因を調査し、logs/x_failsafe.jsonlを確認してください")

if x_ok == 0:
    actions.append("  ⚠ 前日のX投稿がゼロ → ENABLE_X_POST=1 の確認、パイプライン実行ログを確認してください")

# 記事投稿数チェック（pipeline log）
import os, re
pipeline_ok = False
LOGS = [
    Path("/home/aiuser/ai_kpop.log"),
    base / "lifestyle_pipeline.log",
    base / "beauty_pipeline.log",
    base / "fashion_pipeline.log",
]
for p in LOGS:
    if p.exists():
        mtime = datetime.fromtimestamp(os.path.getmtime(p), tz=JST)
        if mtime.strftime("%Y-%m-%d") == yesterday:
            pipeline_ok = True
            break

if not pipeline_ok:
    actions.append("  ⚠ 前日のパイプライン実行記録なし → cron設定・サーバー稼働状況を確認してください")

# 月次進捗
day_of_month = now.day
if day_of_month <= 10:
    actions.append(f"  📅 月初フェーズ ({day_of_month}日経過) → コンテンツ量を積み上げる時期。品質重視で5本/日を維持")
elif day_of_month <= 20:
    actions.append(f"  📅 月中フェーズ ({day_of_month}日経過) → SEO効果が出始める時期。低CTR記事のリライトを検討")
else:
    actions.append(f"  📅 月末フェーズ ({day_of_month}日経過) → 月次目標の達成状況を確認。CTR改善・収益導線強化")

if not actions:
    actions.append("  ✅ 特段の対応事項なし。通常運用を継続してください")

print("\n".join(actions))
PYPOLICY
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [SECTION 7] 直近 TOP記事（GSC）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOP_PAGES=$(python3 - << 'PYTOP'
import json
from pathlib import Path

m = Path("/home/aiuser/google_metrics/metrics_yesterday.json")
if not m.exists():
    print("  ⬜ GSCデータなし")
    exit()

d = json.loads(m.read_text())
pages = d.get("gsc",{}).get("top_pages",[])[:5]
if not pages:
    print("  ⬜ GSCデータなし")
    exit()

for i, p in enumerate(pages, 1):
    url = p.get("page","").replace("https://www.kpopjournal.tokyo","")[:35]
    clicks = p.get("clicks", 0)
    imps = p.get("impressions", 0)
    ctr = p.get("ctr", 0)
    pos = p.get("position", 0)
    print(f"  {i}. {url:<36} C:{clicks:>3} I:{imps:>4} CTR:{ctr*100:.1f}% Pos:{pos:.1f}")
PYTOP
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# [組み立て] フルブリーフ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRIEF=$(cat << BRIEF_EOF
${KPI_DASHBOARD}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📡 パイプライン稼働状況
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
${PIPELINE_STATUS}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🐦 X投稿実績（${YESTERDAY_LABEL}）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
${X_POST_SUMMARY}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📝 前日投稿記事
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
${ARTICLE_LIST}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏆 GSC TOP記事（直近）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
${TOP_PAGES}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔧 自動修復ログ（${YESTERDAY_LABEL}）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
${REPAIR_SUMMARY}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 本日の優先アクション
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
${POLICY}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Generated by ミュウツー (CFO/Data) | 監視: ポリゴンZ (SRE) | ${TODAY} 09:00 JST
BRIEF_EOF
)

echo "$BRIEF"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Discord送信（#daily-ceo-report）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
source "$SCRIPT_DIR/lib/discord_channels.sh" 2>/dev/null || true
WEBHOOK=$(get_discord_webhook "morning" 2>/dev/null || echo "")
[ -z "$WEBHOOK" ] && WEBHOOK="${DISCORD_WEBHOOK:-}"

if [[ -z "$WEBHOOK" ]]; then
  echo ""
  echo "⚠ DISCORD_WEBHOOK 未設定 → Discord送信スキップ"
  exit 0
fi

# Discord は 2000文字制限のため、KPIダッシュボード部分を優先
# 複数メッセージに分割して送信
send_discord() {
  local msg="$1"
  local trimmed
  trimmed=$(echo "$msg" | head -c 1950)
  local http_code
  http_code=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$WEBHOOK" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json,sys; print(json.dumps({'content': sys.argv[1]}))" "$trimmed")" \
    --connect-timeout 10 --max-time 15 2>/dev/null || echo "000")
  echo "$http_code"
}

# メッセージ1: KPIダッシュボード
MSG1="📋 **CEO Morning Brief — ${TODAY}**

\`\`\`
${KPI_DASHBOARD}
\`\`\`"

# メッセージ2: 運営状況サマリー
MSG2="📡 **パイプライン稼働** | 🐦 **X投稿実績**
\`\`\`
${PIPELINE_STATUS}
---
${X_POST_SUMMARY}
---
🎯 本日アクション:
${POLICY}
\`\`\`"

CODE1=$(send_discord "$MSG1")
sleep 1
CODE2=$(send_discord "$MSG2")

if [[ "$CODE1" == "204" || "$CODE1" == "200" ]]; then
  echo ""
  echo "✅ Discord送信完了 (MSG1: $CODE1, MSG2: $CODE2)"
else
  echo ""
  echo "⚠ Discord送信失敗 (HTTP $CODE1 / $CODE2)"
fi
