#!/usr/bin/env python3
"""post + popup の両方を16項目完全監査"""
import sys, os
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.full_audit_engine import full_audit, fetch_posts, save_audit_state


def main():
    summary = {}
    by_severity = {'high': 0, 'medium': 0, 'low': 0}
    by_type = {}

    for post_type in ['post', 'popup']:
        print(f"\n=== {post_type} 監査 ===")
        posts = fetch_posts(post_type, hours=12, per_page=30)
        print(f"対象: {len(posts)}件")

        s = {'audited': 0, 'with_issues': 0}
        for p in posts:
            issues = full_audit(p, post_type)
            save_audit_state(p['id'], post_type, issues)
            s['audited'] += 1

            if issues:
                s['with_issues'] += 1
                for i in issues:
                    sev = i.get('severity', 'low')
                    if sev in by_severity:
                        by_severity[sev] += 1
                    by_type[i['type']] = by_type.get(i['type'], 0) + 1

                title = p['title']['rendered'] if isinstance(p['title'], dict) else p['title']
                issue_summary = ', '.join(i['type'] for i in issues[:5])
                extra = f'+{len(issues)-5}' if len(issues) > 5 else ''
                print(f"  {p['id']} [{post_type}] {title[:35]}: {len(issues)} ({issue_summary}{extra})")

        summary[post_type] = s

    print(f"\n=== サマリ ===")
    for pt, s in summary.items():
        print(f"  {pt}: 監査{s['audited']}件 / issue検出{s['with_issues']}件")
    print(f"  severity: high={by_severity['high']}, medium={by_severity['medium']}, low={by_severity['low']}")

    if by_type:
        print(f"\n  TOP issue types:")
        for t, c in sorted(by_type.items(), key=lambda x: -x[1])[:10]:
            print(f"    {t}: {c}")


if __name__ == '__main__':
    main()
