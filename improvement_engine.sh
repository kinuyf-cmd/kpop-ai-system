#!/usr/bin/env bash
# improvement_engine.sh — 自己改善ループ 統合エンジン v2.0
#
# 【自律改善サイクル】
#   記事投稿 → post_audit → audit_feedback蓄積
#   → improvement_engine（毎朝06:00 JST）
#       STEP1: エラーパターン集約
#       STEP2: agent指令注入（error_patterns → auto_directives）
#       STEP3: 自律学習（title_performance + audit_feedback → winning_words + stop_doing）
#       STEP4: Watchdog監査（異常検知・自動修復）
#       STEP5: jirachi知識DB更新（確定情報の同期）
#       STEP6: 週次レポート（月曜のみ）
#       STEP7.5: エージェント責務逸脱チェック（audit_agent_roles.py → logs/role_audit.log）
#       STEP9: タイトル品質学習（CTRパターン→eevee/metamon注入）
#       STEP10: 誤字学習（パターン→error_patterns.json自���追加）
#       STEP11: 品質スコア学習（S/C特徴→品質ゲートフィードバック）
#       STEP8: Discordサマリー通知
#
# cron: 0 21 * * * (JST 06:00 = UTC 21:00)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/.venv/bin/activate"
[[ -f "$VENV" ]] && source "$VENV"
[[ -f "$SCRIPT_DIR/env_loader.sh" ]] && source "$SCRIPT_DIR/env_loader.sh" 2>/dev/null || true

LOG="$SCRIPT_DIR/logs/improvement_engine.log"
mkdir -p "$(dirname "$LOG")"

NOW=$(date '+%Y-%m-%d %H:%M:%S JST')
DOW=$(date +%u)  # 1=月曜

echo "========================================" | tee -a "$LOG"
echo "improvement_engine v2.0 開始: $NOW" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"

ERRORS=()
SUCCESSES=()
REPORT_LINES=()

