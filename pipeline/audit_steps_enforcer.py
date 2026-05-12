#!/usr/bin/env python3
"""4項目監査未達記事の自動draft化 (2026-05-10新設)

cron想定 (15分間隔推奨):
  */15 * * * * cd /home/aiuser/kpop-ai-system && python3 pipeline/audit_steps_enforcer.py >> logs/audit_steps_enforcer.log 2>&1

動作:
  1. 直近30分以内に publish された記事を取得
  2. 各記事について audit_steps.jsonl の 4項目entry を確認
  3. publish後30分以内に4項目揃わない → status='draft' へ自動戻し
  4. Slack通知 (オプション)

これにより「私(claude)が監査を省略しても、cron が回路から外れた状態で再検証→未達なら強制 draft化」
を実現。memory「監査は4項目セット必須」のprocedural強制機構。
"""
import sys, os, json, subprocess
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.audit_steps_log import is_fully_audited, missing_steps, REQUIRED_STEPS

WP_BASE = 'https://www.kpopjournal.tokyo'
WP_AUTH = '/home/aiuser/.wp_auth'

# publish後 grace_minutes 以内に4項目揃わなければ draft化
# full_audit_runner/llm_proofreader/thumbnail_contam_audit が毎時稼働するため
# 最大60分のlatency想定 + 30分の安全マージン = 90分 (2026-05-11調整)
GRACE_MINUTES = int(os.getenv('AUDIT_STEPS_GRACE_MIN', '90'))
LOOKBACK_HOURS = int(os.getenv('AUDIT_STEPS_LOOKBACK_H', '6'))


def wp_get(path):
    return json.loads(subprocess.check_output(
        ['curl', '-sf', f'{WP_BASE}{path}', '-K', WP_AUTH], timeout=30
    ).decode())


def wp_post(path, payload):
    out = subprocess.check_output([
        'curl', '-s', '-X', 'POST', f'{WP_BASE}{path}',
        '-K', WP_AUTH, '-H', 'Content-Type: application/json',
        '--data-binary', json.dumps(payload, ensure_ascii=False)
    ], timeout=60).decode()
    return json.loads(out)


def main():
    now = datetime.now(timezone.utc)
    lookback_cutoff = (now - timedelta(hours=LOOKBACK_HOURS)).strftime('%Y-%m-%dT%H:%M:%S')
    posts = wp_get(f'/wp-json/wp/v2/posts?status=publish&after={lookback_cutoff}&per_page=50&_fields=id,title,date,date_gmt,slug,link,status')
    print(f"[{now.isoformat()}] 対象publish記事 {len(posts)}件 (直近{LOOKBACK_HOURS}h)")

    grace_cutoff = now - timedelta(minutes=GRACE_MINUTES)
    enforced = 0
    skipped_in_grace = 0
    fully_audited = 0
    enforced_ids = []

    for p in posts:
        pid = p['id']
        try:
            pub_dt = datetime.fromisoformat(p['date_gmt'].replace('Z', '+00:00'))
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if pub_dt > grace_cutoff:
            # まだgrace内
            skipped_in_grace += 1
            continue

        # 4項目entry確認 (publish後の時刻のみ対象)
        if is_fully_audited(pid, since_ts=pub_dt.timestamp()):
            fully_audited += 1
            continue

        # 未達 → draft化
        miss = missing_steps(pid, since_ts=pub_dt.timestamp())
        title = p['title']['rendered'] if isinstance(p['title'], dict) else p['title']
        print(f"  ENFORCE draft: id={pid} {title[:40]} missing={miss}")
        try:
            wp_post(f'/wp-json/wp/v2/posts/{pid}', {'status': 'draft'})
            enforced += 1
            enforced_ids.append({'id': pid, 'title': title[:60], 'missing': miss})
        except Exception as e:
            print(f"    err: {e}")

    print(f"--- summary ---")
    print(f"  in_grace(skip): {skipped_in_grace}")
    print(f"  fully_audited: {fully_audited}")
    print(f"  enforced_to_draft: {enforced}")
    if enforced_ids:
        # 通知用 evidence 残し
        evid_dir = '/home/aiuser/kpop-ai-system/logs/audit_steps_enforce'
        os.makedirs(evid_dir, exist_ok=True)
        evid_path = os.path.join(evid_dir, f"{now.strftime('%Y%m%d_%H%M')}.json")
        with open(evid_path, 'w', encoding='utf-8') as f:
            json.dump({'ts': now.isoformat(), 'enforced': enforced_ids}, f, ensure_ascii=False, indent=2)
        print(f"  evidence: {evid_path}")


if __name__ == '__main__':
    main()
