#!/usr/bin/env python3
"""WP記事内のプロフィール block (<dl>メンバー<dd>...</dd></dl>) を
config/artist_database.json と照合し、stale/extra member 混入を検出する。

2026-05-12 post 22075 で発覚した「config は 6人正なのに WP 本文には Jinni 含む7人と
LLM 幻覚で書かれている」事故への再発防止 scan。

config の members に対し、WP 本文の members 列が:
  - missing  : config にあるのに本文に無い
  - extra    : 本文にあるのに config に無い (= stale or 幻覚混入)
  - mismatch : 件数不一致

Usage:
  python3 scripts/scan_wp_profile_stale_member.py [--hours 24] [--max 200] [--json]
  python3 scripts/scan_wp_profile_stale_member.py --post-id 22075   # 単発

cron想定 (1日1回 / 朝 6:10):
  10 6 * * * cd /home/aiuser/kpop-ai-system && python3 scripts/scan_wp_profile_stale_member.py >> logs/scan_profile_stale.log 2>&1
"""
import argparse, json, os, re, sys
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

WP_BASE = 'https://www.kpopjournal.tokyo'
DB_PATH = '/home/aiuser/kpop-ai-system/config/artist_database.json'


def _normalize(name: str) -> str:
    """Lily / LILY / lily を統一比較するため小文字化 + 周辺空白除去。"""
    return name.strip().lower()


def extract_profile_block(html: str) -> dict | None:
    """記事HTMLから kpj-artist-profile block 内のメンバー列・代表曲を抽出。

    Returns: {'artist_name': str, 'members': list[str]} or None
    """
    m = re.search(
        r'<div class="kpj-artist-profile">.*?<h3>([^<]+)\s*プロフィール</h3>.*?'
        r'<dt>メンバー</dt>\s*<dd>([^<]+)</dd>',
        html, re.DOTALL,
    )
    if not m:
        return None
    artist = m.group(1).strip()
    members_raw = m.group(2).strip()
    members = [x.strip() for x in re.split(r'[,、]', members_raw) if x.strip()]
    return {'artist_name': artist, 'members': members}


def compare(wp_members: list[str], db_members: list[str]) -> dict:
    """WP本文 members と config members を照合。

    Returns: {
      'missing': list[str],  # config にあるのに WP 本文に無い
      'extra':   list[str],  # WP 本文にあるのに config に無い (= stale/幻覚)
      'count_match': bool,
    }
    """
    wp_set = {_normalize(x) for x in wp_members}
    db_set = {_normalize(x) for x in db_members}
    missing = [m for m in db_members if _normalize(m) not in wp_set]
    extra = [m for m in wp_members if _normalize(m) not in db_set]
    return {
        'missing': missing,
        'extra': extra,
        'count_match': len(wp_members) == len(db_members),
    }


def _load_db() -> dict:
    with open(DB_PATH, encoding='utf-8') as f:
        return json.load(f)


def _fetch_recent_posts(hours: int, per_page: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
    url = (f'{WP_BASE}/wp-json/wp/v2/posts?after={cutoff}'
           f'&per_page={min(per_page,100)}&_fields=id,date,title,link,content,status')
    req = Request(url, headers={'User-Agent': 'kpj-stale-scan/1.0'})
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _fetch_single_post(pid: int) -> dict:
    url = f'{WP_BASE}/wp-json/wp/v2/posts/{pid}?_fields=id,date,title,link,content,status'
    req = Request(url, headers={'User-Agent': 'kpj-stale-scan/1.0'})
    with urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def scan_post(post: dict, db: dict) -> dict | None:
    """1記事を scan。違反があれば dict を返す、なければ None。"""
    html = post.get('content', {}).get('rendered', '') or post.get('content', {}).get('raw', '')
    block = extract_profile_block(html)
    if not block:
        return None
    artist = block['artist_name']
    if artist not in db:
        # database 未登録 (新規 artist) — scan 対象外
        return None
    db_members = db[artist].get('members', [])
    if not db_members:
        return None
    diff = compare(block['members'], db_members)
    if not diff['extra'] and not diff['missing']:
        return None
    return {
        'post_id': post['id'],
        'link': post.get('link', ''),
        'artist': artist,
        'wp_members': block['members'],
        'db_members': db_members,
        'missing': diff['missing'],
        'extra': diff['extra'],
        'severity': 'high' if diff['extra'] else 'medium',
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=int, default=24)
    ap.add_argument('--max', type=int, default=200)
    ap.add_argument('--post-id', type=int, default=0, help='単一記事のみ scan')
    ap.add_argument('--json', action='store_true', help='JSON 出力')
    args = ap.parse_args()

    db = _load_db()
    posts = ([_fetch_single_post(args.post_id)] if args.post_id
             else _fetch_recent_posts(args.hours, args.max))

    violations = []
    for p in posts:
        try:
            v = scan_post(p, db)
            if v:
                violations.append(v)
        except Exception as e:
            print(f'  skip pid={p.get("id")}: {e}', file=sys.stderr)

    if args.json:
        print(json.dumps({'scanned': len(posts), 'violations': violations},
                         ensure_ascii=False, indent=2))
        return

    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    print(f'[{now}] scanned={len(posts)} violations={len(violations)}')
    for v in violations:
        print(f'  [{v["severity"]}] pid={v["post_id"]} {v["artist"]}')
        if v['extra']:
            print(f'    extra (stale/幻覚): {v["extra"]}')
        if v['missing']:
            print(f'    missing: {v["missing"]}')
        print(f'    db_members:    {v["db_members"]}')
        print(f'    wp_members:    {v["wp_members"]}')
        print(f'    link:          {v["link"]}')


if __name__ == '__main__':
    main()
