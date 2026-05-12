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


X_QUEUE_PATH = '/home/aiuser/kpop-ai-system/config/x_post_queue.json'


def _purge_from_x_queue(post_id):
    """draft化された記事を x_post_queue から除去 (skip & remove ループ防止)"""
    try:
        if not os.path.exists(X_QUEUE_PATH):
            return 0
        with open(X_QUEUE_PATH, encoding='utf-8') as f:
            data = json.load(f)
        queue = data.get('queue', [])
        target = int(post_id)
        before = len(queue)
        new_queue = [e for e in queue if int(e.get('post_id', 0) or 0) != target]
        if len(new_queue) == before:
            return 0
        data['queue'] = new_queue
        data['count'] = len(new_queue)
        data['updated'] = datetime.now(JST).strftime('%Y-%m-%d %H:%M')
        tmp = X_QUEUE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, X_QUEUE_PATH)
        return before - len(new_queue)
    except Exception as e:
        print(f"  [hook] x_queue purge err: {e}")
        return 0


def _draft_post(post_id, reason):
    """記事をdraft化 + Next.js ISRキャッシュパージ + x_queue除去"""
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
        # x_post_queue から除去 (scheduler の skip ループ防止)
        removed = _purge_from_x_queue(post_id)
        if removed:
            print(f"  [hook] x_queue purge: pid={post_id} ({removed}件除去)")
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

    # 3. pre_publish_gate 再実行（公開後の全項目チェック — 公開前ゲートと同一ロジック）
    try:
        post_fresh = _fetch_post(post_id)
        if post_fresh:
            _pf_title = post_fresh.get('title', {}).get('rendered', '')
            _pf_content = post_fresh.get('content', {}).get('rendered', '')
            _pf_excerpt = post_fresh.get('excerpt', {}).get('rendered', '')
            _pf_slug = post_fresh.get('slug', '')
            _pf_fm = post_fresh.get('featured_media', 0)
            _pf_cats = post_fresh.get('categories', [])

            # 記事本文からソースURLを抽出（no_source誤BLOCKを防止）
            # ドメインリストは config/source_domains.json から読み込み (2026-05-07修正)
            import re as _re_hook
            from lib.source_domains import source_url_regex as _src_re
            _src_urls = _re_hook.findall(_src_re(), _pf_content)
            _src_url = _src_urls[0] if _src_urls else None
            _src_signals = [{'url': u, 'title': ''} for u in _src_urls[:3]] if _src_urls else None

            # 2026-05-11: kind を breaking_articles.jsonl から判定 (hardcoded 'news' は
            # breaking 記事の content_short を BLOCK に昇格させてしまう事故対策)
            _detected_kind = 'news'
            try:
                _ba_path = '/home/aiuser/kpop-ai-system/logs/breaking_articles.jsonl'
                with open(_ba_path, encoding='utf-8') as _baf:
                    for _bal in _baf:
                        try:
                            _bad = json.loads(_bal)
                            if _bad.get('post_id') == post_id:
                                _detected_kind = 'breaking'
                                break
                        except Exception:
                            continue
            except FileNotFoundError:
                pass

            from lib.pre_publish_gate import pre_publish_gate as _recheck_gate
            # 2026-05-12 (コスト削減): publish 直前の pre_publish_gate で既に
            # factcheck_v2 を実行済みのため、同じ content への再 LLM 呼出は
            # 同じ結果を返すだけで純粋なロス。skip_llm_factcheck=True で構造/
            # サムネ/HTMLバランス等の deterministic check のみ再実行する。
            _gate_r = _recheck_gate(
                title=_pf_title, body_html=_pf_content,
                post_type=post_type, kind=_detected_kind,
                source_url=_src_url, source_signals=_src_signals,
                slug=_pf_slug, featured_media=_pf_fm,
                categories=_pf_cats, excerpt=_pf_excerpt,
                status='publish',
                skip_llm_factcheck=True,
            )
            if _gate_r['verdict'] == 'BLOCK':
                block_reasons = _gate_r.get('block_reasons', [])
                # self-match 除外: 自身のpost_idを「類似テーマ」として検出するbug回避 (2026-05-07)
                # pre_publish_gate の duplicate_title は WP search でID自身も拾うため、
                # 公開後のhook再ゲートだと毎回 self-match で BLOCK→draft化される事故になる
                _self_id_marker = f'(ID={post_id})'
                block_reasons = [r for r in block_reasons if _self_id_marker not in r]
                if block_reasons:
                    _draft_post(post_id, f"post-publish gate BLOCK: {block_reasons[:2]}")
                    result['status'] = 'draft'
                    result['issues'].extend([f'gate_block: {r[:50]}' for r in block_reasons])
                    print(f"  [hook] post-publish gate BLOCK: {block_reasons[:2]}")
                else:
                    print(f"  [hook] post-publish gate self-match のみ → 無視")
            elif _gate_r.get('warn_reasons'):
                result['issues'].extend([f'gate_warn: {r[:50]}' for r in _gate_r['warn_reasons'][:3]])
                print(f"  [hook] post-publish gate WARN: {len(_gate_r['warn_reasons'])}件")
    except Exception as e:
        print(f"  [hook] gate recheck err: {e}")

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

    # === Phase 30 CTA injection DISABLED (2026-05-07 emergency removal) ===
    # 視覚崩壊のため Phase 30.3 再設計まで停止。
    # if result.get('status') != 'draft':
    #     try:
    #         from cta.new_post_injector import inject_hybrid_cta
    #         cta_result = inject_hybrid_cta(post_id)
    #         if cta_result['status'] == 'success':
    #             result['changes'].append(f"hybrid_cta: {cta_result['injected_positions']}")
    #             print(f"  [hook] Phase30 CTA: {cta_result['injected_positions']}")
    #         elif cta_result['status'] == 'skipped':
    #             pass
    #         elif cta_result['status'] == 'error':
    #             print(f"  [hook] Phase30 CTA err: {cta_result.get('reason', '?')}")
    #     except Exception as e:
    #         print(f"  [hook] Phase30 CTA import err: {e}")

    # 7. OGP/Twitterカード設定（全enricher/CTA完了後の最終ステップ）
    # enricherやCTAが記事を更新した後にOGPを設定することで上書きを防ぐ
    if result.get('status') != 'draft':
        try:
            from lib.ogp_twitter_card_optimizer import fix_post_meta as _fix_ogp
            _ogp_r = _fix_ogp(post_id)
            if _ogp_r.get('fixes'):
                result['changes'].append(f"ogp_final: {_ogp_r['fixes']}")
                print(f"  [hook] OGP最終設定: {_ogp_r['fixes']}")
        except Exception as _oe:
            print(f"  [hook] OGP err: {_oe}")

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
