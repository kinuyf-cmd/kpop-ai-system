#!/usr/bin/env python3
"""X投稿スケジューラー — キューベースの時間分散投稿

設計思想:
  記事公開時にXへ即時投稿せず、x_post_queue.json にキューイング。
  本スクリプトがcronで定期実行され、ピーク時間帯に合わせて投稿する。

投稿タイミング設計:
  - 07:00-08:00 (通勤): 3件まで
  - 12:00-13:00 (昼休み): 3件まで
  - 17:00-18:00 (退勤): 2件まで
  - 19:00-21:00 (ゴールデン): 5件まで (最重要)
  - 上記以外: 1件/時 (フィラー)

投稿間隔: 最低5分（同一時間帯内で分散）

Usage:
  python3 -m pipeline.x_scheduled_poster           # キューから投稿実行
  python3 -m pipeline.x_scheduled_poster --status  # キュー状態確認

cron: */15 7-21 * * * (15分おきに確認・投稿)
"""
import json
import os
import sys
import time
import base64
import argparse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

BASE = Path('/home/aiuser/kpop-ai-system')
QUEUE_FILE = BASE / 'config' / 'x_post_queue.json'
POSTS_LOG = BASE / 'logs' / 'x_posts.jsonl'
SCHEDULE_LOG = BASE / 'logs' / 'x_scheduled.log'

# 時間帯ごとの最大投稿数/日
SLOTS = {
    7:  3,   # 07:xx
    8:  2,   # 08:xx
    12: 3,   # 12:xx
    13: 2,   # 13:xx
    17: 2,   # 17:xx
    18: 2,   # 18:xx
    19: 3,   # 19:xx (ゴールデン前半)
    20: 3,   # 20:xx (ゴールデン中盤)
    21: 2,   # 21:xx (ゴールデン後半)
}
DEFAULT_SLOT_SIZE = 1  # 上記以外の時間帯
MIN_INTERVAL_MIN = 5   # 同一時間帯内の最低間隔(分)
PRIORITY_GENRES = {'news', 'breaking', 'comeback', 'chart'}  # 優先ジャンル


def load_queue() -> list:
    if not QUEUE_FILE.exists():
        return []
    try:
        data = json.loads(QUEUE_FILE.read_text(encoding='utf-8'))
        return data.get('queue', [])
    except (json.JSONDecodeError, OSError):
        return []


def _writeback_tweet_id(post_id: int, tweet_id: str):
    """tweet_idをWordPressメタ+ローカルTSVに書き戻し"""
    try:
        import urllib.request
        url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}"
        import base64
        WP_USER = os.environ.get('WP_USER', 'kpop-bot')
        WP_PASS = os.environ.get('WP_PASS', '')
        auth = f"Basic {base64.b64encode(f'{WP_USER}:{WP_PASS}'.encode()).decode()}"
        payload = json.dumps({"meta": {"_x_tweet_id": str(tweet_id)}}).encode()
        req = urllib.request.Request(url, data=payload, headers={
            "Authorization": auth, "Content-Type": "application/json",
        }, method="POST")
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass
    # ローカルTSV
    tsv_path = BASE / 'logs' / 'tweet_id_db.tsv'
    try:
        with open(tsv_path, 'a', encoding='utf-8') as f:
            f.write(f"{post_id}\t{tweet_id}\t\t{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")
    except Exception:
        pass


def save_queue(queue: list):
    data = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'count': len(queue),
        'queue': queue,
    }
    QUEUE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def enqueue(title: str, url: str, post_id: int = None, genre: str = '',
            artist: str = '', priority: str = 'normal'):
    """投稿をキューに追加（x_poster.pyから呼ばれる）"""
    queue = load_queue()

    # 重複チェック
    if any(e.get('url') == url for e in queue):
        return False

    entry = {
        'title': title[:120],
        'url': url,
        'post_id': post_id,
        'genre': genre,
        'artist': artist,
        'priority': priority,
        'queued_at': datetime.now().isoformat(),
    }
    queue.append(entry)
    save_queue(queue)
    return True


