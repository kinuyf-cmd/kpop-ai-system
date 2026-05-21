#!/usr/bin/env bash
# run_agent_monitor.sh — AI会社 統合監視システム v2.0
# CEO: ミュウツー / オーナー: 人間（閲覧専用）
# 既存pipeline・記事への変更なし（読み取り専用分析 → JSON/HTML出力のみ）
#
# 使い方:
#   bash run_agent_monitor.sh            # 1回実行
#   bash run_agent_monitor.sh --watch    # 5分ごとに繰り返し実行
#   bash run_agent_monitor.sh --cron     # cronモード（ログ出力のみ）

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV="$SCRIPT_DIR/.venv/bin/activate"
[[ -f "$VENV" ]] && source "$VENV"
[[ -f "$SCRIPT_DIR/env_loader.sh" ]] && source "$SCRIPT_DIR/env_loader.sh" 2>/dev/null || true

MODE="${1:-}"
NOW=$(date '+%Y-%m-%d %H:%M:%S JST')

run_once() {
  echo "========================================"
  echo " K-POP Journal AI Company"
  echo " 統合監視システム v2.0"
  echo " CEO: ミュウツー | オーナー: 閲覧専用"
  echo " 実行: $(date '+%Y-%m-%d %H:%M:%S JST')"
  echo "========================================"
  echo ""

  echo "[STEP1] エージェントメトリクス集計..."
  python3 "$SCRIPT_DIR/lib/agent_monitor.py"

  echo ""
  echo "[STEP2] ダッシュボードHTML生成..."
  python3 "$SCRIPT_DIR/generate_dashboard.py"

  echo ""
  echo "[STEP3] Discord異常通知判定..."
  NOTIFIER_JSON=$(python3 "$SCRIPT_DIR/lib/discord_notifier.py" 2>&1 | tee /dev/stderr | tail -1)

  # 通知サマリーをJSONから抽出（最終行がJSON）
  NOTIFY_SENT=$(echo "$NOTIFIER_JSON"     | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('sent',0))"       2>/dev/null || echo "?")
  NOTIFY_SUPP=$(echo "$NOTIFIER_JSON"     | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('suppressed',0))" 2>/dev/null || echo "?")
  NOTIFY_SKIP=$(echo "$NOTIFIER_JSON"     | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('skipped',0))"    2>/dev/null || echo "?")
  NOTIFY_FAIL=$(echo "$NOTIFIER_JSON"     | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('failed',0))"     2>/dev/null || echo "?")

  echo ""
  echo "[STEP4] キュー再送（前回失敗分）..."
  RETRY_JSON=$(python3 "$SCRIPT_DIR/lib/alert_queue.py" --retry 2>&1 | tee /dev/stderr | tail -1)
  RETRY_SENT=$(echo "$RETRY_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); r=d.get('queue_retry',d); print(r.get('sent',0))"            2>/dev/null || echo "0")
  RETRY_PEND=$(echo "$RETRY_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); r=d.get('queue_retry',d); print(r.get('pending',0))"         2>/dev/null || echo "0")
  RETRY_PERM=$(echo "$RETRY_JSON" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); r=d.get('queue_retry',d); print(r.get('permanent_failed',0))" 2>/dev/null || echo "0")

  # dashboard_summary.json から追加KPI + CEO判断抽出
  SUMMARY_JSON="$SCRIPT_DIR/dashboard_summary.json"
  UNRES_CRIT=$(python3 -c "import json; d=json.load(open('$SUMMARY_JSON')); print(d.get('unresolved_critical_count',0))" 2>/dev/null || echo "0")
  UNRES_WARN=$(python3 -c "import json; d=json.load(open('$SUMMARY_JSON')); print(d.get('unresolved_warning_count',0))"  2>/dev/null || echo "0")
  BLOCKERS=$(python3 -c "
import json
try:
    d = json.load(open('$SUMMARY_JSON'))
    bl = d.get('revenue_blocker_top3', [])
    for b in bl:
        print(f\"     💸 {b['name']} — {b['rate']:.0%} ({b['status']})\")
except: pass
" 2>/dev/null || true)
  MOST_DANGER=$(python3 -c "
import json
try:
    d = json.load(open('$SUMMARY_JSON'))
    fa = d.get('failing_agent_top3', [])
    if fa: print(fa[0].get('name','') + ' (' + str(round(fa[0].get('rate',0)*100)) + '%)')
except: pass
" 2>/dev/null || echo "—")
  # CEO判断4項目
  CEO_IMMEDIATE=$(python3 -c "import json; d=json.load(open('$SUMMARY_JSON')); print(d.get('ceo_immediate_action','—'))" 2>/dev/null || echo "—")
  CEO_FIX=$(python3 -c "import json; d=json.load(open('$SUMMARY_JSON')); print(d.get('ceo_today_fix','—'))" 2>/dev/null || echo "—")
  CEO_LEVER=$(python3 -c "import json; d=json.load(open('$SUMMARY_JSON')); print(d.get('ceo_revenue_lever','—'))" 2>/dev/null || echo "—")
  CEO_IGNORE=$(python3 -c "import json; d=json.load(open('$SUMMARY_JSON')); print(d.get('ceo_ignore_today','—'))" 2>/dev/null || echo "—")
  CEO_CONF=$(python3 -c "import json; d=json.load(open('$SUMMARY_JSON')); print(d.get('ceo_confidence','—'))" 2>/dev/null || echo "—")
  # CEO最新命令キュー
  CEO_CMD=$(python3 -c "
import json
try:
    lines = [l.strip() for l in open('$SCRIPT_DIR/logs/ceo_action_queue.jsonl') if l.strip()]
    if not lines: print('命令キューなし'); raise SystemExit
    rec = json.loads(lines[-1])
    atype_map = {
        'retry_alert_queue':       '再送実行',
        'inspect_agent_failure':   'エージェント調査',
        'inspect_revenue_blocker': '売上阻害調査',
        'monitor_only':            '監視継続',
    }
    prio   = rec.get('priority','—')
    atype  = atype_map.get(rec.get('action_type',''), rec.get('action_type','—'))
    agent  = rec.get('target_agent','') or '—'
    log    = rec.get('target_log','') or '—'
    effect = rec.get('expected_effect','') or '—'
    print(f'{prio} / {atype} / {agent} / {log}')
    print(f'     期待効果: {effect}')
except SystemExit: pass
except Exception as e: print(f'取得エラー: {e}')
" 2>/dev/null || echo "—")

  echo ""
  echo "========================================"
  echo "✅ 完了: $(date '+%H:%M:%S')"
  echo "  📊 agent_metrics.json       — エージェント評価"
  echo "  🔧 optimization_actions.json — 改善アクション"
  echo "  💰 revenue_metrics.json      — 売上KPI"
  echo "  🏢 org_map.json              — AI組織マップ"
  echo "  📋 dashboard_summary.json    — 経営サマリー"
  echo "  🖥️  dashboard.html            — オーナー経営画面"
  echo ""
  echo "  🔔 Discord通知サマリー:"
  echo "     直送  — 送信成功: ${NOTIFY_SENT}件 / 抑制: ${NOTIFY_SUPP}件 / スキップ: ${NOTIFY_SKIP}件"
  echo "     再送  — 成功: ${RETRY_SENT}件 / pending残: ${RETRY_PEND}件 / 永続失敗: ${RETRY_PERM}件"
  [[ "$NOTIFY_FAIL" != "0" && "$NOTIFY_FAIL" != "?" ]] && \
    echo "     ❌ 直送失敗 ${NOTIFY_FAIL}件 → キューに保存済み（次回再送）"
  [[ "$RETRY_PERM" != "0" && "$RETRY_PERM" != "?" ]] && \
    echo "     ⚠️  永続失敗 ${RETRY_PERM}件 → logs/alert_retry_history.jsonl を確認"
  echo ""
  echo "  🚨 未解決アラート:"
  [[ "$UNRES_CRIT" != "0" ]] && echo "     🔴 CRITICAL pending: ${UNRES_CRIT}件 — 即対応してください" || echo "     ✅ CRITICAL: なし"
  [[ "$UNRES_WARN" != "0" ]] && echo "     🟡 WARNING  pending: ${UNRES_WARN}件" || echo "     ✅ WARNING : なし"
  echo ""
  echo "  💸 売上阻害ボトルネック TOP3:"
  if [[ -n "$BLOCKERS" ]]; then
    echo "$BLOCKERS"
  else
    echo "     ✅ 売上阻害なし"
  fi
  echo ""
  echo "  🤖 最危険AI: ${MOST_DANGER}"
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  🧠 ミュウツー CEO判断 [信頼度: ${CEO_CONF}]"
  echo "  ──────────────────────────────────────"
  echo "  🩸 今すぐ止血   : ${CEO_IMMEDIATE}"
  echo "  🔧 今日直す1点  : ${CEO_FIX}"
  echo "  💰 今日の売上レバー: ${CEO_LEVER}"
  echo "  😴 今は触らない : ${CEO_IGNORE}"
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  🧾 CEO最新命令キュー:"
  echo "  ${CEO_CMD}"
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  ⚡ CEO命令実行結果:"
  EXEC_STATE_JSON="$SCRIPT_DIR/logs/ceo_execution_state.json"
  if [[ -f "$EXEC_STATE_JSON" ]]; then
    EXEC_PROC=$(python3 -c "import json; d=json.load(open('$EXEC_STATE_JSON')); print(d.get('processed_count_this_run',0))"  2>/dev/null || echo "0")
    EXEC_DONE=$(python3 -c "import json; d=json.load(open('$EXEC_STATE_JSON')); print(d.get('done_count_this_run',0))"       2>/dev/null || echo "0")
    EXEC_FAIL=$(python3 -c "import json; d=json.load(open('$EXEC_STATE_JSON')); print(d.get('failed_count_this_run',0))"     2>/dev/null || echo "0")
    EXEC_BLOC=$(python3 -c "import json; d=json.load(open('$EXEC_STATE_JSON')); print(d.get('blocked_count_this_run',0))"    2>/dev/null || echo "0")
    EXEC_RESULT=$(python3 -c "import json; d=json.load(open('$EXEC_STATE_JSON')); print(d.get('last_result','—'))"           2>/dev/null || echo "—")
    EXEC_REASON=$(python3 -c "
import json
try:
    d = json.load(open('$EXEC_STATE_JSON'))
    m = {'unsupported_action_type':'未対応タイプ','missing_target_log':'対象ログ欠落','no_recent_data':'データなし',
         'duplicate_in_progress':'実行中重複','skipped_duplicate_done':'直近済み重複',
         'unsafe_operation_denied':'実行推奨なし','exception_during_exec':'例外エラー','queue_write_failure':'キュー書込失敗'}
    r = d.get('last_reason','')
    print(m.get(r,r) if r else '—')
except: print('—')
" 2>/dev/null || echo "—")
    EXEC_TYPE=$(python3 -c "
import json
try:
    d = json.load(open('$EXEC_STATE_JSON'))
    m = {'retry_alert_queue':'再送実行','inspect_agent_failure':'エージェント調査','inspect_revenue_blocker':'売上阻害調査','monitor_only':'監視継続'}
    print(m.get(d.get('last_action_type',''), d.get('last_action_type','—')))
except: print('—')
" 2>/dev/null || echo "—")
    EXEC_AGENT=$(python3 -c "import json; d=json.load(open('$EXEC_STATE_JSON')); print(d.get('last_target_agent','') or '—')" 2>/dev/null || echo "—")
    EXEC_SUMM=$(python3  -c "import json; d=json.load(open('$EXEC_STATE_JSON')); print(d.get('last_summary','')[:80])"         2>/dev/null || echo "—")
    EXEC_SAFE_RETRY=$(python3 -c "import json; d=json.load(open('$EXEC_STATE_JSON')); print(d.get('safe_retry_count_this_run',0))"   2>/dev/null || echo "0")
    EXEC_SAFE_INSP=$(python3  -c "import json; d=json.load(open('$EXEC_STATE_JSON')); print(d.get('safe_inspect_count_this_run',0))" 2>/dev/null || echo "0")
    echo "  処理 ${EXEC_PROC}件 / done ${EXEC_DONE} / failed ${EXEC_FAIL} / blocked ${EXEC_BLOC}"
    echo "  🛡️  CEO安全実行: retry ${EXEC_SAFE_RETRY}件成功 / inspect ${EXEC_SAFE_INSP}件保存 / blocked ${EXEC_BLOC}件"
    echo "  最新: ${EXEC_TYPE} / ${EXEC_AGENT} / ${EXEC_RESULT}"
    [[ "$EXEC_REASON" != "—" && -n "$EXEC_REASON" ]] && echo "  理由: ${EXEC_REASON}"
    echo "  要約: ${EXEC_SUMM}"
  else
    echo "  実行履歴なし（初回実行後に表示されます）"
  fi
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  🧩 CEO改善候補:"
  IMP_QUEUE_JSON="$SCRIPT_DIR/logs/ceo_improvement_queue.jsonl"
  if [[ -f "$IMP_QUEUE_JSON" ]]; then
    IMP_PENDING=$(python3 -c "
import json
with open('$IMP_QUEUE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending   = [r for r in recs if r.get('status')=='pending']
high      = sum(1 for r in pending if r.get('priority')=='HIGH')
medium    = sum(1 for r in pending if r.get('priority')=='MEDIUM')
safe_n    = sum(1 for r in pending if r.get('safety_class')=='SAFE')
review_n  = sum(1 for r in pending if r.get('safety_class')=='REVIEW')
blocked_n = sum(1 for r in pending if r.get('safety_class')=='BLOCKED')
exec_true = sum(1 for r in pending if r.get('execute_recommended') is True)
print(f'pending {len(pending)}件 / SAFE {safe_n}件 / REVIEW {review_n}件 / BLOCKED {blocked_n}件')
print(f'  実行推奨 true {exec_true}件')
" 2>/dev/null || echo "—")
    IMP_LATEST=$(python3 -c "
import json
try:
    with open('$IMP_QUEUE_JSON') as f:
        recs = [json.loads(l) for l in f if l.strip()]
    if not recs: print('なし'); raise SystemExit
    r = recs[-1]
    m = {'prompt_fix':'プロンプト修正','timeout_fix':'タイムアウト修正','monitor_continue':'監視継続','retry_config':'リトライ設定'}
    itype = m.get(r.get('improvement_type',''), r.get('improvement_type','—'))
    sc = r.get('safety_class') or r.get('priority','—')
    print(f\"{r.get('target_agent','—') or '—'} / {itype} / {sc}\")
except SystemExit: pass
except Exception as e: print(f'取得エラー: {e}')
" 2>/dev/null || echo "—")
    echo "  ${IMP_PENDING}"
    echo "  最新: ${IMP_LATEST}"
  else
    echo "  改善候補なし（inspect実行後に生成されます）"
  fi
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  🚀 CEO実行準備キュー (SAFEのみ):"
  READY_QUEUE_JSON="$SCRIPT_DIR/logs/ceo_ready_queue.jsonl"
  if [[ -f "$READY_QUEUE_JSON" ]]; then
    READY_STATS=$(python3 -c "
import json
from pathlib import Path
with open('$READY_QUEUE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending  = [r for r in recs if r.get('status')=='pending']
high     = sum(1 for r in pending if r.get('priority')=='HIGH')
medium   = sum(1 for r in pending if r.get('priority')=='MEDIUM')
er_path  = Path('$SCRIPT_DIR/logs/ceo_execution_ready_queue.jsonl')
er_pend  = 0
er_latest_agent = '—'
er_latest_type  = '—'
er_latest_prio  = '—'
if er_path.exists():
    er_recs = [json.loads(l) for l in er_path.read_text().splitlines() if l.strip()]
    er_pend_recs = [r for r in er_recs if r.get('status')=='pending']
    er_pend = len(er_pend_recs)
    if er_recs:
        m = {'prompt_fix':'プロンプト修正','timeout_fix':'タイムアウト修正','monitor_continue':'監視継続'}
        lr = er_recs[-1]
        er_latest_agent = lr.get('target_agent','—') or '—'
        er_latest_type  = m.get(lr.get('improvement_type',''), lr.get('improvement_type','—'))
        er_latest_prio  = lr.get('priority','—')
print(f'pending {len(pending)}件 / HIGH {high}件 / MEDIUM {medium}件')
print(f'  🧠 実行候補レーン: {er_pend}件 / 最新: {er_latest_agent} / {er_latest_type} / {er_latest_prio}')
" 2>/dev/null || echo "—")
    READY_LATEST=$(python3 -c "
import json
try:
    with open('$READY_QUEUE_JSON') as f:
        recs = [json.loads(l) for l in f if l.strip()]
    if not recs: print('なし'); raise SystemExit
    r = recs[-1]
    m = {'prompt_fix':'プロンプト修正','timeout_fix':'タイムアウト修正','monitor_continue':'監視継続','retry_config':'リトライ設定'}
    itype = m.get(r.get('improvement_type',''), r.get('improvement_type','—'))
    print(f\"{r.get('target_agent','—') or '—'} / {itype} / {r.get('priority','—')}\")
except SystemExit: pass
except Exception as e: print(f'取得エラー: {e}')
" 2>/dev/null || echo "—")
    echo "  ${READY_STATS}"
    echo "  最新: ${READY_LATEST}"
  else
    echo "  実行準備キューなし（SAFE候補が積まれると自動生成されます）"
  fi
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  🧪 CEO実行シミュレーション:"
  SIM_QUEUE_JSON="$SCRIPT_DIR/logs/ceo_execution_simulation.jsonl"
  if [[ -f "$SIM_QUEUE_JSON" ]]; then
    SIM_STATS=$(python3 -c "
import json
with open('$SIM_QUEUE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('status')=='pending']
high_r  = sum(1 for r in pending if r.get('risk_level')=='high')
med_r   = sum(1 for r in pending if r.get('risk_level')=='medium')
low_r   = sum(1 for r in pending if r.get('risk_level')=='low')
print(f'pending {len(pending)}件 / high {high_r}件 / medium {med_r}件 / low {low_r}件')
if recs:
    m = {'prompt_change_simulation':'プロンプト変更シミュ','timeout_change_simulation':'タイムアウト変更シミュ','monitor_only_simulation':'監視継続シミュ'}
    lr = recs[-1]
    st = m.get(lr.get('simulation_type',''), lr.get('simulation_type','—'))
    print(f\"  最新: {lr.get('target_agent','—') or '(全体)'} / {st} / {lr.get('risk_level','—')}\")
" 2>/dev/null || echo "—")
    echo "  ${SIM_STATS}"
  else
    echo "  シミュレーションなし（execution_readyキューから自動登録されます）"
  fi
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  🏁 CEO実行優先順位:"
  RANKED_QUEUE_JSON="$SCRIPT_DIR/logs/ceo_execution_ranked_queue.jsonl"
  if [[ -f "$RANKED_QUEUE_JSON" ]]; then
    python3 -c "
import json
with open('$RANKED_QUEUE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('status')=='pending']
held    = [r for r in recs if r.get('status')=='held']
high_p  = sum(1 for r in recs if r.get('priority')=='HIGH')
med_p   = sum(1 for r in recs if r.get('priority')=='MEDIUM')
low_p   = sum(1 for r in recs if r.get('priority')=='LOW')
print(f'  pending {len(pending)}件 / held {len(held)}件 / HIGH {high_p}件 / MEDIUM {med_p}件 / LOW {low_p}件')
ordered = sorted([r for r in pending if r.get('execution_order',0)>0], key=lambda r: r.get('execution_order',99))
if ordered:
    top = ordered[0]
    print(f\"  1位: {top.get('target_agent','—')} / score {top.get('priority_score','—')}\")
if recs:
    lr = recs[-1]
    it = {'prompt_fix':'プロンプト修正','timeout_fix':'タイムアウト修正','monitor_continue':'監視継続'}.get(lr.get('improvement_type',''), lr.get('improvement_type','—'))
    print(f\"  最新: {lr.get('target_agent','—')} / {it} / {lr.get('status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  優先順位キューなし（シミュレーション後に自動生成されます）"
  fi
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  📦 CEO送信パケット:"
  PACKET_QUEUE_JSON="$SCRIPT_DIR/logs/ceo_execution_packet_queue.jsonl"
  if [[ -f "$PACKET_QUEUE_JSON" ]]; then
    python3 -c "
import json
with open('$PACKET_QUEUE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('packet_status')=='pending']
high_p  = sum(1 for r in pending if r.get('priority')=='HIGH')
med_p   = sum(1 for r in pending if r.get('priority')=='MEDIUM')
low_p   = sum(1 for r in pending if r.get('priority')=='LOW')
print(f'  pending {len(pending)}件 / HIGH {high_p}件 / MEDIUM {med_p}件 / LOW {low_p}件')
ordered = sorted([r for r in pending if r.get('execution_order',0)>0], key=lambda r: r.get('execution_order',99))
if ordered:
    top = ordered[0]
    print(f\"  1位: {top.get('target_agent','—')} / score {top.get('priority_score','—')}\")
if recs:
    lr = recs[-1]
    it = {'prompt_fix':'プロンプト修正','timeout_fix':'タイムアウト修正','monitor_continue':'監視継続'}.get(lr.get('improvement_type',''), lr.get('improvement_type','—'))
    print(f\"  最新: {lr.get('target_agent','—')} / {it} / {lr.get('packet_status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  パケットなし（ranked queueから自動登録されます）"
  fi
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  📨 CEO実行要求パケット:"
  DISPATCH_QUEUE_JSON="$SCRIPT_DIR/logs/ceo_execution_dispatch_request_queue.jsonl"
  if [[ -f "$DISPATCH_QUEUE_JSON" ]]; then
    python3 -c "
import json
with open('$DISPATCH_QUEUE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('dispatch_status')=='pending']
high_p  = sum(1 for r in pending if r.get('priority')=='HIGH')
med_p   = sum(1 for r in pending if r.get('priority')=='MEDIUM')
low_p   = sum(1 for r in pending if r.get('priority')=='LOW')
print(f'  pending {len(pending)}件 / HIGH {high_p}件 / MEDIUM {med_p}件 / LOW {low_p}件')
ordered = sorted([r for r in pending if r.get('execution_order',0)>0], key=lambda r: r.get('execution_order',99))
if ordered:
    top = ordered[0]
    print(f\"  1位: {top.get('target_agent','—')} / score {top.get('priority_score','—')}\")
if recs:
    lr = recs[-1]
    it = {'prompt_fix':'プロンプト修正','timeout_fix':'タイムアウト修正','monitor_continue':'監視継続'}.get(lr.get('improvement_type',''), lr.get('improvement_type','—'))
    print(f\"  最新: {lr.get('target_agent','—')} / {it} / {lr.get('dispatch_status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  dispatch要求なし（packet queueから自動登録されます）"
  fi
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  🧩 CEO実行スタブ:"
  STUB_QUEUE_JSON="$SCRIPT_DIR/logs/ceo_execution_executor_stub_queue.jsonl"
  if [[ -f "$STUB_QUEUE_JSON" ]]; then
    python3 -c "
import json
with open('$STUB_QUEUE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('stub_status')=='pending']
high_p  = sum(1 for r in pending if r.get('priority')=='HIGH')
med_p   = sum(1 for r in pending if r.get('priority')=='MEDIUM')
low_p   = sum(1 for r in pending if r.get('priority')=='LOW')
print(f'  pending {len(pending)}件 / HIGH {high_p}件 / MEDIUM {med_p}件 / LOW {low_p}件')
ordered = sorted([r for r in pending if r.get('execution_order',0)>0], key=lambda r: r.get('execution_order',99))
if ordered:
    top = ordered[0]
    print(f\"  1位: {top.get('target_agent','—')} / score {top.get('priority_score','—')}\")
if recs:
    lr = recs[-1]
    it = {'prompt_fix':'プロンプト修正','timeout_fix':'タイムアウト修正','monitor_continue':'監視継続'}.get(lr.get('improvement_type',''), lr.get('improvement_type','—'))
    print(f\"  最新: {lr.get('target_agent','—')} / {it} / {lr.get('stub_status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  スタブなし（dispatch queueから自動登録されます）"
  fi
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  🧪 CEOドライラン結果:"
  DRY_RUN_QUEUE_JSON="$SCRIPT_DIR/logs/ceo_execution_dry_run_result_queue.jsonl"
  if [[ -f "$DRY_RUN_QUEUE_JSON" ]]; then
    python3 -c "
import json
with open('$DRY_RUN_QUEUE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('dry_run_status')=='pending']
high_r  = sum(1 for r in pending if r.get('predicted_risk')=='high')
med_r   = sum(1 for r in pending if r.get('predicted_risk')=='medium')
low_r   = sum(1 for r in pending if r.get('predicted_risk')=='low')
print(f'  pending {len(pending)}件 / high {high_r}件 / medium {med_r}件 / low {low_r}件')
ordered = sorted([r for r in pending if r.get('execution_order',0)>0], key=lambda r: r.get('execution_order',99))
if ordered:
    top = ordered[0]
    print(f\"  1位: {top.get('target_agent','—')} / benefit {top.get('predicted_benefit_score','—')}\")
if recs:
    lr = recs[-1]
    it = {'prompt_fix':'プロンプト修正','timeout_fix':'タイムアウト修正','monitor_continue':'監視継続'}.get(lr.get('improvement_type',''), lr.get('improvement_type','—'))
    print(f\"  最新: {lr.get('target_agent','—')} / {it} / {lr.get('dry_run_status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  ドライランなし（stub queueから自動登録されます）"
  fi
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  🎯 CEO最終実行候補:"
  CANDIDATE_QUEUE_JSON="$SCRIPT_DIR/logs/ceo_execution_candidate_queue.jsonl"
  if [[ -f "$CANDIDATE_QUEUE_JSON" ]]; then
    python3 -c "
import json
with open('$CANDIDATE_QUEUE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('candidate_status')=='pending']
high_p  = sum(1 for r in pending if r.get('priority')=='HIGH')
med_p   = sum(1 for r in pending if r.get('priority')=='MEDIUM')
low_p   = sum(1 for r in pending if r.get('priority')=='LOW')
print(f'  pending {len(pending)}件 / HIGH {high_p}件 / MEDIUM {med_p}件 / LOW {low_p}件')
ordered = sorted([r for r in pending if r.get('execution_order',0)>0], key=lambda r: r.get('execution_order',99))
if ordered:
    top = ordered[0]
    print(f\"  1位: {top.get('target_agent','—')} / score {top.get('priority_score','—')}\")
if recs:
    lr = recs[-1]
    it = {'prompt_fix':'プロンプト修正','timeout_fix':'タイムアウト修正','monitor_continue':'監視継続'}.get(lr.get('improvement_type',''), lr.get('improvement_type','—'))
    print(f\"  最新: {lr.get('target_agent','—')} / {it} / {lr.get('candidate_status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  最終候補なし（dry_run queueから自動登録されます）"
  fi
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  🚦 CEO限定実行候補:"
  LIMITED_QUEUE_JSON="$SCRIPT_DIR/logs/ceo_limited_execution_queue.jsonl"
  if [[ -f "$LIMITED_QUEUE_JSON" ]]; then
    python3 -c "
import json
with open('$LIMITED_QUEUE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('limited_status')=='pending']
high_p  = sum(1 for r in pending if r.get('priority')=='HIGH')
med_p   = sum(1 for r in pending if r.get('priority')=='MEDIUM')
low_p   = sum(1 for r in pending if r.get('priority')=='LOW')
print(f'  pending {len(pending)}件 / HIGH {high_p}件 / MEDIUM {med_p}件 / LOW {low_p}件')
ordered = sorted([r for r in pending if r.get('execution_order',0)>0], key=lambda r: r.get('execution_order',99))
if ordered:
    top = ordered[0]
    print(f\"  1位: {top.get('target_agent','—')} / score {top.get('priority_score','—')}\")
if recs:
    lr = recs[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / prompt_fix / {lr.get('limited_status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  限定実行候補なし（execution_candidate queueから自動登録されます）"
  fi
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  🛡 CEO実行ガード結果:"
  GUARD_QUEUE_JSON="$SCRIPT_DIR/logs/ceo_execution_guard_result_queue.jsonl"
  if [[ -f "$GUARD_QUEUE_JSON" ]]; then
    python3 -c "
import json
with open('$GUARD_QUEUE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
allowed = [r for r in recs if r.get('guard_status')=='allowed']
blocked = [r for r in recs if r.get('guard_status')=='blocked']
print(f'  allowed {len(allowed)}件 / blocked {len(blocked)}件')
ordered = sorted([r for r in allowed if r.get('execution_order',0)>0], key=lambda r: r.get('execution_order',99))
if ordered:
    top = ordered[0]
    print(f\"  1位: {top.get('target_agent','—')} / score {top.get('priority_score','—')}\")
if recs:
    lr = recs[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / {lr.get('guard_status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  ガード判定なし（limited_execution queueから自動判定されます）"
  fi
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  🧩 CEO設定変更計画:"
  PATCH_PLAN_JSON="$SCRIPT_DIR/logs/ceo_config_patch_plan_queue.jsonl"
  if [[ -f "$PATCH_PLAN_JSON" ]]; then
    python3 -c "
import json
with open('$PATCH_PLAN_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('plan_status')=='pending']
held    = [r for r in recs if r.get('plan_status')=='held']
print(f'  pending {len(pending)}件 / held {len(held)}件')
ordered = sorted([r for r in pending if r.get('execution_order',0)>0], key=lambda r: r.get('execution_order',99))
if ordered:
    top = ordered[0]
    print(f\"  1位: {top.get('target_agent','—')} / {top.get('patch_path','—')}\")
if recs:
    lr = recs[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / {lr.get('plan_status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  変更計画なし（execution_guard allowed から自動生成されます）"
  fi
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  📝 CEO設定適用待ち:"
  APPLY_QUEUE_JSON="$SCRIPT_DIR/logs/ceo_config_apply_queue.jsonl"
  if [[ -f "$APPLY_QUEUE_JSON" ]]; then
    python3 -c "
import json
with open('$APPLY_QUEUE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('apply_status')=='pending']
print(f'  pending {len(pending)}件')
if pending:
    top = pending[0]
    print(f\"  1位: {top.get('target_agent','—')} / {top.get('target_config','—')}\")
if recs:
    lr = recs[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / {lr.get('apply_status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  適用待ちなし（config_patch_plan から自動登録されます）"
  fi
  echo ""
  echo "  ──────────────────────────────────────"
  echo "  ✅ CEO設定変更結果:"
  APPLY_RESULT_JSON="$SCRIPT_DIR/logs/ceo_config_apply_result_queue.jsonl"
  if [[ -f "$APPLY_RESULT_JSON" ]]; then
    python3 -c "
import json
with open('$APPLY_RESULT_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
applied = sum(1 for r in recs if r.get('result_status')=='applied')
blocked = sum(1 for r in recs if r.get('result_status')=='blocked')
failed  = sum(1 for r in recs if r.get('result_status')=='failed')
print(f'  applied {applied}件 / blocked {blocked}件 / failed {failed}件')
if recs:
    lr = recs[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / {lr.get('result_status','—')}\")
    if lr.get('diff_path'):
        print(f\"  diff: {lr.get('diff_path','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  変更結果なし（config_apply_queue から自動実行されます）"
  fi
  echo "========================================"

  echo "  📊 CEO実行結果観測:"
  EXEC_RESULT_JSON="$SCRIPT_DIR/logs/ceo_agent_execution_result_queue.jsonl"
  if [[ -f "$EXEC_RESULT_JSON" ]]; then
    python3 -c "
import json
with open('$EXEC_RESULT_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
success = sum(1 for r in recs if r.get('status')=='success')
fail    = sum(1 for r in recs if r.get('status')=='fail')
print(f'  total {len(recs)}件 / success {success}件 / fail {fail}件')
if recs:
    lr = recs[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / {lr.get('status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  実行結果なし（config_apply_result から自動収集されます）"
  fi
  echo "========================================"

  echo "  📈 CEOパフォーマンス評価:"
  PERF_EVAL_JSON="$SCRIPT_DIR/logs/ceo_performance_evaluation_queue.jsonl"
  if [[ -f "$PERF_EVAL_JSON" ]]; then
    python3 -c "
import json
with open('$PERF_EVAL_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
improved   = sum(1 for r in recs if r.get('evaluation_result')=='improved')
no_change  = sum(1 for r in recs if r.get('evaluation_result')=='no_change')
degraded   = sum(1 for r in recs if r.get('evaluation_result')=='degraded')
print(f'  improved {improved}件 / no_change {no_change}件 / degraded {degraded}件')
if recs:
    lr = recs[-1]
    delta = lr.get('delta', 0)
    print(f\"  最新: {lr.get('target_agent','—')} / {lr.get('evaluation_result','—')} (delta {delta:+.3f})\")
" 2>/dev/null || echo "  —"
  else
    echo "  性能評価なし（実行結果観測から自動評価されます）"
  fi
  echo "========================================"

  echo "  🔁 CEOフィードバックループ:"
  FEEDBACK_JSON="$SCRIPT_DIR/logs/ceo_feedback_loop_queue.jsonl"
  if [[ -f "$FEEDBACK_JSON" ]]; then
    python3 -c "
import json
with open('$FEEDBACK_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
keep         = sum(1 for r in recs if r.get('feedback_type')=='keep')
minor_adjust = sum(1 for r in recs if r.get('feedback_type')=='minor_adjust')
urgent_fix   = sum(1 for r in recs if r.get('feedback_type')=='urgent_fix')
print(f'  keep {keep}件 / minor_adjust {minor_adjust}件 / urgent_fix {urgent_fix}件')
if recs:
    lr = recs[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / {lr.get('feedback_type','—')} / priority={lr.get('priority','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  フィードバックなし（性能評価から自動生成されます）"
  fi
  echo "========================================"

  echo "  ♻️ CEO再投入優先順位:"
  REINJECT_JSON="$SCRIPT_DIR/logs/ceo_reinject_priority_queue.jsonl"
  if [[ -f "$REINJECT_JSON" ]]; then
    python3 -c "
import json
with open('$REINJECT_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending  = [r for r in recs if r.get('status')=='pending']
critical = sum(1 for r in pending if r.get('reinject_priority_label')=='CRITICAL')
high     = sum(1 for r in pending if r.get('reinject_priority_label')=='HIGH')
medium   = sum(1 for r in pending if r.get('reinject_priority_label')=='MEDIUM')
low      = sum(1 for r in pending if r.get('reinject_priority_label')=='LOW')
print(f'  pending {len(pending)}件 / CRITICAL {critical}件 / HIGH {high}件 / MEDIUM {medium}件 / LOW {low}件')
top1 = sorted(pending, key=lambda r: (r.get('reinject_order',999), -r.get('reinject_priority_score',0)))
if top1:
    t = top1[0]
    print(f\"  1位: {t.get('target_agent','—')} / score {t.get('reinject_priority_score',0):.3f} / {t.get('reinject_priority_label','—')}\")
if pending:
    lr = pending[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / score {lr.get('reinject_priority_score',0):.3f} / {lr.get('reinject_priority_label','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  再投入候補なし（フィードバックループ完了後に自動生成されます）"
  fi
  echo "========================================"

  echo "  📨 CEO再投入ディスパッチ:"
  DISPATCH_JSON="$SCRIPT_DIR/logs/ceo_reinject_dispatch_queue.jsonl"
  if [[ -f "$DISPATCH_JSON" ]]; then
    python3 -c "
import json
with open('$DISPATCH_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('dispatch_status')=='pending']
high    = sum(1 for r in pending if r.get('reinject_priority_label') in ('CRITICAL','HIGH'))
medium  = sum(1 for r in pending if r.get('reinject_priority_label')=='MEDIUM')
print(f'  pending {len(pending)}件 / HIGH+ {high}件 / MEDIUM {medium}件')
top1 = sorted(pending, key=lambda r: (r.get('reinject_order',999), -r.get('reinject_priority_score',0)))
if top1:
    t = top1[0]
    print(f\"  1位: {t.get('target_agent','—')} / score {t.get('reinject_priority_score',0):.3f} / {t.get('reinject_priority_label','—')}\")
if pending:
    lr = pending[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / label {lr.get('reinject_priority_label','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  ディスパッチ候補なし（再投入優先順位から自動生成されます）"
  fi
  echo "========================================"

  echo "  ♻️ CEO限定再投入候補:"
  RETURN_JSON="$SCRIPT_DIR/logs/ceo_reinject_limited_return_queue.jsonl"
  if [[ -f "$RETURN_JSON" ]]; then
    python3 -c "
import json
with open('$RETURN_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('return_status')=='pending']
high    = sum(1 for r in pending if r.get('reinject_priority_label') in ('CRITICAL','HIGH'))
medium  = sum(1 for r in pending if r.get('reinject_priority_label')=='MEDIUM')
print(f'  pending {len(pending)}件 / HIGH+ {high}件 / MEDIUM {medium}件')
top1 = sorted(pending, key=lambda r: (r.get('reinject_order',999), -r.get('reinject_priority_score',0)))
if top1:
    t = top1[0]
    print(f\"  1位: {t.get('target_agent','—')} / score {t.get('reinject_priority_score',0):.3f} / {t.get('reinject_priority_label','—')}\")
if pending:
    lr = pending[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / {lr.get('return_target_lane','limited_execution_queue')} / {lr.get('return_status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  限定再投入候補なし（dispatch_queue から自動生成されます）"
  fi
  echo "========================================"

  echo "  🛡 CEO再投入ゲート:"
  GATE_JSON="$SCRIPT_DIR/logs/ceo_reinject_gate_queue.jsonl"
  if [[ -f "$GATE_JSON" ]]; then
    python3 -c "
import json
with open('$GATE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('gate_status')=='pending']
blocked = [r for r in recs if r.get('gate_status')=='blocked']
print(f'  pending {len(pending)}件 / blocked {len(blocked)}件')
top1 = sorted(pending, key=lambda r: (r.get('reinject_order',999), -r.get('reinject_priority_score',0)))
if top1:
    t = top1[0]
    print(f\"  1位: {t.get('target_agent','—')} / score {t.get('reinject_priority_score',0):.3f} / {t.get('reinject_priority_label','—')}\")
if pending or blocked:
    lr = (pending or blocked)[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / {lr.get('gate_status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  ゲート判定なし（limited_return_queue から自動生成されます）"
  fi
  echo "========================================"

  echo "  🧩 CEO再投入パッチ候補:"
  PATCH_READY_JSON="$SCRIPT_DIR/logs/ceo_reinject_patch_ready_queue.jsonl"
  if [[ -f "$PATCH_READY_JSON" ]]; then
    python3 -c "
import json
with open('$PATCH_READY_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('patch_ready_status')=='pending']
high    = sum(1 for r in pending if r.get('reinject_priority_label') in ('CRITICAL','HIGH'))
medium  = sum(1 for r in pending if r.get('reinject_priority_label')=='MEDIUM')
print(f'  pending {len(pending)}件 / HIGH+ {high}件 / MEDIUM {medium}件')
top1 = sorted(pending, key=lambda r: (r.get('reinject_order',999), -r.get('reinject_priority_score',0)))
if top1:
    t = top1[0]
    print(f\"  1位: {t.get('target_agent','—')} / score {t.get('reinject_priority_score',0):.3f} / {t.get('reinject_priority_label','—')}\")
if pending:
    lr = pending[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / {lr.get('patch_target_lane','ceo_config_patch_plan_queue')} / {lr.get('patch_ready_status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  パッチ接続候補なし（gate_queue から自動生成されます）"
  fi
  echo "========================================"

  echo "  📌 CEO再接続予約:"
  RESERVE_JSON="$SCRIPT_DIR/logs/ceo_reinject_patch_reserve_queue.jsonl"
  if [[ -f "$RESERVE_JSON" ]]; then
    python3 -c "
import json
with open('$RESERVE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending  = [r for r in recs if r.get('reserve_status')=='pending']
critical = sum(1 for r in pending if r.get('reserve_label')=='CRITICAL')
high     = sum(1 for r in pending if r.get('reserve_label')=='HIGH')
medium   = sum(1 for r in pending if r.get('reserve_label')=='MEDIUM')
low      = sum(1 for r in pending if r.get('reserve_label')=='LOW')
print(f'  pending {len(pending)}件 / CRITICAL {critical}件 / HIGH {high}件 / MEDIUM {medium}件 / LOW {low}件')
top1 = sorted(pending, key=lambda r: (r.get('reserve_order',999), -r.get('reserve_priority_score',0)))
if top1:
    t = top1[0]
    print(f\"  1位: {t.get('target_agent','—')} / score {t.get('reserve_priority_score',0):.3f} / {t.get('reserve_label','—')}\")
if pending:
    lr = pending[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / label {lr.get('reserve_label','—')} / order {lr.get('reserve_order','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  再接続予約なし（patch_ready_queue から自動生成されます）"
  fi
  echo "========================================"

  echo "  ✅ CEO再投入コミット:"
  COMMIT_JSON="$SCRIPT_DIR/logs/ceo_reinject_patch_commit_queue.jsonl"
  PATCH_PLAN_JSON="$SCRIPT_DIR/logs/ceo_config_patch_plan_queue.jsonl"
  if [[ -f "$COMMIT_JSON" ]]; then
    python3 -c "
import json
with open('$COMMIT_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('commit_status')=='pending']
# patch_plan の reinject_commit 件数
promoted = 0
try:
    with open('$PATCH_PLAN_JSON') as f2:
        promoted = sum(1 for l in f2 if l.strip() and json.loads(l).get('source')=='reinject_commit')
except: pass
# history の duplicate 件数
dup = 0
try:
    import os
    hist_path = '$COMMIT_JSON'.replace('_queue.jsonl','_history.jsonl')
    if os.path.exists(hist_path):
        with open(hist_path) as f3:
            dup = sum(1 for l in f3 if l.strip() and json.loads(l).get('commit_status') in ('commit_duplicate','patch_plan_duplicate'))
except: pass
print(f'  pending {len(pending)}件 / promoted {promoted}件 / duplicate {dup}件')
top1 = sorted(pending, key=lambda r: (r.get('reserve_order',999), -r.get('reserve_priority_score',0)))
if top1:
    t = top1[0]
    print(f\"  1位: {t.get('target_agent','—')} / score {t.get('reserve_priority_score',0):.3f} / {t.get('reserve_label','—')}\")
if pending:
    lr = pending[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / {lr.get('patch_target_lane','ceo_config_patch_plan_queue')} / {lr.get('commit_status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  コミット待ちなし（patch_reserve_queue から自動生成されます）"
  fi
  echo "========================================"

  echo "  🛡 CEO apply解放ゲート:"
  APPLY_GATE_JSON="$SCRIPT_DIR/logs/ceo_reinject_apply_gate_queue.jsonl"
  if [[ -f "$APPLY_GATE_JSON" ]]; then
    python3 -c "
import json
with open('$APPLY_GATE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('gate_status')=='pending']
blocked = [r for r in recs if r.get('gate_status')=='blocked']
print(f'  pending {len(pending)}件 / blocked {len(blocked)}件 / 全 {len(recs)}件')
top1 = sorted(pending, key=lambda r: -float(r.get('priority_score',0)))
if top1:
    t = top1[0]
    print(f\"  1位: {t.get('target_agent','—')} / score {t.get('priority_score',0):.3f} / {t.get('priority','—')}\")
if pending:
    lr = pending[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / gate_status {lr.get('gate_status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  apply解放ゲート待ちなし（ceo_config_patch_plan_queue から自動生成されます）"
  fi
  echo "========================================"

  echo "  🚦 CEO apply候補レーン:"
  APPLY_READY_JSON="$SCRIPT_DIR/logs/ceo_reinject_apply_ready_queue.jsonl"
  if [[ -f "$APPLY_READY_JSON" ]]; then
    python3 -c "
import json
with open('$APPLY_READY_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('apply_ready_status')=='pending']
high   = sum(1 for r in pending if r.get('priority')=='HIGH')
medium = sum(1 for r in pending if r.get('priority')=='MEDIUM')
print(f'  pending {len(pending)}件 / HIGH {high}件 / MEDIUM {medium}件 / execution_blocked=true')
top1 = sorted(pending, key=lambda r: -float(r.get('priority_score',0)))
if top1:
    t = top1[0]
    print(f\"  1位: {t.get('target_agent','—')} / score {t.get('priority_score',0):.3f} / {t.get('priority','—')}\")
if pending:
    lr = pending[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / {lr.get('next_executor','ceo_config_executor.py')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  apply候補なし（apply_gate_queue から自動生成されます）"
  fi
  echo "========================================"

  echo "  🔓 CEO最終解放候補:"
  UNLOCK_CANDIDATE_JSON="$SCRIPT_DIR/logs/ceo_reinject_apply_unlock_candidate_queue.jsonl"
  UNLOCK_HISTORY_JSON="$SCRIPT_DIR/logs/ceo_reinject_apply_unlock_candidate_history.jsonl"
  if [[ -f "$UNLOCK_CANDIDATE_JSON" ]]; then
    python3 -c "
import json, os
with open('$UNLOCK_CANDIDATE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending  = [r for r in recs if r.get('unlock_candidate_status')=='pending']
critical = sum(1 for r in pending if r.get('priority')=='CRITICAL')
high     = sum(1 for r in pending if r.get('priority')=='HIGH')
blocked  = 0
try:
    if os.path.exists('$UNLOCK_HISTORY_JSON'):
        with open('$UNLOCK_HISTORY_JSON') as fh:
            blocked = sum(1 for l in fh if l.strip() and (json.loads(l).get('status') or '').startswith('blocked_'))
except: pass
print(f'  pending {len(pending)}件 / CRITICAL {critical}件 / HIGH {high}件 / blocked {blocked}件')
top1 = sorted(pending, key=lambda r: (-float(r.get('priority_score',0)), r.get('target_agent','')))
if top1:
    t = top1[0]
    print(f\"  1位: {t.get('target_agent','—')} / score {t.get('priority_score',0):.3f} / {t.get('priority','—')}\")
if pending:
    lr = pending[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / {lr.get('unlock_target','execution_blocked_toggle_only')} / {lr.get('unlock_candidate_status','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  最終解放候補なし（apply_ready_queue から自動生成されます）"
  fi
  echo "========================================"

  echo "  ⚖️ CEO最終解放判定:"
  UNLOCK_JUDGE_JSON="$SCRIPT_DIR/logs/ceo_reinject_unlock_judge_queue.jsonl"
  UNLOCK_JUDGE_HIST_JSON="$SCRIPT_DIR/logs/ceo_reinject_unlock_judge_history.jsonl"
  if [[ -f "$UNLOCK_JUDGE_JSON" ]]; then
    python3 -c "
import json, os
with open('$UNLOCK_JUDGE_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending  = [r for r in recs if r.get('judge_status')=='pending']
critical = sum(1 for r in pending if r.get('priority')=='CRITICAL')
high     = sum(1 for r in pending if r.get('priority')=='HIGH')
blocked  = 0
try:
    if os.path.exists('$UNLOCK_JUDGE_HIST_JSON'):
        with open('$UNLOCK_JUDGE_HIST_JSON') as fh:
            blocked = sum(1 for l in fh if l.strip() and (json.loads(l).get('status') or '').startswith('blocked_'))
except: pass
print(f'  pending {len(pending)}件 / CRITICAL {critical}件 / HIGH {high}件 / blocked {blocked}件')
top1 = sorted(pending, key=lambda r: (-float(r.get('priority_score',0)), r.get('target_agent','')))
if top1:
    t = top1[0]
    print(f\"  1位: {t.get('target_agent','—')} / score {t.get('priority_score',0):.3f} / {t.get('priority','—')}\")
if pending:
    lr = pending[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / {lr.get('judge_result','unlockable_if_unblocked')} / {lr.get('judge_status','—')}\")
print('  ※ 再投入パート終端 — execution_blocked=true / unlock実行は別パート')
" 2>/dev/null || echo "  —"
  else
    echo "  最終解放判定済みなし（unlock_candidate_queue から自動生成されます）"
  fi
  echo "========================================"

  echo "  🔓 CEO解放実行待ち:"
  UNLOCK_EXEC_JSON="$SCRIPT_DIR/logs/ceo_unlock_execute_queue.jsonl"
  if [[ -f "$UNLOCK_EXEC_JSON" ]]; then
    python3 -c "
import json
with open('$UNLOCK_EXEC_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending  = [r for r in recs if r.get('unlock_status')=='pending']
unlocked = [r for r in recs if r.get('unlock_status')=='unlocked']
print(f'  pending {len(pending)}件 / unlocked {len(unlocked)}件 / 全 {len(recs)}件')
top1 = sorted(pending, key=lambda r: (-float(r.get('priority_score',0)), r.get('target_agent','')))
if top1:
    t = top1[0]
    print(f\"  1位: {t.get('target_agent','—')} / score {t.get('priority_score',0):.3f} / {t.get('priority','—')}\")
    print(f\"  unlock: python3 lib/ceo_unlock_executor.py unlock {t.get('duplicate_key','<key>')}\")
if unlocked:
    print(f\"  最新unlock済み: {unlocked[-1].get('target_agent','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  解放実行待ちなし（unlock_judge_queue から自動生成されます）"
  fi
  echo "========================================"

  echo "  📝 CEO apply実行待ち:"
  APPLY_EXEC_JSON="$SCRIPT_DIR/logs/ceo_apply_execute_queue.jsonl"
  if [[ -f "$APPLY_EXEC_JSON" ]]; then
    python3 -c "
import json
with open('$APPLY_EXEC_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
pending = [r for r in recs if r.get('apply_execute_status')=='pending']
print(f'  pending {len(pending)}件 / 全 {len(recs)}件')
top1 = sorted(pending, key=lambda r: (-float(r.get('priority_score',0)), r.get('target_agent','')))
if top1:
    t = top1[0]
    print(f\"  1位: {t.get('target_agent','—')} / {t.get('patch_path','—')} / {t.get('agent_key','—')}\")
    print(f\"  apply 実行: python3 lib/ceo_unlock_executor.py apply\")
" 2>/dev/null || echo "  —"
  else
    echo "  apply実行待ちなし（unlock 実行後に自動昇格されます）"
  fi
  echo "========================================"

  echo "  ✅ CEO apply実行結果:"
  APPLY_RESULT_EXEC_JSON="$SCRIPT_DIR/logs/ceo_apply_execute_result_queue.jsonl"
  if [[ -f "$APPLY_RESULT_EXEC_JSON" ]]; then
    python3 -c "
import json
with open('$APPLY_RESULT_EXEC_JSON') as f:
    recs = [json.loads(l) for l in f if l.strip()]
applied  = sum(1 for r in recs if r.get('result_status')=='applied')
failed   = sum(1 for r in recs if r.get('result_status')=='failed')
blocked  = sum(1 for r in recs if r.get('result_status')=='blocked')
print(f'  applied {applied}件 / failed {failed}件 / blocked {blocked}件 / 全 {len(recs)}件')
if recs:
    lr = recs[-1]
    print(f\"  最新: {lr.get('target_agent','—')} / {lr.get('result_status','—')} / hash={lr.get('config_hash','—')}\")
    if lr.get('backup_path'):
        print(f\"  backup: {lr.get('backup_path','—')}\")
    if lr.get('diff_path'):
        print(f\"  diff:   {lr.get('diff_path','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  apply実行結果なし（apply 実行後に記録されます）"
  fi
  echo "========================================"

  echo "  ⏳ unlock期限管理（AV）:"
  EXPIRY_JSON="$SCRIPT_DIR/logs/ceo_unlock_expiry_queue.jsonl"
  if [[ -f "$EXPIRY_JSON" ]]; then
    python3 -c "
import json
recs = [json.loads(l) for l in open('$EXPIRY_JSON') if l.strip()]
expired = [r for r in recs if r.get('expiry_status') == 'expired']
print(f'  expired {len(expired)}件 / 全{len(recs)}件')
if expired:
    t = expired[-1]
    print(f\"  最新: agent={t.get('target_agent','—')} expires_at={t.get('unlock_expires_at','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  unlock_expiry キューなし"
  fi
  echo "========================================"

  echo "  🔒 post-apply再ロック候補（AW）:"
  POST_LOCK_JSON="$SCRIPT_DIR/logs/ceo_post_apply_lock_queue.jsonl"
  if [[ -f "$POST_LOCK_JSON" ]]; then
    python3 -c "
import json
recs = [json.loads(l) for l in open('$POST_LOCK_JSON') if l.strip()]
pending = [r for r in recs if r.get('status') == 'pending']
print(f'  pending {len(pending)}件 / 全{len(recs)}件')
if pending:
    t = pending[-1]
    print(f\"  最新: agent={t.get('target_agent','—')} registered={t.get('registered_at','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  post_apply_lock キューなし"
  fi
  echo "========================================"

  echo "  ↩️ rollback候補（AX）:"
  ROLLBACK_JSON="$SCRIPT_DIR/logs/ceo_rollback_request_queue.jsonl"
  if [[ -f "$ROLLBACK_JSON" ]]; then
    python3 -c "
import json
recs = [json.loads(l) for l in open('$ROLLBACK_JSON') if l.strip()]
pending = [r for r in recs if r.get('status') == 'pending']
print(f'  pending {len(pending)}件 / 全{len(recs)}件')
if pending:
    t = pending[-1]
    print(f\"  最新: agent={t.get('target_agent','—')} reason={str(t.get('reason',''))[:60]}\")
    print(f\"  rollback: python3 lib/ceo_config_executor.py rollback {t.get('target_agent','<agent>')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  rollback_request キューなし"
  fi
  echo "========================================"

  echo "  🧹 stale operation（AY）:"
  STALE_JSON="$SCRIPT_DIR/logs/ceo_stale_operation_queue.jsonl"
  if [[ -f "$STALE_JSON" ]]; then
    python3 -c "
import json
from collections import Counter
recs = [json.loads(l) for l in open('$STALE_JSON') if l.strip()]
pending = [r for r in recs if r.get('status') == 'pending']
types = Counter(r.get('operation_type','unknown') for r in pending)
print(f'  pending {len(pending)}件 / 全{len(recs)}件')
for t, n in types.items():
    print(f'    {t}: {n}件')
if pending:
    t = pending[-1]
    print(f\"  最新: agent={t.get('target_agent','—')} op={t.get('operation_type','—')} stale_min={t.get('stale_minutes','—')}\")
" 2>/dev/null || echo "  —"
  else
    echo "  stale_operation キューなし"
  fi
  echo "========================================"

  echo "  🚨 Hardening最優先:"
  SUMMARY_JSON="$SCRIPT_DIR/dashboard_summary.json"
  if [[ -f "$SUMMARY_JSON" ]]; then
    python3 -c "
import json
s = json.loads(open('$SUMMARY_JSON').read())
issue   = s.get('hardening_top_issue','none')
prio    = s.get('hardening_top_priority','NONE')
target  = s.get('hardening_top_target','—')
action  = s.get('hardening_required_action','異常なし')
command = s.get('hardening_required_command','bash run_agent_monitor.sh')
reason  = s.get('hardening_escalation_reason','')
esc     = s.get('hardening_is_escalated', False)
print('  ──────────────────────────────────────')
print(f'  issue:   {issue}')
print(f'  priority:{prio}')
print(f'  target:  {target}')
print(f'  action:  {action}')
print(f'  command: {command}')
if reason:
    print(f'  reason:  {reason}')
if esc:
    print('  [ESCALATED] ceo_immediate_action を上書き済み')
print('  ──────────────────────────────────────')
" 2>/dev/null || echo "  dashboard_summary.json 未生成（先に agent_monitor を実行）"
  else
    echo "  dashboard_summary.json なし（先に agent_monitor を実行）"
  fi
  echo "========================================"

  echo "  🧭 CEO運用手順:"
  if [[ -f "$SUMMARY_JSON" ]]; then
    python3 -c "
import json
s = json.loads(open('$SUMMARY_JSON').read())
stage   = s.get('current_operation_stage','monitor_only')
cmd     = s.get('next_required_command','bash run_agent_monitor.sh')
target  = s.get('next_required_target','—')
rb_cmd  = s.get('rollback_command','—')
reason  = s.get('operation_block_reason','—')
conf    = s.get('operation_confidence','LOW')
print('  ──────────────────────────────────────')
print(f'  stage:   {stage}')
print(f'  次コマンド: {cmd}')
print(f'  対象:    {target}')
print(f'  rollback:{rb_cmd}')
print(f'  理由:    {reason}')
print(f'  信頼度:  {conf}')
print('  ──────────────────────────────────────')
" 2>/dev/null || echo "  dashboard_summary.json 未生成（先に agent_monitor を実行）"
  else
    echo "  dashboard_summary.json なし"
  fi
  echo "========================================"

  echo ""
  echo "========================================"
  echo "  ⚡ 今打つべき1コマンド（BB）:"
  if [[ -f "$SUMMARY_JSON" ]]; then
    python3 -c "
import json
s = json.loads(open('$SUMMARY_JSON').read())
cmd    = s.get('ceo_next_command','bash run_agent_monitor.sh')
target = s.get('ceo_next_target','—')
reason = s.get('ceo_next_reason','—')
prio   = s.get('ceo_next_priority','LOW')
stage  = s.get('ceo_next_stage','monitor_only')
print(f'  優先度:  {prio}  stage: {stage}')
print(f'  ▶ {cmd}')
print(f'  対象:    {target}')
print(f'  理由:    {reason}')
" 2>/dev/null || echo "  —"
  else
    echo "  dashboard_summary.json なし"
  fi
  echo "========================================"

  echo "  🔍 apply後判定（BC）:"
  JUDGE_JSON="$SCRIPT_DIR/logs/ceo_post_apply_judge_queue.jsonl"
  if [[ -f "$JUDGE_JSON" ]]; then
    python3 -c "
import json
recs = [json.loads(l) for l in open('$JUDGE_JSON') if l.strip()]
keep = [r for r in recs if r.get('judge_label')=='keep_monitoring']
adj  = [r for r in recs if r.get('judge_label')=='re_adjust_minor']
roll = [r for r in recs if r.get('judge_label')=='rollback_recommended']
print(f'  keep={len(keep)} re_adjust={len(adj)} rollback推奨={len(roll)} 全{len(recs)}件')
if roll:
    t = roll[-1]
    print(f'  最新rollback推奨: {t.get(\"target_agent\",\"—\")} reason={t.get(\"judge_reason\",\"—\")[:60]}')
" 2>/dev/null || echo "  —"
  else
    echo "  post_apply_judge キューなし"
  fi
  echo "========================================"

  echo "  🚦 rollback振り分け（BD）:"
  DISPATCH_JSON="$SCRIPT_DIR/logs/ceo_rollback_dispatch_queue.jsonl"
  WATCH_JSON="$SCRIPT_DIR/logs/ceo_rollback_watch_queue.jsonl"
  python3 -c "
import json, os
dispatch = [json.loads(l) for l in open('$DISPATCH_JSON') if l.strip()] if os.path.exists('$DISPATCH_JSON') else []
watch    = [json.loads(l) for l in open('$WATCH_JSON')    if l.strip()] if os.path.exists('$WATCH_JSON')    else []
dp = [r for r in dispatch if r.get('router_status')=='pending']
wp = [r for r in watch    if r.get('router_status')=='pending']
print(f'  dispatch_pending={len(dp)} watch_pending={len(wp)}')
if dp:
    t = dp[-1]
    print(f'  最新dispatch: {t.get(\"target_agent\",\"—\")} cmd={t.get(\"rollback_command\",\"—\")}')
" 2>/dev/null || echo "  —"
  echo "========================================"

  echo "  🔐 安全不変条件（BG）:"
  INVAR_JSON="$SCRIPT_DIR/logs/ceo_invariant_violation_queue.jsonl"
  if [[ -f "$INVAR_JSON" ]]; then
    python3 -c "
import json
recs = [json.loads(l) for l in open('$INVAR_JSON') if l.strip()]
pending = [r for r in recs if r.get('violation_status')=='pending']
print(f'  violations pending={len(pending)} 全{len(recs)}件')
if pending:
    t = pending[-1]
    print(f'  最新違反: rule={t.get(\"rule\",\"—\")} agent={t.get(\"target_agent\",\"—\")}')
    print(f'  detail: {str(t.get(\"detail\",\"\"))[:80]}')
else:
    print('  ✅ 違反なし')
" 2>/dev/null || echo "  —"
  else
    echo "  ✅ 不変条件違反なし（キューなし）"
  fi
  echo "========================================"

  echo "  🧹 stale cleanup計画（BE）:"
  STALE_PLAN_JSON="$SCRIPT_DIR/logs/ceo_stale_cleanup_plan_queue.jsonl"
  if [[ -f "$STALE_PLAN_JSON" ]]; then
    python3 -c "
import json
exec_path = __import__('pathlib').Path('$SCRIPT_DIR/logs/ceo_unlock_execute_queue.jsonl')
already_unlocked = set()
if exec_path.exists():
    for l in exec_path.open():
        l = l.strip()
        if not l: continue
        try:
            r = json.loads(l)
            if r.get('unlock_status') == 'unlocked' and r.get('actual_unlocked') is True:
                already_unlocked.add(r.get('duplicate_key', ''))
        except: pass
recs = [json.loads(l) for l in open('$STALE_PLAN_JSON') if l.strip()]
pending = [r for r in recs if r.get('plan_status')=='pending'
           and r.get('duplicate_key','') not in already_unlocked]
by_cat = {}
for r in pending:
    c = r.get('category','unknown')
    by_cat[c] = by_cat.get(c, 0) + 1
print(f'  stale_cleanup pending={len(pending)} 全{len(recs)}件')
if by_cat:
    for c, n in by_cat.items():
        print(f'    {c}: {n}件')
if pending:
    t = pending[-1]
    print(f'  最新: agent={t.get(\"target_agent\",\"—\")} cat={t.get(\"category\",\"—\")}')
    print(f'  cmd: {str(t.get(\"cleanup_command\",\"\"))[:80]}')
else:
    print('  ✅ stale cleanup候補なし（unlock済み除外後）')
" 2>/dev/null || echo "  —"
  else
    echo "  ✅ stale cleanup計画なし"
  fi
  echo "========================================"

  echo "  🗺️ ライフサイクルトレース top3（BF）:"
  TRACES_JSON="$SCRIPT_DIR/lifecycle_traces.json"
  if [[ -f "$TRACES_JSON" ]]; then
    python3 -c "
import json
traces = json.loads(open('$TRACES_JSON').read())
for i, t in enumerate(traces[:3]):
    medal = ['🥇','🥈','🥉'][i]
    print(f'  {medal} {t.get(\"agent\",\"—\"):20s} lanes={t.get(\"lane_count\",0):2d} last={t.get(\"latest_lane\",\"—\")}')
    print(f'       {t.get(\"lane_summary\",\"\")}')
if not traces:
    print('  トレースなし')
" 2>/dev/null || echo "  —"
  else
    echo "  lifecycle_traces.json なし"
  fi
  echo "========================================"

  echo "  ⚙️  実行モード（BL）:"
  RUNTIME_MODE_JSON="$SCRIPT_DIR/config/runtime_mode.json"
  if [[ -f "$RUNTIME_MODE_JSON" ]]; then
    python3 -c "
import json
m = json.loads(open('$RUNTIME_MODE_JSON').read())
mode   = m.get('mode','MANUAL')
unlock = m.get('auto_unlock', False)
apply  = m.get('auto_apply', False)
rb     = m.get('auto_rollback', False)
print(f'  mode: {mode}')
print(f'  auto_unlock:   {\"ON\" if unlock else \"OFF\"}')
print(f'  auto_apply:    {\"ON\" if apply  else \"OFF\"} {\"(SAFE_AUTO永久禁止)\" if mode==\"SAFE_AUTO\" else \"\"}')
print(f'  auto_rollback: {\"ON\" if rb     else \"OFF\"}')
print(f'  変更: config/runtime_mode.json の mode を MANUAL / SAFE_AUTO / FULL_AUTO に書き換え')
" 2>/dev/null || echo "  —"
  else
    echo "  config/runtime_mode.json なし"
  fi
  echo "========================================"

  echo "  🤖 AUTO EXECUTION（BM）:"
  AUTO_EXEC_JSON="$SCRIPT_DIR/logs/ceo_auto_exec_log_queue.jsonl"
  AUTO_RB_JSON="$SCRIPT_DIR/logs/ceo_auto_rollback_result_queue.jsonl"
  python3 -c "
import json, os
logs = [json.loads(l) for l in open('$AUTO_EXEC_JSON') if l.strip()] if os.path.exists('$AUTO_EXEC_JSON') else []
rb_r = [json.loads(l) for l in open('$AUTO_RB_JSON')  if l.strip()] if os.path.exists('$AUTO_RB_JSON')  else []
# summary json からこのrun実績
try:
    s = json.loads(open('$SCRIPT_DIR/dashboard_summary.json').read())
    this_unlock = s.get('auto_exec_this_run_unlock', 0)
    this_apply  = s.get('auto_exec_this_run_apply',  0)
    this_rb     = s.get('auto_exec_this_run_rb',     0)
    mode        = s.get('auto_exec_mode', 'MANUAL')
    total_unlock = s.get('auto_exec_unlock_count', 0)
    total_apply  = s.get('auto_exec_apply_count',  0)
    total_rb     = s.get('auto_exec_rollback_count', 0)
    latest_action = s.get('auto_exec_latest_action', '—')
    latest_agent  = s.get('auto_exec_latest_agent',  '—')
    latest_status = s.get('auto_exec_latest_status', '—')
except:
    mode = 'MANUAL'
    this_unlock = this_apply = this_rb = 0
    total_unlock = total_apply = total_rb = 0
    latest_action = latest_agent = latest_status = '—'
print(f'  mode: {mode}')
print(f'  今回実行: unlock={this_unlock} apply={this_apply} rollback={this_rb}')
print(f'  累計実行: unlock={total_unlock} apply={total_apply} rollback={total_rb}')
if logs:
    t = logs[-1]
    print(f'  最新: {t.get(\"action_type\",\"—\")} / {t.get(\"target_agent\",\"—\")} / {t.get(\"exec_status\",\"—\")}')
    print(f'  理由: {str(t.get(\"exec_reason\",\"—\"))[:80]}')
else:
    print('  自動実行ログなし（MANUALモードでは生成されません）')
" 2>/dev/null || echo "  —"
  echo "========================================"

  echo "  🟢 SAFE_AUTO移行判定（BN）:"
  SAFE_AUTO_GATE_JSON="$SCRIPT_DIR/logs/ceo_safe_auto_gate_queue.jsonl"
  if [[ -f "$SAFE_AUTO_GATE_JSON" ]]; then
    python3 -c "
import json
recs = [json.loads(l) for l in open('$SAFE_AUTO_GATE_JSON') if l.strip()]
if not recs:
    print('  safe_auto_gate 未評価')
else:
    r = recs[-1]
    status = r.get('gate_status','—')
    blocked = r.get('blocked_count', 0)
    conf = r.get('confidence','—')
    icon = '✅' if status=='ready' else '🔴'
    print(f'  {icon} gate_status={status} blocked={blocked} confidence={conf}')
    cmd = r.get('top_required_command','—')
    reason = r.get('top_required_reason','—')
    if status != 'ready':
        print(f'  次アクション: {str(cmd)[:120]}')
        print(f'  理由: {str(reason)[:100]}')
    else:
        print('  全条件クリア — SAFE_AUTO移行準備完了')
" 2>/dev/null || echo "  —"
  else
    echo "  safe_auto_gate_queue なし（Phase30未実行）"
  fi
  echo "========================================"

  echo "  🧹 stale解消候補（BO）:"
  STALE_RESOLUTION_JSON="$SCRIPT_DIR/logs/ceo_stale_resolution_queue.jsonl"
  if [[ -f "$STALE_RESOLUTION_JSON" ]]; then
    python3 -c "
import json
from pathlib import Path
# unlock済みキーを除外
exec_path = Path('$SCRIPT_DIR/logs/ceo_unlock_execute_queue.jsonl')
already_unlocked = set()
if exec_path.exists():
    already_unlocked = {r.get('duplicate_key','') for r in [json.loads(l) for l in exec_path.open() if l.strip()]
                        if r.get('unlock_status')=='unlocked' and r.get('actual_unlocked') is True}
recs = [json.loads(l) for l in open('$STALE_RESOLUTION_JSON') if l.strip()]
pending = [r for r in recs if r.get('resolution_status')=='pending' and r.get('duplicate_key','') not in already_unlocked]
high = [r for r in pending if r.get('resolve_priority')=='HIGH']
print(f'  stale解消候補 pending={len(pending)}件 HIGH={len(high)}件')
if pending:
    top = high[0] if high else pending[0]
    print(f'  最優先: {top.get(\"target_agent\",\"—\")} ({top.get(\"resolve_action\",\"—\")} / {top.get(\"resolve_priority\",\"—\")})')
    print(f'  提案コマンド: {str(top.get(\"suggested_command\",\"—\"))[:120]}')
    print(f'  stale経過: {top.get(\"stale_minutes\",0):.1f}分')
else:
    print('  stale解消候補なし（unlock済み含む）')
" 2>/dev/null || echo "  —"
  else
    echo "  stale_resolution_queue なし（Phase31未実行）"
  fi
  echo "========================================"

  echo "  🎯 unlock最終候補（BP）:"
  UNLOCK_PICK_JSON="$SCRIPT_DIR/logs/ceo_unlock_pick_queue.jsonl"
  if [[ -f "$UNLOCK_PICK_JSON" ]]; then
    python3 -c "
import json
recs = [json.loads(l) for l in open('$UNLOCK_PICK_JSON') if l.strip()]
top1 = next((r for r in reversed(recs) if r.get('is_top') and r.get('pick_status') in ('active','pending')), None)
total = len([r for r in recs if r.get('pick_status') in ('active','pending')])
print(f'  unlock_pick候補 total={total}件')
if top1:
    rev = '💰' if top1.get('is_revenue') else ''
    print(f'  {rev} TOP1: {top1.get(\"target_agent\",\"—\")} (score={top1.get(\"pick_score\",0)} priority={top1.get(\"priority\",\"—\")})')
    print(f'  ▶ コマンド: {str(top1.get(\"command\",\"—\"))[:120]}')
    print(f'  理由: {str(top1.get(\"why_now\",\"—\"))[:100]}')
    print(f'  rollback: {str(top1.get(\"rollback_command\",\"—\"))[:80]}')
else:
    print('  top1候補なし（stale/invariant除外 or judge_queue empty）')
" 2>/dev/null || echo "  —"
  else
    echo "  unlock_pick候補なし（stale/invariant除外により candidates=0）"
  fi
  echo "========================================"

  echo "  🚦 モード移行チェック（BQ）:"
  MODE_TRANSITION_JSON="$SCRIPT_DIR/logs/ceo_mode_transition_queue.jsonl"
  if [[ -f "$MODE_TRANSITION_JSON" ]]; then
    python3 -c "
import json, os
recs = [json.loads(l) for l in open('$MODE_TRANSITION_JSON') if l.strip()]
# 現在モード確認
mode = 'MANUAL'
mode_path = '$SCRIPT_DIR/config/runtime_mode.json'
try:
    mode = json.loads(open(mode_path).read()).get('mode', 'MANUAL')
except Exception:
    pass
already_in_safe_auto = mode in ('SAFE_AUTO', 'FULL_AUTO')
if not recs:
    print('  モード移行チェック 未実行')
else:
    r = recs[-1]
    all_green = r.get('all_green', False)
    failed = r.get('failed_count', 0)
    status = r.get('transition_status','—')
    if already_in_safe_auto:
        print(f'  ✅ モード移行完了済み（現在: {mode}） — チェック不要')
    else:
        icon = '✅' if all_green else '❌'
        print(f'  {icon} transition_status={status} failed={failed}件')
        items = r.get('check_items', [])
        for item in items:
            ok_icon = '✅' if item.get('ok') else '❌'
            print(f'    {ok_icon} {item.get(\"name\",\"—\")} ({item.get(\"current\",\"—\")})')
        if not all_green:
            cmd = r.get('next_command','—')
            reason = r.get('next_reason','—')
            print(f'  次アクション: {str(cmd)[:120]}')
            print(f'  未クリア理由: {str(reason)[:100]}')
        else:
            print('  全チェック通過 — SAFE_AUTO切替コマンドを確認してください')
" 2>/dev/null || echo "  —"
  else
    echo "  mode_transition_queue なし（Phase33未実行）"
  fi
  echo "========================================"

  echo "  🔓 unlock前最終説明（BH）:"
  UNLOCK_EXPLAIN_JSON="$SCRIPT_DIR/logs/ceo_unlock_explain_queue.jsonl"
  if [[ -f "$UNLOCK_EXPLAIN_JSON" ]]; then
    python3 -c "
import json
recs = [json.loads(l) for l in open('$UNLOCK_EXPLAIN_JSON') if l.strip()]
pending = [r for r in recs if r.get('explain_status')=='pending']
print(f'  unlock_explain pending={len(pending)}件 全{len(recs)}件')
if pending:
    t = pending[-1]
    print(f'  対象:   {t.get(\"target_agent\",\"—\")} (priority={t.get(\"priority\",\"—\")} score={t.get(\"priority_score\",0):.4f})')
    print(f'  ▶ 手動コマンド:')
    print(f'    {str(t.get(\"next_manual_command\",\"—\"))[:120]}')
    print(f'  理由:   {str(t.get(\"why_now\",\"—\"))[:100]}')
    print(f'  打つと: {str(t.get(\"what_changes\",\"—\"))[:100]}')
    print(f'  次stage: {t.get(\"expected_next_stage\",\"—\")}')
    print(f'  失敗時: {str(t.get(\"rollback_command\",\"—\"))[:80]}')
else:
    print('  unlock 実行前説明なし（unlock_execute pending なし）')
" 2>/dev/null || echo "  —"
  else
    echo "  unlock_explain_queue なし"
  fi
  echo "========================================"

  echo "  📝 apply前最終説明（BI）:"
  APPLY_EXPLAIN_JSON="$SCRIPT_DIR/logs/ceo_apply_explain_queue.jsonl"
  if [[ -f "$APPLY_EXPLAIN_JSON" ]]; then
    python3 -c "
import json
recs = [json.loads(l) for l in open('$APPLY_EXPLAIN_JSON') if l.strip()]
pending = [r for r in recs if r.get('explain_status')=='pending']
print(f'  apply_explain pending={len(pending)}件 全{len(recs)}件')
if pending:
    t = pending[-1]
    print(f'  対象:        {t.get(\"target_agent\",\"—\")}')
    print(f'  patch_path:  {t.get(\"patch_path\",\"—\")}')
    print(f'  after_value: {str(t.get(\"after_value\",\"—\"))[:80]}')
    print(f'  target_config: {t.get(\"target_config\",\"—\")}')
    print(f'  backup_path: {t.get(\"backup_path\",\"—\")}')
    print(f'  ▶ 手動コマンド:')
    print(f'    {str(t.get(\"next_manual_command\",\"—\"))[:100]}')
else:
    print('  apply 実行前説明なし（apply_execute pending なし）')
" 2>/dev/null || echo "  —"
  else
    echo "  apply_explain_queue なし"
  fi
  echo "========================================"

  echo "  🚫 実行禁止条件（BJ）:"
  FINAL_BLOCK_JSON="$SCRIPT_DIR/logs/ceo_final_block_queue.jsonl"
  if [[ -f "$FINAL_BLOCK_JSON" ]]; then
    python3 -c "
import json
exec_path = __import__('pathlib').Path('$SCRIPT_DIR/logs/ceo_unlock_execute_queue.jsonl')
already_unlocked = set()
if exec_path.exists():
    for l in exec_path.open():
        l = l.strip()
        if not l: continue
        try:
            r = json.loads(l)
            if r.get('unlock_status') == 'unlocked' and r.get('actual_unlocked') is True:
                already_unlocked.add(r.get('duplicate_key', ''))
        except: pass
recs = [json.loads(l) for l in open('$FINAL_BLOCK_JSON') if l.strip()]
blocked = [r for r in recs if r.get('block_status')=='blocked'
           and r.get('duplicate_key','') not in already_unlocked]
ready   = [r for r in recs if r.get('block_status')=='ready']
print(f'  禁止={len(blocked)}件 / 実行可={len(ready)}件 / 全{len(recs)}件')
if blocked:
    t = blocked[-1]
    reasons = t.get('blocked_reason',[])
    print(f'  最新禁止: agent={t.get(\"target_agent\",\"—\")} type={t.get(\"check_type\",\"—\")}')
    for r in reasons[:3]:
        print(f'    ・{r}')
    if len(reasons) > 3:
        print(f'    ...他{len(reasons)-3}件')
else:
    print('  ✅ 実行禁止条件なし（unlock済み除外後）')
" 2>/dev/null || echo "  —"
  else
    echo "  ✅ 実行禁止条件チェック未実行"
  fi
  echo "========================================"

  echo "  ✅ 実行後確認チェックリスト（BK）:"
  CHECKLIST_JSON="$SCRIPT_DIR/logs/ceo_post_command_checklist_queue.jsonl"
  if [[ -f "$CHECKLIST_JSON" ]]; then
    python3 -c "
import json
recs = [json.loads(l) for l in open('$CHECKLIST_JSON') if l.strip()]
pending = [r for r in recs if r.get('checklist_status')=='active']
print(f'  チェックリスト active={len(pending)}件 全{len(recs)}件')
if pending:
    t = pending[-1]
    items = t.get('items',[])
    print(f'  対象: {t.get(\"target_agent\",\"—\")} / stage: {t.get(\"stage\",\"—\")} / 項目数: {len(items)}')
    for item in items[:3]:
        print(f'  {item.get(\"order\",\"?\")}.  {item.get(\"item\",\"—\")[:80]}')
    if len(items) > 3:
        print(f'     ...他{len(items)-3}項目')
else:
    print('  確認チェックリストなし（unlock/apply pending がなければ生成されません）')
" 2>/dev/null || echo "  —"
  else
    echo "  確認チェックリストなし"
  fi
  echo "========================================"
}

if [[ "$MODE" == "--watch" ]]; then
  echo "[WATCH] 5分ごとに自動更新します (Ctrl+C で終了)"
  run_once
  while true; do
    sleep 300
    echo ""
    echo "[WATCH] 更新: $(date '+%H:%M:%S')"
    python3 "$SCRIPT_DIR/lib/agent_monitor.py" 2>&1 | grep -E "✅|❌|ERROR" || true
    python3 "$SCRIPT_DIR/generate_dashboard.py"
    python3 "$SCRIPT_DIR/lib/discord_notifier.py" 2>&1 | grep -E "CRITICAL|WARNING|送信" || true
    echo "[WATCH] ✅ 更新完了"
  done

elif [[ "$MODE" == "--cron" ]]; then
  # cronモード: サイレント実行（エラーのみ出力）
  python3 "$SCRIPT_DIR/lib/agent_monitor.py" 2>/dev/null
  python3 "$SCRIPT_DIR/generate_dashboard.py" 2>/dev/null
  python3 "$SCRIPT_DIR/lib/discord_notifier.py" 2>/dev/null || true
  python3 "$SCRIPT_DIR/lib/alert_queue.py" --retry 2>/dev/null || true

else
  run_once
fi
