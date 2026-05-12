#!/usr/bin/env python3
"""auto-auditor cron: 直近 publish 記事を独立4項目監査 (2026-05-12新設)

publish から監査までのラグを既存 enforcer (受動30分) より短縮し、
FAIL は能動的に draft 化して読者への晒し時間を分単位に圧縮する。

kpop-auditor 手動運用 (Agent subagent_type='kpop-auditor') の cron版。
画像視覚確認は Claude Read が使えないため heuristic
(lib.thumbnail_vision_validator) で代替する点だけ手動版から downgrade。

cron想定:
  */30 6-22 * * * cd /home/aiuser/kpop-ai-system && python3 pipeline/auto_audit_recent.py >> logs/auto_audit_recent.log 2>&1

env:
  AUTO_AUDIT_LOOKBACK_MIN=35   : 何分前までの publish を対象にするか (default 35)
  AUTO_AUDIT_NO_DRAFT=1        : FAIL でも auto-draft しない (dry-run 用)
"""
import os, re, sys, json, base64, urllib.request
from datetime import datetime, timezone, timedelta
from io import BytesIO

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

from bs4 import BeautifulSoup
from PIL import Image

from lib.audit_steps_log import record_step
from lib.full_audit_engine import full_audit
from lib.thumbnail_vision_validator import validate_thumbnail
from lib.discord_channel_router import send_to_channel, ChannelType
from pipeline.llm_proofreader import proofread_post

LOOKBACK_MIN = int(os.getenv('AUTO_AUDIT_LOOKBACK_MIN', '35'))
NO_DRAFT = os.getenv('AUTO_AUDIT_NO_DRAFT', '0') == '1'
SOURCE = 'auto-auditor'
WP_BASE = 'https://www.kpopjournal.tokyo'
AUDIT_LOG = '/home/aiuser/kpop-ai-system/logs/audit_steps.jsonl'

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()


def _req(url, method='GET', payload=None):
    headers = {'Authorization': f'Basic {AUTH}'}
    data = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def fetch_recent_publishes():
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MIN)).strftime('%Y-%m-%dT%H:%M:%S')
    posts = []
    for ep in ['posts', 'popup']:
        try:
            url = f'{WP_BASE}/wp-json/wp/v2/{ep}?status=publish&after={cutoff}&per_page=20&_embed=true'
            arr = _req(url)
            for p in arr:
                p['_post_type'] = ep
                posts.append(p)
        except Exception as e:
            print(f"[fetch err {ep}] {e}")
    return posts


def already_audited_by_auto(post_id, since_ts):
    """このpost_idが auto-auditor で4項目すべて記録済か"""
    if not os.path.exists(AUDIT_LOG):
        return False
    steps_seen = set()
    with open(AUDIT_LOG, encoding='utf-8') as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get('post_id') != int(post_id) or e.get('source') != SOURCE:
                continue
            try:
                ts = datetime.fromisoformat(e['ts']).timestamp()
            except Exception:
                continue
            if ts < since_ts:
                continue
            steps_seen.add(e.get('step'))
    return steps_seen >= {'structure', 'thumbnail', 'factcheck', 'body_read'}


def audit_thumbnail(post):
    """heuristic thumbnail check (Claude vision なしの cron 用)"""
    media = (post.get('_embedded') or {}).get('wp:featuredmedia') or []
    if not media:
        return 'fail', 'NO_THUMBNAIL'
    src = media[0].get('source_url', '')
    alt = media[0].get('alt_text', '')
    if not src:
        return 'fail', 'NO_THUMBNAIL_URL'
    title = post['title']['rendered'] if isinstance(post['title'], dict) else post['title']
    try:
        with urllib.request.urlopen(src, timeout=20) as r:
            img_bytes = r.read()
        img = Image.open(BytesIO(img_bytes))
        w, h = img.size
        if h > w:
            return 'fail', f'PORTRAIT w={w} h={h}'
        if not alt:
            return 'warn', f'EMPTY_ALT w={w} h={h}'
        return 'ok', f'{w}x{h} alt_present'
    except Exception as e:
        return 'warn', f'thumb_check_err: {str(e)[:60]}'


def audit_body(post):
    """memory_compliance パターンと同じ body_read regex check"""
    title = post['title']['rendered'] if isinstance(post['title'], dict) else post['title']
    body_html = post['content']['rendered'] if isinstance(post['content'], dict) else post['content']
    slug = post.get('slug', '')
    plain = BeautifulSoup(body_html, 'html.parser').get_text(' ', strip=True)
    flags = []
    if re.search(r'&(amp|lt|gt|quot|#\d+);', plain):
        flags.append('HTML_ENTITY_RESIDUE')
    if '```' in plain:
        flags.append('CODEBLOCK_MARKER')
    m_slug = re.search(r'(20\d{2})', slug)
    m_body = re.search(r'(20\d{2})', plain[:500])
    if m_slug and m_body and m_slug.group(1) != m_body.group(1):
        flags.append(f'YEAR_MISMATCH s={m_slug.group(1)} b={m_body.group(1)}')
    soup = BeautifulSoup(body_html, 'html.parser')
    rb = soup.find_all('div', class_=re.compile(r'related|other-posts'))
    if rb and any('http' in b.get_text() for b in rb):
        flags.append('RELATED_LINK_LEAK_IN_BODY')
    title_terms = re.findall(r'[A-Za-z]{2,}|[゠-ヿ]{2,}', title)
    title_terms = [t for t in title_terms if t.lower() not in ('the', 'and', 'for', 'with')]
    if title_terms and not any(t in plain for t in title_terms[:3]):
        flags.append(f'TITLE_BODY_DIVERGENCE missing={title_terms[:3]}')
    status = 'ok' if not flags else (
        'warn' if len(flags) == 1 and flags[0].startswith('TITLE_BODY_DIVERGENCE') else 'fail'
    )
    return status, flags


