#!/bin/bash
# set -e は使わない: 1段のclaude失敗で全停止を避け、safe_claudeで継続する
set -uo pipefail

BASE="$HOME/ai_company"
REPORTS="$BASE/reports"
mkdir -p "$REPORTS"

# 共通ヘルパー（safe_claude / category_balance_summary / meeting_discord_post）
REPO_BASE="$(cd "$(dirname "$0")/.." && pwd)"
source "$REPO_BASE/lib/meeting_helper.sh"

# --- ai_meeting.log への tee 記録（再発防止: cron経由で単独ログが更新されない問題の修正） ---
AI_MEETING_LOG="${AI_MEETING_LOG:-$REPO_BASE/logs/ai_meeting.log}"
mkdir -p "$(dirname "$AI_MEETING_LOG")" 2>/dev/null || true
{
  echo ""
  echo "=== [$(date '+%Y-%m-%d %H:%M:%S')] run_ai_meeting 開始 ==="
} >> "$AI_MEETING_LOG" 2>/dev/null
# 以後の stdout/stderr を ai_meeting.log にも複製
exec > >(tee -a "$AI_MEETING_LOG") 2>&1

echo "=== 0.5. Phase 4: 競合サイト監視結果取り込み ==="
COMPETITOR_QUEUE=$(python3 - <<'PYCOMP'
import json
from pathlib import Path
q = []
p = Path("/home/aiuser/kpop-ai-system/logs/competitor_article_queue.jsonl")
if p.exists():
    for line in p.read_text(errors="replace").splitlines()[-10:]:
        try:
            r = json.loads(line.strip())
            if r.get("status") == "pending":
                q.append(r)
        except: pass
if q:
    print(f"【競合サイト対抗記事キュー {len(q)}件】")
    for item in q[:5]:
        print(f"  ■ [{item.get('source','')}] {item.get('competitor_title','')[:50]}")
        print(f"    提案: {item.get('suggested_angle','')[:60]}")
else:
    print("【競合対抗キュー】なし")
PYCOMP
)

echo "=== 1. 戦略会議（並列化v2） ==="

# Step 1a: バタフリーのトレンド収集（他3エージェントの入力になるため先行実行）
claude --dangerously-skip-permissions --agent butterfree -p "
あなたはトレンド責任者です。
今日のK-POPトレンドを5つ抽出してください。

出力形式：
【担当】butterfree
【結論】
【詳細】
【課題】
【提案】
【優先度】
" > "$REPORTS/butterfree_report.md"

# Step 1b: ラプラス・ミミッキュ・ジラーチを並列実行（全てバタフリーレポートを入力とする）
claude --dangerously-skip-permissions --agent lapras -p "
あなたはSEO責任者です。
以下のレポートを読み、検索流入の観点で評価してください。

$(cat "$REPORTS/butterfree_report.md")

出力形式：
【担当】lapras
【結論】
【詳細】
【課題】
【提案】
【優先度】
" > "$REPORTS/lapras_report.md" &
PID_LAPRAS=$!

claude --dangerously-skip-permissions --agent mimikyu -p "
あなたは競合分析責任者です。
以下を読み、競合上の弱点と勝ち筋を出してください。

$(cat "$REPORTS/butterfree_report.md")

出力形式：
【担当】mimikyu
【結論】
【詳細】
【課題】
【提案】
【優先度】
" > "$REPORTS/mimikyu_report.md" &
PID_MIMIKYU=$!

claude --dangerously-skip-permissions --agent jirachi_kpop -p "
あなたは未来予測責任者です。
以下を踏まえて、今後バズるテーマを予測してください。

$(cat "$REPORTS/butterfree_report.md")

出力形式：
【担当】jirachi
【結論】
【詳細】
【課題】
【提案】
【優先度】
" > "$REPORTS/jirachi_report.md" &
PID_JIRACHI=$!

