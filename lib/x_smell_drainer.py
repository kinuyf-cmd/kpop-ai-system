#!/usr/bin/env python3
"""X AI smell tweet drainer

2026-05-12: v13 word salad / v12 AI smell の過去ツイートを X API DELETE で削除する
ドレイナー。DELETE API は 50req/15min の rate limit があるため、cron で 1 回あたり
30 件まで処理して queue を消化する。

入力: data/x_smell_delete_queue.jsonl (1行 = {"tid": "...", "type": "hook|reply", "date": ...})
出力: queue を消費 (削除済は除去)
ログ: logs/x_smell_drainer.log
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path('/home/aiuser/kpop-ai-system')
QUEUE = BASE / 'data' / 'x_smell_delete_queue.jsonl'
LOG = BASE / 'logs' / 'x_smell_drainer.log'
BATCH_LIMIT = 30
SLEEP_BETWEEN = 5  # 秒 (5s * 30 = 2.5min は rate limit safe)

sys.path.insert(0, str(BASE))


def log(msg: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f'[{datetime.now().isoformat()}] {msg}\n')


def main():
    if not QUEUE.exists():
        log('queue file not found, nothing to do')
        return

    from lib.x_tweet_manager import delete_tweet

    remaining = []
    with open(QUEUE, encoding='utf-8') as f:
        for line in f:
            try:
                remaining.append(json.loads(line))
            except Exception:
                pass

    if not remaining:
        log('queue empty')
        return

    batch = remaining[:BATCH_LIMIT]
    keep = remaining[BATCH_LIMIT:]

    deleted = 0
    rate_limited = 0
    other_err = 0
    rate_limit_hit_idx = None

    for i, t in enumerate(batch):
        tid = t.get('tid')
        if not tid:
            continue
        r = delete_tweet(tid)
        if r.get('success'):
            if r.get('deleted'):
                deleted += 1
            # already_deleted (404) は成功扱い
            elif r.get('reason') == 'already_deleted':
                deleted += 1
        else:
            err = str(r.get('error', ''))
            if 'Too Many Requests' in err or '429' in err:
                rate_limited += 1
                if rate_limit_hit_idx is None:
                    rate_limit_hit_idx = i
                # rate limit に達したら残りは次回 cron へ
                keep = batch[i:] + keep
                break
            else:
                other_err += 1
                log(f'  err tid={tid}: {err[:120]}')
                # other err は queue から除去 (永久に失敗するなら再試行無意味)
        time.sleep(SLEEP_BETWEEN)

    # Rewrite queue
    with open(QUEUE, 'w', encoding='utf-8') as f:
        for t in keep:
            f.write(json.dumps(t, ensure_ascii=False) + '\n')

    log(f'batch done: deleted={deleted} rate_limited={rate_limited} other_err={other_err} queue_remaining={len(keep)}')
    print(f'deleted={deleted} rate_limited={rate_limited} other_err={other_err} queue_remaining={len(keep)}')


if __name__ == '__main__':
    main()
