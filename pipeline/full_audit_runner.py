#!/usr/bin/env python3
"""post + popup の両方を16項目完全監査"""
import sys, os
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.full_audit_engine import full_audit, fetch_posts, save_audit_state, get_x_post_summary
from lib.audit_steps_log import record_step


def main():
    try:
        from lib.staff_task_manager import begin_task, end_task as _end_task
        _STF_ID, _TSK_ID = "KPJ-0033", begin_task("KPJ-0033", "full_audit_runner")
    except: _STF_ID = _TSK_ID = None
    summary = {}
    by_severity = {'high': 0, 'medium': 0, 'low': 0}
    by_type = {}
    x_stats = {'posted': 0, 'missing': 0, 'error': 0}

    for post_type in ['post', 'popup']:
        print(f"\n=== {post_type} 監査 ===")
        posts = fetch_posts(post_type, hours=12, per_page=30)
        print(f"対象: {len(posts)}件")

        s = {'audited': 0, 'with_issues': 0}
        for p in posts:
            issues = full_audit(p, post_type)
            save_audit_state(p['id'], post_type, issues)
            s['audited'] += 1

            _structure_ok = not any(i.get('severity') == 'high' for i in issues)
            record_step(p['id'], 'structure',
                        status='ok' if _structure_ok else 'fail',
                        detail=f'issues={len(issues)}',
                        source='full_audit_runner')

            # X投稿確認（毎回レポート）
            x_info = get_x_post_summary(p['id'], post_slug=p.get('slug'), post_url=p.get('link'))
            if x_info.get('posted'):
                x_stats['posted'] += 1
            elif x_info.get('status') == 'error':
                x_stats['error'] += 1
            else:
                x_stats['missing'] += 1

            title = p['title']['rendered'] if isinstance(p['title'], dict) else p['title']

            if issues:
                s['with_issues'] += 1
                for i in issues:
                    sev = i.get('severity', 'low')
                    if sev in by_severity:
                        by_severity[sev] += 1
                    by_type[i['type']] = by_type.get(i['type'], 0) + 1

                issue_summary = ', '.join(i['type'] for i in issues[:5])
                extra = f'+{len(issues)-5}' if len(issues) > 5 else ''
                print(f"  {p['id']} [{post_type}] {title[:35]}: {len(issues)} ({issue_summary}{extra})")

            # X投稿レポート行（毎回出力）
            x_mark = '✅' if x_info.get('posted') else '❌'
            x_detail = x_info.get('text', '')[:50] if x_info.get('posted') else x_info.get('error', 'X未投稿')[:50]
            print(f"    X: {x_mark} {x_detail}")

        summary[post_type] = s

    print(f"\n=== サマリ ===")
    for pt, s in summary.items():
        print(f"  {pt}: 監査{s['audited']}件 / issue検出{s['with_issues']}件")
    print(f"  severity: high={by_severity['high']}, medium={by_severity['medium']}, low={by_severity['low']}")
    print(f"  X投稿: {x_stats['posted']}投稿済 / {x_stats['missing']}未投稿 / {x_stats['error']}エラー")

    if by_type:
        print(f"\n  TOP issue types:")
        for t, c in sorted(by_type.items(), key=lambda x: -x[1])[:10]:
            print(f"    {t}: {c}")


try:
    if _TSK_ID and _STF_ID: _end_task(_STF_ID, _TSK_ID, "success")
except: pass

if __name__ == '__main__':
    main()
