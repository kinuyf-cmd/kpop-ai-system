#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# auto_repair.sh — porygon_z による自律調査・修復ループ
#
# 使用法:
#   bash ai_company/auto_repair.sh              # 通常実行
#   bash ai_company/auto_repair.sh --dry-run    # コマンド実行なし、確認のみ
#
# cronから: 毎日 6:05 に実行（前夜の未解決問題を朝イチで処理）
# watchdogから: エラー検知時にバックグラウンド呼び出し
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$BASE/logs"
REPAIR_LOG="$LOGS/auto_repair.log"

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
fi

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S JST')] $*" | tee -a "$REPAIR_LOG"
}

log "=== auto_repair.sh 開始 (dry_run=$DRY_RUN) ==="

# ── 環境セットアップ ──────────────────────────────────────────
export PATH="/home/aiuser/.local/bin:$PATH"
if [ -f "$BASE/.venv/bin/activate" ]; then
  source "$BASE/.venv/bin/activate"
fi
if [ -f "$BASE/env_loader.sh" ]; then
  source "$BASE/env_loader.sh"
fi

# ── 1. データ収集 ─────────────────────────────────────────────
log "--- [1/3] データ収集中 ---"

# watchdog_alerts.jsonl: 直近24h
ALERTS_DATA=""
if [ -f "$LOGS/watchdog_alerts.jsonl" ]; then
  ALERTS_DATA=$(python3 - <<'PYEOF'
import json, sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
since = now - timedelta(hours=24)
path = Path("/home/aiuser/kpop-ai-system/logs/watchdog_alerts.jsonl")
rows = []
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
            ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
        if ts >= since:
            rows.append(r)
    except Exception:
        pass
if rows:
    for r in rows[-20:]:
        print(f"  [{r.get('ts','')}] [{r.get('check','')}] {r.get('message','')[:100]}")
else:
    print("  直近24hのアラートなし")
PYEOF
)
fi

# pipeline.jsonl: 直近エラー
PIPELINE_ERRORS=""
if [ -f "$LOGS/pipeline.jsonl" ]; then
  PIPELINE_ERRORS=$(python3 - <<'PYEOF'
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
since = datetime.now(JST) - timedelta(hours=24)
path = Path("/home/aiuser/kpop-ai-system/logs/pipeline.jsonl")
rows = []
for line in path.read_text(errors="replace").splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        r = json.loads(line)
        if r.get("status") != "error":
            continue
        ts_str = r.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(JST)
        except Exception:
            continue
        if ts >= since:
            rows.append(r)
    except Exception:
        pass
if rows:
    for r in rows[-10:]:
        print(f"  [{r.get('timestamp','')}] step={r.get('step','')} msg={r.get('message','')[:100]}")
else:
    print("  直近24hのpipelineエラーなし")
PYEOF
)
fi

# 各パイプラインログの末尾20行
PIPELINE_LOG_TAILS=""
declare -A PIPELINE_LOGS=(
  ["速報"]="/home/aiuser/ai_kpop.log"
  ["美容"]="$LOGS/beauty_pipeline.log"
  ["戦略"]="$LOGS/strategy_pipeline.log"
  ["ライフスタイル"]="$LOGS/lifestyle_pipeline.log"
  ["ファッション"]="$LOGS/fashion_pipeline.log"
)
for label in "${!PIPELINE_LOGS[@]}"; do
  logfile="${PIPELINE_LOGS[$label]}"
  if [ -f "$logfile" ]; then
    tail_content=$(tail -n 20 "$logfile" 2>/dev/null || echo "(読み取り失敗)")
    PIPELINE_LOG_TAILS="${PIPELINE_LOG_TAILS}
=== ${label}パイプライン末尾 ($(stat -c '%y' "$logfile" 2>/dev/null | cut -c1-16)) ===
${tail_content}"
  else
    PIPELINE_LOG_TAILS="${PIPELINE_LOG_TAILS}
=== ${label}パイプライン: ログファイルなし ==="
  fi
done

# x_post.log: 直近30行
X_POST_LOG=""
if [ -f "$LOGS/x_post.log" ]; then
  X_POST_LOG=$(tail -n 30 "$LOGS/x_post.log" 2>/dev/null || echo "(読み取り失敗)")
fi

# x_failsafe.jsonl: 全内容
X_FAILSAFE=""
if [ -f "$LOGS/x_failsafe.jsonl" ]; then
  X_FAILSAFE=$(cat "$LOGS/x_failsafe.jsonl" 2>/dev/null || echo "(読み取り失敗)")
  [ -z "$X_FAILSAFE" ] && X_FAILSAFE="(空 = フェイルセーフ未発動)"
fi

