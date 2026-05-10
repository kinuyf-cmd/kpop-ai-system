#!/usr/bin/env python3
"""汚染サムネ自動修復 (2026-05-10)

入力: contamination scan結果 (JSON list of dicts with pid/title/thumb_url/issues)
処理:
  1. タイトルからartist推定 (subject-first)
  2. resolve(artist_name) で本人写真取得
  3. smart_crop で1200x675にリサイズ
  4. WP Media API にアップロード
  5. featured_media を更新
  6. 旧mediaがログ残り次第出力 (要・人手で削除判断)

Usage:
  python3 pipeline/thumbnail_auto_repair.py [--input PATH] [--dry-run] [--limit N]

Daily cron (replaces detection-only audit):
  0 11 * * * cd /home/aiuser/kpop-ai-system && python3 pipeline/thumbnail_contamination_audit.py >> ... && \
  python3 pipeline/thumbnail_auto_repair.py --input /tmp/contam_recent.json --auto >> ...
"""
import os
import sys
import json
import argparse
import urllib.request
import base64
import time
import tempfile

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')
from PIL import Image
from lib.thumbnail_source_resolver import resolve
from lib.thumbnail_resolver import smart_crop
from lib.collectors.korean_base import is_kpop_related
from lib.frontend_cache import purge_paths
from lib.unified_publisher import _validate_thumbnail

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
LOG_PATH = '/home/aiuser/kpop-ai-system/logs/thumbnail_auto_repair.jsonl'

# 「アーティスト写真」が必要ない記事タイプ — タイトルパターンでスキップ
NON_ARTIST_KEYWORDS = [
    'ガイド', '完全ガイド', '保存版', 'まとめ',
    '旅行', '聖地', 'コンセント', '電圧', 'WiFi', '持ち物',
    'ドラマ映画', '映画ガイド', 'ファンチャント', '韓国コスメ', 'ドラマ名作',
]


def detect_artist(title: str) -> str:
    """タイトルからartist推定 (subject-first)。HTML entityをdecodeして判定"""
    import html
    title = html.unescape(title)
    arts = is_kpop_related(title)
    if not arts:
        return ''
    # AGENCY/GENERIC除外
    from lib.collectors.korean_base import GENERIC_EVENT_KW, AGENCY_ONLY_KW
    for a in arts:
        if a not in GENERIC_EVENT_KW and a not in AGENCY_ONLY_KW:
            return a
    return ''


def is_non_artist_article(title: str) -> bool:
    return any(kw in title for kw in NON_ARTIST_KEYWORDS)


def upload_media(image_path: str, alt: str, title_str: str) -> int:
    fname = f'autofix_{int(time.time())}.jpg'
    with open(image_path, 'rb') as f:
        data = f.read()
    req = urllib.request.Request(
        'https://www.kpopjournal.tokyo/wp-json/wp/v2/media',
        data=data, method='POST',
        headers={'Authorization': f'Basic {AUTH}',
                 'Content-Type': 'image/jpeg',
                 'Content-Disposition': f'attachment; filename="{fname}"'})
    media = json.loads(urllib.request.urlopen(req, timeout=60).read())
    mid = media['id']
    # alt
    alt_req = urllib.request.Request(
        f'https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{mid}',
        data=json.dumps({'alt_text': alt, 'title': title_str}).encode(),
        method='POST',
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
    urllib.request.urlopen(alt_req, timeout=20)
    return mid


def attach_to_post(pid: int, media_id: int) -> int:
    req = urllib.request.Request(
        f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{pid}',
        data=json.dumps({'featured_media': media_id}).encode(),
        method='POST',
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
    r = json.loads(urllib.request.urlopen(req, timeout=20).read())
    return r.get('featured_media', 0)


def repair_one(item: dict, dry_run: bool = False) -> dict:
    pid = item['pid']
    title = item.get('title', '')
    slug = item.get('slug', '')
    result = {'pid': pid, 'title': title[:50], 'action': 'skip', 'reason': ''}

    # まずartist検出 — 取れたら「ガイド/まとめ」記事でも本人写真化を試みる
    # (例: "TXT、日本5大ドームツアー決定...まとめ" → TXT記事)
    artist = detect_artist(title)
    if not artist:
        # artist不明 + 非アーティスト記事キーワード → skip確定
        if is_non_artist_article(title):
            result['reason'] = 'non_artist_article'
            return result
        result['reason'] = 'no_artist_detected'
        return result
    result['artist'] = artist

    # Resolve artist photo
    r = resolve(artist_name=artist, article_type='concrete')
    if not r or not r.get('image_path'):
        result['reason'] = 'no_artist_photo'
        return result
    src_path = r['image_path']
    result['source'] = r.get('source', '')

    # Process to 1200x675
    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tf:
        Image.open(src_path).convert('RGB').save(tf.name, 'JPEG', quality=92)
        temp_path = tf.name
    try:
        ok = smart_crop(temp_path, 1200, 675)
        if not ok:
            result['reason'] = 'smart_crop_failed'
            return result

        # 2026-05-10: 公開前gate (Shorts/portrait/極小をBLOCK)
        valid, reason = _validate_thumbnail(temp_path)
        if not valid:
            result['reason'] = f'gate_block: {reason}'
            return result

        if dry_run:
            result['action'] = 'would_replace'
            result['reason'] = f'with {artist} photo from {result["source"]}'
            return result

        # Upload
        alt = f"{artist} のサムネイル画像"
        mid = upload_media(temp_path, alt, f"{artist} group photo")
        new_fm = attach_to_post(pid, mid)
        result['action'] = 'replaced'
        result['new_media_id'] = mid
        result['old_media_id'] = item.get('media_id', 0)

        # Cache purge
        if slug:
            purge_paths([f'/{slug}/'])
            result['cache_purged'] = True
    finally:
        try:
            os.unlink(temp_path)
        except Exception:
            pass

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='/tmp/contam_real.json',
                        help='Path to contamination JSON list')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--auto', action='store_true', help='Skip confirmation')
    args = parser.parse_args()

    with open(args.input, encoding='utf-8') as f:
        items = json.load(f)
        if isinstance(items, dict) and 'contaminated' in items:
            items = items['contaminated']

    if args.limit:
        items = items[:args.limit]

    print(f"=== Auto-repair: {len(items)} items ({'dry-run' if args.dry_run else 'LIVE'}) ===")

    if not args.auto and not args.dry_run:
        print("⚠️ This will modify production WP. Use --auto or --dry-run to skip prompt.")
        try:
            ans = input("Continue? (y/N): ").strip().lower()
            if ans != 'y':
                print("aborted")
                return
        except EOFError:
            print("non-interactive mode, requires --auto")
            return

    results = []
    actioned = 0
    for i, item in enumerate(items):
        r = repair_one(item, dry_run=args.dry_run)
        results.append(r)
        if r['action'] in ('replaced', 'would_replace'):
            actioned += 1
        print(f"  [{i+1}/{len(items)}] {r['pid']} {r['action']} - {r.get('reason', '')[:50]}")

    print(f"\n=== Summary: {actioned}/{len(items)} actioned ===")
    by_action = {}
    for r in results:
        by_action[r['action']] = by_action.get(r['action'], 0) + 1
    print(f"breakdown: {by_action}")

    # Log
    if not args.dry_run:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        from datetime import datetime, timezone, timedelta
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'ts': datetime.now(timezone(timedelta(hours=9))).isoformat(),
                'total': len(items), 'actioned': actioned,
                'results': results,
            }, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
