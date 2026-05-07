#!/usr/bin/env python3
"""X投稿リトライプロセッサ v2.0 — config/x_retry_queue.json をバッチ消化

改善点 (v2.0):
  - バッチ処理: 毎回最大 BATCH_SIZE 件を処理（API間隔3秒）
  - 専用レート: リトライ枠は通常投稿と独立（x_poster.pyのレート制限をバイパス）
  - テンプレート活用: x_post_templates.py で品質確保
  - キュー衛生: 7日超古エントリ削除、投稿済URL重複除去
  - 失敗時は末尾移動せずスキップ（無限ループ防止）

cron: 45 9-21 * * * (毎時45分)
"""
import sys, os, json, time, pathlib, re
from datetime import datetime, timedelta

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

BASE = pathlib.Path('/home/aiuser/kpop-ai-system')
QUEUE_FILE = str(BASE / 'config' / 'x_retry_queue.json')
LOG_FILE = str(BASE / 'logs' / 'x_retry.log')
POSTS_LOG = str(BASE / 'logs' / 'x_posts.jsonl')

# Patch retry log path to avoid root-owned file issue
sys.path.insert(0, str(BASE / 'google_metrics'))
import post_to_x
post_to_x.RETRY_LOG = pathlib.Path(str(BASE / 'logs' / 'x_retry_log_v2.jsonl'))

BATCH_SIZE = 5       # 1回の実行で最大5件処理
API_INTERVAL = 3     # API呼び出し間隔（秒）
STALE_DAYS = 7       # これより古いエントリは削除
MAX_FAILURES = 3     # 同一エントリの最大失敗回数


def load_queue():
    if not os.path.exists(QUEUE_FILE):
        return []
    try:
        data = json.load(open(QUEUE_FILE, encoding='utf-8'))
        return data.get('queue', [])
    except (json.JSONDecodeError, OSError):
        return []