# watchdog_repairs.jsonl: 直近24h
RECENT_REPAIRS=""
if [ -f "$LOGS/watchdog_repairs.jsonl" ]; then
  RECENT_REPAIRS=$(python3 - <<'PYEOF'
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
since = datetime.now(JST) - timedelta(hours=24)
path = Path("/home/aiuser/kpop-ai-system/logs/watchdog_repairs.jsonl")
rows = []
for line in path.read_text(errors="replace").splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        r = json.loads(line)
        ts_str = r.get("ts", "")
        try:
            ts = datetime.fromisoformat(ts_str).astimezone(JST)
        except Exception:
            continue
        if ts >= since:
            rows.append(r)
    except Exception:
        pass
if rows:
    for r in rows[-10:]:
        print(f"  [{r.get('ts','')}] {r.get('action','')} : {r.get('message','')[:100]}")
else:
    print("  直近24hの自動修復なし")
PYEOF
)
fi

log "データ収集完了"

# ── 2. porygon_z エージェント呼び出し ─────────────────────────
log "--- [2/3] porygon_z に自律調査・修復指示 ---"

PROMPT="あなたはSRE責任者（ポリゴンZ）です。
以下のシステムデータを読み、自律的に問題を調査・修復してください。
「人間が気づく前に自分で気づき、自分で直す」が原則です。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【watchdog_alerts.jsonl（直近24h）】
${ALERTS_DATA}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【pipeline.jsonl エラー（直近24h）】
${PIPELINE_ERRORS}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【各パイプラインログ末尾】
${PIPELINE_LOG_TAILS}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【x_post.log（直近30行）】
${X_POST_LOG}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【x_failsafe.jsonl】
${X_FAILSAFE}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【watchdog_repairs.jsonl（直近24h）】
${RECENT_REPAIRS}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 出力指示

以下の順に必ず出力してください。

### 1. 調査結果サマリー
- 検知した問題を箇条書きで（根拠はログの事実のみ）
- 「問題なし」の場合は根拠を示して「前24h: 異常ゼロ」と明記

### 2. 修復アクション
修復が必要な場合、以下のアクションリストから選んで ACTION: 行として出力してください。
不要な場合・人間対応が必要な場合もその旨を明記してください。

利用可能なアクションとフォーマット（全て「ACTION: 」プレフィックス必須）:

  # フェイルセーフ解除
  ACTION: bash -c 'echo -n > /home/aiuser/kpop-ai-system/logs/x_failsafe.jsonl'

  # Googleインデックス再送信（URLを実際のものに置換）
  ACTION: bash /home/aiuser/kpop-ai-system/google_metrics/request_index.sh <URL>

  # パイプライン再実行（スクリプト名を実際のものに置換）
  ACTION: bash /home/aiuser/kpop-ai-system/<pipeline>.sh

  # Discord #urgent_errors に通知（メッセージを実際のものに置換）
  ACTION: bash /home/aiuser/kpop-ai-system/kpop_notify.sh error auto_repair \"<メッセージ>\"

  # 複数アクションが必要な場合はACTION:行を複数出力
  # 人間対応が必要な場合: ACTION: HUMAN_REQUIRED <理由>

### 3. 修復後の確認コメント
- 実行したアクションの期待効果
- 次回watchdog実行（30分後）での確認ポイント
- 再発防止提案（あれば）

### 注意事項
- ログの事実のみ報告（推測で補完しない）
- 質問しない・前置きしない・必ず出力する
- 修復アクションは実行可能なコマンドのみ
- archive_and_exit code=1 はNGワード検出による正常終了（パイプライン停止ではない）場合もある
"

# claude呼び出し
CLAUDE_OUTPUT=$(claude --dangerously-skip-permissions --agent porygon_z -p "$PROMPT" 2>&1) || true

log "porygon_z 応答受信（${#CLAUDE_OUTPUT}文字）"

# 応答をログに保存
{
  echo ""
  echo "=== porygon_z 応答 [$(date '+%Y-%m-%d %H:%M:%S')] ==="
  echo "$CLAUDE_OUTPUT"
  echo "=== 応答終了 ==="
  echo ""
} >> "$REPAIR_LOG"

# ── 3. ACTION行をパースして実行 ──────────────────────────────
log "--- [3/3] アクション実行 ---"

ACTION_COUNT=0
ACTIONS_EXECUTED=()
HUMAN_REQUIRED=()