wait $PID_LAPRAS  && echo "  ✓ lapras完了"  || echo "  ⚠ lapras失敗"
wait $PID_MIMIKYU && echo "  ✓ mimikyu完了" || echo "  ⚠ mimikyu失敗"
wait $PID_JIRACHI && echo "  ✓ jirachi完了" || echo "  ⚠ jirachi失敗"

echo "=== 1.5. 記事企画会議（各エージェントからアイデア提案・並列実行） ==="

# 直近3日の投稿タイトルを取得（重複回避用）
# 動的カテゴリ分布検出（偏り ≥40% のカテゴリを自動フラグ）
CATEGORY_BALANCE=$(category_balance_summary 3)

PLANNING_CONTEXT="
【今日の日付】$(date '+%Y年%m月%d日')

${CATEGORY_BALANCE}

【制約】
- 上記で ⚠偏り とマーキングされたカテゴリは1日1本まで
- 直近3日と同じテーマは提案禁止
- タイトル案は具体的なアーティスト名・数字・時事を含めること
"

# バタフリー：トレンド視点の記事アイデア（並列）
claude --dangerously-skip-permissions --agent butterfree -p "
あなたはトレンド責任者（バタフリー）です。
以下の状況を踏まえて、明日投稿すべき記事アイデアを提案してください。

${PLANNING_CONTEXT}

【トレンドレポート（自分の分析）】
$(cat "$REPORTS/butterfree_report.md")

出力形式：
【担当】butterfree
【記事アイデア提案】
  1. タイトル案：（具体的なタイトル）
     カテゴリ：（speed/beauty/travel/fashion/chart/解説/ゴシップのいずれか）
     根拠：（なぜ今このテーマか、1〜2行）
  2. タイトル案：（具体的なタイトル）
     カテゴリ：（同上）
     根拠：（1〜2行）
  3. タイトル案：（具体的なタイトル）
     カテゴリ：（同上）
     根拠：（1〜2行）
【カテゴリ偏りへの意見】（1〜2行、⚠フラグがあった場合のみ）
【優先度】高 / 中 / 低
" > "$REPORTS/planning_butterfree.md" &
PID_PL_BUTTERFREE=$!

# ラプラス：SEO視点の記事アイデア（並列）
claude --dangerously-skip-permissions --agent lapras -p "
あなたはSEO責任者（ラプラス）です。
以下の状況を踏まえて、SEO的に勝てる記事アイデアを提案してください。

${PLANNING_CONTEXT}

【SEOレポート（自分の分析）】
$(cat "$REPORTS/lapras_report.md")

出力形式：
【担当】lapras
【記事アイデア提案】
  1. タイトル案：（具体的なタイトル）
     カテゴリ：（speed/beauty/travel/fashion/chart/解説/ゴシップのいずれか）
     狙うキーワード：（メインKW）
     根拠：（検索ボリューム・競合状況、1〜2行）
  2. タイトル案：（具体的なタイトル）
     カテゴリ：（同上）
     狙うキーワード：（メインKW）
     根拠：（1〜2行）
  3. タイトル案：（具体的なタイトル）
     カテゴリ：（同上）
     狙うキーワード：（メインKW）
     根拠：（1〜2行）
【カテゴリ偏りへの意見】（SEO観点で1〜2行、⚠フラグ時のみ）
【優先度】高 / 中 / 低
" > "$REPORTS/planning_lapras.md" &
PID_PL_LAPRAS=$!

# ミミッキュ：競合差別化視点の記事アイデア（並列）
claude --dangerously-skip-permissions --agent mimikyu -p "
あなたは競合分析責任者（ミミッキュ）です。
競合サイトが書いていない、差別化できる記事アイデアを提案してください。

${PLANNING_CONTEXT}

【競合分析レポート（自分の分析）】
$(cat "$REPORTS/mimikyu_report.md")

