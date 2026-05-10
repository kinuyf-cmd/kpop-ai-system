#!/usr/bin/env python3
"""日次サムネ汚染検出 (2026-05-10完璧化)

直近24時間に公開された記事のサムネをスキャンし、
YouTube Shortsパターン/縦長画像/極小画像を検出してDiscordとログに通知。

Cron: 毎日 11:00 JST 実行を想定
"""
import os
import sys
import json
import urllib.request
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')
from lib.thumbnail_source_resolver import _is_shorts_thumbnail

LOG_PATH = '/home/aiuser/kpop-ai-system/logs/thumbnail_contamination_audit.jsonl'
DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK_URL', '')


def fetch_recent_posts(hours: int = 24) -> list:
    # WP REST after は ISO8601 (timezone なし) を要求
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
    posts = []
    for page in range(1, 4):
        url = (f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts'
               f'?per_page=50&page={page}&after={cutoff}'
               f'&_fields=id,title,slug,featured_media,date,link')
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kpj-audit/1.0'})
            d = json.loads(urllib.request.urlopen(req, timeout=15).read())
            if not d:
                break
            posts.extend(d)
        except Exception as e:
            print(f"page {page} fetch err: {e}")
            break
    return posts


def get_thumb_url(media_id: int) -> str:
    try:
        url = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{media_id}?_fields=source_url'
        req = urllib.request.Request(url, headers={'User-Agent': 'kpj-audit/1.0'})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        return d.get('source_url', '')
    except Exception:
        return ''


def check_thumbnail(post: dict) -> dict:
    """1記事のサムネを検査して結果dictを返す"""
    pid = post['id']
    fm = post.get('featured_media', 0)
    if not fm:
        return {'pid': pid, 'status': 'no_thumb'}
    thumb_url = get_thumb_url(fm)
    if not thumb_url:
        return {'pid': pid, 'status': 'media_unreachable'}
    # 意図的な非写真サムネはFP対策で除外 (DALL-E art / template texts)
    fn = thumb_url.split('/')[-1].lower()
    KNOWN_NON_SHORTS = ['v6_regen_', 'dalle', 'kpop-v4-thumb', 'buzzlab',
                        'kpop_journal_', 'korea-voltage', 'fanchant']
    if any(p in fn for p in KNOWN_NON_SHORTS):
        return {'pid': pid, 'status': 'intentional_design', 'date': post.get('date', '')}
    try:
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tf:
            with urllib.request.urlopen(thumb_url, timeout=12) as r:
                tf.write(r.read())
            path = tf.name
        try:
            from PIL import Image
            img = Image.open(path).convert('RGB')
            w, h = img.size
            issues = []
            if h > w:
                issues.append(f'portrait_{w}x{h}')
            if w < 300 or h < 200:
                issues.append(f'too_small_{w}x{h}')
            if _is_shorts_thumbnail(path):
                issues.append('shorts_pattern')
            return {
                'pid': pid, 'title': post['title']['rendered'][:50],
                'slug': post['slug'], 'thumb_url': thumb_url,
                'issues': issues, 'status': 'contaminated' if issues else 'clean',
            }
        finally:
            os.unlink(path)
    except Exception as e:
        return {'pid': pid, 'status': f'err: {e}'}


def post_to_discord(message: str):
    if not DISCORD_WEBHOOK:
        return
    try:
        req = urllib.request.Request(
            DISCORD_WEBHOOK,
            data=json.dumps({'content': message}).encode(),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"discord err: {e}")


def main():
    posts = fetch_recent_posts(hours=24)
    print(f"[thumb-audit] scanning {len(posts)} posts (last 24h)")
    contaminated = []
    for p in posts:
        r = check_thumbnail(p)
        if r.get('status') == 'contaminated':
            contaminated.append(r)
            print(f"  [{r['pid']}] {r.get('title','')} → {','.join(r['issues'])}")

    summary = {
        'ts': datetime.now(timezone(timedelta(hours=9))).isoformat(),
        'scanned': len(posts),
        'contaminated_count': len(contaminated),
        'items': contaminated,
    }
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(summary, ensure_ascii=False) + '\n')

    if contaminated:
        msg_lines = [f"🚨 サムネ汚染検出 {len(contaminated)}件 (24h, scanned={len(posts)})"]
        for c in contaminated[:10]:
            msg_lines.append(f"- [{c['pid']}] {c.get('title','')[:30]} → {','.join(c['issues'])}")
        post_to_discord('\n'.join(msg_lines))
        # 2026-05-10完璧化: 検出→自動修復チェーン
        # 真の完璧は「検出後に放置せず即修復」。FP分は自動的にskipされる
        try:
            print(f"[thumb-audit] triggering auto-repair on {len(contaminated)} items...")
            import subprocess, tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tf:
                json.dump(contaminated, tf, ensure_ascii=False)
                tf_path = tf.name
            r = subprocess.run(
                ['python3', '/home/aiuser/kpop-ai-system/pipeline/thumbnail_auto_repair.py',
                 '--input', tf_path, '--auto'],
                capture_output=True, text=True, timeout=600
            )
            print(r.stdout[-500:] if r.stdout else '')
            if r.returncode != 0:
                print(f"[thumb-audit] auto-repair err code={r.returncode}: {r.stderr[-300:]}")
            else:
                # repaired分をDiscordに通知
                post_to_discord(f"♻️ Auto-repair完了: {r.stdout.split('Summary:')[-1][:100] if 'Summary:' in r.stdout else 'see log'}")
            os.unlink(tf_path)
        except Exception as e:
            print(f"[thumb-audit] auto-repair chain err: {e}")
    else:
        print(f"[thumb-audit] clean ({len(posts)} scanned)")

    print(f"[thumb-audit] done. log: {LOG_PATH}")
    return len(contaminated)


if __name__ == '__main__':
    sys.exit(0 if main() == 0 else 1)
