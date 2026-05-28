"""thumbnail_relevance_audit.py — サムネ画像と記事タイトルの関連性を自動監査。

Claude Vision で画像を見て「タイトルのアーティスト/トピックと無関係でないか」を判定。
不適切と判定された記事を JSON でレポートし、owner_decision_queue に投入。

Usage:
  python3 lib/thumbnail_relevance_audit.py --since 2026-05-27
  python3 lib/thumbnail_relevance_audit.py --post-ids 3095,3146
  python3 lib/thumbnail_relevance_audit.py --report-only  # 既存ログから集計
"""
from __future__ import annotations
import argparse
import base64
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path('/home/aiuser/kpop-ai-system')
PUBLISH_LOG = ROOT / 'logs/unified_publish.jsonl'
OUT = ROOT / 'logs/thumbnail_audit.jsonl'
WP_RO = '/usr/local/sbin/kpop/kpop-wp-ro'


def _wp(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(['sudo', '-n', WP_RO] + args,
                       capture_output=True, text=True, check=False)
    return p.returncode, p.stdout


def _resolve_thumbnail_url(post_id: int) -> str | None:
    code, out = _wp(['post', 'meta', 'get', str(post_id), '_thumbnail_id'])
    if code != 0:
        return None
    tid = out.strip()
    if not tid.isdigit():
        return None
    code, out = _wp(['post', 'meta', 'get', tid, '_wp_attached_file'])
    if code != 0:
        return None
    rel = out.strip()
    if not rel:
        return None
    return f'https://www.kpopjournal.tokyo/wp-content/uploads/{rel}'


def _list_recent_posts(since: str) -> list[dict]:
    recs = []
    if not PUBLISH_LOG.exists():
        return recs
    with PUBLISH_LOG.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not r.get('success'):
                continue
            if r.get('ts', '') < since:
                continue
            if r.get('kind') not in ('breaking', 'original'):
                continue
            recs.append({
                'post_id': r['post_id'],
                'title': r.get('title', ''),
                'ts': r.get('ts', ''),
                'thumb_source': r.get('thumb_source'),
            })
    return recs


def _audit_one(post_id: int, title: str) -> dict:
    """Claude Vision で 1件監査。"""
    url = _resolve_thumbnail_url(post_id)
    if not url:
        return {'post_id': post_id, 'title': title, 'verdict': 'no_thumb',
                'reason': 'thumbnail_url_unresolved'}
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=15) as r:
            blob = r.read()
        b64 = base64.b64encode(blob).decode()
    except Exception as e:
        return {'post_id': post_id, 'title': title, 'verdict': 'fetch_error',
                'reason': str(e)[:120], 'url': url}

    import anthropic
    from dotenv import load_dotenv
    load_dotenv('/home/aiuser/kpop-ai-system/.env')
    client = anthropic.Anthropic()
    prompt = (
        f'記事タイトル: 「{title}」\n\n'
        '上記の画像が、このK-POP記事タイトルのアーティスト/トピックと'
        '明らかに無関係でないかを判定してください。\n'
        '判定: relevant(タイトルのアーティストや内容と整合する) / '
        'unrelated(明らかに無関係・別人物別アーティスト) / '
        'ambiguous(判定困難・抽象画像など)\n\n'
        'JSON で {"verdict": "...", "reason": "..."} のみ返してください。'
    )
    try:
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=300,
            messages=[{
                'role': 'user',
                'content': [
                    {'type': 'image', 'source': {
                        'type': 'base64', 'media_type': 'image/jpeg',
                        'data': b64,
                    }},
                    {'type': 'text', 'text': prompt},
                ],
            }],
        )
        txt = ''.join(b.text for b in resp.content if getattr(b, 'type', '') == 'text')
        m = re.search(r'\{[^}]*"verdict"[^}]*\}', txt, re.DOTALL)
        if m:
            j = json.loads(m.group(0))
        else:
            j = {'verdict': 'parse_error', 'reason': txt[:200]}
    except Exception as e:
        j = {'verdict': 'api_error', 'reason': str(e)[:200]}
    return {'post_id': post_id, 'title': title, 'url': url,
            'verdict': j.get('verdict', '?'), 'reason': j.get('reason', '')}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default='2026-05-27')
    ap.add_argument('--post-ids', default='')
    ap.add_argument('--limit', type=int, default=50)
    ap.add_argument('--report-only', action='store_true')
    args = ap.parse_args()

    if args.report_only:
        unrelated = []
        if OUT.exists():
            with OUT.open() as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get('verdict') == 'unrelated':
                        unrelated.append(r)
        print(f'unrelated thumbnails: {len(unrelated)}')
        for r in unrelated[-20:]:
            print(f'  post={r["post_id"]} title={r["title"][:50]} reason={r["reason"][:80]}')
        return

    if args.post_ids:
        targets = []
        for pid in args.post_ids.split(','):
            pid = pid.strip()
            if pid.isdigit():
                code, out = _wp(['post', 'get', pid, '--field=post_title'])
                title = out.strip() if code == 0 else ''
                targets.append({'post_id': int(pid), 'title': title})
    else:
        targets = _list_recent_posts(args.since)[:args.limit]

    print(f'audit targets: {len(targets)}')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('a') as out_f:
        for t in targets:
            r = _audit_one(t['post_id'], t['title'])
            r['audit_ts'] = datetime.now().isoformat()
            out_f.write(json.dumps(r, ensure_ascii=False) + '\n')
            out_f.flush()
            print(f'  {r["post_id"]} verdict={r["verdict"]} {r["title"][:40]}')


if __name__ == '__main__':
    main()
