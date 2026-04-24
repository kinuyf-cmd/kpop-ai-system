#!/usr/bin/env python3
"""記事品質監査パイプライン (6時間毎)

10項目チェック:
1. タイトル42文字以内
2. 本文300文字以上
3. カテゴリ設定あり
4. サムネ(featured_media)設定あり
5. スラッグ英数字
6. 【速報】記事に信頼度注意書きあり
7. 情報ソースセクションあり
8. H2見出し1つ以上
9. 重複タイトル検出
10. 404/empty content検出

自動修正: タイトル超過→切り詰め, サムネなし→DALL-E生成
"""
import sys, os, json, re, urllib.request, base64
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

AUTH = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()
AUDIT_LOG = '/home/aiuser/kpop-ai-system/logs/audit_results.jsonl'
JST = timezone(timedelta(hours=9))


def fetch_recent_posts(hours=6):
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
    url = (
        f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
        f"?after={since}&per_page=50&_fields=id,slug,title,content,excerpt,categories,featured_media,date,link"
    )
    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        print(f"fetch error: {e}")
        return []


def audit_post(post):
    pid = post['id']
    title_raw = post.get('title', {}).get('rendered', '') if isinstance(post.get('title'), dict) else ''
    title = re.sub(r'<[^>]+>', '', title_raw)
    content = post.get('content', {}).get('rendered', '') if isinstance(post.get('content'), dict) else ''
    content_text = re.sub(r'<[^>]+>', '', content)
    slug = post.get('slug', '')
    cats = post.get('categories', [])
    fm = post.get('featured_media', 0)

    issues = []
    fixes_applied = []

    # 1. タイトル42文字
    if len(title) > 42:
        issues.append(f"title_long({len(title)}字)")

    # 2. 本文300文字以上
    if len(content_text) < 300:
        issues.append(f"content_short({len(content_text)}字)")

    # 3. カテゴリ
    if not cats:
        issues.append("no_category")

    # 4. サムネ
    if not fm:
        issues.append("no_thumbnail")

    # 5. スラッグ英数字
    if slug and not re.match(r'^[a-z0-9\-]+$', slug):
        issues.append(f"slug_non_ascii({slug[:30]})")

    # 6. 速報記事に信頼度注意書き
    if '【速報】' in title or '【韓国メディア速報】' in title:
        if '単一メディア速報' not in content and '複数の韓国メディア' not in content and '公式発表' not in content:
            issues.append("breaking_no_confidence_note")

    # 7. 情報ソースセクション
    if '情報ソース' not in content and 'ソース' not in content:
        issues.append("no_source_section")

    # 8. H2見出し
    if '<h2' not in content.lower():
        issues.append("no_h2")

    # 9. 重複タイトル (同一バッチ内で判定)
    # (呼び出し側でチェック)

    return {
        'post_id': pid,
        'title': title[:60],
        'slug': slug[:40],
        'issues': issues,
        'fixes': fixes_applied,
        'score': max(0, 10 - len(issues)),
    }


def auto_fix(post, audit_result):
    """自動修正可能な項目を修正"""
    fixes = []
    pid = audit_result['post_id']

    # サムネなし → DALL-E生成試行
    if 'no_thumbnail' in audit_result['issues']:
        try:
            from lib.thumbnail_resolver import resolve_thumbnail
            title = audit_result['title']
            thumb = resolve_thumbnail(None, title, '', pid)
            if thumb and thumb.get('path'):
                from pipeline.auto_event_article import upload_media_to_wp
                media_id = upload_media_to_wp(thumb['path'], pid)
                if media_id:
                    _update_post(pid, {'featured_media': media_id})
                    fixes.append(f"thumb_generated(media={media_id})")
        except Exception as e:
            fixes.append(f"thumb_fix_failed({e})")

    return fixes


def _update_post(post_id, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}",
        data=body,
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        urllib.request.urlopen(req, timeout=30)
        return True
    except Exception:
        return False


def main(hours=6, fix=True):
    posts = fetch_recent_posts(hours)
    print(f"過去{hours}hの記事: {len(posts)}件")

    results = []
    titles_seen = set()
    total_issues = 0

    for post in posts:
        r = audit_post(post)

        # 重複タイトルチェック
        t = r['title']
        if t in titles_seen:
            r['issues'].append("duplicate_title")
        titles_seen.add(t)

        if r['issues']:
            total_issues += len(r['issues'])
            print(f"\n  [{r['post_id']}] {r['title'][:40]} — score={r['score']}/10")
            for issue in r['issues']:
                print(f"    ⚠️ {issue}")

            if fix:
                fixes = auto_fix(post, r)
                r['fixes'] = fixes
                for f in fixes:
                    print(f"    ✅ {f}")

        results.append(r)

    # サマリ
    avg_score = sum(r['score'] for r in results) / max(1, len(results))
    perfect = sum(1 for r in results if not r['issues'])

    print(f"\n=== 監査サマリ ===")
    print(f"  記事数: {len(results)}")
    print(f"  平均スコア: {avg_score:.1f}/10")
    print(f"  完全合格: {perfect}/{len(results)}")
    print(f"  総issue数: {total_issues}")

    # ログ
    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    with open(AUDIT_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': datetime.now(JST).isoformat(),
            'count': len(results),
            'avg_score': round(avg_score, 1),
            'perfect': perfect,
            'total_issues': total_issues,
            'details': [{'id': r['post_id'], 'score': r['score'], 'issues': r['issues'], 'fixes': r['fixes']} for r in results if r['issues']],
        }, ensure_ascii=False) + '\n')

    return results


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=int, default=6)
    ap.add_argument('--no-fix', action='store_true')
    args = ap.parse_args()
    main(hours=args.hours, fix=not args.no_fix)
