#!/usr/bin/env python3
"""日次バッチ監査 — 公開24h以内全件×4項目+横断突合

既存個別監査(post_audit.sh, lib/full_audit_engine, comprehensive_audit)が
記事単位でしか動かず、複数記事/複数系統を跨ぐ違反(同日サムネ重複・
WP↔Xqueue不整合・cat-tag-fm三点不整合・letterboxサムネ等)が検出され
ない問題を解決する。

実行:
  python3 pipeline/daily_batch_audit.py            # 監査のみ
  python3 pipeline/daily_batch_audit.py --auto-fix # 自動修正も実行
  python3 pipeline/daily_batch_audit.py --hours 48 # 過去48hに広げる

出力:
  logs/daily_batch_audit_YYYYMMDD.json — 違反詳細
  Discord 通知(設定があれば)
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from lib.cross_audit import (
    check_letterbox,
    check_thumb_duplicate_today,
    check_artist_triplet,
    check_wp_xqueue_consistency,
    detect_title_artist,
)

WP_BASE = 'https://www.kpopjournal.tokyo'
HOME = os.path.expanduser('~')
JST = timezone(timedelta(hours=9))


def fetch_recent_posts(hours: int = 24) -> list[dict]:
    cutoff = (datetime.now(JST) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
    posts = []
    for page in range(1, 4):
        r = subprocess.run(
            ['curl', '-s', '-K', f'{HOME}/.wp_auth',
             f'{WP_BASE}/wp-json/wp/v2/posts?after={cutoff}&status=publish'
             f'&per_page=50&page={page}&_fields=id,date,title,link,categories,tags,featured_media&context=edit'],
            capture_output=True, text=True, timeout=30)
        try:
            data = json.loads(r.stdout)
            if not isinstance(data, list) or not data:
                break
            posts.extend(data)
        except Exception:
            break
    return posts


def audit_per_post(post: dict) -> dict:
    pid = post['id']
    title = (post.get('title') or {}).get('rendered', '')
    fm = post.get('featured_media', 0)
    issues = []

    # featured_mediaのURL取得
    fm_url = ''
    if fm:
        r = subprocess.run(
            ['curl', '-s', '-K', f'{HOME}/.wp_auth',
             f'{WP_BASE}/wp-json/wp/v2/media/{fm}?_fields=source_url,media_details,alt_text'],
            capture_output=True, text=True, timeout=15)
        try:
            m = json.loads(r.stdout)
            fm_url = m.get('source_url', '')
            md = m.get('media_details', {})
            w, h = md.get('width', 0), md.get('height', 0)
            alt = m.get('alt_text', '')
            # 縦長サムネ (height>width) は memory ルールで NG
            if w and h and h > w:
                issues.append({'severity': 'high', 'type': 'portrait_thumbnail',
                               'detail': f'{w}x{h}'})
            if not alt:
                issues.append({'severity': 'medium', 'type': 'thumbnail_alt_empty'})
        except Exception:
            pass

    # letterbox検査
    if fm_url:
        lb = check_letterbox(fm_url)
        if lb.get('is_letterbox'):
            issues.append({'severity': 'high', 'type': 'thumbnail_letterbox',
                           'detail': f"mode={lb.get('mode')} L_sim={lb.get('left_color_sim')}"})

    # artist三点整合
    triplet = check_artist_triplet(pid)
    if triplet['verdict'] == 'MISMATCH':
        issues.append({'severity': 'critical', 'type': 'artist_mismatch',
                       'detail': '; '.join(triplet['mismatches'])})

    # 内部リンク数 (主軸への2本以上)
    r = subprocess.run(
        ['curl', '-s', '-K', f'{HOME}/.wp_auth',
         f'{WP_BASE}/wp-json/wp/v2/posts/{pid}?context=edit&_fields=content'],
        capture_output=True, text=True, timeout=15)
    try:
        d = json.loads(r.stdout)
        content = (d.get('content') or {}).get('raw', '')
        kpopj_links = content.count('kpopjournal.tokyo')
        if kpopj_links < 2:
            issues.append({'severity': 'medium', 'type': 'low_internal_links',
                           'detail': f'count={kpopj_links}'})
        # 情報ソース欄に隣接記事/タイムスタンプ混入(kstyle bug pattern)
        import re as _re
        src_section = _re.search(r'情報ソース[\s\S]{0,500}', content)
        if src_section:
            snip = src_section.group(0)
            if _re.search(r'\d{4}/\d{2}/\d{2}\s*\d{2}:\d{2}', snip) or '【PHOTO】' in snip:
                issues.append({'severity': 'high', 'type': 'source_section_polluted',
                               'detail': 'date stamp or sibling article title in source line'})
    except Exception:
        pass

    return {'post_id': pid, 'title': title[:60], 'fm': fm, 'issues': issues}


def audit_cross_batch(posts: list[dict]) -> dict:
    """記事横断の整合性検査"""
    findings = {}
    pids = [p['id'] for p in posts]

    # 同日サムネ重複
    dups = check_thumb_duplicate_today(pids)
    findings['thumb_duplicates'] = dups

    # WP-Xqueue整合
    findings['wp_xqueue'] = check_wp_xqueue_consistency()

    return findings


def auto_fix(per_post_results: list[dict], cross: dict) -> list[str]:
    """自動修正可能な違反だけを修正。重大判断はユーザー任せ。"""
    fixes = []
    # 1. WP-Xqueue: draft/trashの除去 + artistフィールド再生成
    queue_path = BASE / 'config' / 'x_post_queue.json'
    if queue_path.exists():
        q = json.load(open(queue_path))
        items = q if isinstance(q, list) else (q.get('queue') or q.get('items') or [])
        violations = cross.get('wp_xqueue', {}).get('wp_status_violations', [])
        bad_pids = {v['post_id'] for v in violations}
        if bad_pids:
            kept = [it for it in items if int(it.get('post_id') or 0) not in bad_pids]
            if isinstance(q, list):
                json.dump(kept, open(queue_path, 'w'), ensure_ascii=False, indent=2)
            else:
                key = 'queue' if 'queue' in q else 'items'
                q[key] = kept
                json.dump(q, open(queue_path, 'w'), ensure_ascii=False, indent=2)
            fixes.append(f'x_queue: removed {len(items)-len(kept)} non-publish entries')

        # artist再生成
        artist_fixes = cross.get('wp_xqueue', {}).get('artist_field_mismatches', [])
        if artist_fixes:
            q2 = json.load(open(queue_path))
            items2 = q2 if isinstance(q2, list) else (q2.get('queue') or q2.get('items') or [])
            ids_to_fix = {f['post_id']: f['title_artist'] for f in artist_fixes}
            n_fixed = 0
            for it in items2:
                pid = int(it.get('post_id') or 0)
                if pid in ids_to_fix:
                    it['artist'] = ids_to_fix[pid] or ''
                    n_fixed += 1
            if isinstance(q2, list):
                json.dump(items2, open(queue_path, 'w'), ensure_ascii=False, indent=2)
            else:
                key = 'queue' if 'queue' in q2 else 'items'
                q2[key] = items2
                json.dump(q2, open(queue_path, 'w'), ensure_ascii=False, indent=2)
            fixes.append(f'x_queue: corrected artist field for {n_fixed} entries')

    return fixes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=int, default=24)
    ap.add_argument('--auto-fix', action='store_true')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    posts = fetch_recent_posts(args.hours)
    if not args.quiet:
        print(f'[daily_batch_audit] {len(posts)}件 (last {args.hours}h)')

    per_post = []
    for p in posts:
        r = audit_per_post(p)
        per_post.append(r)
        if r['issues'] and not args.quiet:
            print(f"  pid={r['post_id']} ({r['title']}): {len(r['issues'])} issues")
            for iss in r['issues']:
                print(f"    [{iss['severity'].upper()}] {iss['type']}: {iss.get('detail','')}")

    cross = audit_cross_batch(posts)

    # サマリ
    crit_count = sum(1 for r in per_post for i in r['issues'] if i['severity'] == 'critical')
    high_count = sum(1 for r in per_post for i in r['issues'] if i['severity'] == 'high')
    med_count = sum(1 for r in per_post for i in r['issues'] if i['severity'] == 'medium')

    cross_violations = (
        len(cross.get('thumb_duplicates', [])) +
        len(cross.get('wp_xqueue', {}).get('wp_status_violations', [])) +
        len(cross.get('wp_xqueue', {}).get('artist_field_mismatches', []))
    )

    if not args.quiet:
        print(f"\n=== サマリ ===")
        print(f"  per-post: critical={crit_count} high={high_count} medium={med_count}")
        print(f"  cross-batch violations: {cross_violations}")
        print(f"  thumb_duplicates: {len(cross.get('thumb_duplicates', []))}")
        print(f"  wp_xqueue draft/trash: {len(cross.get('wp_xqueue', {}).get('wp_status_violations', []))}")
        print(f"  artist field mismatches: {len(cross.get('wp_xqueue', {}).get('artist_field_mismatches', []))}")

    fix_actions = []
    if args.auto_fix:
        fix_actions = auto_fix(per_post, cross)
        if not args.quiet:
            print(f"\n=== auto-fix ===")
            for f in fix_actions:
                print(f"  ✓ {f}")

    # 保存
    log_dir = BASE / 'logs'
    log_dir.mkdir(exist_ok=True)
    out_path = log_dir / f'daily_batch_audit_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    json.dump({
        'ran_at': datetime.now(JST).isoformat(),
        'hours': args.hours,
        'posts_audited': len(posts),
        'per_post': per_post,
        'cross_batch': cross,
        'auto_fix_actions': fix_actions,
        'summary': {
            'critical': crit_count, 'high': high_count, 'medium': med_count,
            'cross_violations': cross_violations,
        },
    }, open(out_path, 'w'), ensure_ascii=False, indent=2)
    if not args.quiet:
        print(f"\n  log: {out_path}")

    # 異常時はexit 1
    if crit_count > 0 or cross_violations > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
