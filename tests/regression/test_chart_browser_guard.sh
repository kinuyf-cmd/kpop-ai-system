#!/usr/bin/env bash
# Soompi チャート更新スクリプトが、Playwright ブラウザ欠落を
# 「無言で据え置き」にせず、自己修復と通知を行うことを検証する。
#
# 2026-08-23: ブラウザ実体が消えた状態で 16回連続 exit 0 して無通知だった。
# 本番のチャートは August Week 2 のまま8日間止まっていた。
set -uo pipefail
S="$(cd "$(dirname "$0")/../.." && pwd)/tools/chart/cron_update_soompi_chart.sh"
fail=0
chk() { if eval "$2"; then echo "  ✓ $1"; else echo "  ✗ $1"; fail=1; fi; }

chk "ブラウザ存在チェックがある"        "grep -q 'ensure_browser\|playwright install' '$S'"
chk "自動インストールを試みる"          "grep -q 'playwright install' '$S'"
chk "URL発見失敗を連続回数で検知する"   "grep -q 'FAIL_STREAK\|fail_streak' '$S'"
chk "失敗が続いたらDiscord通知する"     "grep -q 'notify\|discord' '$S'"
chk "非破壊(失敗時に既存を消さない)"    "grep -q '既存維持' '$S'"
# INSTALLATION_COMPLETE マーカーが残っていると playwright install は実体が
# 無くてもスキップする。マーカーを消してから入れ直す必要がある。
chk "installスキップ対策(マーカー除去)"  "grep -q 'INSTALLATION_COMPLETE' '$S'"
[ "$fail" = 0 ] && echo "PASS" || { echo "FAIL"; exit 1; }
