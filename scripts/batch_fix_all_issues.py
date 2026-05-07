#!/usr/bin/env python3
"""
一括修正スクリプト — audit_state.jsonl の全issue を対象に修正実行

Phase 1: HTMLタグ/テキスト/meta/slug/category修正 (GPT + ルールベース)
Phase 2: GSCインデックス一括送信 (quota: 180/日)
Phase 3: X投稿リトライ (rate: 3/時)
Phase 4: サムネイル生成

※ Phase 1 を先に実行し、Phase 2-4 は別途またはcronで消化
"""
import sys, os, json, re, time
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

BASE = Path('/home/aiuser/kpop-ai-system')
AUDIT_STATE = BASE / 'data' / 'audit_state.jsonl'
SKIP_PATH = BASE / 'data' / 'audit_fixer_skip.json'
FIXED_LOG = BASE / 'logs' / 'audit_fixed.jsonl'
BATCH_LOG = BASE / 'logs' / 'batch_fix_20260501.log'

from pipeline.audit_fixer_universal import (
    fetch_post, update_post, rewrite_with_gpt, generate_meta_description,
    fix_unclosed_tags, FIXABLE_TYPES, GPT_REWRITE_TYPES,
)
from lib.gsc_indexing import notify_url_updated, get_access_token, get_quota_remaining

JST = timezone(timedelta(hours=9))