while IFS= read -r line; do
  # ACTION: プレフィックスの行を抽出（空白を許容）
  if [[ "$line" =~ ^[[:space:]]*ACTION:[[:space:]](.+)$ ]]; then
    cmd="${BASH_REMATCH[1]}"
    cmd="${cmd#"${cmd%%[![:space:]]*}"}"  # 先頭空白除去

    # HUMAN_REQUIRED は実行しない
    if [[ "$cmd" == HUMAN_REQUIRED* ]]; then
      reason="${cmd#HUMAN_REQUIRED }"
      HUMAN_REQUIRED+=("$reason")
      log "  [HUMAN_REQUIRED] $reason"
      continue
    fi

    ACTION_COUNT=$((ACTION_COUNT + 1))
    log "  [ACTION #$ACTION_COUNT] $cmd"

    if [ "$DRY_RUN" = true ]; then
      log "    -> [DRY-RUN] 実行スキップ"
      ACTIONS_EXECUTED+=("[DRY-RUN] $cmd")
    else
      # コマンド実行（エラーは握り潰さずログに記録）
      set +e
      exec_output=$(cd "$BASE" && eval "$cmd" 2>&1)
      exec_exit=$?
      set -e

      if [ $exec_exit -eq 0 ]; then
        log "    -> 実行成功 (exit=$exec_exit)"
        [ -n "$exec_output" ] && log "    出力: ${exec_output:0:200}"
        ACTIONS_EXECUTED+=("OK: $cmd")
      else
        log "    -> 実行失敗 (exit=$exec_exit): ${exec_output:0:200}"
        ACTIONS_EXECUTED+=("FAIL(exit=$exec_exit): $cmd")
      fi
    fi
  fi
done <<< "$CLAUDE_OUTPUT"

if [ $ACTION_COUNT -eq 0 ]; then
  log "  アクションなし（問題なし or 人間対応必要）"
fi

# ── Discord に修復結果を通知 ──────────────────────────────────
# アクションがあった場合 or HUMAN_REQUIREDがあった場合のみ通知
NOTIFY_NEEDED=false
[ ${#ACTIONS_EXECUTED[@]} -gt 0 ] && NOTIFY_NEEDED=true
[ ${#HUMAN_REQUIRED[@]} -gt 0 ] && NOTIFY_NEEDED=true

if [ "$NOTIFY_NEEDED" = true ] && [ "$DRY_RUN" = false ]; then
  NOTIFY_MSG="auto_repair 完了 ($(date '+%m/%d %H:%M'))"

  if [ ${#ACTIONS_EXECUTED[@]} -gt 0 ]; then
    NOTIFY_MSG="${NOTIFY_MSG}\n実行アクション(${#ACTIONS_EXECUTED[@]}件):"
    for a in "${ACTIONS_EXECUTED[@]}"; do
      NOTIFY_MSG="${NOTIFY_MSG}\n  • ${a:0:100}"
    done
  fi

  if [ ${#HUMAN_REQUIRED[@]} -gt 0 ]; then
    NOTIFY_MSG="${NOTIFY_MSG}\n人間対応必要(${#HUMAN_REQUIRED[@]}件):"
    for h in "${HUMAN_REQUIRED[@]}"; do
      NOTIFY_MSG="${NOTIFY_MSG}\n  ⚠️ ${h:0:100}"
    done
  fi

  # Discord通知（discord_channels.sh 経由）
  source "$BASE/lib/discord_channels.sh" 2>/dev/null || true
  WEBHOOK=$(get_discord_webhook "urgent_errors" 2>/dev/null || echo "")
  if [ -z "$WEBHOOK" ] && [ -f ~/.kpop_discord_webhook ]; then
    WEBHOOK=$(cat ~/.kpop_discord_webhook | tr -d '[:space:]')
  fi

  if [ -n "$WEBHOOK" ]; then
    STATUS_ICON="🔧"
    [ ${#HUMAN_REQUIRED[@]} -gt 0 ] && STATUS_ICON="⚠️"
    python3 - <<PYEOF 2>/dev/null || true
import json, urllib.request
webhook = "$WEBHOOK"
msg = """${NOTIFY_MSG}"""
payload = json.dumps({
    "username": "auto_repair",
    "embeds": [{
        "title": "${STATUS_ICON} [自律修復] auto_repair.sh 実行結果",
        "description": msg.replace("\\n", "\n")[:2000],
        "color": 0xFF9900 if "HUMAN_REQUIRED" in msg else 0x00CC00,
    }]
}).encode()
req = urllib.request.Request(webhook, data=payload,
    headers={"Content-Type": "application/json"}, method="POST")
urllib.request.urlopen(req, timeout=10)
print("Discord通知完了")
PYEOF
    log "Discord #urgent_errors に通知完了"
  else
    log "Discord webhook未設定 → 通知スキップ"
  fi
fi

log "=== auto_repair.sh 完了 (actions=$ACTION_COUNT, human_required=${#HUMAN_REQUIRED[@]}) ==="
