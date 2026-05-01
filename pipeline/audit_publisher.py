#!/usr/bin/env python3
"""記事投稿監査システム (10項目+自動修正+学習)"""
import os, sys, json, urllib.request, base64, re
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
for line in open('/home/aiuser/kpop-ai-system/.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

AUTH = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()
AUDIT_LOG = '/home/aiuser/kpop-ai-system/logs/audit_issues.jsonl'
LESSONS = '/home/aiuser/kpop-ai-system/docs/lessons_learned.md'
RULES = '/home/aiuser/kpop-ai-system/config/latest_rules.json'
JST = timezone(timedelta(hours=9))
ISSUES = []
REWRITE_QUEUE = '/home/aiuser/kpop-ai-system/data/rewrite_queue.jsonl'


def _add_to_rewrite_queue(post_id, post_url, reason):
    """リライト担当にdraft記事を送る"""
    existing_pending = False
    if os.path.exists(REWRITE_QUEUE):
        with open(REWRITE_QUEUE, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get('post_id') == post_id and d.get('status') == 'pending':
                        existing_pending = True
                        break
                except:
                    pass
    if not existing_pending:
        entry = {
            'ts': datetime.now().isoformat(),
            'post_id': post_id, 'post_url': post_url,
            'reason': reason, 'retry_count': 0, 'status': 'pending',
        }
        os.makedirs(os.path.dirname(REWRITE_QUEUE), exist_ok=True)
        with open(REWRITE_QUEUE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        print(f"  [{post_id}] rewrite_queue追加: {reason}")


def _wp_get(endpoint):
    req = urllib.request.Request(
        f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}",
        headers={'Authorization': f'Basic {AUTH}'},
    )
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def _wp_update(post_id, data):
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


def _record(pid, url, issue, detail, severity='medium'):
    entry = {'ts': datetime.now().isoformat(), 'post_id': pid, 'url': url,
             'issue': issue, 'detail': detail, 'severity': severity}
    ISSUES.append(entry)
    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    with open(AUDIT_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def _clean(raw):
    t = re.sub(r'<[^>]+>', '', raw)
    for ent, ch in [('&#8220;','"'),('&#8221;','"'),('&#8216;',"'"),('&#8217;',"'"),
                     ('&amp;','&'),('&#8230;','…'),('&hellip;','…')]:
        t = t.replace(ent, ch)
    return t.strip()


def audit_post(p):
    pid = p['id']
    purl = p.get('link', '')
    title = _clean(p.get('title', {}).get('rendered', '') if isinstance(p.get('title'), dict) else '')
    slug = p.get('slug', '')
    content = p.get('content', {}).get('rendered', '') if isinstance(p.get('content'), dict) else ''
    excerpt = p.get('excerpt', {}).get('rendered', '') if isinstance(p.get('excerpt'), dict) else ''
    fm_id = p.get('featured_media', 0)
    cat_ids = p.get('categories', [])
    content_text = re.sub(r'<[^>]+>', '', content).strip()
    excerpt_text = re.sub(r'<[^>]+>', '', excerpt).strip()
    fixes = {}

    # 1. タイトル長 (42字、prefix込み50字許容)
    if len(title) > 50:
        _record(pid, purl, 'title_long', f'{len(title)}字', 'high')
        try:
            from lib.title_optimizer import optimize_title
            new = optimize_title(title, content_text[:500])
            if '【速報】' in title: new = f'【速報】{new}'[:50]
            elif '【韓国メディア速報】' in title: new = f'【韓国メディア速報】{new}'[:50]
            if len(new) < len(title):
                fixes['title'] = new
                print(f"  [{pid}] title: {len(title)}→{len(new)}字")
        except Exception as e:
            print(f"  title fix err: {e}")

    # 2. タイトル切断
    if title.endswith(('…', '...', '、')):
        _record(pid, purl, 'title_truncated', title[-10:], 'high')

    # 3. スラッグ (URLエンコード検出)
    if slug and re.search(r'%[0-9a-fA-F]{2}', slug):
        _record(pid, purl, 'slug_encoded', slug[:30], 'medium')
        try:
            from lib.title_optimizer import generate_slug
            new_slug = generate_slug(title)
            if new_slug and re.match(r'^[a-z0-9\-]+$', new_slug):
                fixes['slug'] = new_slug
                print(f"  [{pid}] slug: {new_slug}")
        except Exception:
            pass

    # 4. 本文品質 (800字+日本語比率30%)
    content_core = re.sub(r'※[^<\n]*|情報ソース[\s\S]*', '', content_text).strip()
    if len(content_core) < 800:
        _record(pid, purl, 'body_short', f'{len(content_core)}字', 'high')
        if len(content_core) < 50:
            _wp_update(pid, {'status': 'draft'})
            print(f"  [{pid}] 🔴 重大品質違反(本文{len(content_core)}字) → draft化")
            _record(pid, purl, 'quality_critical', f'{len(content_core)}字で強制draft化', 'high')
            _add_to_rewrite_queue(pid, purl, f'本文{len(content_core)}字(50字未満)')
    if len(content_core) > 30:
        ja_chars = sum(1 for c in content_core if '\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff')
        ja_ratio = ja_chars / max(len(content_core), 1)
        if ja_ratio < 0.3:
            _record(pid, purl, 'body_non_japanese', f'ja_ratio={ja_ratio*100:.0f}%', 'high')
            if ja_ratio < 0.1:
                _wp_update(pid, {'status': 'draft'})
                print(f"  [{pid}] 🔴 日本語比率{ja_ratio*100:.0f}% → draft化")
                _add_to_rewrite_queue(pid, purl, f'日本語比率{ja_ratio*100:.0f}%')

    # 5. サムネ
    if not fm_id:
        _record(pid, purl, 'no_thumbnail', '', 'high')
    else:
        try:
            mr = _wp_get(f'media/{fm_id}')
            md = mr.get('media_details', {})
            mw, mh = md.get('width', 0), md.get('height', 0)
            if mw > 0 and mh > 0 and abs(mw / mh - 16 / 9) > 0.15:
                _record(pid, purl, 'thumb_aspect', f'{mw}x{mh}', 'medium')
        except Exception:
            pass

    # 6. カテゴリ
    if not cat_ids:
        _record(pid, purl, 'no_category', '', 'medium')

    # 7. メタdesc
    if len(excerpt_text) < 80:
        _record(pid, purl, 'meta_short', f'{len(excerpt_text)}字', 'medium')
        try:
            from lib.title_optimizer import generate_meta_description
            new_meta = generate_meta_description(title, content_text[:500])
            if new_meta and len(new_meta) >= 80:
                fixes['excerpt'] = new_meta
                print(f"  [{pid}] meta: {len(new_meta)}字")
        except Exception:
            pass

    # 8. 信頼度注意書き
    if '【韓国メディア速報】' in title:
        if '単一メディア' not in content and '複数の韓国メディア' not in content:
            _record(pid, purl, 'confidence_missing', '', 'medium')

    # 9. GSC通知
    gsc_log = '/home/aiuser/kpop-ai-system/data/gsc_indexing_log.jsonl'
    if purl and os.path.exists(gsc_log):
        notified = any(
            json.loads(l).get('url') == purl and json.loads(l).get('status') == 'ok'
            for l in open(gsc_log) if l.strip()
        )
        if not notified:
            _record(pid, purl, 'gsc_missing', '', 'medium')
            try:
                from lib.gsc_indexing import notify_url_updated
                notify_url_updated(purl)
                print(f"  [{pid}] GSC recover")
            except Exception:
                pass

    # 10. X投稿
    x_log = '/home/aiuser/kpop-ai-system/logs/x_posts.jsonl'
    if purl and os.path.exists(x_log):
        tweeted = any(
            json.loads(l).get('url') == purl and json.loads(l).get('status') == 'ok'
            for l in open(x_log) if l.strip()
        )
        if not tweeted:
            _record(pid, purl, 'x_missing', '', 'low')

    if fixes:
        _wp_update(pid, fixes)

    return fixes


def update_lessons(summary):
    if not summary.get('total'): return
    top = sorted(summary['by_type'].items(), key=lambda x: -x[1])[:5]
    if not any(v >= 2 for _, v in top): return
    addition = f"\n\n## 監査教訓 ({datetime.now().strftime('%Y-%m-%d %H:%M')})\n\n"
    for issue, cnt in top:
        addition += f"- **{issue}**: {cnt}件\n"
    with open(LESSONS, 'a', encoding='utf-8') as f:
        f.write(addition)
    print("  lessons_learned.md 更新")


def update_rules(summary):
    if not os.path.exists(RULES): return
    try:
        d = json.load(open(RULES, encoding='utf-8'))
    except Exception:
        return
    d.setdefault('editorial_audit', {})
    d['editorial_audit']['last_audit'] = datetime.now().isoformat()
    d['editorial_audit']['last_summary'] = summary
    d['updated_at'] = datetime.now().isoformat()
    json.dump(d, open(RULES, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


def main(hours=12):
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
    url = (f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
           f"?after={since}&per_page=100"
           f"&_fields=id,title,content,excerpt,slug,date,categories,featured_media,link")
    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        posts = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        print(f"fetch error: {e}")
        return

    print(f"=== 過去{hours}h監査: {len(posts)}件 ===")
    for p in posts:
        audit_post(p)

    by_type = {}
    by_sev = {'high': 0, 'medium': 0, 'low': 0}
    for i in ISSUES:
        by_type[i['issue']] = by_type.get(i['issue'], 0) + 1
        by_sev[i.get('severity', 'medium')] += 1

    summary = {'total': len(ISSUES), 'by_type': by_type, 'by_severity': by_sev}
    print(f"\n=== 結果: {len(ISSUES)}件 ===")
    print(f"  severity: {by_sev}")
    for k, v in sorted(by_type.items(), key=lambda x: -x[1])[:8]:
        print(f"  {k}: {v}")

    update_lessons(summary)
    update_rules(summary)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=int, default=12)
    args = ap.parse_args()
    main(hours=args.hours)