出力形式：
【担当】mimikyu
【記事アイデア提案】
  1. タイトル案：（具体的なタイトル）
     カテゴリ：（speed/beauty/travel/fashion/chart/解説/ゴシップのいずれか）
     競合との差別化点：（1〜2行）
  2. タイトル案：（具体的なタイトル）
     カテゴリ：（同上）
     競合との差別化点：（1〜2行）
  3. タイトル案：（具体的なタイトル）
     カテゴリ：（同上）
     競合との差別化点：（1〜2行）
【カテゴリ偏りへの意見】（競合観点で1〜2行、⚠フラグ時のみ）
【優先度】高 / 中 / 低
" > "$REPORTS/planning_mimikyu.md" &
PID_PL_MIMIKYU=$!

# ジラーチ：未来予測視点の記事アイデア（並列）
claude --dangerously-skip-permissions --agent jirachi_kpop -p "
あなたは未来予測責任者（ジラーチ）です。
これから注目されるテーマを先読みした記事アイデアを提案してください。

${PLANNING_CONTEXT}

【未来予測レポート（自分の分析）】
$(cat "$REPORTS/jirachi_report.md")

出力形式：
【担当】jirachi
【記事アイデア提案】
  1. タイトル案：（具体的なタイトル）
     カテゴリ：（speed/beauty/travel/fashion/chart/解説/ゴシップのいずれか）
     先読み根拠：（なぜ近日中に注目されるか、1〜2行）
  2. タイトル案：（具体的なタイトル）
     カテゴリ：（同上）
     先読み根拠：（1〜2行）
  3. タイトル案：（具体的なタイトル）
     カテゴリ：（同上）
     先読み根拠：（1〜2行）
【カテゴリ偏りへの意見】（トレンド観点で1〜2行、⚠フラグ時のみ）
【優先度】高 / 中 / 低
" > "$REPORTS/planning_jirachi.md" &
PID_PL_JIRACHI=$!

# 4つの企画会議の完了を待機
wait $PID_PL_BUTTERFREE && echo "  ✓ planning_butterfree完了" || echo "  ⚠ planning_butterfree失敗"
wait $PID_PL_LAPRAS     && echo "  ✓ planning_lapras完了"     || echo "  ⚠ planning_lapras失敗"
wait $PID_PL_MIMIKYU    && echo "  ✓ planning_mimikyu完了"    || echo "  ⚠ planning_mimikyu失敗"
wait $PID_PL_JIRACHI    && echo "  ✓ planning_jirachi完了"    || echo "  ⚠ planning_jirachi失敗"

echo "=== 1.9. Phase 4: 本日KPI実績ブリーフ注入 ==="
KPI_EVENING_BRIEF=$(python3 "$REPO_BASE/lib/daily_kpi_injector.py" --evening-brief 2>/dev/null || echo "【本日KPIデータ】取得不可")
echo "  ✓ KPI夜会ブリーフ取得完了"

echo "=== 2. 編集長の意思決定 ==="

# --- 意思決定アーカイブ: 上書き前に前回を保全 ---
ARCHIVE_BASE="$BASE/reports/archive"
ARCHIVE_DATE=$(date '+%Y%m%d_%H%M%S')
ARCHIVE_DIR="$ARCHIVE_BASE/$ARCHIVE_DATE"
mkdir -p "$ARCHIVE_DIR"
for _arc_file in mewtwo_decision.md arceus_audit.md porygon_review.md; do
  [ -f "$REPORTS/$_arc_file" ] && cp "$REPORTS/$_arc_file" "$ARCHIVE_DIR/$_arc_file" 2>/dev/null || true
done
echo "  ✓ 前回意思決定をアーカイブ: $ARCHIVE_DIR"
# 30日超のアーカイブを自動削除（ディスク肥大防止）
find "$ARCHIVE_BASE" -maxdepth 1 -type d -mtime +30 -exec rm -rf {} + 2>/dev/null || true