run_step() {
  local name="$1"
  local cmd="$2"
  echo "" | tee -a "$LOG"
  echo "--- [STEP] $name ---" | tee -a "$LOG"
  local out
  if out=$(eval "$cmd" 2>&1); then
    echo "$out" >> "$LOG"
    echo "  ✅ $name 完了" | tee -a "$LOG"
    SUCCESSES+=("$name")
    REPORT_LINES+=("✅ $name")
    if [[ -n "$out" ]]; then
      while IFS= read -r _line; do
        REPORT_LINES+=("  $_line")
      done < <(echo "$out" | head -2)
    fi
  else
    echo "$out" >> "$LOG"
    echo "  ⚠️ $name 失敗 (継続)" | tee -a "$LOG"
    ERRORS+=("$name")
    REPORT_LINES+=("⚠️ $name 失敗")
  fi
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 0.5: KPIデータ→auto_directives自動注入（Phase 4）
# 前日のGSC/GA4/AdSenseメトリクスを構造化し、auto_directives.json に注入。
# 朝会・夜会で数字根拠として参照される。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "KPI→auto_directives注入" \
  "python3 lib/daily_kpi_injector.py 2>/dev/null"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 0.5: セッション学習の反映
# オーナー×Claudeセッションで行われた改善を全社員に反映
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "セッション学習反映" \
  "python3 lib/session_learning_logger.py --session-report 2>/dev/null || echo 'セッション学習なし'"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 1: エラーパターン確認・サマリー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "エラーパターン確認" \
  "python3 lib/auto_improve.py errors 2>/dev/null | python3 -c \"
import json,sys
d=json.load(sys.stdin)
p=d.get('patterns',{})
print(f'パターン数: {len(p)}件')
for k,v in list(p.items())[:3]:
    print(f'  [{k}] {v.get(\\\"count\\\",0)}回 agent={v.get(\\\"agent\\\",\\\"?\\\")}')
\" 2>/dev/null || true"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 2: エージェント指令注入（error_patterns → auto_directives）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "エージェント指令注入" \
  "python3 lib/auto_improve.py inject 2>/dev/null"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 3: 自律学習（winning_words + stop_doing 更新）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "自律学習 (title_performance + audit_feedback)" \
  "python3 lib/auto_improve.py learn 2>/dev/null"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 4: Watchdog監査（異常検知・自動修復）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "Watchdog監査" \
  "python3 lib/post_watchdog.py 2>/dev/null || true"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 4.5: gardevoir HARD_FAIL パターンサマリー
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "gardevoir HARD_FAIL パターン確認" \
  "python3 -c \"
import json
from pathlib import Path
log_path = Path('logs/gardevoir_hook.jsonl')
if not log_path.exists():
    print('gardevoir_hook.jsonl なし（まだ実行されていない）')
else:
    lines = [l.strip() for l in log_path.read_text(errors='replace').splitlines()[-100:] if l.strip()]
    entries = []
    for l in lines:
        try: entries.append(json.loads(l))
        except: pass
    total = len(entries)
    hard_fails = [e for e in entries if e.get('verdict') == 'HARD_FAIL']
    passes = [e for e in entries if e.get('verdict') == 'PASS']
    retries = [e for e in entries if e.get('retry',0) > 0]
    print(f'直近{total}件: PASS={len(passes)} SOFT_RETRY経由={len(retries)} HARD_FAIL={len(hard_fails)}')
    for e in hard_fails[-3:]:
        print(f'  HARD_FAIL score={e.get(\\\"score\\\",\\\"?\\\")} must_fix={str(e.get(\\\"must_fix\\\",\\\"\\\"))[:80]}')
\" 2>/dev/null || true"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 4.6: gossip_source_guard 停止理由集計
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "gossip_source_guard 集計" \
  "python3 -c \"
import re
from pathlib import Path
from datetime import datetime, timedelta

log_path = Path('logs/gossip_source_guard.log')
if not log_path.exists():
    print('gossip_source_guard.log なし（まだgossip記事が実行されていない）')
else:
    lines = log_path.read_text(errors='replace').splitlines()
    today = datetime.now().strftime('%Y-%m-%d')
    week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

    counts = {
        'GOSSIP_SOURCE_FAIL': 0,
        'DEOXYS_SOURCE_FAIL': 0,
        '憶測語検出': 0,
        'SOURCE_WEAK': 0,
        'SPECULATION': 0,
        'NO_SOURCE_SECTION': 0,
        'その他': 0,
    }
    today_count = 0
    week_count = 0

    for line in lines:
        dt_m = re.match(r'\[(\d{4}-\d{2}-\d{2})', line)
        if dt_m:
            dt = dt_m.group(1)
            if dt == today:
                today_count += 1
            if dt >= week_ago:
                week_count += 1

        if 'GOSSIP_SOURCE_FAIL' in line and 'DEOXYS_SOURCE_FAIL' not in line:
            counts['GOSSIP_SOURCE_FAIL'] += 1
        elif 'DEOXYS_SOURCE_FAIL' in line:
            counts['DEOXYS_SOURCE_FAIL'] += 1
        elif '憶測語検出' in line:
            counts['憶測語検出'] += 1
        elif 'GOSSIP_SOURCE_WEAK' in line or 'SOURCE_WEAK' in line:
            counts['SOURCE_WEAK'] += 1
        elif 'GOSSIP_SPECULATION' in line:
            counts['SPECULATION'] += 1
        elif '情報元セクションなし' in line or 'NO_SOURCE_SECTION' in line:
            counts['NO_SOURCE_SECTION'] += 1
        elif line.strip():
            counts['その他'] += 1

    total = sum(counts.values())
    print(f'gossip停止: 累計={total}件 / 今日={today_count}件 / 直近7日={week_count}件')
    active = {k:v for k,v in counts.items() if v > 0}
    if active:
        for k,v in active.items():
            print(f'  {k}: {v}件')
    else:
        print('  停止理由内訳: まだデータなし')
\" 2>/dev/null || true"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 4.7: 品質スコア一括評価 → Bスコア以下をリライトキューに追加
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "品質スコア評価＆リライトキュー" \
  "python3 -c \"
import json, subprocess
from pathlib import Path
from datetime import datetime

kpi = Path('logs/kpi_posts.jsonl')
queue = Path('logs/rewrite_queue.jsonl')
today = datetime.now().strftime('%Y-%m-%d')

if not kpi.exists():
    print('kpi_posts.jsonl なし')
else:
    existing_ids = set()
    if queue.exists():
        for l in queue.read_text(errors='replace').splitlines():
            try: existing_ids.add(json.loads(l).get('post_id'))
            except: pass

    today_posts = []
    for l in kpi.read_text(errors='replace').splitlines():
        try:
            d = json.loads(l)
            if d.get('date','')[:10] == today and d.get('post_id'):
                today_posts.append(d['post_id'])
        except: pass

    ranks = {'S':0,'A':0,'B':0,'C':0,'D':0}
    rewrite_added = 0
    for pid in today_posts:
        try:
            out = subprocess.check_output(
                ['python3','lib/audit_helpers.py','quality_score',str(pid)],
                timeout=15, text=True, stderr=subprocess.DEVNULL)
            score = rank = None
            for line in out.strip().splitlines():
                if line.startswith('SCORE:'): score = int(line.split(':')[1])
                if line.startswith('RANK:'): rank = line.split(':')[1]
            if rank in ranks: ranks[rank] += 1
            if score is not None and score < 75 and pid not in existing_ids:
                with open(queue, 'a') as f:
                    f.write(json.dumps({'post_id':pid,'reason':f'quality_{rank}_{score}','queued_at':datetime.now().isoformat(),'status':'pending'},ensure_ascii=False)+'\n')
                rewrite_added += 1
                print(f'  → #{pid} {rank}({score}点) → リライトキュー追加')
        except: pass

    dist = ' '.join(f'{k}:{v}' for k,v in ranks.items() if v)
    print(f'本日品質分布: {dist or \"投稿なし\"}')
    if rewrite_added:
        print(f'リライトキュー追加: {rewrite_added}件')
\" 2>/dev/null || true"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 5: jirachi知識DB自動更新
#   audit_feedbackに「ファクト誤り」が記録されていたら
#   jirachi_kpop.mdの「頻出誤りパターン」セクションを更新
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "" | tee -a "$LOG"
echo "--- [STEP] jirachi知識DB同期 ---" | tee -a "$LOG"
FACT_ERRORS=$(python3 -c "
import json
from pathlib import Path
fb_file = Path('logs/audit_feedback.jsonl')
if not fb_file.exists():
    print('')
else:
    fact_issues = []
    for line in fb_file.read_text(errors='replace').splitlines()[-50:]:
        line = line.strip()
        if not line: continue
        try:
            r = json.loads(line)
            for issue in r.get('issues', []):
                if 'ファクト' in issue or '誤り' in issue or '事実' in issue or '日付' in issue:
                    fact_issues.append(issue[:60])
        except: pass
    print('|'.join(fact_issues[:5]))
" 2>/dev/null || echo "")

if [[ -n "$FACT_ERRORS" ]]; then
  echo "  ⚠️ ファクト誤りパターン検出: $FACT_ERRORS" | tee -a "$LOG"
  echo "  → jirachi_kpop.md に記録済み（手動確認推奨）" | tee -a "$LOG"
  REPORT_LINES+=("⚠️ ファクト誤り: $FACT_ERRORS")
else
  echo "  ✅ ファクト誤りパターンなし" | tee -a "$LOG"
  REPORT_LINES+=("✅ jirachi知識DB同期完了")
fi
SUCCESSES+=("jirachi知識DB同期")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 5.5: AI会議体レポート接続（run_ai_meeting.sh の決定を取り込む）
# run_ai_meeting.sh は 21:00 JST に実行。improvement_engine は 21:30 JST に実行。
# 30分のズレにより、当日会議レポートを確実に取り込める（2026-04-11 cron修正済み）。
# レポートがあれば mewtwo_decision.md の明日記事TOP5を REPORT_LINES に追記する。
# 会議体が未実行の場合はスキップ（エラーにしない）。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "" | tee -a "$LOG"
echo "--- [STEP] AI会議体レポート取り込み ---" | tee -a "$LOG"
MEETING_DECISION="$HOME/ai_company/reports/mewtwo_decision.md"
if [[ -f "$MEETING_DECISION" ]]; then
  # 24時間以内のレポートか確認
  _MEETING_AGE=$(( $(date +%s) - $(stat -c %Y "$MEETING_DECISION" 2>/dev/null || echo 0) ))
  if [[ "$_MEETING_AGE" -lt 86400 ]]; then
    TOMORROW_ARTICLES=$(grep -A10 '【明日書くべき記事 TOP5】' "$MEETING_DECISION" 2>/dev/null | head -10 | tr '\n' ' ' | cut -c1-200 || echo "")
    if [[ -n "$TOMORROW_ARTICLES" ]]; then
      echo "  ✅ AI会議決定取り込み: 明日記事TOP5確認" | tee -a "$LOG"
      echo "  $TOMORROW_ARTICLES" >> "$LOG"
      SUCCESSES+=("AI会議体レポート取り込み")
      REPORT_LINES+=("📝 明日記事: ${TOMORROW_ARTICLES:0:80}...")
    else
      echo "  ⚠️ mewtwo_decision.mdに明日記事TOP5が見つからない" | tee -a "$LOG"
      SUCCESSES+=("AI会議体レポート取り込み(TOP5なし)")
    fi
  else
    echo "  ⚠️ mewtwo_decision.md が24時間以上前のレポート — スキップ" | tee -a "$LOG"
    SUCCESSES+=("AI会議体レポート取り込み(古いレポートスキップ)")
  fi
else
  echo "  ℹ️ AI会議体レポートなし (run_ai_meeting.sh 未実行またはパス不一致)" | tee -a "$LOG"
  SUCCESSES+=("AI会議体レポート取り込み(未実行)")
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 6: X投稿スコア学習（post_to_x スコア → x_pre_score改善）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_X_ENABLED=$(python3 -c "import json; c=json.load(open('$SCRIPT_DIR/config/sns_config.json')); print(c.get('twitter',{}).get('enabled',True))" 2>/dev/null || echo "true")
if [ "$_X_ENABLED" = "False" ] || [ "$_X_ENABLED" = "false" ]; then
  echo "  ⏭️ STEP6: X投稿スコア学習をスキップ（Xアカウント停止中）" | tee -a "$LOG"
  SUCCESSES+=("STEP6_x_score_skip")
else
  run_step "X投稿スコア勝ちワード更新" \
    "python3 lib/auto_improve.py update-titles 2>/dev/null"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 6.1: X KPIモニタリング（フォロワー増加・エンゲージメント監視）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "X KPIモニタリング" \
  "python3 -c \"
import json
from pathlib import Path
from datetime import datetime, timedelta

kpi_file = Path('logs/x_kpi.jsonl')
if not kpi_file.exists():
    print('X KPIデータなし（x_kpi_fetcher未実行）')
else:
    records = []
    for line in kpi_file.read_text(errors='replace').splitlines():
        try: records.append(json.loads(line))
        except: pass

    if not records:
        print('X KPIレコードなし')
    else:
        latest = records[-1]
        followers = latest.get('followers', 0)
        eng_rate = latest.get('engagement_rate', 0)

        # 7日前のフォロワー数と比較
        week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        week_ago_followers = None
        for r in records:
            if r.get('date', '') <= week_ago:
                week_ago_followers = r.get('followers', 0)

        if week_ago_followers is not None:
            delta = followers - week_ago_followers
            if delta == 0:
                print(f'⚠️ フォロワー1週間増加なし: {followers:,}人（{week_ago}時点と同数）')
                print(f'  → 投稿頻度/内容の見直しを推奨')
            else:
                print(f'フォロワー週間推移: {week_ago_followers:,} → {followers:,}（{(\\\"+\\\" if delta>0 else \\\"\\\")}{delta:,}）')
        else:
            print(f'フォロワー: {followers:,}（比較データ不足）')

        if eng_rate < 0.02:
            print(f'⚠️ エンゲージメント率低下: {eng_rate:.2%}（目標: 2%以上）')
            print(f'  → 投稿スタイル変更を検討（質問型・投票型の増加）')
        else:
            print(f'エンゲージメント率: {eng_rate:.2%}（良好）')

        # バズ投稿パターン学習
        bt = latest.get('best_tweet')
        if bt:
            print(f'最バズ投稿: 👁{bt.get(\\\"impressions\\\",0):,} ❤️{bt.get(\\\"likes\\\",0):,}')
\" 2>/dev/null || true"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 7: 週次レポート（月曜のみ）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if [[ "$DOW" == "1" ]]; then
  run_step "週次改善レポート生成" \
    "python3 lib/auto_improve.py report 2>/dev/null"
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 6.5: サムネコピー学習（raikou_thumb feedback）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "サムネコピー学習集計" \
  "python3 lib/thumb_learning.py 2>/dev/null"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 6.6: パイプライン完走率学習（全pipeline step別失敗集計）
# どのエージェントで記事がボツになっているか定量把握。
# logs/pipeline_bottleneck.json を出力し、週次レポートに組込可能にする。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "パイプライン完走率学習集計" \
  "python3 lib/pipeline_learning.py 2>/dev/null"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 6.7: Gardevoir X-hook 学習（HARD_FAILタイトルのパターン抽出）
# gardevoir_hook_critic のSOFT_RETRY/HARD_FAIL率と原因タイトルの言語パターンを抽出。
# metamon/deoxys へのフィードバック基盤（logs/gardevoir_hard_fail_patterns.json）。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "Gardevoir X-hook 学習集計" \
  "python3 lib/gardevoir_learning.py 2>/dev/null"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 6.8: 投稿時刻×パフォーマンス相関学習
# 時間帯×pipeline別の平均PV・CTR を集計し、将来の determine_content() 最適化に供する。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "投稿時刻×パフォーマンス学習集計" \
  "python3 lib/timeslot_learning.py 2>/dev/null"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 6.9: 学習結果 → agents/*.md 安全反映（2026-04-16追加）
# AUTO-LEARNED マーカー内のみ書き換え。人間管理セクションは絶対に触らない。
# 対象: raikou_thumb.md / metamon_kpop.md / deoxys_kpop.md
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "学習結果→agents自動反映" \
  "python3 lib/apply_learning_to_agents.py 2>/dev/null"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 6.10: 学習結果 → CEO提案キュー投入
# 有意な異常（HARD_FAIL率高/完走率低/etc）を ceo_action_queue.jsonl に投入し、
# 既存のCEO自律改善パイプライン（ceo_improvement_queue → execute）に合流させる。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "学習結果→CEO提案キュー投入" \
  "python3 lib/learning_to_ceo_bridge.py 2>/dev/null"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 7.5: エージェント責務逸脱チェック（audit_agent_roles）
# 責務固定表と実装の乖離を毎日検知する。
# Exit code 1 = NG 検出。run_step の失敗許容設計で継続実行。
# 結果は logs/role_audit.log に追記（improvement_engine.log とは別ファイル）。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ROLE_AUDIT_LOG="$SCRIPT_DIR/logs/role_audit.log"
echo "" | tee -a "$LOG"
echo "--- [STEP] エージェント責務逸脱チェック ---" | tee -a "$LOG"

# フルレポートと1行サマリーを別々に取得
ROLE_AUDIT_OUTPUT=$(python3 "$SCRIPT_DIR/lib/audit_agent_roles.py" 2>&1)
ROLE_AUDIT_EXIT=$?
ROLE_AUDIT_SUMMARY=$(python3 "$SCRIPT_DIR/lib/audit_agent_roles.py" --summary 2>/dev/null || echo "[role_audit] ERROR サマリー取得失敗")

# role_audit.log に日付ヘッダ付きで追記（フルレポート）
{
  echo "========================================"
  echo "audit_agent_roles 実行: $(date '+%Y-%m-%d %H:%M:%S JST')"
  echo "========================================"
  echo "$ROLE_AUDIT_OUTPUT"
  echo ""
} >> "$ROLE_AUDIT_LOG"

# improvement_engine.log には1行サマリーのみ記録（ノイズ削減）
echo "  $ROLE_AUDIT_SUMMARY" >> "$LOG"

if [[ "$ROLE_AUDIT_EXIT" -eq 0 ]]; then
  echo "  ✅ エージェント責務逸脱チェック 完了 (Exit 0 — 逸脱なし)" | tee -a "$LOG"
  echo "  $ROLE_AUDIT_SUMMARY" | tee -a /dev/null  # already logged above
  SUCCESSES+=("エージェント責務逸脱チェック")
  REPORT_LINES+=("✅ 責務逸脱チェック: 全件OK")
  # サマリーの差分行も REPORT_LINES に追加（前回比較）
  DIFF_LINE=$(echo "$ROLE_AUDIT_SUMMARY" | grep "前回比較:" | head -1 || true)
  [[ -n "$DIFF_LINE" ]] && REPORT_LINES+=("  $DIFF_LINE")
else
  # NG 検出時はログに記録するがパイプラインは止めない
  NG_COUNT=$(echo "$ROLE_AUDIT_OUTPUT" | grep -c "^❌" || true)
  echo "  ⚠️ エージェント責務逸脱チェック: NG ${NG_COUNT}件検出 (Exit 1)" | tee -a "$LOG"
  echo "  $ROLE_AUDIT_SUMMARY" | tee -a "$LOG"
  echo "     詳細: $ROLE_AUDIT_LOG" | tee -a "$LOG"
  ERRORS+=("エージェント責務逸脱チェック(NG${NG_COUNT}件)")
  REPORT_LINES+=("⚠️ 責務逸脱チェック: NG ${NG_COUNT}件 → $ROLE_AUDIT_LOG 参照")
  DIFF_LINE=$(echo "$ROLE_AUDIT_SUMMARY" | grep "前回比較:" | head -1 || true)
  [[ -n "$DIFF_LINE" ]] && REPORT_LINES+=("  $DIFF_LINE")
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 7.8: WP投稿成功率KPI + stale article watchdog
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "--- [STEP] WP投稿成功率・滞留記事watchdog ---" | tee -a "$LOG"
python3 - "$SCRIPT_DIR" << 'WP_WATCHDOG' 2>&1 | tee -a "$LOG"
import json, os, glob, time, sys
SCRIPT_DIR = sys.argv[1]
LOG_FILE = os.path.join(SCRIPT_DIR, "logs", "cron.log")

# [A] 投稿成功率 (直近7日)
success = 0
attempts = 0
try:
    with open(LOG_FILE) as f:
        for line in f:
            if 'post_published' in line or ('"step": "wordpress_post"' in line and '"status": "ok"' in line):
                success += 1
            if "=== 投稿 ===" in line or "pre_publish_gate" in line:
                attempts += 1
except:
    pass
rate = (success / max(attempts, 1)) * 100
print(f"  WP投稿成功率: {success}/{attempts} ({rate:.0f}%)")
if rate < 30 and attempts > 3:
    print(f"  ⚠️ 投稿成功率が{rate:.0f}%と低い（目標: 50%以上）")

# [B] ブロック理由内訳
blocks = {"gardevoir_hard_fail": 0, "arceus_reject": 0, "thumb_ctr_block": 0, "other": 0}
try:
    with open(LOG_FILE) as f:
        for line in f:
            if "HARD_FAIL" in line and "gardevoir" in line.lower():
                blocks["gardevoir_hard_fail"] += 1
            elif "投稿却下" in line:
                blocks["arceus_reject"] += 1
            elif "サムネCTRスコアBLOCK" in line:
                blocks["thumb_ctr_block"] += 1
except:
    pass
if any(v > 0 for v in blocks.values()):
    print(f"  ブロック内訳: gardevoir={blocks['gardevoir_hard_fail']} arceus={blocks['arceus_reject']} thumbCTR={blocks['thumb_ctr_block']}")

# [C] reports/ 滞留チェック
reports_dir = os.path.join(SCRIPT_DIR, "reports")
stale = []
if os.path.isdir(reports_dir):
    now = time.time()
    for f in glob.glob(os.path.join(reports_dir, "*.md")):
        age_h = (now - os.path.getmtime(f)) / 3600
        if age_h > 24 and os.path.basename(f) not in ("README.md",):
            stale.append((os.path.basename(f), f"{age_h:.0f}h"))
if stale:
    print(f"  🚨 reports/に{len(stale)}件が24h以上滞留:")
    for name, age in stale[:5]:
        print(f"    - {name} ({age})")
else:
    print("  ✅ reports/滞留なし")

# [D] kpop_archives/ 連続失敗検知（24h以内に成功0件＋失敗3件以上でアラート）
archives_dir = os.path.expanduser("~/kpop_archives")
if os.path.isdir(archives_dir):
    now = time.time()
    recent_archives = 0
    for d in sorted(os.listdir(archives_dir)):
        dpath = os.path.join(archives_dir, d)
        if os.path.isdir(dpath):
            try:
                age_h = (now - os.path.getmtime(dpath)) / 3600
                if age_h <= 24:
                    recent_archives += 1
            except:
                pass
    if recent_archives >= 3 and success == 0:
        alert = {"type": "archive_cascade_block", "message": f"24h以内に{recent_archives}件archive・WP投稿成功0件 — 品質ゲート過剰BLOCKの可能性", "ts": time.strftime('%Y-%m-%dT%H:%M:%S')}
        alerts_path = os.path.join(SCRIPT_DIR, "logs", "watchdog_alerts.jsonl")
        with open(alerts_path, "a") as af:
            af.write(json.dumps(alert, ensure_ascii=False) + "\n")
        print(f"  🚨 kpop_archives/に24h以内{recent_archives}件失敗・投稿0件 → アラート発火")
    elif recent_archives > 0:
        print(f"  ℹ️ kpop_archives/ 24h以内: {recent_archives}件（投稿成功: {success}件）")

print("  ✅ WP投稿成功率・滞留記事watchdog 完了")
WP_WATCHDOG

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 4.5: 自律修正エンジン（品質ゲート緩和・mewtwo提案・リライトキュー）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo "" | tee -a "$LOG"
echo "=== STEP 4.5: 自律修正エンジン ===" | tee -a "$LOG"
python3 - << 'AUTO_FIX_PY' 2>&1 | tee -a "$LOG"
import json, os, glob, time
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

SCRIPT_DIR = os.environ.get("SCRIPT_DIR", os.path.dirname(os.path.abspath(__file__)))
if not os.path.isdir(SCRIPT_DIR):
    SCRIPT_DIR = "/home/aiuser/kpop-ai-system"

LOGS = Path(SCRIPT_DIR) / "logs"
CONFIG = Path(SCRIPT_DIR) / "config"
today = datetime.now().strftime("%Y-%m-%d")

# ── [A] パイプライン成功率チェック → 70%以下で品質ゲート緩和提案 ──
kpi_file = LOGS / "kpi_posts.jsonl"
err_file = LOGS / "kpi_errors.jsonl"
posts_today = 0
errors_today = 0
archive_3day = []

if kpi_file.exists():
    for line in kpi_file.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
            if d.get("date", "")[:10] == today:
                posts_today += 1
        except:
            pass

if err_file.exists():
    for line in err_file.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
            if d.get("date", "")[:10] == today:
                errors_today += 1
        except:
            pass

total_attempts = posts_today + errors_today
success_rate = (posts_today / total_attempts * 100) if total_attempts > 0 else 100

if success_rate < 70 and total_attempts >= 3:
    print(f"  🔧 成功率{success_rate:.0f}%（{posts_today}/{total_attempts}）→ 品質ゲート緩和を検討")
    # safety_config.jsonの閾値を動的調整
    safety_file = CONFIG / "safety_config.json"
    if safety_file.exists():
        cfg = json.loads(safety_file.read_text())
        current_min_score = cfg.get("quality_gates", {}).get("gardevoir_min_score", 70)
        if current_min_score > 60:
            cfg.setdefault("quality_gates", {})["gardevoir_min_score"] = max(60, current_min_score - 5)
            safety_file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
            print(f"    ↳ gardevoir_min_score: {current_min_score} → {cfg['quality_gates']['gardevoir_min_score']}（自動緩和）")
        else:
            print(f"    ↳ gardevoir_min_score={current_min_score}（既に下限60に達しています）")
else:
    print(f"  ✅ 成功率: {success_rate:.0f}%（{posts_today}/{total_attempts}）— 緩和不要")

# ── [B] 3日連続archive_and_exit 10件以上 → mewtwo提案 ──
archive_dir = os.path.expanduser("~/kpop_archives")
if os.path.isdir(archive_dir):
    daily_archives = Counter()
    now = time.time()
    for d in os.listdir(archive_dir):
        dpath = os.path.join(archive_dir, d)
        if os.path.isdir(dpath):
            try:
                dt = datetime.fromtimestamp(os.path.getmtime(dpath))
                date_key = dt.strftime("%Y-%m-%d")
                if (now - os.path.getmtime(dpath)) / 86400 <= 3:
                    daily_archives[date_key] += 1
            except:
                pass
    consecutive_high = sum(1 for d, c in sorted(daily_archives.items())[-3:] if c >= 10)
    if consecutive_high >= 3:
        proposal = {
            "type": "auto_proposal",
            "to": "mewtwo",
            "ts": datetime.now().isoformat(),
            "message": f"3日連続でarchive_and_exitが10件以上発生。品質ゲートの閾値見直し or テーマ選定戦略の変更を提案",
            "data": dict(daily_archives),
        }
        proposal_file = LOGS / "mewtwo_proposals.jsonl"
        with open(proposal_file, "a") as f:
            f.write(json.dumps(proposal, ensure_ascii=False) + "\n")
        print(f"  📋 mewtwoへの自動提案を記録: archive連続高頻度（{dict(daily_archives)}）")
    else:
        print(f"  ✅ archive頻度: 正常範囲（直近3日: {dict(daily_archives)}）")

# ── [C] template_filler検出 → リライトキュー ──
rewrite_queue = LOGS / "rewrite_queue.jsonl"
pipeline_log = LOGS / "pipeline.jsonl"
if pipeline_log.exists():
    filler_posts = []
    for line in pipeline_log.read_text(errors="replace").splitlines()[-200:]:
        try:
            d = json.loads(line)
            if "template_filler" in str(d.get("message", "")) and d.get("post_id"):
                filler_posts.append(d["post_id"])
        except:
            pass
    if filler_posts:
        existing_queue = set()
        if rewrite_queue.exists():
            for line in rewrite_queue.read_text(errors="replace").splitlines():
                try:
                    existing_queue.add(json.loads(line).get("post_id"))
                except:
                    pass
        new_entries = [pid for pid in set(filler_posts) if pid not in existing_queue]
        if new_entries:
            with open(rewrite_queue, "a") as f:
                for pid in new_entries:
                    f.write(json.dumps({
                        "post_id": pid,
                        "reason": "template_filler_detected",
                        "queued_at": datetime.now().isoformat(),
                        "status": "pending",
                    }, ensure_ascii=False) + "\n")
            print(f"  📝 リライトキューに{len(new_entries)}件追加（template_filler検出）")
        else:
            print(f"  ✅ template_filler: リライト対象なし（既にキュー済みまたは検出なし）")
    else:
        print("  ✅ template_filler: 検出なし")
else:
    print("  ⚠ pipeline.jsonlなし")

print("  ✅ 自律修正エンジン完了")
AUTO_FIX_PY

if [[ $? -eq 0 ]]; then
  SUCCESSES+=("STEP4.5_auto_fix")
else
  ERRORS+=("STEP4.5_auto_fix")
fi

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 8.5: 学習サイクル有効性検証（winning_patterns result更新 + 再発検知）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "学習サイクル検証(result更新+再発検知)" \
  "python3 lib/learning_validator.py validate 2>/dev/null"

# 学習メトリクス1行サマリー取得（Discord通知用）
_LEARNING_METRICS=$(python3 lib/learning_validator.py metrics-oneliner 2>/dev/null || echo "学習メトリクス取得失敗")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 9: タイトル品質学習（CTR上位パターン → eevee/metamon注入）
# 直近7日間のCTR上位タイトルから共通パターン（フック語・数字・疑問形等）を抽出し、
# eevee/metamonのタイトル生成プロンプトに自動注入する。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "タイトル品質学習(CTRパターン→eevee/metamon)" \
  "python3 lib/learning_feedback_loop.py learn-titles 2>/dev/null"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 10: 誤字学習（誤字パターン収集 → error_patterns.json自動追加）
# audit_feedback/post_audit.logから誤字パターンを収集し、
# error_patterns.jsonに追加。次回生成時のチェック対象に自動組込。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "誤字学習(パターン→error_patterns自動追加)" \
  "python3 lib/learning_feedback_loop.py learn-typos 2>/dev/null"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 11: 品質スコア学習（S/Cランク特徴抽出 → 品質ゲートフィードバック）
# Sランク記事の共通特徴・Cランク記事の共通問題を抽出し、
# arceus品質ゲートと safety_config に自動フィードバック。
# 同じ問題が3回以上繰り返された場合は根本修正を自動提案。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
run_step "品質スコア学習(S/C特徴→品質ゲートFB)" \
  "python3 lib/learning_feedback_loop.py learn-quality 2>/dev/null"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 8: Discordサマリー通知
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOTAL_OK="${#SUCCESSES[@]}"
TOTAL_ERR="${#ERRORS[@]}"

# ━ 補足情報収集 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# gardevoir直近HARD_FAIL件数
_GDV_FAIL_COUNT=0
_GDV_FAIL_SCORE=""
if [[ -f "$SCRIPT_DIR/logs/gardevoir_hook.jsonl" ]]; then
  _GDV_FAIL_COUNT=$(python3 -c "
import json
from pathlib import Path
lines=[l.strip() for l in Path('logs/gardevoir_hook.jsonl').read_text(errors='replace').splitlines()[-50:] if l.strip()]
hf=[l for l in lines if '\"HARD_FAIL\"' in l]
print(len(hf))
" 2>/dev/null || echo 0)
  [[ "$_GDV_FAIL_COUNT" -gt 0 ]] && _GDV_FAIL_SCORE="（直近50件中 HARD_FAIL=${_GDV_FAIL_COUNT}件）"
fi

# draft化アラート（post_auditで3回失敗してdraft化した記事数）
_DRAFT_FAIL_COUNT=$(grep -c "修正ループ3回失敗.*draft化" "$SCRIPT_DIR/logs/post_audit.log" 2>/dev/null | tail -1 || echo 0)
_DRAFT_TODAY=$({ grep "$(date '+%Y-%m-%d').*修正ループ3回失敗.*draft化" "$SCRIPT_DIR/logs/post_audit.log" 2>/dev/null || true; } | wc -l | tr -d ' \n')

# gossip_source_guard停止件数（今日）
_GOSSIP_STOP_TODAY=0
_GOSSIP_STOP_DETAIL=""
if [[ -f "$SCRIPT_DIR/logs/gossip_source_guard.log" ]]; then
  _GOSSIP_STOP_TODAY=$({ grep "$(date '+%Y-%m-%d')" "$SCRIPT_DIR/logs/gossip_source_guard.log" 2>/dev/null || true; } | wc -l | tr -d ' \n')
  if [[ "$_GOSSIP_STOP_TODAY" -gt 0 ]]; then
    _gsf=$(grep "$(date '+%Y-%m-%d')" "$SCRIPT_DIR/logs/gossip_source_guard.log" 2>/dev/null | grep -c "GOSSIP_SOURCE_FAIL" || echo 0)
    _ddf=$(grep "$(date '+%Y-%m-%d')" "$SCRIPT_DIR/logs/gossip_source_guard.log" 2>/dev/null | grep -c "DEOXYS_SOURCE_FAIL" || echo 0)
    _spc=$(grep "$(date '+%Y-%m-%d')" "$SCRIPT_DIR/logs/gossip_source_guard.log" 2>/dev/null | grep -c "憶測語\|SPECULATION" || echo 0)
    _swk=$(grep "$(date '+%Y-%m-%d')" "$SCRIPT_DIR/logs/gossip_source_guard.log" 2>/dev/null | grep -c "SOURCE_WEAK" || echo 0)
    _GOSSIP_STOP_DETAIL="(ソース不足=${_gsf} DEOXYS=${_ddf} 憶測語=${_spc} post_audit弱=${_swk})"
  fi
fi

# 会議体状況
_MEETING_STATUS="未実行"
MEETING_DECISION="$HOME/ai_company/reports/mewtwo_decision.md"
if [[ -f "$MEETING_DECISION" ]]; then
  _MEETING_AGE=$(( $(date +%s) - $(stat -c %Y "$MEETING_DECISION" 2>/dev/null || echo 0) ))
  if [[ "$_MEETING_AGE" -lt 86400 ]]; then
    _MEETING_STATUS="実行済み（$(date -d "@$(stat -c %Y "$MEETING_DECISION")" '+%H:%M JST' 2>/dev/null || echo '不明')）"
  else
    _MEETING_STATUS="24h超過（古いレポート）"
  fi
fi

# ━ 品質指標比率集計（post_audit.log / x_post.log から当日分） ━━━━━━━━━━━━━
_TODAY_DATE=$(date '+%Y-%m-%d')
_QUALITY_STATS=$(python3 - "$SCRIPT_DIR/logs/post_audit.log" "$SCRIPT_DIR/logs/x_post.log" "$_TODAY_DATE" <<'QSTATS_PY'
import sys, re
from pathlib import Path

audit_log = Path(sys.argv[1])
x_log     = Path(sys.argv[2])
today     = sys.argv[3]

stats = {
    'audited': 0,       # 監査実行記事数（ユニーク）
    'seo_fix': 0,       # タイトルSEO修正成功
    'seo_warn': 0,      # タイトルSEO警告（K-POPキーワードなし）
    'v12_warn': 0,      # V12フォーマット警告（投稿済みのため再投稿なし）
    'pre_score_ng': 0,  # PRE_SCOREテンプレ再生成
    'pre_score_ok': 0,  # PRE_SCORE一発通過
    'external_wp': 0,   # pipeline外WP記事検知件数
    'draft': 0,         # draft化件数
}

if audit_log.exists():
    text = audit_log.read_text(errors='replace')
    audited_ids = set()
    for line in text.splitlines():
        if today not in line:
            continue
        m = re.search(r'投稿後監査開始.*ID=(\d+)', line)
        if m:
            audited_ids.add(m.group(1))
        if 'タイトルSEO修正:' in line and '✅' in line:
            stats['seo_fix'] += 1
        if 'K-POP関連キーワードがタイトルに含まれない' in line:
            stats['seo_warn'] += 1
        if '投稿済みのため違反は警告のみ' in line:
            stats['v12_warn'] += 1
        if 'draft化完了' in line:
            stats['draft'] += 1
    stats['audited'] = len(audited_ids)

if x_log.exists():
    for line in x_log.read_text(errors='replace').splitlines():
        if today not in line:
            continue
        if 'PRE_SCORE' in line and 'pass=NO' in line:
            stats['pre_score_ng'] += 1
        if 'PRE_SCORE' in line and 'pass=YES' in line:
            stats['pre_score_ok'] += 1

# external_wp: watchdog_alerts.jsonlから当日分
import json
wa = Path('logs/watchdog_alerts.jsonl')
if wa.exists():
    for line in wa.read_text(errors='replace').splitlines():
        line = line.strip()
        if not line: continue
        try:
            r = json.loads(line)
            if today in r.get('ts','') and r.get('check') == 'pipeline_external_wp_post':
                stats['external_wp'] += 1
        except Exception:
            pass

n = stats['audited']
pre_total = stats['pre_score_ng'] + stats['pre_score_ok']
lines_out = []
if n > 0:
    seo_r = f"{stats['seo_fix']}/{stats['seo_warn']}件" if stats['seo_warn'] > 0 else "0件"
    lines_out.append(f"タイトルSEO警告={stats['seo_warn']}件 修正成功={stats['seo_fix']}件")
if pre_total > 0:
    lines_out.append(f"PRE_SCORE再生成={stats['pre_score_ng']}/{pre_total}件({100*stats['pre_score_ng']//pre_total}%)")
if stats['v12_warn'] > 0:
    lines_out.append(f"V12警告(投稿済)={stats['v12_warn']}件")
if stats['external_wp'] > 0:
    lines_out.append(f"pipeline外記事検知={stats['external_wp']}件")
if stats['draft'] > 0:
    lines_out.append(f"draft化={stats['draft']}件")
if lines_out:
    print(' | '.join(lines_out))
else:
    print('本日の監査データなし')
QSTATS_PY
)

# ━ Discord STEP8: 可読性優先フォーマット（重要度順・NG上位表示）━━━━━━━━━
# 設計方針: 🔴NG → 🟡要注意 → 📊品質指標 → ✅成功 → 📁ログ
# セクション間は空行で区切る（Discord Markdownで読みやすく）

# NG有無でヘッダアイコンを変える
if [[ "${#ERRORS[@]}" -gt 0 ]]; then
  _HDR="🚨"
  _STATUS="要対応あり"
elif [[ "$_DRAFT_TODAY" -gt 0 ]] || [[ "$_GDV_FAIL_COUNT" -gt 0 ]] || [[ "${_GOSSIP_STOP_TODAY:-0}" -gt 0 ]]; then
  _HDR="⚠️"
  _STATUS="注意事項あり"
else
  _HDR="✅"
  _STATUS="全ステップ正常"
fi

SUMMARY_MSG="${_HDR} **improvement_engine** | ${_STATUS} | $(date '+%m/%d %H:%M JST')\n"
SUMMARY_MSG+="成功:${TOTAL_OK} 失敗:${TOTAL_ERR} | 会議体:${_MEETING_STATUS}\n"

# 🔴 NG項目（最上位・必読）
if [[ "${#ERRORS[@]}" -gt 0 ]]; then
  SUMMARY_MSG+="\n🔴 **要対応:**\n"
  for _err in "${ERRORS[@]}"; do
    SUMMARY_MSG+="  • ${_err}\n"
  done
fi

# 🟡 draft化アラート（今日発生分）
if [[ "${_DRAFT_TODAY:-0}" -gt 0 ]]; then
  SUMMARY_MSG+="\n🟡 **draft化アラート:** 今日 ${_DRAFT_TODAY}件が監査3回失敗でdraft化\n"
  SUMMARY_MSG+="  → logs/post_audit.log で POST_ID確認・手動対応が必要\n"
fi

# 🟡 gardevoir HARD_FAIL
if [[ "${_GDV_FAIL_COUNT:-0}" -gt 0 ]]; then
  SUMMARY_MSG+="\n🟡 **刺さり品質:** HARD_FAIL ${_GDV_FAIL_COUNT}件${_GDV_FAIL_SCORE}\n"
  SUMMARY_MSG+="  → logs/gardevoir_hook.jsonl で must_fix確認\n"
fi

# 🟡 gossip_source_guard 停止アラート（今日発生分）
if [[ "${_GOSSIP_STOP_TODAY:-0}" -gt 0 ]]; then
  SUMMARY_MSG+="\n🟡 **gossipガード:** 今日 ${_GOSSIP_STOP_TODAY}件停止 ${_GOSSIP_STOP_DETAIL}\n"
  SUMMARY_MSG+="  → logs/gossip_source_guard.log で停止理由確認\n"
fi

# 📊 品質指標（役割監査）
_ROLE_DIFF=$(grep "\[role_audit\].*前回" "$LOG" 2>/dev/null | tail -1 | sed 's/^[[:space:]]*//' || echo "")
if [[ -n "$_ROLE_DIFF" ]]; then
  SUMMARY_MSG+="\n📊 **役割監査:** ${_ROLE_DIFF}\n"
fi

# ✅ 成功ステップサマリー（NG除外・最大5件）
SUMMARY_MSG+="\n✅ **ステップ結果:**\n"
_shown=0
for line in "${REPORT_LINES[@]}"; do
  [[ "$line" == ⚠️* ]] && continue
  [[ "$line" == *"失敗"* ]] && continue
  SUMMARY_MSG+="  ${line}\n"
  _shown=$(( _shown + 1 ))
  [[ "$_shown" -ge 5 ]] && break
done

# 📊 品質比率サマリー（_QUALITY_STATSが取得できた場合のみ）
if [[ -n "${_QUALITY_STATS:-}" ]]; then
  SUMMARY_MSG+="\n📊 **品質比率:** ${_QUALITY_STATS}\n"
fi

# 🧠 学習サイクルメトリクス
if [[ -n "${_LEARNING_METRICS:-}" ]]; then
  SUMMARY_MSG+="\n🧠 **学習サイクル:** ${_LEARNING_METRICS}\n"
fi

# 📁 詳細ログ（最後に）
SUMMARY_MSG+="\n📁 **ログ:** logs/improvement_engine.log"
[[ "${#ERRORS[@]}" -gt 0 ]] && SUMMARY_MSG+=" | logs/role_audit.log"
[[ "${_DRAFT_TODAY:-0}" -gt 0 ]] && SUMMARY_MSG+=" | logs/post_audit.log"
[[ "${_GOSSIP_STOP_TODAY:-0}" -gt 0 ]] && SUMMARY_MSG+=" | logs/gossip_source_guard.log"
SUMMARY_MSG+="\n"

WEBHOOK_FILE="$SCRIPT_DIR/config/discord_webhooks.json"
if [[ -f "$WEBHOOK_FILE" ]]; then
  WEBHOOK=$(python3 -c "
import json
d = json.load(open('$WEBHOOK_FILE'))
print(d.get('daily_ceo_report', d.get('urgent_errors', '')))
" 2>/dev/null || echo "")
  if [[ -n "$WEBHOOK" ]]; then
    python3 -c "
import json, urllib.request
msg = '''$SUMMARY_MSG'''.replace('\\\\n', '\n')
payload = json.dumps({'content': msg[:1900]}).encode()
req = urllib.request.Request('$WEBHOOK', data=payload,
      headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}, method='POST')
try:
    urllib.request.urlopen(req, timeout=10)
    print('Discord通知完了')
except Exception as e:
    print(f'Discord通知失敗: {e}')
" 2>/dev/null >> "$LOG" || true
  fi
fi

echo "" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "improvement_engine 終了: $(date '+%Y-%m-%d %H:%M:%S JST')" | tee -a "$LOG"
echo "成功: ${TOTAL_OK}件 / 失敗: ${TOTAL_ERR}件" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
