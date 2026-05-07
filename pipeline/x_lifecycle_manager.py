#!/usr/bin/env python3
"""X投稿ライフサイクル管理 — 記事状態変化に応じたツイート削除・再投稿・OGP同期

3つのジョブを統合:
  1. draft/削除記事のツイート自動削除 (404リンク撲滅)
  2. サムネ更新記事のツイート再投稿 (Twitterカードキャッシュ対応)
  3. OGP未設定記事の修復 (og:image/twitter:image同期)

Usage:
  python3 -m pipeline.x_lifecycle_manager              # 全ジョブ実行
  python3 -m pipeline.x_lifecycle_manager --cleanup    # 404ツイート削除のみ
  python3 -m pipeline.x_lifecycle_manager --repost     # サムネ更新分の再投稿のみ
  python3 -m pipeline.x_lifecycle_manager --ogp-sync   # OGP同期のみ
  python3 -m pipeline.x_lifecycle_manager --dry-run    # チェックのみ

cron: 0 10,16,22 * * * (1日3回: 朝昼夜)
"""
import json
import os
import sys
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

BASE = Path('/home/aiuser/kpop-ai-system')
POSTS_LOG = BASE / 'logs' / 'x_posts.jsonl'
LIFECYCLE_LOG = BASE / 'logs' / 'x_lifecycle.jsonl'
REPOST_TRACKER = BASE / 'data' / 'x_repost_tracker.json'

# WP API設定
import base64
WP_USER = os.getenv('WP_USER', 'kpop-bot')
WP_PASS = os.getenv('WP_PASS', '')
WP_AUTH = f"Basic {base64.b64encode(f'{WP_USER}:{WP_PASS}'.encode()).decode()}"
WP_BASE = "https://www.kpopjournal.tokyo/wp-json/wp/v2"


