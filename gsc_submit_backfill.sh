#!/bin/bash
# gsc_submit_backfill.sh — 公開済みだが未申請の記事を毎朝 GSC Indexing API に申請する。
#
# 背景: post_publish_hook は今後の自動投稿をカバーするが、popup等フックを通らない
#       経路や過去分の漏れは残る。本スクリプトが日次でDB公開記事 vs 申請ログを
#       突合し、未申請をクォータ内(180/日)で価値順に申請する=漏れの恒久ゼロ化。
# 認証: venv_kpi(google-auth) + service_account.json。ローカル限定。
set -euo pipefail
cd "$(dirname "$0")"

RO=/usr/local/sbin/kpop/kpop-wp-ro
LOG_DIR="$HOME/.kpop_recovery/gsc_watch"
mkdir -p "$LOG_DIR"
TS=$(date '+%Y-%m-%d %H:%M:%S')
echo "[$TS] ===== gsc_submit_backfill 開始 ====="

# DB公開記事の slug 一覧を取得
sudo -n "$RO" post list --post_type=post --post_status=publish --fields=post_name --format=json 2>/dev/null > /tmp/gsc_bf_posts.json || {
  echo "[$TS] DB取得失敗 → skip"; exit 0; }

venv_kpi/bin/python3 <<'PY'
import sys, json, re
sys.path.insert(0, '.')
from lib.gsc_indexing import notify_url_updated, get_quota_remaining

# 申請済み slug
submitted = set()
try:
    for line in open('data/gsc_indexing_log.jsonl'):
        line = line.strip()
        if not line: continue
        try: d = json.loads(line)
        except: continue
        # 実際に Google へ届いた成功系のみ「申請済み」とみなす。
        # quota_exceeded/error/failed は未送信なので除外し、翌日に再送する。
        if d.get('status') not in ('ok', 'skipped_dup'): continue
        m = re.search(r'tokyo/([^/?#]+)', d.get('url', ''))
        if m: submitted.add(m.group(1))
except FileNotFoundError:
    pass

posts = json.load(open('/tmp/gsc_bf_posts.json'))
slugs = [p.get('post_name', '') for p in posts if p.get('post_name')]
never = [s for s in slugs if s not in submitted]

# 価値順: 非popup(通常記事)を先に、popupを後に
non_popup = [s for s in never if not s.startswith('popup-')]
popup = [s for s in never if s.startswith('popup-')]
ordered = non_popup + popup

if not ordered:
    print("  未申請なし → 完了(漏れゼロ)")
    raise SystemExit

BASE = "https://www.kpopjournal.tokyo/"
ok = quota = err = 0
for slug in ordered:
    if get_quota_remaining() <= 0:
        quota += 1
        continue
    try:
        r = notify_url_updated(f"{BASE}{slug}/")
        if r.get('status') == 'ok': ok += 1
        else: err += 1
    except Exception:
        err += 1
print(f"  未申請 {len(ordered)}件中: 申請成功 {ok} / クォータ保留 {quota} / エラー {err}")
print(f"  残量 {get_quota_remaining()}件")
PY

echo "[$TS] ===== gsc_submit_backfill 完了 ====="