RECENT_PIPELINE_STATUS=$(python3 - << 'PYPIPE'
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
base = Path("/home/aiuser/kpop-ai-system/logs")
kpi_path = base / "kpi_posts.jsonl"
today = now.strftime("%Y-%m-%d")
yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

# 直近投稿記事の確認
recent_posts = []
if kpi_path.exists():
    import json
    for line in kpi_path.read_text(errors="replace").splitlines()[-10:]:
        try:
            r = json.loads(line.strip())
            posted = r.get("published_at","")[:10]
            if posted in (today, yesterday):
                recent_posts.append(f"  [{posted}] {r.get('title','')[:40]} (CTR={r.get('ctr','?')}, X={r.get('x_post_status','?')})")
        except: pass

# x_failsafe状態
failsafe_active = False
failsafe_path = base / "x_failsafe.jsonl"
if failsafe_path.exists():
    lines = [l for l in failsafe_path.read_text(errors="replace").splitlines() if l.strip()]
    if lines:
        try:
            import json
            last = json.loads(lines[-1])
            if last.get("event") == "failsafe_triggered":
                failsafe_active = True
        except: pass

print(f"【直近48時間の投稿記事】")
print("\n".join(recent_posts) if recent_posts else "  データなし")
print(f"【X投稿フェイルセーフ】{'⛔ 発動中' if failsafe_active else '✅ 正常'}")
PYPIPE
)

claude --dangerously-skip-permissions --agent mewtwo -p "
あなたはミュウツー（CEO）です。
今日の各部門レポート・記事企画提案・直近の実績データを統合し、明日以降の方針を決定してください。
（注：記事テーマの最終決定は編集長デオキシスの権限。あなたはCEOとして戦略・投資・ジャンル方針を示す）

【トレンド情報（バタフリー）】
$(cat "$REPORTS/butterfree_report.md")

【SEO分析（ラプラス）】
$(cat "$REPORTS/lapras_report.md")

【競合分析（ミミッキュ）】
$(cat "$REPORTS/mimikyu_report.md")

【未来予測（ジラーチ）】
$(cat "$REPORTS/jirachi_report.md")

【記事企画提案（バタフリー）】
$(cat "$REPORTS/planning_butterfree.md")

【記事企画提案（ラプラス）】
$(cat "$REPORTS/planning_lapras.md")

【記事企画提案（ミミッキュ）】
$(cat "$REPORTS/planning_mimikyu.md")

【記事企画提案（ジラーチ）】
$(cat "$REPORTS/planning_jirachi.md")

【直近パイプライン・投稿状況】
${RECENT_PIPELINE_STATUS}

${KPI_EVENING_BRIEF}

【カテゴリバランス自動検出（動的）】
${CATEGORY_BALANCE}
⚠偏り フラグが付いたカテゴリがあれば、編集長として是正方針を示すこと。

${COMPETITOR_QUEUE}
※競合が先行報道したトピックがあれば、差別化しつつ対抗記事を優先検討せよ。

出力形式：
【担当】mewtwo
【今日の重要ポイントTOP3】（各1〜2行、数字根拠付き）
【明日書くべき記事 TOP5】
  ※各エージェントの企画提案を踏まえて編集長が厳選・決定すること
  1. タイトル案：（具体的なタイトル）
     カテゴリ：（speed/beauty/travel/fashion/chart/解説/ゴシップ）
     採用エージェント：（誰の提案か、または独自判断）
     採用理由：（1行）
  2. （同形式）
  3. （同形式）
  4. （同形式）
  5. （同形式）
【カテゴリ偏り対処方針】（⚠偏りフラグがあった場合のみ必須、なければ「偏りなし」）
  偏りカテゴリ：（どのカテゴリが偏ったか）
  原因分析：（なぜ多発したか）
  対処方針：（具体的な制限・ルール変更）
  今後の方針：（当該カテゴリ1日何本まで、どんなテーマならOKか）
