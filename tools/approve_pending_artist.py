#!/usr/bin/env python3
"""pending_artists.jsonl の entry を承認 → WP category + idol wiki を自動作成。

Usage:
    python3 tools/approve_pending_artist.py --list
    python3 tools/approve_pending_artist.py <artist_name>          # 単一承認
    python3 tools/approve_pending_artist.py --all                  # pending 全件
    python3 tools/approve_pending_artist.py --dry-run <artist>     # 動作確認のみ

各承認は以下を行う:
  1. WP category 作成 (parent=26, name + slug)
  2. profile_wiki_builder.build_one() で profile JSON + wiki page 作成
  3. internal_link_dictionary + frontend slug list 更新
  4. pending queue に resolved marker append

Note: profile_wiki_builder は Claude Sonnet + Web Search を 1 call (~$0.05/artist) 消費する。
"""
from __future__ import annotations
import argparse
import base64
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

from lib.pending_artist_queue import list_pending, mark_resolved
from pipeline.missing_artist_scanner import (
    name_to_slug, get_idol_child_categories,
)

WP_BASE = 'https://www.kpopjournal.tokyo/wp-json/wp/v2'
MASTER_PATH = Path('/home/aiuser/kpop-ai-system/config/artist_master.json')


def _load_master() -> dict:
    if not MASTER_PATH.exists():
        return {'artists': []}
    return json.loads(MASTER_PATH.read_text(encoding='utf-8'))


def is_in_master(artist_name: str) -> bool:
    """artist_master.json に登録済かを name_en / name_ja で照合 (case-insensitive)。"""
    master = _load_master()
    name_norm = artist_name.strip().lower()
    for a in master.get('artists', []):
        for field in ('name_en', 'name_ja', 'id'):
            v = (a.get(field) or '').strip().lower()
            if v and v == name_norm:
                return True
    return False