def log(msg):
    ts = datetime.now(JST).strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    with open(BATCH_LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def load_latest_audit():
    """audit_state.jsonl から最新レコードのみ取得 (post_id でデデュプ)"""
    latest = {}
    with open(AUDIT_STATE, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                pid = d.get('post_id')
                latest[pid] = d
            except:
                pass
    return latest


def load_skip_list():
    if SKIP_PATH.exists():
        try:
            return json.load(open(SKIP_PATH, encoding='utf-8'))
        except:
            pass
    return {}


def save_skip_list(sl):
    with open(SKIP_PATH, 'w', encoding='utf-8') as f:
        json.dump(sl, f, ensure_ascii=False, indent=2)


def record_fix(pid, ptype, keys):
    with open(FIXED_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'post_id': pid, 'post_type': ptype,
            'fixed_keys': keys,
            'fixed_at': datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False) + '\n')


def phase1_content_fixes(audit_data, skip_list, max_gpt=80):
    """Phase 1: unclosed_p, text_*, meta_desc_short, slug_encoded, no_artist_category"""
    log("=== Phase 1: コンテンツ修正 ===")

    # 対象を抽出
    targets = []
    for pid, rec in audit_data.items():
        if skip_list.get(str(pid), {}).get('skipped'):
            continue
        issues = rec.get('issues', [])
        fixable = [i for i in issues if i['type'] in FIXABLE_TYPES]
        if fixable:
            targets.append((pid, rec.get('post_type', 'post'), fixable))

    log(f"  対象記事: {len(targets)}件 (max GPT calls: {max_gpt})")

    fixed = 0
    gpt_calls = 0
    errors = 0

    for pid, ptype, issues in targets:
        if gpt_calls >= max_gpt:
            log(f"  GPT上限 {max_gpt} 到達、中断")
            break

        issue_types = [i['type'] for i in issues]
        post = fetch_post(pid, ptype)
        if not post:
            errors += 1
            continue

        title = post.get('title', {}).get('rendered', '') if isinstance(post.get('title'), dict) else ''
        payload = {}

        # 1. slug_encoded → 単純slug
        if 'slug_encoded' in issue_types:
            payload['slug'] = f"{ptype}-{pid}"

        # 2. カテゴリ修正
        if 'no_artist_category' in issue_types:
            try:
                from lib.auto_category import detect_artist_categories
                detected = detect_artist_categories(title)
                if detected:
                    current = post.get('categories', [])
                    payload['categories'] = list(set(current + detected))
            except:
                pass

        # 3. meta_desc_short/no_meta_description → excerpt生成
        if any(t in issue_types for t in ('meta_desc_short', 'no_meta_description')):
            payload['excerpt'] = generate_meta_description(post)

        # 4. unclosed_p のみ(テキスト問題なし) → タグ閉じのみ
        text_issues = [i for i in issues if i['type'].startswith('text_')
                       or i['type'] in ('unclosed_h2', 'unclosed_p', 'few_internal_links')]
        needs_gpt = [i for i in text_issues if i['type'] in GPT_REWRITE_TYPES]

        if needs_gpt:
            # GPTリライト
            new_content = rewrite_with_gpt(post, text_issues, ptype)
            if new_content and len(new_content) > 200:
                payload['content'] = new_content
                gpt_calls += 1
            else:
                # GPT失敗時はタグ閉じだけ試行
                content = post.get('content', {}).get('rendered', '')
                if 'unclosed_p' in issue_types or 'unclosed_h2' in issue_types:
                    payload['content'] = fix_unclosed_tags(content)
        elif 'unclosed_p' in issue_types or 'unclosed_h2' in issue_types:
            # テキスト問題なし、タグ閉じのみ
            content = post.get('content', {}).get('rendered', '')
            payload['content'] = fix_unclosed_tags(content)

        if payload:
            if update_post(pid, ptype, payload):
                fixed += 1
                record_fix(pid, ptype, list(payload.keys()))
                log(f"  [OK] id={pid} {title[:30]} -> {list(payload.keys())}")
            else:
                errors += 1
                log(f"  [ERR] id={pid} update失敗")
        else:
            log(f"  [SKIP] id={pid} 修正項目なし")

        # API負荷軽減
        time.sleep(0.5)

    log(f"  Phase 1 完了: {fixed}件修正, {errors}件エラー, GPT={gpt_calls}回")
    return fixed


def phase2_gsc_indexing(audit_data):
    """Phase 2: no_gsc_indexing の記事をGSCに送信"""
    log("=== Phase 2: GSCインデックス送信 ===")

    quota = get_quota_remaining()
    log(f"  本日残りquota: {quota}")
    if quota <= 0:
        log("  quota枯渇、スキップ")
        return 0

    # 対象URL収集
    targets = []
    for pid, rec in audit_data.items():
        issues = rec.get('issues', [])
        if any(i['type'] == 'no_gsc_indexing' for i in issues):
            targets.append(pid)

    log(f"  対象: {len(targets)}件 (quota: {quota})")

    token = get_access_token()
    if not token:
        log("  GSC認証失敗")
        return 0

    sent = 0
    for pid in targets[:quota]:
        # 記事URLを取得
        post = fetch_post(pid, 'post')
        if not post:
            continue
        url = post.get('link', '')
        if not url:
            continue

        result = notify_url_updated(url, token)
        status = result.get('status', 'error')
        if status in ('ok', 'fallback_ok'):
            sent += 1
        else:
            log(f"  [WARN] id={pid} GSC送信失敗: {status}")

        time.sleep(1)  # API負荷軽減

        if sent % 20 == 0:
            log(f"  ... {sent}件送信済み")

    log(f"  Phase 2 完了: {sent}/{len(targets)}件 送信")
    return sent


def phase3_x_posting(audit_data, max_posts=3):
    """Phase 3: x_missing の記事をX投稿 (レート制限あり)"""
    log("=== Phase 3: X投稿 ===")

    targets = []
    for pid, rec in audit_data.items():
        issues = rec.get('issues', [])
        if any(i['type'] in ('x_missing', 'x_post_error') for i in issues):
            targets.append(pid)

    log(f"  対象: {len(targets)}件 (今回上限: {max_posts}件)")

    try:
        from lib.x_poster import post_tweet
    except ImportError as e:
        log(f"  x_poster import失敗: {e}")
        return 0

    posted = 0
    for pid in targets[:max_posts]:
        post = fetch_post(pid, 'post')
        if not post:
            continue
        title = post.get('title', {}).get('rendered', '') if isinstance(post.get('title'), dict) else ''
        link = post.get('link', '')
        if not title or not link:
            continue
        if post.get('status') != 'publish':
            continue

        result = post_tweet(title, link, post_id=pid)
        if result.get('success'):
            posted += 1
            log(f"  [OK] id={pid} X投稿成功")
        else:
            log(f"  [WARN] id={pid} X投稿失敗: {result.get('error', '')[:50]}")

        time.sleep(2)

    log(f"  Phase 3 完了: {posted}/{min(len(targets), max_posts)}件 投稿")
    return posted


def phase4_thumbnails(audit_data):
    """Phase 4: no_thumbnail 記事にサムネイル生成"""
    log("=== Phase 4: サムネイル生成 ===")

    targets = []
    for pid, rec in audit_data.items():
        issues = rec.get('issues', [])
        if any(i['type'] in ('no_thumbnail', 'no_og_image') for i in issues):
            targets.append(pid)

    log(f"  対象: {len(targets)}件")
    if not targets:
        return 0

    # post_thumbnail_generator を使う
    try:
        from pipeline.post_thumbnail_generator import generate_and_upload_thumbnail
        generated = 0
        for pid in targets:
            try:
                result = generate_and_upload_thumbnail(pid)
                if result:
                    generated += 1
                    log(f"  [OK] id={pid} サムネ生成成功")
                else:
                    log(f"  [WARN] id={pid} サムネ生成失敗")
            except Exception as e:
                log(f"  [ERR] id={pid} {e}")
            time.sleep(2)
        log(f"  Phase 4 完了: {generated}/{len(targets)}件")
        return generated
    except ImportError:
        log("  post_thumbnail_generator import失敗、スキップ")
        return 0


def main():
    log("=" * 60)
    log("一括修正開始")

    audit_data = load_latest_audit()
    skip_list = load_skip_list()

    # 統計
    total = len(audit_data)
    with_issues = sum(1 for d in audit_data.values() if d.get('issues'))
    log(f"監査済み: {total}件, 問題あり: {with_issues}件 ({with_issues/total*100:.1f}%)")

    # Phase 1: コンテンツ修正
    p1 = phase1_content_fixes(audit_data, skip_list, max_gpt=80)

    # Phase 2: GSCインデックス
    p2 = phase2_gsc_indexing(audit_data)

    # Phase 3: X投稿 (レート制限のため3件ずつ)
    p3 = phase3_x_posting(audit_data, max_posts=3)

    # Phase 4: サムネイル
    p4 = phase4_thumbnails(audit_data)

    log("=" * 60)
    log(f"修正合計: コンテンツ={p1}, GSC={p2}, X={p3}, サムネ={p4}")
    log("完了")


if __name__ == '__main__':
    main()