【今やるべきアクション】（優先度HIGH/MED/LOW付き、具体的）
【やめること・削ること】（コスト削減・品質向上の観点）
【次に伸ばすジャンル】（旅行/美容/ファッション/速報/チャートから選択と根拠）
【異常検知】（パイプライン・投稿・収益面の問題、なければ「異常なし」）
【deoxysへの指示】（明日の速報記事テーマ・角度）
【metamonへの指示】（CTRリライト優先記事または改善方針）
【meowthへの指示】（注力すべき収益導線・ジャンル）
【porygon_zへの申し送り】（インフラ面の懸念・対応依頼）
" > "$REPORTS/mewtwo_decision.md"

echo "=== 3. 制作指示を分配 ==="

python3 - << 'PY'
from pathlib import Path
base = Path.home() / "ai_company" / "reports"
decision = (base / "mewtwo_decision.md").read_text()

def extract_section(text, header):
    lines = text.splitlines()
    out = []
    capture = False
    for line in lines:
        stripped = line.lstrip("#").strip()
        if stripped.startswith(header):
            capture = True
            continue
        if capture and stripped.startswith("【") and not stripped.startswith(header):
            break
        if capture:
            out.append(line)
    return "\n".join(out).strip()

(base / "deoxys_task.md").write_text(extract_section(decision, "【deoxysへの指示】"))
(base / "metamon_task.md").write_text(extract_section(decision, "【metamonへの指示】"))
(base / "meowth_task.md").write_text(extract_section(decision, "【meowthへの指示】"))
print("task files created")
PY

echo "=== 4. 制作部が実行 ==="

claude --dangerously-skip-permissions --agent deoxys_kpop -p "
あなたは速報記事担当です。
以下の編集長指示に従って記事を作成してください。

$(cat "$REPORTS/deoxys_task.md")

出力形式：
1行目：タイトル
2行目以降：HTML本文
" > "$REPORTS/deoxys_output.md"

claude --dangerously-skip-permissions --agent metamon_kpop -p "
あなたはCTR改善担当です。
以下の記事をCTR重視で改善してください。

編集長指示:
$(cat "$REPORTS/metamon_task.md")

記事:
$(cat "$REPORTS/deoxys_output.md")

出力形式：
1行目：タイトル
2行目以降：HTML本文
" > "$REPORTS/metamon_output.md"

claude --dangerously-skip-permissions --agent meowth -p "
あなたはニャース（収益化責任者）です。
以下の完成記事に最適な収益導線を設計してください。

【編集長指示】
$(cat "$REPORTS/meowth_task.md")

【完成記事（タイトル＋HTML本文）】
$(cat "$REPORTS/metamon_output.md" | head -c 3000)

【実行すること】
1. 記事ジャンルを判定する（美容/ファッション/旅行/グッズ/速報/チャート）
2. ジャンルに合う具体的なアフィリエイト・サービスを選定する（楽天/Amazon/じゃらん等）
3. CTA文言を2〜3個作成する（具体的な便益を示す文言のみ）
4. CTAを挿入すべき記事内の位置を指定する（どのH2見出しの後か）
5. 月間収益予測を出す（想定PV・RPM・CVRから計算）

出力形式：
【担当】meowth
【記事ジャンル】（美容/ファッション/旅行/グッズ/速報/チャートのいずれか）
【推奨アフィリエイト】
  1位: （サービス名）→（商品カテゴリ）→（CTA文言）→（配置位置）
  2位: （サービス名）→（商品カテゴリ）→（CTA文言）→（配置位置）
【AdSense最適化提案】（1〜2行）
【収益予測（月間）】
  想定PV: 〇〇
  想定RPM: 〇〇円
  想定収益: 〇〇円
【課題】（現在の収益上の課題）
【次回への改善提案】
" > "$REPORTS/meowth_output.md"

echo "=== 5. SRE部がインフラ監査 ==="