def audit_one(post):
    pid = post['id']
    ep = post['_post_type']  # 'posts' or 'popup'
    title = post['title']['rendered'] if isinstance(post['title'], dict) else post['title']

    # Step 1: structure
    pt = 'popup' if ep == 'popup' else 'post'
    try:
        issues = full_audit(post, pt)
        high = [i for i in issues if i.get('severity') == 'high']
        s_status = 'ok' if not high else 'fail'
        s_detail = f'high={len(high)} total={len(issues)}'
    except Exception as e:
        s_status, s_detail = 'warn', f'audit_err: {str(e)[:80]}'
    record_step(pid, 'structure', s_status, s_detail, source=SOURCE)

    # Step 2: thumbnail (heuristic)
    t_status, t_detail = audit_thumbnail(post)
    record_step(pid, 'thumbnail', t_status, t_detail, source=SOURCE)

    # Step 3: factcheck (新規 LLM 呼出)
    try:
        r = proofread_post(post)
        nc = len(r.get('critical', []))
        nh = len(r.get('high', []))
        score = r.get('score', 0)
        fc_status = 'fail' if nc > 0 else ('warn' if nh > 0 else 'ok')
        fc_detail = f'C={nc} H={nh} score={score}'
    except Exception as e:
        fc_status, fc_detail = 'warn', f'factcheck_err: {str(e)[:80]}'
    record_step(pid, 'factcheck', fc_status, fc_detail, source=SOURCE)

    # Step 4: body_read
    b_status, b_flags = audit_body(post)
    b_detail = f'flags={b_flags[:5]}'
    record_step(pid, 'body_read', b_status, b_detail, source=SOURCE)

    statuses = [s_status, t_status, fc_status, b_status]
    if any(s == 'fail' for s in statuses):
        verdict = 'FAIL'
    elif any(s == 'warn' for s in statuses):
        verdict = 'WARN'
    else:
        verdict = 'PASS'

    return {
        'post_id': pid, 'title': title[:60], 'ep': ep,
        'verdict': verdict,
        'structure': (s_status, s_detail),
        'thumbnail': (t_status, t_detail),
        'factcheck': (fc_status, fc_detail),
        'body_read': (b_status, b_detail),
    }


def auto_draft(pid, ep):
    try:
        path = f'/wp-json/wp/v2/{ep}/{pid}'
        _req(f'{WP_BASE}{path}', method='POST', payload={'status': 'draft'})
        return True
    except Exception as e:
        print(f"  [auto_draft err {pid}] {e}")
        return False


def main():
    now = datetime.now(timezone.utc)
    print(f"=== auto_audit_recent {now.isoformat()} (lookback={LOOKBACK_MIN}min) ===")
    posts = fetch_recent_publishes()
    print(f"  対象 publish: {len(posts)}件")

    summary = {'examined': len(posts), 'audited': 0, 'skipped': 0,
               'pass': 0, 'warn': 0, 'fail': 0, 'drafted': 0, 'fail_records': []}

    for p in posts:
        pid = p['id']
        try:
            pub_dt = datetime.fromisoformat(p['date_gmt'].replace('Z', '+00:00'))
        except Exception:
            pub_dt = now - timedelta(hours=1)
        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        if already_audited_by_auto(pid, pub_dt.timestamp()):
            summary['skipped'] += 1
            continue

        r = audit_one(p)
        summary['audited'] += 1
        print(f"  {pid} {r['verdict']:4} | {r['title']} | "
              f"S={r['structure'][0]} T={r['thumbnail'][0]} F={r['factcheck'][0]} B={r['body_read'][0]}")

        if r['verdict'] == 'FAIL':
            summary['fail'] += 1
            summary['fail_records'].append(r)
            if not NO_DRAFT:
                if auto_draft(pid, r['ep']):
                    summary['drafted'] += 1
                    print(f"    → DRAFTED")
        elif r['verdict'] == 'WARN':
            summary['warn'] += 1
        else:
            summary['pass'] += 1

    print(f"\n--- summary ---")
    print(f"  examined={summary['examined']} audited={summary['audited']} skipped={summary['skipped']}")
    print(f"  PASS={summary['pass']} WARN={summary['warn']} FAIL={summary['fail']} drafted={summary['drafted']}")

    # Discord notification (FAIL only)
    if summary['fail'] > 0:
        lines = []
        for r in summary['fail_records'][:10]:
            reasons = []
            for k in ('structure', 'thumbnail', 'factcheck', 'body_read'):
                st, det = r[k]
                if st == 'fail':
                    reasons.append(f'{k}={det[:50]}')
            lines.append(f"- {r['post_id']} {r['title']}\n  {' | '.join(reasons)}")
        body = (
            f"auto-auditor FAIL {summary['fail']}件 (auto-drafted {summary['drafted']}件)\n\n"
            + "\n".join(lines)
            + f"\n\nlog: logs/auto_audit_recent.log"
        )
        send_to_channel(
            ChannelType.ERROR,
            f"🔴 auto-auditor FAIL {summary['fail']}件",
            body,
        )


if __name__ == '__main__':
    main()