def _log(entry: dict):
    LIFECYCLE_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry['ts'] = datetime.now().isoformat()
    with open(LIFECYCLE_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def _wp_get(path: str):
    import urllib.request
    url = f"{WP_BASE}{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": WP_AUTH,
        "User-Agent": "x-lifecycle-manager/1.0",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _wp_get_safe(path: str):
    """WP API GET (エラー時None)"""
    try:
        return _wp_get(path)
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# JOB 1: draft/削除記事のツイート自動削除
# ═══════════════════════════════════════════════════════════════════════════════

def get_posted_tweet_entries(days: int = 14) -> list:
    """直近N日のX投稿エントリ(post_id付き)を取得"""
    if not POSTS_LOG.exists():
        return []
    cutoff = datetime.now() - timedelta(days=days)
    entries = []
    for line in open(POSTS_LOG, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            if e.get('status') != 'ok' or not e.get('tweet_id'):
                continue
            if not e.get('post_id') and not e.get('url'):
                continue
            ts = datetime.fromisoformat(e.get('ts', '2000-01-01'))
            if ts >= cutoff:
                entries.append(e)
        except (json.JSONDecodeError, ValueError):
            continue
    return entries


def extract_post_id_from_url(url: str) -> int:
    """URLからWP post_idを推定 (URLの末尾数字)"""
    if not url:
        return 0
    import re
    m = re.search(r'/(\d+)/?$', url)
    return int(m.group(1)) if m else 0


def _is_popup_url(url: str) -> bool:
    """URLがpopup記事かどうか判定"""
    return '/popup/' in (url or '')


def check_article_status(post_id: int, url: str = '') -> str:
    """WP APIで記事ステータスを確認（通常記事 + popup カスタムポストタイプ対応）"""
    # まず通常の posts エンドポイントで確認
    post = _wp_get_safe(f"/posts/{post_id}?_fields=id,status,link")
    if post is not None:
        return post.get('status', 'unknown')

    # 通常postsで見つからない場合、popup カスタムポストタイプを確認
    post = _wp_get_safe(f"/popup/{post_id}?_fields=id,status")
    if post is not None:
        return post.get('status', 'unknown')

    # URLで直接アクセスして200か確認（最終フォールバック）
    if url:
        try:
            import urllib.request
            req = urllib.request.Request(url, method='HEAD', headers={
                'User-Agent': 'x-lifecycle-check/1.0'
            })
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 200:
                    return 'publish'
        except Exception:
            pass

    return 'not_found'


def cleanup_404_tweets(dry_run: bool = False) -> dict:
    """draft/trash/not_found記事のツイートを削除"""
    from lib.x_tweet_manager import delete_tweet

    entries = get_posted_tweet_entries(days=30)
    print(f"[cleanup] 直近30日の投稿: {len(entries)}件をチェック")

    # post_id → {tweet_ids, url} のマッピング
    post_tweets = {}
    for e in entries:
        pid = e.get('post_id') or extract_post_id_from_url(e.get('url', ''))
        if pid:
            if pid not in post_tweets:
                post_tweets[pid] = {'tweet_ids': [], 'url': e.get('url', '')}
            post_tweets[pid]['tweet_ids'].append(e.get('tweet_id'))

    deleted = 0
    checked = 0
    errors = 0
    already_gone = 0

    for pid, info in post_tweets.items():
        tweet_ids = info['tweet_ids']
        url = info['url']
        status = check_article_status(pid, url=url)
        checked += 1

        if status in ('publish',):
            continue  # 公開中 → 問題なし

        # draft/trash/not_found → ツイート削除
        print(f"  [!] post_id={pid} status={status} → {len(tweet_ids)}件のツイート削除")

        for tid in set(tweet_ids):  # 重複除去
            if dry_run:
                print(f"      [DRY] delete tweet {tid}")
                deleted += 1
                continue

            result = delete_tweet(tid)
            if result.get('success'):
                if result.get('deleted'):
                    deleted += 1
                    print(f"      ✓ deleted {tid}")
                else:
                    already_gone += 1
                    print(f"      - already gone {tid}")
            else:
                err_text = result.get('error', '')
                if 'Too Many Requests' in err_text or result.get('status') == 429:
                    print(f"      ⏸ rate limited — 残りは次回実行で処理")
                    _log({'action': 'cleanup_404', 'rate_limited': True, 'deleted_so_far': deleted})
                    save_result = {'checked': checked, 'deleted': deleted,
                                   'already_gone': already_gone, 'errors': errors,
                                   'rate_limited': True}
                    print(f"[cleanup] rate limited停止: deleted={deleted} remaining={len(post_tweets)-checked}")
                    return save_result
                errors += 1
                print(f"      ✗ error {tid}: {err_text[:60]}")

            time.sleep(20)  # API rate limit (50 DELETE/15min = 1回/18秒)

        _log({
            'action': 'cleanup_404',
            'post_id': pid,
            'status': status,
            'tweet_ids': list(set(tweet_ids)),
            'deleted': not dry_run,
        })

    result = {
        'checked': checked,
        'deleted': deleted,
        'already_gone': already_gone,
        'errors': errors,
    }
    print(f"[cleanup] 完了: checked={checked} deleted={deleted} already_gone={already_gone} errors={errors}")
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# JOB 2: サムネ更新時のツイート再投稿
# ═══════════════════════════════════════════════════════════════════════════════

def _load_repost_tracker() -> dict:
    """再投稿トラッカーを読み込み"""
    if REPOST_TRACKER.exists():
        try:
            return json.loads(REPOST_TRACKER.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return {'reposted': {}}


def _save_repost_tracker(data: dict):
    REPOST_TRACKER.parent.mkdir(parents=True, exist_ok=True)
    REPOST_TRACKER.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def find_thumbnail_updated_posts(days: int = 3) -> list:
    """直近N日でサムネが更新された記事を特定

    判定: x_posts.jsonl投稿時のOGP画像 vs 現在のfeatured_imageが異なる
    """
    entries = get_posted_tweet_entries(days=days)
    tracker = _load_repost_tracker()

    candidates = []
    for e in entries:
        pid = e.get('post_id') or extract_post_id_from_url(e.get('url', ''))
        if not pid:
            continue
        # 既に再投稿済みのものはスキップ
        if str(pid) in tracker.get('reposted', {}):
            continue

        # WPから現在のサムネURL取得
        post = _wp_get_safe(f"/posts/{pid}?_fields=id,status,featured_media,link,title,categories")
        if not post or post.get('status') != 'publish':
            continue

        featured_media = post.get('featured_media', 0)
        if not featured_media:
            continue

        # 現在のfeatured_mediaのURL取得
        media = _wp_get_safe(f"/media/{featured_media}?_fields=source_url")
        if not media:
            continue
        current_thumb = media.get('source_url', '')

        # OGPで確認: 公開ページのog:imageが現在のサムネと一致するか
        from lib.ogp_twitter_card_optimizer import check_live_ogp
        live = check_live_ogp(post.get('link', ''))
        og_image = live.get('og_image', '') or live.get('twitter_image', '')

        # 不一致 = サムネ更新後にOGPが追いついていない or Twitterキャッシュ問題
        if og_image and current_thumb and og_image != current_thumb:
            candidates.append({
                'post_id': pid,
                'title': post.get('title', {}).get('rendered', '')[:60],
                'link': post.get('link', ''),
                'old_og': og_image,
                'current_thumb': current_thumb,
                'tweet_id': e.get('tweet_id'),
                'categories': post.get('categories', []),
            })

    return candidates


def repost_updated_thumbnails(dry_run: bool = False, max_repost: int = 5) -> dict:
    """サムネ更新された記事: 旧ツイート削除 → OGP修復 → 新ツイート投稿"""
    from lib.x_tweet_manager import delete_tweet
    from lib.ogp_twitter_card_optimizer import fix_post_meta
    from lib.x_poster import post_tweet

    candidates = find_thumbnail_updated_posts(days=7)
    print(f"[repost] サムネ不一致: {len(candidates)}件")

    reposted = 0
    tracker = _load_repost_tracker()

    for item in candidates[:max_repost]:
        pid = item['post_id']
        print(f"  post_id={pid} {item['title']}")
        print(f"    old_og:  {item['old_og'][:80]}")
        print(f"    current: {item['current_thumb'][:80]}")

        if dry_run:
            print(f"    [DRY] would delete+repost")
            reposted += 1
            continue

        # Step 1: OGP修復 (featured_imageに合わせる)
        ogp_result = fix_post_meta(pid)
        print(f"    OGP fix: {ogp_result.get('status')} fixes={ogp_result.get('fixes', [])}")

        # Step 2: 旧ツイート削除
        tid = item.get('tweet_id')
        if tid:
            del_result = delete_tweet(tid)
            print(f"    delete tweet {tid}: {del_result.get('success')}")
            time.sleep(2)

        # Step 3: 新ツイート投稿
        time.sleep(5)  # OGPキャッシュ反映待ち
        import re
        title_clean = re.sub(r'<[^>]+>', '', item['title'])
        x_result = post_tweet(title_clean, item['link'], post_id=pid, genre='news')
        if x_result.get('success'):
            print(f"    ✓ reposted tid={x_result.get('tweet_id')}")
            reposted += 1
        else:
            print(f"    ✗ repost failed: {x_result.get('error', '')[:60]}")

        # トラッカー更新
        tracker.setdefault('reposted', {})[str(pid)] = {
            'date': datetime.now().isoformat(),
            'old_tweet': tid,
            'new_tweet': x_result.get('tweet_id'),
        }

        _log({
            'action': 'repost_thumbnail',
            'post_id': pid,
            'old_tweet': tid,
            'new_tweet': x_result.get('tweet_id'),
            'success': x_result.get('success', False),
        })

        time.sleep(15)  # バースト防止

    _save_repost_tracker(tracker)
    print(f"[repost] 完了: {reposted}/{len(candidates)}件再投稿")
    return {'candidates': len(candidates), 'reposted': reposted}


# ═══════════════════════════════════════════════════════════════════════════════
# JOB 3: OGP同期 (publish時に必ず実行)
# ═══════════════════════════════════════════════════════════════════════════════

def sync_ogp_for_recent(days: int = 1, dry_run: bool = False) -> dict:
    """直近N日の公開記事でOGP未設定/不一致を修復"""
    from lib.ogp_twitter_card_optimizer import fix_post_meta

    # 直近の公開記事を取得
    after = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")
    try:
        posts = _wp_get(f"/posts?status=publish&per_page=50&after={after}&orderby=date&order=desc&_fields=id,featured_media,meta")
    except Exception as e:
        print(f"[ogp-sync] WP API error: {e}")
        return {'error': str(e)}

    fixed = 0
    checked = 0
    print(f"[ogp-sync] 直近{days}日の記事: {len(posts)}件")

    for post in posts:
        pid = post['id']
        featured_media = post.get('featured_media', 0)
        meta = post.get('meta', {})

        # featured_mediaがあるのにOGP画像が未設定の記事を修復
        needs_fix = False
        if featured_media and not meta.get('_aioseo_og_image_custom_url'):
            needs_fix = True
        if featured_media and not meta.get('_aioseo_twitter_image_custom_url'):
            needs_fix = True
        if meta.get('_aioseo_twitter_card') != 'summary_large_image':
            needs_fix = True

        if not needs_fix:
            continue

        checked += 1
        if dry_run:
            print(f"  [DRY] #{pid} needs OGP fix")
            fixed += 1
            continue

        result = fix_post_meta(pid)
        if result.get('fixes'):
            fixed += 1
            print(f"  [+] #{pid} fixed: {result['fixes']}")

    print(f"[ogp-sync] 完了: checked={checked} fixed={fixed}")
    return {'checked': checked, 'fixed': fixed}


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="X投稿ライフサイクル管理")
    parser.add_argument("--cleanup", action="store_true", help="404ツイート削除のみ")
    parser.add_argument("--repost", action="store_true", help="サムネ更新分の再投稿のみ")
    parser.add_argument("--ogp-sync", action="store_true", help="OGP同期のみ")
    parser.add_argument("--dry-run", action="store_true", help="チェックのみ（変更なし）")
    args = parser.parse_args()

    run_all = not (args.cleanup or args.repost or args.ogp_sync)
    print(f"=== x_lifecycle_manager: {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")

    if run_all or args.ogp_sync:
        sync_ogp_for_recent(days=2, dry_run=args.dry_run)
        print()

    if run_all or args.cleanup:
        cleanup_404_tweets(dry_run=args.dry_run)
        print()

    if run_all or args.repost:
        repost_updated_thumbnails(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