# watchdogログ・修復ログを収集してポリゴンZに渡す
WATCHDOG_SUMMARY=$(python3 - << 'PYEOF'
import json, sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
since = now - timedelta(hours=24)

base = Path("/home/aiuser/kpop-ai-system/logs")

def read_jsonl_since(path, since):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
            ts_str = r.get("ts", r.get("timestamp", ""))
            try:
                ts = datetime.fromisoformat(ts_str).astimezone(JST)
            except Exception:
                try:
                    ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
                except Exception:
                    continue
            if ts >= since:
                rows.append(r)
        except Exception:
            pass
    return rows

alerts  = read_jsonl_since(base / "watchdog_alerts.jsonl", since)
repairs = read_jsonl_since(base / "watchdog_repairs.jsonl", since)
watchdog_log = base / "watchdog.log"
last_watchdog = "不明"
if watchdog_log.exists():
    lines = [l for l in watchdog_log.read_text(errors="replace").splitlines() if "監査開始" in l]
    if lines:
        last_watchdog = lines[-1].replace("[watchdog] 監査開始 ", "").strip()

# パイプラインログ稼働状況
import os
today = now.strftime("%Y-%m-%d")
PIPELINE_LOGS = [
    (Path("/home/aiuser/ai_kpop.log"), "速報(07:00)"),
    (base / "beauty_pipeline.log", "美容(11:00)"),
    (base / "strategy_pipeline.log", "戦略(12:00)"),
    (base / "lifestyle_pipeline.log", "ライフスタイル(15:00)"),
    (base / "fashion_pipeline.log", "ファッション(18:00)"),
    (base / "morning_brief.log", "モーニングブリーフ(09:00)"),
    (base / "ai_meeting.log", "AI会議(21:00)"),
]
pipeline_status = []
for log_path, label in PIPELINE_LOGS:
    if not log_path.exists():
        pipeline_status.append(f"  {label}: ❌ ログなし")
    else:
        mtime = datetime.fromtimestamp(os.path.getmtime(log_path), tz=JST)
        if mtime.strftime("%Y-%m-%d") == today:
            pipeline_status.append(f"  {label}: ✅ {mtime.strftime('%H:%M')}更新")
        else:
            pipeline_status.append(f"  {label}: ⚠ 前回={mtime.strftime('%m/%d %H:%M')}")

print("【watchdog最終実行】", last_watchdog)
print("【パイプライン稼働状況（直近）】")
print("\n".join(pipeline_status))
print(f"【自動修復（24h）】{len(repairs)}件")
for r in repairs[:3]:
    print(f"  🔧 {r.get('action','')} : {r.get('message','')[:80]}")
print(f"【未解決アラート（24h）】{len(alerts)}件")
for r in alerts[:3]:
    print(f"  🚨 {r.get('check','')} : {r.get('message','')[:80]}")
PYEOF
)

claude --dangerously-skip-permissions --agent porygon_z -p "
あなたはSRE責任者（ポリゴンZ）です。
以下のインフラデータを読み、SRE日次レポートを出力してください。

【インフラデータ】
${WATCHDOG_SUMMARY}

【編集長の本日判断】
$(cat "$REPORTS/mewtwo_decision.md" 2>/dev/null | head -50)

出力形式：
【担当】porygon_z
【インフラ稼働サマリー】（パイプライン別 ✅/❌）
【自動修復実績】（件数と内容）
【未解決問題】（あれば根本原因と再発防止策）
【X投稿状態】
【明日への申し送り】
" > "$REPORTS/porygon_z_sre.md"

echo "=== 6. アルセウスによる品質最終監査 ==="

claude --dangerously-skip-permissions --agent arceus -p "
あなたはアルセウス（AI総監督・最終承認者）です。
本日のAI日次会議の全出力を監査し、採点・評価してください。

【CEO戦略判断（ミュウツー）】
$(cat "$REPORTS/mewtwo_decision.md" | head -c 2000)

