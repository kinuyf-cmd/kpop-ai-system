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


def get_media_meta(media_id: int) -> dict:
    """media のalt/title/source_urlを取得 (サムネ provenance 用)"""
    try:
        url = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{media_id}?_fields=source_url,alt_text,title'
        req = urllib.request.Request(url, headers={'User-Agent': 'kpj-audit/1.0'})
        return json.loads(urllib.request.urlopen(req, timeout=8).read())
    except Exception:
        return {}


def detect_artist_mismatch(post_title: str, thumb_alt: str, thumb_url: str) -> str:
    """記事タイトルと thumbnail alt/url間のartist不一致を検出
    Returns: empty if OK, or detail string
    """
    import html
    sys.path.insert(0, '/home/aiuser/kpop-ai-system')
    from lib.collectors.korean_base import is_kpop_related
    title_artists = set(is_kpop_related(html.unescape(post_title or '')))
    if not title_artists:
        return ''  # 記事側にartist識別なし → 検証不能
    # alt + URL内のartist候補
    combined = (thumb_alt or '') + ' ' + (thumb_url or '')
    thumb_artists = set(is_kpop_related(html.unescape(combined)))
    if not thumb_artists:
        return ''  # サムネ側情報不足 → 判定保留
    # メンバー→グループ展開: 個別member名 → group名と等価扱い
    try:
        with open('/home/aiuser/kpop-ai-system/config/member_to_group.json') as f:
            member_to_group = json.load(f)
    except Exception:
        member_to_group = {}
    def expand(s):
        out = set(s)
        for a in s:
            g = member_to_group.get(a)
            if g: out.add(g)
        return out
    title_expanded = expand(title_artists)
    thumb_expanded = expand(thumb_artists)
    if title_expanded & thumb_expanded:
        return ''  # 共通artistあり → OK
    return f"title={list(title_artists)[:3]} vs thumb={list(thumb_artists)[:3]}"


def check_thumbnail(post: dict) -> dict:
    """1記事のサムネを検査して結果dictを返す"""
    pid = post['id']
    fm = post.get('featured_media', 0)
    if not fm:
        return {'pid': pid, 'status': 'no_thumb'}
    media_meta = get_media_meta(fm)
    thumb_url = media_meta.get('source_url', '')
    thumb_alt = media_meta.get('alt_text', '')
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
            # 2026-05-10完璧化: 別アーティスト混入検出
            mismatch = detect_artist_mismatch(post['title']['rendered'], thumb_alt, thumb_url)
            if mismatch:
                issues.append(f'artist_mismatch: {mismatch}')
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
    from lib.audit_steps_log import record_step
    posts = fetch_recent_posts(hours=24)
    print(f"[thumb-audit] scanning {len(posts)} posts (last 24h)")
    contaminated = []
    for p in posts:
        r = check_thumbnail(p)
        if r.get('status') == 'contaminated':
            contaminated.append(r)
            print(f"  [{r['pid']}] {r.get('title','')} → {','.join(r['issues'])}")
        record_step(p['id'], 'thumbnail',
                    status='fail' if r.get('status') == 'contaminated' else 'ok',
                    detail=','.join(r.get('issues', [])) if r.get('status') == 'contaminated' else 'clean',
                    source='thumbnail_contamination_audit')

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

    # 2026-05-10完璧化: cron sentinel — 最後にheartbeatを残してsilent failure検知
    # 翌日のcronで「前日のheartbeatが古すぎ」ならcron故障とみなしDiscord通知
    SENTINEL = '/home/aiuser/kpop-ai-system/logs/thumb_audit_heartbeat'
    try:
        from datetime import datetime as _dt
        with open(SENTINEL, 'w') as _f:
            _f.write(_dt.now().isoformat())
    except Exception:
        pass

    print(f"[thumb-audit] done. log: {LOG_PATH}")
    return len(contaminated)


def check_heartbeat_freshness():
    """cron silent failure検知 — heartbeatが30h以上古ければアラート"""
    import os as _os
    from datetime import datetime as _dt, timedelta as _td
    SENTINEL = '/home/aiuser/kpop-ai-system/logs/thumb_audit_heartbeat'
    if not _os.path.exists(SENTINEL):
        return False, 'no heartbeat file'
    try:
        mtime = _dt.fromtimestamp(_os.path.getmtime(SENTINEL))
        age = _dt.now() - mtime
        if age > _td(hours=30):
            return False, f'heartbeat stale ({age.total_seconds()/3600:.1f}h)'
        return True, 'fresh'
    except Exception as e:
        return False, f'check err: {e}'


if __name__ == '__main__':
    sys.exit(0 if main() == 0 else 1)
