"""全pipeline健全性監視 — registry連携 + Discord緊急通知 (*/30 cron)"""
import sys, os, json, glob, re, time

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

from datetime import datetime, timedelta

REGISTRY = 'config/pipeline_registry.json'

ALERT_PATTERNS = [
    r'NameError', r'ImportError', r'ModuleNotFoundError',
    r'AttributeError.*not defined', r'Traceback',
]


def check():
    """ログファイル内の例外パターン検知"""
    since = (datetime.now() - timedelta(hours=24)).timestamp()
    alerts = []
    for f in glob.glob('logs/*.log'):
        if os.path.getmtime(f) < since:
            continue
        try:
            content = open(f).read()[-20000:]
            for pat in ALERT_PATTERNS:
                matches = re.findall(pat, content)
                if matches:
                    alerts.append({'file': os.path.basename(f), 'pattern': pat, 'count': len(matches)})
        except Exception:
            pass
    if alerts:
        os.makedirs('logs', exist_ok=True)
        with open('logs/pipeline_alerts.log', 'a') as af:
            af.write(f'\n=== {datetime.now().isoformat()} ===\n')
            for a in alerts:
                af.write(f'  {a["file"]}: {a["pattern"]} x{a["count"]}\n')
    return alerts


def check_thumbnail_v6():
    """直近24hの記事サムネがv6準拠(1200x675)かチェック"""
    import urllib.request, base64
    try:
        from dotenv import load_dotenv
        load_dotenv('/home/aiuser/kpop-ai-system/.env')
    except Exception:
        pass
    wp_user = os.environ.get('WP_USER', '')
    wp_pass = os.environ.get('WP_PASS', '')
    auth_header = 'Basic ' + base64.b64encode(f'{wp_user}:{wp_pass}'.encode()).decode()
    since = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%S')
    bad = []
    try:
        url = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?after={since}&per_page=50&_fields=id,title,featured_media'
        req = urllib.request.Request(url, headers={'Authorization': auth_header})
        posts = json.loads(urllib.request.urlopen(req, timeout=15).read())
        for p in posts:
            fm_id = p.get('featured_media', 0)
            if not fm_id:
                bad.append({'id': p['id'], 'issue': 'no_thumbnail'})
                continue
            try:
                murl = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{fm_id}?_fields=media_details,alt_text'
                mreq = urllib.request.Request(murl, headers={'Authorization': auth_header})
                m = json.loads(urllib.request.urlopen(mreq, timeout=10).read())
                d = m.get('media_details', {})
                w, h = d.get('width', 0), d.get('height', 0)
                # v6基準: 1200x675、OGP標準: 1200x630 も許容
                if w != 1200 or h not in (675, 630):
                    bad.append({'id': p['id'], 'issue': f'size_{w}x{h}', 'fm': fm_id})
                if not m.get('alt_text'):
                    bad.append({'id': p['id'], 'issue': 'no_alt', 'fm': fm_id})
            except Exception:
                pass
    except Exception:
        pass
    if bad:
        os.makedirs('logs', exist_ok=True)
        with open('logs/pipeline_alerts.log', 'a') as af:
            af.write(f'\n=== {datetime.now().isoformat()} thumbnail_v6 ===\n')
            for b in bad:
                af.write(f'  post {b["id"]}: {b["issue"]}\n')
    return bad


def check_all_pipelines():
    """registry連携: 全pipelineのcron沈黙検知"""
    if not os.path.exists(REGISTRY):
        return [], []

    reg = json.load(open(REGISTRY))
    now = time.time()
    critical = []
    warning = []

    for name, info in reg['pipelines'].items():
        log_path = info['log']
        cat = info.get('category', 'medium')
        max_min = info.get('max_silence_min', 180)

        if not os.path.exists(log_path):
            # aliases対応: 別名ログパスがあれば探す
            alias_log = None
            for alias in info.get('aliases', []):
                cand = f'logs/{alias}.log'
                if os.path.exists(cand):
                    alias_log = cand
                    break
            if alias_log:
                log_path = alias_log  # alias側ログで沈黙チェックへ
            elif cat in ['critical', 'high']:
                critical.append({'pipeline': name, 'issue': 'log_missing', 'category': cat})
                continue
            else:
                warning.append({'pipeline': name, 'issue': 'log_missing', 'category': cat})
                continue
        else:
            elapsed_min = (now - os.path.getmtime(log_path)) / 60
            if elapsed_min > max_min:
                entry = {'pipeline': name, 'silent_min': int(elapsed_min), 'max': max_min, 'category': cat}
                if cat == 'critical':
                    critical.append(entry)
                else:
                    warning.append(entry)

    # アラートログ書き出し
    if critical or warning:
        with open('logs/pipeline_alerts.log', 'a') as af:
            af.write(f'\n=== PIPELINE SILENCE {datetime.now().isoformat()} ===\n')
            for i in critical:
                desc = i.get('issue') or f"{i.get('silent_min', '?')}分沈黙"
                af.write(f'  CRITICAL: {i["pipeline"]} — {desc}\n')
            for i in warning:
                desc = i.get('issue') or f"{i.get('silent_min', '?')}分沈黙"
                af.write(f'  WARNING: {i["pipeline"]} — {desc}\n')

    return critical, warning