【速報記事（デオキシス）】
$(cat "$REPORTS/deoxys_output.md" | head -c 1000)

【CTR改善後記事（メタモン）】
$(cat "$REPORTS/metamon_output.md" | head -c 1000)

【収益導線（ニャース）】
$(cat "$REPORTS/meowth_output.md" | head -c 800)

【SREレポート（ポリゴンZ）】
$(cat "$REPORTS/porygon_z_sre.md" | head -c 600)

評価対象と採点基準：
- ミュウツー：方針の具体性・根拠の明確さ、カテゴリ偏り対処方針の妥当性（/20点）
- デオキシス：記事タイトルの有効性・HTML品質（/20点）
- メタモン：CTR改善の適切さ（/20点）
- ニャース：収益導線の現実性・具体性（/20点）
- ポリゴンZ：インフラ状態の正確な把握（/20点）

出力形式：
【担当】arceus
【総合評価】（〇〇点/100点）
【各エージェント採点】
  ミュウツー：〇〇/20 - （理由1行）
  デオキシス：〇〇/20 - （理由1行）
  メタモン：〇〇/20 - （理由1行）
  ニャース：〇〇/20 - （理由1行）
  ポリゴンZ：〇〇/20 - （理由1行）
【記事企画評価】
  最も有望な提案：（タイトル案と採用理由）
  却下すべき提案：（理由付き）
  カテゴリ偏り対処の妥当性：（✅/⚠️/❌と理由1行、偏りなしなら「該当なし」）
【本日の最重要問題点】（具体的に1〜3件）
【明日への改善指示】（各エージェントへの具体的な改善命令）
【投稿判定】（本日制作記事の投稿 ✅可 / ⚠要修正 / ❌停止）
" > "$REPORTS/arceus_audit.md"

echo "=== 7. 分析部が振り返り ==="

WEEKLY_WINS=$(python3 - << 'PYWINS'
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
perf = Path("/home/aiuser/kpop-ai-system/logs/title_performance.jsonl")
if not perf.exists():
    print("パフォーマンスデータなし")
else:
    since = now - timedelta(days=7)
    wins = losses = 0
    for line in perf.read_text(errors="replace").splitlines():
        try:
            r = json.loads(line.strip())
            result = r.get("result","")
            if result == "win": wins += 1
            elif result == "lose": losses += 1
        except: pass
    total = wins + losses
    winrate = f"{wins/total*100:.0f}%" if total > 0 else "N/A"
    print(f"直近7日: win={wins}, lose={losses}, 勝率={winrate}")
PYWINS
)

claude --dangerously-skip-permissions --agent porygon -p "
あなたはポリゴン（データ分析責任者）です。
本日のAI会議結果とパフォーマンスデータを分析し、改善優先度を決定してください。

【編集長判断サマリー】
$(cat "$REPORTS/mewtwo_decision.md" | head -c 1500)

【アルセウス品質監査結果】
$(cat "$REPORTS/arceus_audit.md" | head -c 1000)

【ニャース収益レポート】
$(cat "$REPORTS/meowth_output.md" | head -c 600)

【直近7日パフォーマンス】
${WEEKLY_WINS}

実行すること：
1. 今週のパイプライン品質トレンドを数字で評価する
2. 収益に最も貢献しているジャンル・エージェントを特定する
3. ボトルネック（品質問題・コスト問題・稼働問題）TOP3を特定する
4. ルギアへの週次戦略インプットを準備する

出力形式：
【担当】porygon
【今週のパフォーマンスサマリー】（数字ベース）
【ジャンル別収益貢献度】（高/中/低で評価）
【ボトルネックTOP3】（根拠付き）
【ルギアへの戦略インプット】（来週の方針変更提案）
【優先度】高 / 中 / 低
" > "$REPORTS/porygon_review.md"

echo "✅ AI会社会議 完了"
echo "保存先: $REPORTS"