def save_queue(queue):
    data = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'reason': 'retry_processor_v2',
        'count': len(queue),
        'queue': queue,
    }
    with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _posted_urls() -> set:
    """直近投稿済みURLを取得（重複投稿防止）"""
    urls = set()
    if not os.path.exists(POSTS_LOG):
        return urls
    try:
        with open(POSTS_LOG, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get('status') == 'ok' and entry.get('url'):
                        urls.add(entry['url'])
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        pass
    return urls


def sanitize_queue(queue: list) -> list:
    """キュー衛生管理: 古い/重複/不正エントリを除去"""
    cutoff = datetime.now() - timedelta(days=STALE_DAYS)
    posted = _posted_urls()
    seen_urls = set()
    clean = []
    removed_stale = 0
    removed_dup = 0
    removed_posted = 0

    for item in queue:
        url = item.get('url', '')

        # 不正エントリ除去
        if not url:
            continue

        # 古いエントリ除去
        added_at = item.get('added_at', '')
        if added_at:
            try:
                dt = datetime.fromisoformat(added_at.replace('+09:00', ''))
                if dt < cutoff:
                    removed_stale += 1
                    continue
            except (ValueError, TypeError):
                pass

        # 投稿済みURL除去
        if url in posted:
            removed_posted += 1
            continue

        # キュー内重複除去
        if url in seen_urls:
            removed_dup += 1
            continue
        seen_urls.add(url)

        # 失敗回数超過除去
        if item.get('fail_count', 0) >= MAX_FAILURES:
            continue

        clean.append(item)

    if removed_stale or removed_dup or removed_posted:
        print(f"  sanitize: stale={removed_stale} posted={removed_posted} dup={removed_dup} → {len(clean)}件残")

    return clean


def _build_tweet_text(title: str, url: str, post_id=None, ptype: str = 'post') -> str:
    """テンプレートシステムを使って高品質なツイートテキストを生成"""
    try:
        from lib.x_post_templates import generate_tweet, CATEGORY_TO_GENRE
        # カテゴリ判定（WP APIから取得済みの場合）
        genre = 'news'  # デフォルト
        if ptype == 'popup':
            genre = 'travel'
        tweet = generate_tweet(title, url, genre, include_url=True)
        return tweet
    except Exception as e:
        print(f"  template fallback: {e}")
        # フォールバック: シンプルなテキスト
        hashtags = '#KPOPJOURNAL #KPOP'
        if ptype == 'popup':
            hashtags = '#ポップアップ #KPOP #韓国'
        return f"{title[:80]}\n\n{hashtags}\n\n{url}"


def _post_directly(text: str, url: str, post_id=None) -> dict:
    """x_poster.pyのレート制限をバイパスしてAPIに直接投稿

    リトライプロセッサ専用: 通常投稿とは別枠で処理する。
    2026-05-07: trash記事検知ガード追加 (x_poster と同じ防御)
    """
    # WP記事status再検証 (post_tweet と同じ防御を retry path にも適用)
    if post_id:
        try:
            import urllib.request as _ur, base64 as _b64, json as _json
            _AUTH = _b64.b64encode(b'kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh').decode()
            _u = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}?_fields=id,status,featured_media&status=any'
            _req = _ur.Request(_u, headers={'Authorization': f'Basic {_AUTH}'})
            with _ur.urlopen(_req, timeout=10) as _r:
                _wp = _json.loads(_r.read())
            if _wp.get('status') != 'publish':
                return {'success': False,
                        'error': f'WP記事 {post_id} status={_wp.get("status")} — retry skip'}
            if _wp.get('featured_media', 0) == 0:
                return {'success': False,
                        'error': f'WP記事 {post_id} featured_media未設定 — retry skip'}
        except Exception:
            pass

    try:
        creds, errors = post_to_x.validate_credentials()
        if errors or creds is None:
            return {'success': False, 'error': '; '.join(errors[:2]) if errors else 'credential invalid'}

        tweet_id, attempts = post_to_x.post_tweet(text, '', creds)
        # 成功ログをx_posts.jsonlに記録（post_id含む）
        entry = {
            'ts': datetime.now().isoformat(),
            'tweet_id': tweet_id,
            'text': text[:120],
            'url': url,
            'attempts': attempts,
            'status': 'ok',
            'source': 'retry_processor',
        }
        if post_id:
            entry['post_id'] = post_id
        os.makedirs(os.path.dirname(POSTS_LOG), exist_ok=True)
        with open(POSTS_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

        # tweet_idをWordPressに書き戻す (x_no_tweet_id 再発防止)
        if tweet_id and post_id:
            _write_tweet_id_to_wp(post_id, tweet_id, url)

        return {'success': True, 'tweet_id': tweet_id}
    except Exception as e:
        return {'success': False, 'error': str(e)[:200]}


def _write_tweet_id_to_wp(post_id, tweet_id, url=''):
    """リトライ成功時にtweet_idをWordPressのカスタムフィールドに書き戻す"""
    try:
        import requests, base64
        wp_user = os.getenv('WP_USER', '')
        wp_pass = os.getenv('WP_PASS', '')
        if not wp_user or not wp_pass:
            return
        auth = base64.b64encode(f"{wp_user}:{wp_pass}".encode()).decode()
        headers = {'Authorization': f'Basic {auth}', 'Content-Type': 'application/json'}

        # post_typeを判定 (popup URLならpopup)
        endpoint = 'popup' if '/popup/' in url or '/popup-' in url else 'posts'
        resp = requests.post(
            f'https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}/{post_id}',
            headers=headers,
            json={'meta': {'x_tweet_id': str(tweet_id)}},
            timeout=15
        )
        if resp.status_code == 200:
            print(f"    WP書戻し成功: post_id={post_id} tweet_id={tweet_id}")
        else:
            print(f"    WP書戻し失敗: {resp.status_code}")
    except Exception as e:
        print(f"    WP書戻しエラー: {e}")


def main():
    print(f"=== x_retry_processor v2.0 {datetime.now().isoformat()} ===")

    queue = load_queue()
    if not queue:
        print("  queue empty")
        return

    initial_count = len(queue)
    print(f"  queue: {initial_count}件")

    # キュー衛生管理（古い/重複/投稿済みを除去）
    queue = sanitize_queue(queue)
    if not queue:
        print("  sanitize後: queue empty")
        save_queue(queue)
        return

    if len(queue) < initial_count:
        print(f"  sanitize後: {len(queue)}件")

    # 日次上限チェック（x_poster.pyと同じ制限を適用）
    from lib.x_poster import _recent_posts, MAX_POSTS_PER_DAY
    daily_count = len(_recent_posts(hours=24))
    daily_remaining = max(0, MAX_POSTS_PER_DAY - daily_count)
    if daily_remaining == 0:
        print(f"  日次上限到達: {daily_count}/{MAX_POSTS_PER_DAY}件。スキップ")
        save_queue(queue)
        return
    effective_batch = min(BATCH_SIZE, daily_remaining)
    print(f"  日次: {daily_count}/{MAX_POSTS_PER_DAY} → 今回最大{effective_batch}件")

    # バッチ処理: 最大BATCH_SIZE件（日次上限内）
    processed = 0
    succeeded = 0
    failed_items = []
    remaining_items = list(queue)  # コピー

    for i, item in enumerate(queue[:effective_batch]):
        pid = item.get('post_id') or item.get('pid') or item.get('id')
        ptype = item.get('type', 'post')
        title = item.get('title') or item.get('text', '')
        url = item.get('url', '')

        if not url:
            remaining_items.remove(item)
            continue

        # タイトルがない場合WP APIから取得
        if not title and pid:
            try:
                import requests
                endpoint_type = 'posts' if ptype == 'post' else 'popup'
                p = requests.get(
                    f'https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint_type}/{pid}?_fields=id,title,link',
                    timeout=10
                ).json()
                title = p['title']['rendered'] if isinstance(p.get('title'), dict) else p.get('title', '')
                if not url:
                    url = p.get('link', '')
            except Exception as e:
                print(f"  [{i+1}] WP fetch err pid={pid}: {e}")
                item['fail_count'] = item.get('fail_count', 0) + 1
                continue

        # OGP事前検証（og-default / soft-404 はスキップ）
        try:
            from lib.x_post_url_validator import validate_url as _validate_url
            url_check = _validate_url(url)
            if not url_check.get('ok'):
                reason = url_check.get('reason', '')
                print(f"  [{i+1}] SKIP pid={pid}: URL検証NG ({reason[:60]})")
                remaining_items.remove(item)  # 不正URLはキューから削除
                continue
        except Exception:
            pass  # バリデーション自体の失敗は無視

        # テンプレートでツイートテキスト生成
        tweet_text = _build_tweet_text(title, url, pid, ptype)

        # API呼び出し（直接投稿）
        result = _post_directly(tweet_text, url, post_id=pid)
        processed += 1

        if result.get('success'):
            print(f"  [{i+1}] OK pid={pid} tweet_id={result.get('tweet_id')}")
            remaining_items.remove(item)
            succeeded += 1
        else:
            err = result.get('error', '')
            print(f"  [{i+1}] FAIL pid={pid}: {err[:100]}")

            if '401' in err:
                print("  AUTH ERROR — 中断")
                break
            elif '402' in err or 'CreditsDepleted' in err:
                print("  NO CREDITS — 中断")
                break
            elif 'suspended' in err.lower():
                print("  ACCOUNT SUSPENDED — 中断")
                break

            # 失敗カウント加算（末尾移動はしない）
            item['fail_count'] = item.get('fail_count', 0) + 1
            item['last_error'] = err[:100]

        # API間隔を空ける（最後の1件は不要）
        if i < min(len(queue), BATCH_SIZE) - 1:
            time.sleep(API_INTERVAL)

    # キューを保存
    save_queue(remaining_items)
    print(f"  結果: {succeeded}/{processed}件成功, 残り{len(remaining_items)}件")


if __name__ == '__main__':
    main()
