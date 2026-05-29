#!/bin/bash
# ============================================================
# gsc_index_watch.sh — 新規公開記事のGSCインデックス反映 監視(2026-05-30)
#
# 役割: 当日まで育てるイベント系シリーズ等の新規記事が Google に
#   インデックスされたかを毎朝チェックし、状態をログ+Discord通知する。
#   GSC URL Inspection API を使うため、google_metrics/service_account.json
#   (.gitignore対象=このローカル環境にのみ存在) が必要。クラウド実行不可。
#
# 対象URLは data/gsc_index_watch_targets.txt (1行1スラッグ) で管理。
#   全URLが "Submitted and indexed" になったら、その旨を通知し
#   targets を空にする運用(=監視終了)を促す。
#
# ログ: ~/.kpop_recovery/gsc_watch/watch_YYYYMMDD.log
# 通知: config/discord_webhooks.json の "daily_ceo_report"(あれば)
#
# 使い方:
#   bash gsc_index_watch.sh            # 通常(通知あり)
#   GSC_WATCH_DRY_RUN=1 bash ...       # 通知スキップ
# ============================================================
set -uo pipefail
cd "$(dirname "$0")"

PY=venv_kpi/bin/python3
TARGETS=data/gsc_index_watch_targets.txt
LOGDIR="$HOME/.kpop_recovery/gsc_watch"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/watch_$(date +%Y%m%d).log"

{
  echo "===== GSC index watch $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
  if [ ! -s "$TARGETS" ]; then
    echo "監視対象なし (target list 空)。監視終了状態。"
    exit 0
  fi
  "$PY" - "$TARGETS" <<'PY'
import sys, json, urllib.request
from google.oauth2 import service_account
from google.auth.transport.requests import Request

SA = 'google_metrics/service_account.json'
SITE = 'https://www.kpopjournal.tokyo/'
EP = 'https://searchconsole.googleapis.com/v1/urlInspection/index:inspect'

slugs = [l.strip() for l in open(sys.argv[1], encoding='utf-8') if l.strip() and not l.startswith('#')]
try:
    creds = service_account.Credentials.from_service_account_file(
        SA, scopes=['https://www.googleapis.com/auth/webmasters.readonly'])
    creds.refresh(Request())
    tok = creds.token
except Exception as e:
    print(f"✗ GSC認証失敗(コード/権限正常でも鍵失効の可能性): {e}")
    sys.exit(1)

indexed, pending = [], []
for s in slugs:
    u = f'{SITE}{s}/'
    try:
        r = json.load(urllib.request.urlopen(urllib.request.Request(
            EP, data=json.dumps({'inspectionUrl': u, 'siteUrl': SITE}).encode(),
            headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'}), timeout=30))
        cov = r.get('inspectionResult', {}).get('indexStatusResult', {}).get('coverageState', '?')
    except Exception as e:
        cov = f'ERR {str(e)[:40]}'
    line = f"  {s}: {cov}"
    print(line)
    (indexed if cov == 'Submitted and indexed' else pending).append(s)

print(f"\n--- 集計: indexed {len(indexed)}/{len(slugs)} ---")
if pending:
    print("未反映(クロール待ち):")
    for s in pending:
        print(f"   ・{s}")
else:
    print("🎉 全対象がインデックス済み。data/gsc_index_watch_targets.txt を空にして監視を終了できます。")
PY
} 2>&1 | tee -a "$LOG"

# Discord通知(任意・失敗してもcronは継続)
if [ "${GSC_WATCH_DRY_RUN:-0}" != "1" ] && [ -f lib/discord_notifier.py ]; then
  SUMMARY="$(tail -20 "$LOG")"
  "$PY" lib/discord_notifier.py --channel daily_ceo_report \
       --message "【GSCインデックス監視】$(date +%m/%d)"$'\n'"$SUMMARY" 2>/dev/null || true
fi