def _posts_this_hour() -> int:
    """現在の時間帯に投稿済みの件数。
    1記事 = hook + url_reply の2エントリだが、SLOT制限は記事数基準のため
    mode='hook'のみカウントする (2026-05-07: スロット2倍消化バグ修正)
    """
    if not POSTS_LOG.exists():
        return 0
    now = datetime.now()
    hour_start = now.replace(minute=0, second=0, microsecond=0)
    count = 0
    for line in open(POSTS_LOG, encoding='utf-8'):
        try:
            e = json.loads(line.strip())
            if e.get('status') != 'ok':
                continue
            # hookのみカウント (url_replyは同一記事のフォローアップ)
            if e.get('mode') and e.get('mode') != 'hook':
                continue
            ts = datetime.fromisoformat(e.get('ts', '2000-01-01'))
            if ts >= hour_start:
                count += 1
        except (json.JSONDecodeError, ValueError):
            continue
    return count


def _last_post_time() -> datetime:
    """最後に投稿した時刻"""
    if not POSTS_LOG.exists():
        return datetime.min
    last = datetime.min
    for line in open(POSTS_LOG, encoding='utf-8'):
        try:
            e = json.loads(line.strip())
            if e.get('status') == 'ok':
                ts = datetime.fromisoformat(e.get('ts', '2000-01-01'))
                if ts > last:
                    last = ts
        except (json.JSONDecodeError, ValueError):
            continue
    return last


def _current_slot_limit() -> int:
    """現在時刻のスロット上限"""
    hour = datetime.now().hour
    return SLOTS.get(hour, DEFAULT_SLOT_SIZE)


def _sort_queue(queue: list) -> list:
    """優先度ソート: breaking/news > 通常 > popup/travel"""
    def priority_key(e):
        if e.get('priority') == 'high' or e.get('genre') in PRIORITY_GENRES:
            return 0
        if e.get('genre') in ('travel', 'default', ''):
            return 2
        return 1
    return sorted(queue, key=priority_key)


def process_queue(dry_run: bool = False) -> dict:
    """キューからピーク時間帯に合わせて投稿（フック+URLリプライ方式）"""

    queue = load_queue()
    if not queue:
        print("[scheduler] キュー空")
        return {'processed': 0, 'remaining': 0}

    now = datetime.now()
    hour = now.hour

    # 営業時間外は投稿しない
    if hour < 7 or hour > 21:
        print(f"[scheduler] 営業時間外 ({hour}時) — スキップ")
        return {'processed': 0, 'remaining': len(queue)}

    # 今時間帯の残りスロット
    slot_limit = _current_slot_limit()
    already_posted = _posts_this_hour()
    remaining_slots = max(0, slot_limit - already_posted)

    if remaining_slots <= 0:
        print(f"[scheduler] {hour}時台のスロット消化済み ({already_posted}/{slot_limit})")
        return {'processed': 0, 'remaining': len(queue)}

    # 最低間隔チェック
    last_post = _last_post_time()
    elapsed_min = (now - last_post).total_seconds() / 60
    if elapsed_min < MIN_INTERVAL_MIN:
        wait = MIN_INTERVAL_MIN - elapsed_min
        print(f"[scheduler] 前回投稿から{elapsed_min:.0f}分 — {wait:.0f}分待機")
        return {'processed': 0, 'remaining': len(queue)}

    # 優先度ソート
    queue = _sort_queue(queue)

    # 投稿実行
    to_post = min(remaining_slots, 2)  # 1回の実行で最大2件
    processed = 0
    new_queue = list(queue)

    for entry in queue[:to_post]:
        title = entry.get('title', '')
        url = entry.get('url', '')
        post_id = entry.get('post_id')
        genre = entry.get('genre', '')
        artist = entry.get('artist', '')

        print(f"  posting: {title[:50]}...")

        # 2026-05-08: WP status verify (draft/trash の即時投稿事故防止 — 18765事案)
        # unauthenticated REST APIは publish のみ200を返す。401/404は draft/trash として扱う
        if post_id:
            try:
                import urllib.request, urllib.error, json as _json
                _req = urllib.request.Request(
                    f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}?_fields=id,status",
                    headers={'User-Agent': 'kpopjournal-scheduler/1.0'})
                _is_publish = False
                try:
                    with urllib.request.urlopen(_req, timeout=10) as _r:
                        _wp = _json.loads(_r.read().decode())
                    _is_publish = (_wp.get('status') == 'publish')
                except urllib.error.HTTPError as _he:
                    if _he.code in (401, 403, 404):
                        _is_publish = False  # draft/trash/deleted
                    else:
                        raise
                if not _is_publish:
                    print(f"    ✗ WP not-publish — skip & remove from queue (pid={post_id})")
                    new_queue.remove(entry)
                    processed += 1
                    continue
            except Exception as _e:
                print(f"    [warn] WP status check failed ({_e}) — proceeding")

        if dry_run:
            processed += 1
            new_queue.remove(entry)
            continue

        from lib.x_poster import post_hook_and_reply
        result = post_hook_and_reply(title, url, post_id=post_id, genre=genre, artist=artist)
        if result.get('success'):
            tid = result.get('tweet_id', '')
            rid = result.get('reply_id', '')
            print(f"    ✓ hook={tid} reply={rid}")
            processed += 1
            new_queue.remove(entry)
            # tweet_idをWPに書き戻し（kpop_pipeline.sh互換）
            if tid and post_id:
                _writeback_tweet_id(post_id, tid)
        elif result.get('queued'):
            # レート制限 → 次回に回す
            print(f"    → rate limited, retry later")
            break
        else:
            # 永久エラー → キューから除外
            print(f"    ✗ {result.get('error', '')[:60]}")
            new_queue.remove(entry)
            processed += 1

        time.sleep(15)  # 投稿間隔

    save_queue(new_queue)

    result = {'processed': processed, 'remaining': len(new_queue)}
    print(f"[scheduler] 投稿: {processed}件 / 残キュー: {len(new_queue)}件")

    # 2026-05-07: silent rot 検知用 alert
    # ガード厳格化により全rejectされ続けた場合の早期警告
    # cond: queue>=10あるのに 連続3回以上 processed=0 ならalert
    _alert_silent_rot(processed, len(new_queue))

    return result


