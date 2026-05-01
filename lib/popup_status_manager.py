#!/usr/bin/env python3
"""ポップアップ4段階ステータス管理
announced → confirmed → ongoing → ended
"""
import os
import json
import urllib.request
import base64
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv('/home/aiuser/kpop-ai-system/.env')
except Exception:
    pass

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
JST = timezone(timedelta(hours=9))

STATUSES = {
    'announced': '告知済 (会場/日程未確定)',
    'confirmed': '確定 (会場/日程確定)',
    'ongoing': '開催中',
    'ended': '終了',
}


def determine_status(start_date, end_date, venue=''):
    """日付・会場から4段階ステータスを自動判定"""
    today = datetime.now(JST).date()

    # 終了判定
    if end_date:
        try:
            end = datetime.strptime(end_date[:10], '%Y-%m-%d').date()
            if end < today:
                return 'ended'
        except ValueError:
            pass

    # 会場/日程未確定 → 告知済
    if not venue or venue in ('TBA', '未定', '調整中', ''):
        if not start_date:
            return 'announced'

    if not start_date:
        return 'announced'

    # 開催中判定
    try:
        start = datetime.strptime(start_date[:10], '%Y-%m-%d').date()
        if start <= today:
            return 'ongoing'
    except ValueError:
        return 'announced'

    return 'confirmed'


def _wp_request(url, data=None, method='GET'):
    headers = {'Authorization': f'Basic {AUTH}'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
        method = 'POST'
    req = urllib.request.Request(
        url, data=json.dumps(data).encode() if data else None,
        headers=headers, method=method,
    )
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def scan_and_update_all():
    """全popup記事をスキャンしてステータス更新"""
    try:
        popups = _wp_request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup?per_page=100'
        )
    except Exception as e:
        return {'updated': 0, 'total': 0, 'error': str(e)}

    updated = 0
    changes = []
    for p in popups:
        pid = p['id']
        meta = p.get('meta', {})
        start = meta.get('_popup_start_date', '')
        end = meta.get('_popup_end_date', '')
        venue = meta.get('_popup_address', '') or meta.get('_popup_venue', '')
        old_status = meta.get('_popup_status', 'unknown')

        new_status = determine_status(start, end, venue)

        if new_status != old_status:
            try:
                _wp_request(
                    f'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup/{pid}',
                    data={'meta': {
                        '_popup_status': new_status,
                        '_last_status_update': datetime.now(JST).isoformat(),
                    }},
                )
                updated += 1
                changes.append({
                    'id': pid,
                    'title': p.get('title', {}).get('rendered', '')[:40],
                    'old': old_status, 'new': new_status,
                })
            except Exception as e:
                print(f"  update err {pid}: {e}")

    for c in changes:
        print(f"  {c['old']} → {c['new']}: id={c['id']} {c['title']}")

    return {'updated': updated, 'total': len(popups), 'changes': changes}


# --- 1A: ended記事を archived-popup カテゴリに強制移動 ---

def force_archive_ended():
    """ended判定の記事を全件 archived-popup カテゴリに移動"""
    # archived-popup カテゴリID取得
    try:
        cats = _wp_request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/categories?slug=archived-popup&_fields=id'
        )
    except Exception:
        cats = []
    if not cats:
        return {'error': 'archived-popup category not found', 'moved': 0}
    archived_cat_id = cats[0]['id']

    # upcoming-popup カテゴリID (除去対象)
    try:
        up_cats = _wp_request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/categories?slug=upcoming-popup&_fields=id'
        )
    except Exception:
        up_cats = []
    upcoming_cat_id = up_cats[0]['id'] if up_cats else None

    try:
        popups = _wp_request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup?per_page=100&_fields=id,meta,categories'
        )
    except Exception:
        return {'error': 'fetch failed', 'moved': 0}

    moved = 0
    for p in popups:
        meta = p.get('meta', {})
        if meta.get('_popup_status') != 'ended':
            continue
        current_cats = p.get('categories', []) or []
        if archived_cat_id in current_cats:
            continue
        # upcoming除去 + archived付与
        new_cats = [c for c in current_cats if c != upcoming_cat_id] + [archived_cat_id]
        try:
            _wp_request(
                f'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup/{p["id"]}',
                data={'categories': new_cats},
            )
            moved += 1
        except Exception:
            pass

    return {'moved': moved}


# --- 2B: 予告記事にリッチカード挿入/除去 ---

PENDING_CARD_HTML = (
    '<div style="border-left:4px solid #ff9800;background:#fff8e1;padding:12px 16px;'
    'margin:16px 0;border-radius:4px;">'
    '<p style="margin:0;font-weight:bold;color:#e65100;">'
    '\u23f3 詳細未確定の予告情報です</p>'
    '<p style="margin:8px 0 0 0;font-size:0.95em;color:#555;">'
    '会場・日程の詳細が確定次第、本記事を自動更新します。'
    '最新の確定情報は公式発表をご確認ください。</p></div>\n'
)

_PENDING_CARD_MARKER = '詳細未確定の予告情報です'


def inject_pending_card():
    """announced記事の冒頭に予告リッチカードを挿入"""
    import re as _re
    try:
        popups = _wp_request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup?per_page=100&_fields=id,content,meta'
        )
    except Exception:
        return {'injected': 0, 'error': 'fetch failed'}

    injected = 0
    for p in popups:
        meta = p.get('meta', {})
        if meta.get('_popup_status') != 'announced':
            continue
        content = p.get('content', {})
        if isinstance(content, dict):
            content = content.get('rendered', '')
        if _PENDING_CARD_MARKER in content:
            continue
        new_content = PENDING_CARD_HTML + content
        try:
            _wp_request(
                f'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup/{p["id"]}',
                data={'content': new_content},
            )
            injected += 1
        except Exception:
            pass

    return {'injected': injected}


def remove_pending_card_when_confirmed():
    """confirmed/ongoing記事から予告カードを除去"""
    import re as _re
    try:
        popups = _wp_request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup?per_page=100&_fields=id,content,meta'
        )
    except Exception:
        return {'removed': 0, 'error': 'fetch failed'}

    removed = 0
    for p in popups:
        meta = p.get('meta', {})
        if meta.get('_popup_status') not in ('confirmed', 'ongoing'):
            continue
        content = p.get('content', {})
        if isinstance(content, dict):
            content = content.get('rendered', '')
        if _PENDING_CARD_MARKER not in content:
            continue
        # カードdivを除去
        new_content = _re.sub(
            r'<div style="border-left:4px solid #ff9800.*?</div>\s*',
            '', content, count=1, flags=_re.DOTALL,
        )
        if new_content != content:
            try:
                _wp_request(
                    f'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup/{p["id"]}',
                    data={'content': new_content},
                )
                removed += 1
            except Exception:
                pass

    return {'removed': removed}
