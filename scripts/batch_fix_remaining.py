#!/usr/bin/env python3
"""
残りissue修正:
1. Phase 1 残り78件 (GPT上限引き上げ)
2. Phase 4 サムネイル14件 (正しい関数名で)
3. X投稿追加 (レート制限内で)
"""
import sys, os, json, time
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

BASE = Path('/home/aiuser/kpop-ai-system')
AUDIT_STATE = BASE / 'data' / 'audit_state.jsonl'
FIXED_LOG = BASE / 'logs' / 'audit_fixed.jsonl'
BATCH_LOG = BASE / 'logs' / 'batch_fix_20260501.log'
JST = timezone(timedelta(hours=9))

from pipeline.audit_fixer_universal import (
    fetch_post, update_post, rewrite_with_gpt, generate_meta_description,
    fix_unclosed_tags, FIXABLE_TYPES, GPT_REWRITE_TYPES,
)


def log(msg):
    ts = datetime.now(JST).strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    with open(BATCH_LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def load_latest_audit():
    latest = {}
    with open(AUDIT_STATE, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                latest[d.get('post_id')] = d
            except:
                pass
    return latest


def already_fixed_ids():
    """既に修正済みのpost_idセット"""
    ids = set()
    if FIXED_LOG.exists():
        with open(FIXED_LOG, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    ids.add(d.get('post_id'))
                except:
                    pass
    return ids


def record_fix(pid, ptype, keys):
    with open(FIXED_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'post_id': pid, 'post_type': ptype,
            'fixed_keys': keys,
            'fixed_at': datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False) + '\n')


def phase1_remaining(audit_data, done_ids, max_gpt=80):
    """Phase 1 続き: まだ修正されていない記事"""
    log("=== Phase 1 続き: 残りコンテンツ修正 ===")
    targets = []
    for pid, rec in audit_data.items():
        if pid in done_ids:
            continue
        issues = rec.get('issues', [])
        fixable = [i for i in issues if i['type'] in FIXABLE_TYPES]
        if fixable:
            targets.append((pid, rec.get('post_type', 'post'), fixable))

    log(f"  未修正対象: {len(targets)}件")
    fixed = 0
    gpt_calls = 0

    for pid, ptype, issues in targets:
        if gpt_calls >= max_gpt:
            log(f"  GPT上限 {max_gpt} 到達")
            break

        issue_types = [i['type'] for i in issues]
        post = fetch_post(pid, ptype)
        if not post:
            continue

        title = post.get('title', {}).get('rendered', '') if isinstance(post.get('title'), dict) else ''
        payload = {}

        if 'slug_encoded' in issue_types:
            payload['slug'] = f"{ptype}-{pid}"

        if 'no_artist_category' in issue_types:
            try:
                from lib.auto_category import detect_artist_categories
                detected = detect_artist_categories(title)
                if detected:
                    current = post.get('categories', [])
                    payload['categories'] = list(set(current + detected))
            except:
                pass

        if any(t in issue_types for t in ('meta_desc_short', 'no_meta_description')):
            payload['excerpt'] = generate_meta_description(post)

        text_issues = [i for i in issues if i['type'].startswith('text_')
                       or i['type'] in ('unclosed_h2', 'unclosed_p', 'few_internal_links')]
        needs_gpt = [i for i in text_issues if i['type'] in GPT_REWRITE_TYPES]

        if needs_gpt:
            new_content = rewrite_with_gpt(post, text_issues, ptype)
            if new_content and len(new_content) > 200:
                payload['content'] = new_content
                gpt_calls += 1
            elif 'unclosed_p' in issue_types or 'unclosed_h2' in issue_types:
                content = post.get('content', {}).get('rendered', '')
                payload['content'] = fix_unclosed_tags(content)
        elif 'unclosed_p' in issue_types or 'unclosed_h2' in issue_types:
            content = post.get('content', {}).get('rendered', '')
            payload['content'] = fix_unclosed_tags(content)

        if payload:
            if update_post(pid, ptype, payload):
                fixed += 1
                record_fix(pid, ptype, list(payload.keys()))
                log(f"  [OK] id={pid} {title[:30]} -> {list(payload.keys())}")
            else:
                log(f"  [ERR] id={pid} update失敗")

        time.sleep(0.5)

    log(f"  Phase 1 続き完了: {fixed}件修正, GPT={gpt_calls}回")
    return fixed


def phase4_thumbnails(audit_data):
    """Phase 4: サムネイル生成 (正しい関数名)"""
    log("=== Phase 4: サムネイル生成 ===")
    targets = []
    for pid, rec in audit_data.items():
        issues = rec.get('issues', [])
        if any(i['type'] in ('no_thumbnail', 'no_og_image') for i in issues):
            targets.append(pid)

    log(f"  対象: {len(targets)}件")
    if not targets:
        return 0

    try:
        from pipeline.post_thumbnail_generator import regenerate_for_post
    except ImportError as e:
        log(f"  import失敗: {e}")
        return 0

    generated = 0
    for pid in targets:
        try:
            result = regenerate_for_post(pid)
            if result and result.get('success'):
                generated += 1
                log(f"  [OK] id={pid} サムネ生成成功")
            else:
                log(f"  [WARN] id={pid} サムネ生成失敗: {result}")
        except Exception as e:
            log(f"  [ERR] id={pid} {str(e)[:60]}")
        time.sleep(2)

    log(f"  Phase 4 完了: {generated}/{len(targets)}件")
    return generated


def phase3_x_extra(audit_data, done_ids, max_posts=3):
    """Phase 3 追加: X投稿"""
    log("=== Phase 3 追加: X投稿 ===")
    targets = []
    for pid, rec in audit_data.items():
        issues = rec.get('issues', [])
        if any(i['type'] in ('x_missing', 'x_post_error') for i in issues):
            targets.append(pid)

    # 先ほど投稿済みの3件を除外
    x_log = BASE / 'logs' / 'x_posts.jsonl'
    recent_x = set()
    if x_log.exists():
        with open(x_log, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if '2026-05-01' in d.get('ts', ''):
                        recent_x.add(d.get('post_id'))
                except:
                    pass
    targets = [pid for pid in targets if pid not in recent_x]

    log(f"  対象: {len(targets)}件 (今回上限: {max_posts}件)")

    try:
        from lib.x_poster import post_tweet
    except ImportError as e:
        log(f"  import失敗: {e}")
        return 0

    posted = 0
    for pid in targets[:max_posts]:
        post = fetch_post(pid, 'post')
        if not post:
            continue
        title = post.get('title', {}).get('rendered', '') if isinstance(post.get('title'), dict) else ''
        link = post.get('link', '')
        if not title or not link or post.get('status') != 'publish':
            continue

        result = post_tweet(title, link, post_id=pid)
        if result.get('success'):
            posted += 1
            log(f"  [OK] id={pid} X投稿成功")
        else:
            log(f"  [WARN] id={pid} {result.get('error', '')[:50]}")
        time.sleep(2)

    log(f"  Phase 3 追加完了: {posted}件")
    return posted


def main():
    log("=" * 60)
    log("残り修正開始 (Phase 1残り + Phase 4 + Phase 3追加)")

    audit_data = load_latest_audit()
    done_ids = already_fixed_ids()
    log(f"修正済み: {len(done_ids)}件")

    p1 = phase1_remaining(audit_data, done_ids, max_gpt=80)
    p4 = phase4_thumbnails(audit_data)
    p3 = phase3_x_extra(audit_data, done_ids, max_posts=3)

    log("=" * 60)
    log(f"追加修正合計: コンテンツ={p1}, サムネ={p4}, X={p3}")
    log("完了")


if __name__ == '__main__':
    main()