def notify_discord(critical, warning):
    """critical検知時にDiscord緊急アラート"""
    if not critical:
        return
    try:
        from lib.discord_client import post_as_staff_in_channel, post_to_channel
        msg_lines = [f"**CRITICAL: pipeline停止検知 ({len(critical)}件)**\n"]
        for p in critical[:8]:
            issue = p.get('issue', f"{p.get('silent_min', '?')}分沈黙 (閾値{p.get('max', '?')}分)")
            msg_lines.append(f"- `{p['pipeline']}`: {issue}")
        post_to_channel('🚨-緊急アラート', '\n'.join(msg_lines))
        post_as_staff_in_channel(
            'KPJ-EXE-003',
            f"検知: {len(critical)}件のcritical pipeline停止。即時調査します。\n— アルセウス (CTO)",
            '🚨-緊急アラート',
        )
    except Exception as e:
        print(f'discord通知失敗: {e}')


def check_crontab_sync():
    """crontab.txtとライブcrontabの乖離を検出"""
    import subprocess
    txt_path = '/home/aiuser/kpop-ai-system/crontab.txt'
    try:
        live = subprocess.check_output(['crontab', '-l'], text=True, stderr=subprocess.DEVNULL)
        with open(txt_path) as f:
            saved = f.read()
        live_lines = set(l.strip() for l in live.splitlines() if l.strip() and not l.strip().startswith('#'))
        saved_lines = set(l.strip() for l in saved.splitlines() if l.strip() and not l.strip().startswith('#'))
        missing = live_lines - saved_lines
        extra = saved_lines - live_lines
        drift = len(missing) + len(extra)
        if drift > 5:
            return f"crontab.txt と live crontab に {drift}行の乖離（live追加{len(missing)} / txt余分{len(extra)}）。crontab -l > crontab.txt で同期必要"
    except Exception:
        pass
    return None


def main():
    # 1. 例外パターン検知
    alerts = check()
    print(f'例外検知: {len(alerts)}件')
    for a in alerts:
        print(f'  {a["file"]}: {a["pattern"]} x{a["count"]}')

    # 2. サムネv6チェック
    thumb_issues = check_thumbnail_v6()
    print(f'サムネv6非準拠: {len(thumb_issues)}件')
    for t in thumb_issues:
        print(f'  post {t["id"]}: {t["issue"]}')

    # 3. registry連携: 全pipeline沈黙検知
    critical, warning = check_all_pipelines()
    print(f'pipeline沈黙: critical={len(critical)} warning={len(warning)}')
    for c in critical:
        issue = c.get('issue', f"{c.get('silent_min', '?')}分沈黙")
        print(f'  CRITICAL: {c["pipeline"]} — {issue}')
    for w in warning[:10]:
        issue = w.get('issue', f"{w.get('silent_min', '?')}分沈黙")
        print(f'  WARNING: {w["pipeline"]} — {issue}')

    # 4. Discord通知 (criticalのみ)
    notify_discord(critical, warning)

    # 5. crontab同期チェック
    crontab_drift = check_crontab_sync()
    if crontab_drift:
        warning.append({'pipeline': 'crontab_sync', 'issue': crontab_drift})
        print(f'  WARNING: crontab_sync — {crontab_drift}')

    # 6. JSON status出力 (朝会用)
    status = {
        'timestamp': datetime.now().isoformat(),
        'exception_alerts': len(alerts),
        'thumb_issues': len(thumb_issues),
        'critical': critical,
        'warning': warning,
    }
    with open('logs/pipeline_health_status.json', 'w') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

    # 6. ログタイムスタンプ更新
    with open('logs/pipeline_health.log', 'a') as f:
        f.write(f"{datetime.now().isoformat()} critical={len(critical)} warning={len(warning)} alerts={len(alerts)}\n")

    return status


if __name__ == '__main__':
    main()
