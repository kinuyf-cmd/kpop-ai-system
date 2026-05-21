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
run_step "X投稿スコア勝ちワード更新" \
  "python3 lib/auto_improve.py update-titles 2>/dev/null"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 7: 週次レポート（月曜のみ）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if [[ "$DOW" == "1" ]]; then
  run_step "週次改善レポート生成" \
    "python3 lib/auto_improve.py report 2>/dev/null"
fi

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