def add_master_stub(artist_name: str, slug: str, wp_category_id: int) -> None:
    """profile JSON を読み込んで artist_master に minimal entry を append (--add-to-master 用)。"""
    master = _load_master()
    if any((a.get('id') or '').lower() == slug.lower() for a in master.get('artists', [])):
        return  # 既存
    prof_path = Path(f'/home/aiuser/kpop-ai-system/config/artist_profiles/{slug}.json')
    prof = json.loads(prof_path.read_text(encoding='utf-8')) if prof_path.exists() else {}
    entry = {
        'id': slug,
        'name_en': artist_name,
        'name_ko': '',
        'name_ja': artist_name,
        'slug': f'{slug}-profile',
        'type': 'group',
        'agency': prof.get('agency', ''),
        'debut_date': prof.get('debut_date', ''),
        'wp_category_id': int(wp_category_id),
        'wp_tag_ids': [],
        'members': [
            {'name': m.get('name_en', ''), 'name_ko': m.get('name_kr', ''),
             'birthday': m.get('birth', ''), 'role': m.get('position', '')}
            for m in prof.get('members', [])
        ],
    }
    master.setdefault('artists', []).append(entry)
    MASTER_PATH.write_text(
        json.dumps(master, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def _wp_auth_header() -> str:
    user = os.getenv('WP_USER', '')
    pw = os.getenv('WP_PASS', '')
    if not user or not pw:
        raise RuntimeError('WP_USER/WP_PASS not set in env')
    token = base64.b64encode(f'{user}:{pw}'.encode()).decode()
    return f'Basic {token}'


def create_wp_category(name: str, slug: str, parent: int = 26) -> int:
    """parent=26 (idol) の子カテゴリを作成または re-parent。
    parent=0 で同 slug が既にあれば parent=26 に move する (WP の slug 重複 -idol 自動 suffix 回避)。"""
    # 既存チェック (任意 parent)
    qs = urllib.parse.urlencode({'slug': slug, 'hide_empty': 'false'})
    url = f'{WP_BASE}/categories?{qs}'
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            existing = json.loads(r.read())
    except Exception:
        existing = []
    if existing:
        cat = existing[0]
        cid = int(cat['id'])
        if cat.get('parent') == parent:
            return cid
        # re-parent
        body = json.dumps({'parent': parent}).encode()
        req = urllib.request.Request(
            f'{WP_BASE}/categories/{cid}',
            data=body,
            headers={'Authorization': _wp_auth_header(), 'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            json.loads(r.read())
        return cid

    # 新規作成
    body = json.dumps({'name': name, 'slug': slug, 'parent': parent}).encode()
    req = urllib.request.Request(
        f'{WP_BASE}/categories',
        data=body,
        headers={'Authorization': _wp_auth_header(), 'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.loads(r.read())
    return int(res.get('id', 0))


def build_idol_wiki(artist: str, slug: str) -> bool:
    """profile_wiki_builder.build_one() を呼び profile JSON + wiki page を作成。"""
    import anthropic
    from pipeline import profile_wiki_builder as pwb
    client = anthropic.Anthropic()
    ok = pwb.build_one(client, artist, slug)
    if ok:
        pwb.update_internal_link_dictionary()
        pwb.update_frontend_slug_list()
    return ok


def approve_one(artist: str, dry_run: bool = False,
                add_to_master: bool = False) -> bool:
    slug = name_to_slug(artist)
    if not slug:
        print(f'  ✗ slug generation failed for {artist!r}')
        return False

    print(f'\n→ {artist} (slug={slug})')

    # artist_master gate (memory feedback: auto-create は登録済のみ)
    if not is_in_master(artist) and not add_to_master:
        print(
            f'  ✗ {artist!r} not in artist_master.json. '
            f'手動で追加するか --add-to-master を付けて再実行。'
        )
        return False

    if dry_run:
        print('  [dry-run] would create WP category + idol wiki')
        if add_to_master:
            print('  [dry-run] would append stub to artist_master.json')
        return True

    # 1. WP category
    try:
        cat_id = create_wp_category(artist, slug)
        print(f'  ✓ WP category: id={cat_id}')
    except Exception as e:
        print(f'  ✗ WP category failed: {e}')
        return False

    # 2. idol wiki
    try:
        wiki_ok = build_idol_wiki(artist, slug)
        if wiki_ok:
            print(f'  ✓ idol wiki built')
        else:
            print(f'  ✗ idol wiki failed (continuing)')
    except Exception as e:
        print(f'  ✗ idol wiki error: {e}')
        wiki_ok = False

    # 3. artist_master stub (--add-to-master 時のみ)
    if add_to_master and not is_in_master(artist):
        try:
            add_master_stub(artist, slug, cat_id)
            print(f'  ✓ artist_master stub appended')
        except Exception as e:
            print(f'  ✗ artist_master stub failed: {e}')

    # 4. queue resolve
    mark_resolved(
        artist,
        f'auto-create: category_id={cat_id} wiki_ok={wiki_ok}',
    )
    print(f'  ✓ queue marked resolved')
    return wiki_ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('artist', nargs='?', help='artist name to approve')
    ap.add_argument('--list', action='store_true', help='show pending queue')
    ap.add_argument('--all', action='store_true', help='approve all pending')
    ap.add_argument('--dry-run', action='store_true', help='no side effects')
    ap.add_argument('--add-to-master', action='store_true',
                    help='artist_master.json に未登録なら stub を append して進める')
    args = ap.parse_args()

    pending = list_pending()
    if args.list:
        if not pending:
            print('(pending queue is empty)')
            return
        print(f'pending: {len(pending)} artists')
        for e in pending:
            print(
                f"  - {e['artist']}  (first_seen=post:{e.get('first_seen_post_id')}  "
                f"miss_cat={e.get('missing_category')}  miss_profile={e.get('missing_profile')}  "
                f"ts={e.get('ts','')[:16]})"
            )
        return

    if args.all:
        if not pending:
            print('(pending queue is empty)')
            return
        ok = ng = 0
        for e in pending:
            if approve_one(e['artist'], dry_run=args.dry_run, add_to_master=args.add_to_master):
                ok += 1
            else:
                ng += 1
        print(f'\n=== {ok} approved / {ng} failed ===')
        return

    if not args.artist:
        ap.error('Provide <artist>, --list, or --all')
    approve_one(args.artist, dry_run=args.dry_run, add_to_master=args.add_to_master)


if __name__ == '__main__':
    main()