# Discord送信（#daily-ceo-report チャネル）
MEETING_SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$MEETING_SCRIPT_DIR/lib/discord_channels.sh" 2>/dev/null || true
MEETING_WEBHOOK=$(get_discord_webhook "daily_ceo_report" 2>/dev/null || echo "")
[ -z "$MEETING_WEBHOOK" ] && MEETING_WEBHOOK="${DISCORD_WEBHOOK:-}"
if [ -z "$MEETING_WEBHOOK" ] && [ -f ~/.kpop_discord_webhook ]; then
  MEETING_WEBHOOK=$(cat ~/.kpop_discord_webhook | tr -d '[:space:]')
fi

if [ -n "$MEETING_WEBHOOK" ]; then
  SUMMARY="🏢 AI日次運営会議 完了 ($(date '+%Y-%m-%d %H:%M'))"

  # アルセウス監査スコア取得
  ARCEUS_SCORE=""
  if [ -f "$REPORTS/arceus_audit.md" ]; then
    ARCEUS_SCORE=$(grep -o '【総合評価】.*' "$REPORTS/arceus_audit.md" | head -1 || echo "")
    ARCEUS_VERDICT=$(grep -o '【投稿判定】.*' "$REPORTS/arceus_audit.md" | head -1 || echo "")
    ARCEUS_SECTION="${ARCEUS_SCORE} ${ARCEUS_VERDICT}"
  fi

  # SREレポートを先頭に
  SRE_SECTION=""
  if [ -f "$REPORTS/porygon_z_sre.md" ]; then
    SRE_SECTION=$(grep -A1 '【インフラ稼働サマリー】\|【未解決問題】' "$REPORTS/porygon_z_sre.md" | head -10 | tr '\n' ' ' | cut -c1-400)
  fi

  # 分析レポート（ボトルネックのみ）
  REVIEW=""
  if [ -f "$REPORTS/porygon_review.md" ]; then
    REVIEW=$(grep -A5 '【ボトルネック' "$REPORTS/porygon_review.md" | head -8 | tr '\n' ' ' | cut -c1-400)
  fi

  # mewtwoの明日テーマ（TOP5記事アイデア）
  TMRW=""
  if [ -f "$REPORTS/mewtwo_decision.md" ]; then
    TMRW=$(grep -A20 '【明日書くべき記事 TOP5】' "$REPORTS/mewtwo_decision.md" | head -22 | tr '\n' ' ' | cut -c1-500)
  fi

  # カテゴリ偏り対処方針（動的検出）
  BEAUTY_POLICY=""
  if [ -f "$REPORTS/mewtwo_decision.md" ]; then
    BEAUTY_POLICY=$(grep -A5 '【カテゴリ偏り対処方針】' "$REPORTS/mewtwo_decision.md" | head -6 | tr '\n' ' ' | cut -c1-300)
  fi

  MSG="${SUMMARY}"
  [ -n "$ARCEUS_SECTION" ]  && MSG="${MSG}"$'\n\n'"⚖️ 監査: ${ARCEUS_SECTION}"
  [ -n "$TMRW" ]            && MSG="${MSG}"$'\n\n'"📝 明日の記事TOP5: ${TMRW}"
  [ -n "$BEAUTY_POLICY" ]   && MSG="${MSG}"$'\n\n'"📋 カテゴリ偏り対処: ${BEAUTY_POLICY}"
  [ -n "$SRE_SECTION" ]     && MSG="${MSG}"$'\n\n'"🛡️ SRE: ${SRE_SECTION}"
  [ -n "$REVIEW" ]          && MSG="${MSG}"$'\n\n'"📊 課題: ${REVIEW}"

  curl -s -o /dev/null -X POST "$MEETING_WEBHOOK" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "import json,sys; print(json.dumps({'content': sys.argv[1][:1950]}))" "$MSG")" 2>/dev/null
  echo "✅ Discord送信完了"
fi
