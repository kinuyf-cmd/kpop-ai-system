#!/usr/bin/env python3
"""post_publish_hook.py — 全パイプライン共通のポストパブリッシュフック

記事公開後に必ずこの関数を呼ぶこと。
全品質チェックを統一的に実行し、不合格なら即draft化。

Usage:
  from lib.post_publish_hook import run_post_publish
  result = run_post_publish(post_id)
  # result['status'] = 'pass' | 'draft' | 'error'

実行内容:
  1. enricher (3行まとめ/プロフィール/関連記事/サムネ品質)
  2. full_audit (16項目+chart/matome判定)
  3. fact_check (日付整合性/匿名化/事実検証)
  4. カテゴリ2(デフォルト)除去
  5. 不合格時はdraft化+ログ記録
"""
import sys
import os
import json
import re
import urllib.request
import base64
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
WP_API = 'https://www.kpopjournal.tokyo/wp-json/wp/v2'
JST = timezone(timedelta(hours=9))
HOOK_LOG = '/home/aiuser/kpop-ai-system/logs/post_publish_hook.jsonl'


def _fetch_post(post_id):
    try:
        url = f"{WP_API}/posts/{post_id}?_embed=true"
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        return json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        print(f"  [hook] fetch err: {e}")
        return None


def _draft_post(post_id, reason):
    """記事をdraft化 + Next.js ISRキャッシュパージ"""
    try:
        body = json.dumps({'status': 'draft'}).encode()
        url = f"{WP_API}/posts/{post_id}"
        req = urllib.request.Request(url, data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        slug = result.get('slug', '')
        print(f"  [hook] DRAFT化: {reason}")
        # ISRキャッシュパージ (soft-404防止)
        if slug:
            try:
                from lib.frontend_cache import purge_post
                purge_post(slug)
                print(f"  [hook] cache purge: /{slug}/")
            except Exception:
                pass
        return True
    except Exception as e:
        print(f"  [hook] draft err: {e}")
        return False


def _fix_categories(post_id, categories):
    """カテゴリ2(デフォルト)を除去"""
    if len(categories) > 1 and 2 in categories:
        new_cats = [c for c in categories if c != 2]
        try:
            body = json.dumps({'categories': new_cats}).encode()
            url = f"{WP_API}/posts/{post_id}"
            req = urllib.request.Request(url, data=body, method='POST',
                headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=15)
            print(f"  [hook] カテゴリ修正: {categories} → {new_cats}")
            return new_cats
        except Exception:
            pass
    return categories


def _log(entry):
    os.makedirs(os.path.dirname(HOOK_LOG), exist_ok=True)
    with open(HOOK_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def run_post_publish(post_id, post_type='post'):
    """全パイプライン共通のポストパブリッシュフック

    Returns:
        {'status': 'pass'|'draft'|'error', 'issues': [...], 'changes': [...]}
    """
    result = {'post_id': post_id, 'status': 'pass', 'issues': [], 'changes': []}
    now = datetime.now(JST)
    print(f"  [hook] post_publish_hook start: post_id={post_id}")

    # 0. 記事取得
    post = _fetch_post(post_id)
    if not post:
        result['status'] = 'error'
        result['issues'].append('fetch_failed')
        _log({**result, 'ts': now.isoformat()})
        return result

    title = post.get('title', {}).get('rendered', '')
    content = post.get('content', {}).get('rendered', '')
    categories = post.get('categories', [])

    # 1. enricher (3行まとめ/プロフィール/関連記事/サムネ品質)
    try:
        from pipeline.post_publish_enricher import enrich_post
        er = enrich_post(post_id)
        result['changes'].extend(er.get('changes', []))
        if er.get('status') == 'thumb_draft':
            result['status'] = 'draft'
            result['issues'].append('thumbnail_regen_failed')
    except Exception as e:
        print(f"  [hook] enricher err: {e}")

    # 2. カテゴリ修正
    _fix_categories(post_id, categories)

    # 3. full_audit (再取得してチェック)
    try:
        post_fresh = _fetch_post(post_id)
        if post_fresh:
            from lib.full_audit_engine import full_audit
            issues = full_audit(post_fresh, post_type)
            high_issues = [i for i in issues if i.get('severity') == 'high']
            if high_issues:
                result['issues'].extend([i['type'] for i in high_issues])
                # HIGH issue 2件以上ならdraft化
                if len(high_issues) >= 2:
                    _draft_post(post_id, f"HIGH issues: {[i['type'] for i in high_issues]}")
                    result['status'] = 'draft'
    except Exception as e:
        print(f"  [hook] audit err: {e}")

    # 4. fact_check (浅いチェック)
    try:
        from lib.fact_checker import check_article
        fc = check_article(title, content, post.get('date', ''))
        critical = fc.get('critical', [])
        if critical:
            result['issues'].extend([f'fc_critical: {c}' for c in critical])
            _draft_post(post_id, f"fact_check CRITICAL: {critical}")
            result['status'] = 'draft'
    except Exception as e:
        print(f"  [hook] factcheck err: {e}")

    # 4b. LLMファクトチェック (深いチェック — 捏造検出)
    if result.get('status') != 'draft':  # 既にdraft化されていなければ実行
        try:
            from pipeline.llm_proofreader import proofread_post
            pr = proofread_post(post)
            pr_critical = pr.get('critical', [])
            pr_high = pr.get('high', [])
            if pr_critical:
                result['issues'].extend([f'llm_critical: {c}' for c in pr_critical])
                _draft_post(post_id, f"LLM factcheck CRITICAL: {pr_critical}")
                result['status'] = 'draft'
                print(f"  [hook] LLM factcheck CRITICAL: {len(pr_critical)}件 → draft化")
            elif pr_high:
                result['issues'].extend([f'llm_high: {h}' for h in pr_high])
                # HIGHはWARN扱い（draft化しない）。CRITICALのみdraft化
                print(f"  [hook] LLM factcheck HIGH: {len(pr_high)}件 (WARN — draft化せず)")
            else:
                print(f"  [hook] LLM factcheck PASS (score={pr.get('score', '?')})")
        except Exception as e:
            # LLMファクトチェック失敗 = 品質保証できない → draft化して安全側に倒す
            print(f"  [hook] llm_factcheck err: {e} → draft化")
            _draft_post(post_id, f"LLM factcheck失敗(品質保証不能): {str(e)[:60]}")
            result['status'] = 'draft'
            result['issues'].append(f'llm_factcheck_error: {str(e)[:60]}')

    # 5. 3行まとめ検証
    content_fresh = post.get('content', {}).get('rendered', '')
    if post_type == 'post':
        sum_m = re.search(r'<div class="kpj-summary">(.*?)</div>', content_fresh, re.DOTALL)
        if sum_m:
            li_count = sum_m.group(1).count('<li>')
            if li_count != 3:
                result['issues'].append(f'summary_{li_count}lines')
            if '<td>' in sum_m.group(1):
                result['issues'].append('summary_table_leak')
        # enricherが走った後なのでsummaryなしは警告のみ

    # 6. Phase 30: 新規投稿ハイブリッドCTA自動配置 (5/4以降のみ)
    if result.get('status') != 'draft':
        try:
            from cta.new_post_injector import inject_hybrid_cta
            cta_result = inject_hybrid_cta(post_id)
            if cta_result['status'] == 'success':
                result['changes'].append(f"hybrid_cta: {cta_result['injected_positions']}")
                print(f"  [hook] Phase30 CTA: {cta_result['injected_positions']}")
            elif cta_result['status'] == 'skipped':
                pass  # 既存記事/cutoff前/注入済み — 正常スキップ
            elif cta_result['status'] == 'error':
                print(f"  [hook] Phase30 CTA err: {cta_result.get('reason', '?')}")
        except Exception as e:
            print(f"  [hook] Phase30 CTA import err: {e}")

    # ログ記録
    status_label = result['status']
    issue_count = len(result['issues'])
    print(f"  [hook] 完了: {status_label} issues={issue_count} changes={len(result['changes'])}")
    _log({
        'post_id': post_id,
        'title': title[:50],
        'status': result['status'],
        'issues': result['issues'],
        'changes': result['changes'],
        'ts': now.isoformat(),
    })

    return result
