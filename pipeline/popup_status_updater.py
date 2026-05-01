#!/usr/bin/env python3
"""popup記事の状態を自動更新:
1. unknown状態 → 公式URLから期間再抽出
2. 期間ありでstatus不整合 → 修正
3. 終了後30日 → _popup_archived=1
4. 終了後90日 → draft化
5. 終了後180日 → quarantine候補マーク
"""
import sys, os, json, re, urllib.request, base64
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
JST = timezone(timedelta(hours=9))
LOG = '/home/aiuser/kpop-ai-system/logs/popup_status_updater.jsonl'


def fetch_all_popups():
    url = "https://www.kpopjournal.tokyo/wp-json/wp/v2/popup?per_page=100&_embed=true"
    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        print(f"fetch err: {e}")
        return []


def update_popup(pid, payload):
    body = json.dumps(payload).encode()
    try:
        req = urllib.request.Request(
            f"https://www.kpopjournal.tokyo/wp-json/wp/v2/popup/{pid}",
            data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=20)
        return True
    except Exception as e:
        print(f"  update err {pid}: {e}")
        return False


def extract_dates_from_url(url):
    """公式URLから期間再抽出"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', errors='ignore')
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text)[:5000]

        patterns = [
            r'(\d{4})年(\d{1,2})月(\d{1,2})日.*?[~〜から至\-].*?(\d{1,2})月(\d{1,2})日',
            r'(\d{1,2})月(\d{1,2})日.*?[~〜\-].*?(\d{1,2})月(\d{1,2})日',
            r'(\d{4})/(\d{1,2})/(\d{1,2}).*?[~〜\-].*?(\d{4})/(\d{1,2})/(\d{1,2})',
        ]
        now = datetime.now(JST)
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                groups = m.groups()
                try:
                    if len(groups) == 5:
                        sy = int(groups[0])
                        sm, sd, em, ed = map(int, groups[1:])
                        return datetime(sy, sm, sd).strftime('%Y-%m-%d'), datetime(sy, em, ed).strftime('%Y-%m-%d')
                    elif len(groups) == 4:
                        sm, sd, em, ed = map(int, groups)
                        return datetime(now.year, sm, sd).strftime('%Y-%m-%d'), datetime(now.year, em, ed).strftime('%Y-%m-%d')
                    elif len(groups) == 6:
                        sy, sm, sd, ey, em, ed = map(int, groups)
                        return datetime(sy, sm, sd).strftime('%Y-%m-%d'), datetime(ey, em, ed).strftime('%Y-%m-%d')
                except:
                    pass
    except Exception as e:
        print(f"  url fetch err: {e}")
    return None, None


def determine_status(start_date, end_date):
    if not start_date:
        return 'unknown'
    today = datetime.now(JST).date()
    try:
        s = datetime.strptime(start_date, '%Y-%m-%d').date()
        e = datetime.strptime(end_date, '%Y-%m-%d').date() if end_date else s
        if today < s:
            return 'upcoming'
        elif s <= today <= e:
            return 'ongoing'
        else:
            return 'ended'
    except:
        return 'unknown'


def days_since_end(end_date_str):
    if not end_date_str:
        return 0
    try:
        end = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        return (datetime.now(JST).date() - end).days
    except:
        return 0


def main():
    popups = fetch_all_popups()
    print(f"=== popup状態自動更新: 対象{len(popups)}件 ===")

    stats = {'date_recovered': 0, 'status_updated': 0, 'archived': 0, 'drafted': 0}

    os.makedirs(os.path.dirname(LOG), exist_ok=True)

    for p in popups:
        pid = p['id']
        meta = p.get('meta', {})
        status = meta.get('_popup_status', 'unknown')
        start = meta.get('_popup_start_date', '')
        end = meta.get('_popup_end_date', '')
        official_url = meta.get('_popup_official_url', '')

        # 1. unknown + no dates → re-extract from URL
        if status in ('unknown', '') and not start and official_url:
            new_start, new_end = extract_dates_from_url(official_url)
            if new_start:
                new_status = determine_status(new_start, new_end)
                meta_update = {'_popup_start_date': new_start, '_popup_status': new_status}
                if new_end:
                    meta_update['_popup_end_date'] = new_end
                if update_popup(pid, {'meta': meta_update}):
                    stats['date_recovered'] += 1
                    print(f"  期間回復: id={pid} {new_start}~{new_end} → {new_status}")

        # 2. has dates but status wrong
        elif start and status in ('unknown', ''):
            correct = determine_status(start, end)
            if correct != status:
                if update_popup(pid, {'meta': {'_popup_status': correct}}):
                    stats['status_updated'] += 1
                    print(f"  status修正: id={pid} {status} → {correct}")

        # 3. ended lifecycle management
        elif end and status == 'ended':
            days = days_since_end(end)
            if days >= 90:
                # draft化 (一覧から除外)
                if update_popup(pid, {'status': 'draft'}):
                    stats['drafted'] += 1
                    print(f"  draft化: id={pid} (終了後{days}日)")
            elif days >= 30:
                # archive mark
                if not meta.get('_popup_archived'):
                    if update_popup(pid, {'meta': {'_popup_archived': '1'}}):
                        stats['archived'] += 1
                        print(f"  archive: id={pid} (終了後{days}日)")

    print(f"\nサマリ: 期間回復={stats['date_recovered']} status修正={stats['status_updated']} archive={stats['archived']} draft={stats['drafted']}")

    # 追加: popup_status_manager の統合処理
    try:
        from lib.popup_status_manager import (
            force_archive_ended, inject_pending_card, remove_pending_card_when_confirmed,
        )
        arch = force_archive_ended()
        print(f"archive移動: {arch.get('moved', 0)}件")
        inj = inject_pending_card()
        print(f"予告カード挿入: {inj.get('injected', 0)}件")
        rem = remove_pending_card_when_confirmed()
        print(f"予告カード除去: {rem.get('removed', 0)}件")
    except Exception as e:
        print(f"popup_status_manager統合処理err: {e}")


if __name__ == '__main__':
    main()
