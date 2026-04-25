#!/usr/bin/env python3
"""ポップアップ専用監査 (6時間毎、popup post type のみ)"""
import sys, os, json, re, urllib.request, base64
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv()

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
LOG = '/home/aiuser/kpop-ai-system/logs/popup_audit.jsonl'
JST = timezone(timedelta(hours=9))


def fetch_recent_popups(hours=12):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
    url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/popup?after={cutoff}&per_page=50&_embed=true"
    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        return json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        print(f"fetch err: {e}")
        return []


def audit_popup(p):
    """10項目チェック"""
    issues = []
    title = p['title']['rendered']
    content = p['content']['rendered']
    meta = p.get('meta', {})

    # 1. タイトル長
    if len(title) > 60:
        issues.append({'type': 'title_long', 'severity': 'low'})
    if len(title) < 10:
        issues.append({'type': 'title_short', 'severity': 'high'})

    # 2. 本文長
    plain = re.sub(r'<[^>]+>', '', content)
    if len(plain) < 200:
        issues.append({'type': 'content_short', 'severity': 'high', 'len': len(plain)})

    # 3. 都市必須
    if not meta.get('_popup_city'):
        issues.append({'type': 'no_city', 'severity': 'high'})

    # 4. 期間
    if not meta.get('_popup_start_date'):
        issues.append({'type': 'no_start_date', 'severity': 'medium'})

    # 5. 状態
    if not meta.get('_popup_status') or meta.get('_popup_status') == 'unknown':
        issues.append({'type': 'unknown_status', 'severity': 'medium'})

    # 6. サムネ
    if not p.get('featured_media') or p['featured_media'] == 0:
        issues.append({'type': 'no_thumbnail', 'severity': 'high'})

    # 7. 公式URL
    if not meta.get('_popup_official_url'):
        issues.append({'type': 'no_official_url', 'severity': 'low'})

    # 8. 注意書き
    if 'kpj-disclaimer' not in content and '※情報は変更' not in content:
        issues.append({'type': 'no_disclaimer', 'severity': 'medium'})

    # 9. 住所
    if not meta.get('_popup_address'):
        issues.append({'type': 'no_address', 'severity': 'low'})

    # 10. h2見出し
    if '<h2' not in content:
        issues.append({'type': 'no_h2', 'severity': 'low'})

    return issues


def update_popup_status(popups):
    """終了判定を自動更新"""
    today = datetime.now(JST).date()
    updated = 0
    for p in popups:
        meta = p.get('meta', {})
        end_str = meta.get('_popup_end_date', '')
        current = meta.get('_popup_status', '')
        if not end_str or current == 'ended':
            continue
        try:
            end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
            if today > end_date and current != 'ended':
                # 終了に更新
                body = json.dumps({'meta': {'_popup_status': 'ended'}}).encode()
                req = urllib.request.Request(
                    f'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup/{p["id"]}',
                    data=body, method='POST',
                    headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
                urllib.request.urlopen(req, timeout=15)
                print(f"  状態更新: post_id={p['id']} → ended")
                updated += 1
        except:
            pass
    return updated


def main():
    popups = fetch_recent_popups(hours=168)  # 直近1週間
    print(f"=== popup audit: 対象{len(popups)}件 ===")

    # 状態自動更新
    status_updated = update_popup_status(popups)

    total_issues = 0
    by_severity = {'high': 0, 'medium': 0, 'low': 0}

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        for p in popups:
            issues = audit_popup(p)
            if issues:
                total_issues += len(issues)
                for i in issues:
                    sev = i.get('severity', 'low')
                    by_severity[sev] = by_severity.get(sev, 0) + 1
                f.write(json.dumps({
                    'post_id': p['id'],
                    'title': p['title']['rendered'][:50],
                    'issues': issues,
                    'audited_at': datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False) + '\n')
                print(f"  post_id={p['id']} issues={len(issues)} ({', '.join(i['type'] for i in issues)})")

    print(f"\n総issue: {total_issues} (high={by_severity['high']}, medium={by_severity['medium']}, low={by_severity['low']})")
    if status_updated:
        print(f"状態更新: {status_updated}件")


if __name__ == '__main__':
    main()
