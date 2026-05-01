#!/usr/bin/env python3
"""
公開品質ゲート — 全パイプライン共通の公開後必須チェック
どのパイプラインから公開されても、このゲートを通過しないと公開状態を維持できない。

チェック項目:
1. full_audit (16項目) — critical/high で自動draft化
2. fact_checker — BLOCK で自動draft化
3. サムネイル存在 + ALT設定 + 記事との関連性
4. unclosed HTML修正
5. 結果をlogs/publish_quality_gate.jsonlに記録
"""
import sys, os, json, urllib.request, base64, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

BASE_DIR = '/home/aiuser/kpop-ai-system'
WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
JST = timezone(timedelta(hours=9))
LOG_PATH = os.path.join(BASE_DIR, 'logs/publish_quality_gate.jsonl')


def _wp_get(endpoint):
    url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}"
    req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def _wp_update(post_id, data):
    url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method='POST',
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def check_post(post_id, auto_fix=True):
    """
    公開後の品質ゲート。全チェックを実行し結果を返す。
    auto_fix=True: critical/highがあればdraft化
    Returns: {'pass': bool, 'issues': list, 'actions': list}
    """
    result = {'pass': True, 'issues': [], 'actions': [], 'post_id': post_id}

    try:
        post = _wp_get(f"posts/{post_id}")
    except Exception as e:
        result['pass'] = False
        result['issues'].append({'severity': 'critical', 'type': 'fetch_error', 'detail': str(e)})
        _log_result(result)
        return result

    title = post['title']['rendered'] if isinstance(post['title'], dict) else str(post['title'])
    content_html = post['content']['rendered'] if isinstance(post['content'], dict) else str(post['content'])
    content_text = re.sub('<[^>]+>', '', content_html)

    # ── 1. full_audit ──
    try:
        from lib.full_audit_engine import full_audit
        audit_issues = full_audit(post, post_type='post')
        if isinstance(audit_issues, dict):
            audit_issues = audit_issues.get('issues', [])
        for iss in audit_issues:
            if isinstance(iss, dict):
                result['issues'].append(iss)
    except Exception as e:
        result['issues'].append({'severity': 'medium', 'type': 'audit_error', 'detail': str(e)[:100]})

    # ── 2. fact_check ──
    try:
        from lib.fact_checker import check_article
        fc = check_article(title, content_text[:2000])
        if isinstance(fc, dict):
            if fc.get('verdict') == 'BLOCK':
                result['issues'].append({
                    'severity': 'critical', 'type': 'fact_check_block',
                    'detail': str(fc.get('issues', fc.get('flags', '')))[:200]
                })
    except Exception as e:
        result['issues'].append({'severity': 'low', 'type': 'fact_check_error', 'detail': str(e)[:100]})

    # ── 3. サムネイル検証 ──
    media_id = post.get('featured_media', 0)
    if not media_id:
        result['issues'].append({'severity': 'high', 'type': 'no_thumbnail', 'detail': 'サムネイルなし'})
    else:
        try:
            media = _wp_get(f"media/{media_id}?_fields=alt_text,source_url,media_details")
            # ALT空チェック
            if not media.get('alt_text'):
                result['issues'].append({'severity': 'medium', 'type': 'empty_alt', 'detail': 'サムネALTテキスト空'})
                # 自動修正: タイトルからALT生成
                if auto_fix:
                    try:
                        alt = f"{title}のサムネイル画像"
                        alt_body = json.dumps({'alt_text': alt}).encode()
                        alt_req = urllib.request.Request(
                            f"https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{media_id}",
                            data=alt_body, method='POST',
                            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
                        urllib.request.urlopen(alt_req, timeout=15)
                        result['actions'].append(f'ALT自動設定: {alt[:40]}')
                    except Exception:
                        pass

            # サイズチェック（グラデーション/極小画像の検出）
            details = media.get('media_details', {})
            width = details.get('width', 0)
            height = details.get('height', 0)
            filesize = details.get('filesize', 0)
            if width and height and (width < 600 or height < 300):
                result['issues'].append({'severity': 'high', 'type': 'thumbnail_too_small',
                    'detail': f'サムネサイズ不足: {width}x{height}'})
            if filesize and filesize < 5000:
                result['issues'].append({'severity': 'high', 'type': 'thumbnail_too_light',
                    'detail': f'サムネファイルサイズ異常: {filesize}B (グラデーション疑い)'})
        except Exception as e:
            result['issues'].append({'severity': 'medium', 'type': 'media_check_error', 'detail': str(e)[:100]})

    # ── 4. HTML修正 ──
    if auto_fix:
        try:
            from lib.text_sanitizer import sanitize_gpt_html
            fixed = sanitize_gpt_html(content_html)
            if fixed != content_html:
                _wp_update(post_id, {'content': fixed})
                result['actions'].append('unclosed_p自動修正')
        except Exception:
            pass

    # ── 判定 ──
    criticals = [i for i in result['issues'] if isinstance(i, dict) and i.get('severity') in ('critical', 'high')]
    if criticals:
        result['pass'] = False
        if auto_fix and post.get('status') == 'publish':
            try:
                _wp_update(post_id, {'status': 'draft'})
                result['actions'].append(f'⛔ draft化 (理由: {", ".join(c.get("type","?") for c in criticals[:3])})')
            except Exception:
                result['actions'].append('draft化失敗')

    _log_result(result)
    return result


def _log_result(result):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        'timestamp': datetime.now(JST).isoformat(),
        'post_id': result['post_id'],
        'pass': result['pass'],
        'issue_count': len(result['issues']),
        'critical_count': len([i for i in result['issues'] if isinstance(i, dict) and i.get('severity') in ('critical', 'high')]),
        'actions': result['actions'],
    }
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def gate_recent_posts(hours=1):
    """直近N時間に公開された記事を全件チェック"""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
    try:
        posts = _wp_get(f"posts?after={cutoff}&status=publish&per_page=50&_fields=id,title")
    except Exception as e:
        print(f"記事取得失敗: {e}")
        return

    print(f"=== publish_quality_gate: {datetime.now(JST).strftime('%Y-%m-%d %H:%M')} ===")
    print(f"  直近{hours}hの公開記事: {len(posts)}件")

    passed = 0
    failed = 0
    for p in posts:
        pid = p['id']
        title = p['title']['rendered'] if isinstance(p['title'], dict) else str(p['title'])
        result = check_post(pid)
        status = '✅ PASS' if result['pass'] else '⛔ FAIL'
        print(f"  {status} [{pid}] {title[:40]} (issues={len(result['issues'])})")
        if result['actions']:
            for a in result['actions']:
                print(f"       → {a}")
        if result['pass']:
            passed += 1
        else:
            failed += 1

    print(f"\n  結果: PASS={passed} FAIL={failed}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--post-id', type=int, help='特定の記事をチェック')
    parser.add_argument('--hours', type=int, default=1, help='直近N時間の記事をチェック')
    args = parser.parse_args()

    if args.post_id:
        r = check_post(args.post_id)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        gate_recent_posts(hours=args.hours)