def _alert_silent_rot(processed: int, remaining: int):
    """0件alert: queue 残あるのに連続skipが続いたら警告"""
    alert_log = BASE / 'logs' / 'x_scheduler_silent_rot.jsonl'
    alert_log.parent.mkdir(exist_ok=True)
    # 直近5回の processed history を読む
    history = []
    if alert_log.exists():
        try:
            for line in alert_log.read_text(errors='replace').splitlines()[-5:]:
                d = json.loads(line)
                history.append(d.get('processed', 0))
        except Exception:
            history = []
    # 直近の processed をlogに append
    entry = {
        'ts': datetime.now().isoformat(),
        'processed': processed,
        'remaining': remaining,
    }
    with alert_log.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    # alert: 直近(本回含む)4回連続 processed=0 かつ queue 残>=10
    history.append(processed)
    if remaining >= 10 and len(history) >= 4 and all(h == 0 for h in history[-4:]):
        msg = (f"[ALERT] x_scheduled_poster: 連続4回 0投稿 / queue残 {remaining}件 — "
               f"全guard rejected (trash/og-default疑い) もしくは外部要因。要調査")
        print(msg)
        # logs/alerts.jsonl に追加 (運用alert集約)
        alerts_path = BASE / 'logs' / 'alerts.jsonl'
        with alerts_path.open('a', encoding='utf-8') as f:
            f.write(json.dumps({
                'ts': datetime.now().isoformat(),
                'severity': 'high',
                'source': 'x_scheduled_poster',
                'msg': msg,
                'history': history[-4:],
                'remaining': remaining,
            }, ensure_ascii=False) + '\n')


def show_status():
    """キュー状態表示"""
    queue = load_queue()
    print(f"キュー: {len(queue)}件")
    hour = datetime.now().hour
    print(f"現在: {hour}時台 スロット上限={SLOTS.get(hour, DEFAULT_SLOT_SIZE)}")
    print(f"今時間帯の投稿済み: {_posts_this_hour()}件")
    print(f"最終投稿: {_last_post_time().strftime('%H:%M:%S')}")
    print()
    for i, e in enumerate(queue[:10], 1):
        genre = e.get('genre', '-')
        title = e.get('title', '')[:40]
        queued = e.get('queued_at', '')[:16]
        print(f"  {i}. [{genre}] {title} ({queued})")
    if len(queue) > 10:
        print(f"  ... +{len(queue)-10}件")


def main():
    parser = argparse.ArgumentParser(description="X投稿スケジューラー")
    parser.add_argument("--status", action="store_true", help="キュー状態確認")
    parser.add_argument("--dry-run", action="store_true", help="チェックのみ")
    args = parser.parse_args()

    if args.status:
        show_status()
    else:
        print(f"=== x_scheduled_poster: {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
        process_queue(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
