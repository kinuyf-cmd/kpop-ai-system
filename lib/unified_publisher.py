#!/usr/bin/env python3
"""統一記事投稿関数 - breaking/auto_event/auto_comeback 全てこれを使う

機能: タイトル最適化, スラッグ, メタDesc, サムネ(smart_crop), 引用, カテゴリ判定, GSC通知, ログ
"""
import os, sys, json, urllib.request, base64
from datetime import datetime

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

from lib.title_optimizer import optimize_title, generate_slug, generate_meta_description
from lib.thumbnail_resolver import resolve_thumbnail

try:
    from lib.x_poster import post_tweet as _x_post_tweet
except Exception:
    _x_post_tweet = None

AUTH = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()
PUBLISH_LOG = '/home/aiuser/kpop-ai-system/logs/unified_publish.jsonl'

CONFIDENCE_NOTES = {
    'high': '<p><em>※ 本記事は複数の韓国メディア報道を元に編集部が翻訳・編集しました。</em></p>',
    'medium': '<p><em>※ 本記事は韓国メディアの公式発表・一次報道を元に編集部が翻訳・編集しました。</em></p>',
    'low': ('<p style="background:#FFF9E6;padding:12px;border-left:4px solid #E8B86D;border-radius:4px;margin:16px 0;">'
            '<strong>単一メディア速報</strong><br/>'
            '本記事は韓国メディア1社の報道を元にしています。'
            '続報や公式発表で内容が変更される可能性があります。</p>'),
}


def _fetch_category_id(slug):
    try:
        req = urllib.request.Request(
            f"https://www.kpopjournal.tokyo/wp-json/wp/v2/categories?slug={slug}&_fields=id",
            headers={'Authorization': f'Basic {AUTH}'},
        )
        res = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return res[0]['id'] if res else None
    except Exception:
        return None


def _detect_category_slug(title, body, kind='news'):
    text = (title + ' ' + (body or '')).lower()
    if kind in ('breaking', 'comeback'):
        return 'news'
    if kind == 'event':
        return 'event'
    if any(kw in text for kw in ['ツアー', 'コンサート', 'ライブ', 'ファンミ']):
        return 'event'
    if any(kw in text for kw in ['美容', 'メイク', 'スキンケア', 'コスメ']):
        return 'beauty'
    return 'news'


def _upload_media(image_path):
    try:
        with open(image_path, 'rb') as f:
            data = f.read()
    except Exception:
        return None
    ext = os.path.splitext(image_path)[1][1:].lower() or 'jpg'
    ct = 'image/png' if ext == 'png' else 'image/jpeg'
    filename = f"thumb_{int(datetime.now().timestamp())}.{ext}"
    req = urllib.request.Request(
        "https://www.kpopjournal.tokyo/wp-json/wp/v2/media",
        data=data,
        headers={
            'Authorization': f'Basic {AUTH}',
            'Content-Type': ct,
            'Content-Disposition': f'attachment; filename="{filename}"',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read()).get('id')
    except Exception as e:
        print(f"  media upload error: {e}")
        return None


def _gsc_notify(url):
    try:
        from lib.gsc_indexing import notify_url_updated
        r = notify_url_updated(url)
        return r.get('status') == 'ok'
    except Exception:
        return False


def unified_publish(
    raw_title: str,
    body_html: str,
    source_url: str = None,
    artist: str = None,
    kind: str = 'news',
    confidence: str = 'high',
    source_signals: list = None,
    force_slug: str = None,
    is_breaking: bool = False,
) -> dict:
    """統一投稿関数"""
    log = []

    # 1. タイトル最適化
    optimized = optimize_title(raw_title, body_html[:500] if body_html else '')
    if kind == 'breaking' or confidence == 'low':
        prefix = '【速報】' if kind == 'breaking' else '【韓国メディア速報】'
        title_final = f"{prefix}{optimized}"[:50]
    else:
        title_final = optimized
    log.append(f"title: {title_final} ({len(title_final)}字)")

    # 2. スラッグ
    slug = force_slug or generate_slug(optimized)
    log.append(f"slug: {slug}")

    # 3. メタディスクリプション
    meta_desc = generate_meta_description(title_final, body_html[:500] if body_html else '')

    # 4. 信頼度注意書き
    conf_note = CONFIDENCE_NOTES.get(confidence, '')

    # 5. サムネ解決
    thumb = None
    media_id = None
    attribution_html = ''
    if source_url or artist:
        try:
            thumb = resolve_thumbnail(source_url, title_final, body_html[:500] if body_html else '', 0)
        except Exception as e:
            log.append(f"thumb error: {e}")

    if thumb and thumb.get('path'):
        media_id = _upload_media(thumb['path'])
        log.append(f"media_id: {media_id} ({thumb.get('source')})")
        if thumb.get('source') == 'source_site' and thumb.get('source_url'):
            attribution_html = (
                f'<p style="font-size:11px;color:#888;text-align:right;margin:8px 0;">'
                f'画像: <a href="{thumb["source_url"]}" target="_blank" rel="noopener">元記事より</a></p>\n'
            )

    # 6. 本文組み立て
    sources_html = ''
    if source_signals:
        items = ''.join(
            f'<li><a href="{s.get("url","#")}" target="_blank" rel="noopener">'
            f'{s.get("source_id","?").upper()}</a>: {s.get("title","")[:70]}</li>'
            for s in source_signals[:5]
        )
        sources_html = f'\n<h2>情報ソース</h2>\n<ul>{items}</ul>\n<p><em>※ 最新情報は各公式発表をご確認ください。</em></p>'
    elif source_url:
        sources_html = f'\n<h2>情報ソース</h2>\n<p>元記事: <a href="{source_url}" target="_blank" rel="noopener">{source_url[:60]}</a></p>'

    content = f"{attribution_html}{body_html}\n\n{conf_note}\n{sources_html}"

    # 6.5. 本文品質ゲート
    import re as _re
    _body_text = _re.sub(r'<[^>]+>', '', body_html).strip()
    _body_core = _re.sub(r'※[^<\n]*|情報ソース[\s\S]*', '', _body_text).strip()
    _ja_chars = sum(1 for c in _body_core if '\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff')
    _ja_ratio = _ja_chars / max(len(_body_core), 1)
    _quality_fail = None
    _min_len = 150 if is_breaking else 200
    if len(_body_core) < _min_len:
        _quality_fail = f'本文が短すぎる ({len(_body_core)}字、最低{_min_len}字)'
    elif _ja_ratio < 0.3:
        _quality_fail = f'日本語比率低すぎる ({_ja_ratio*100:.0f}%、最低30%)'
    if _quality_fail:
        log.append(f"🔴 本文品質不合格: {_quality_fail}")
        _log_publish({
            'success': False, 'ts': datetime.now().isoformat(),
            'title': title_final, 'kind': kind,
            'error': f'quality_fail: {_quality_fail}', 'log': log,
        })
        return {'success': False, 'error': f'本文品質: {_quality_fail}', 'log': log}
    log.append(f"✅ 本文品質OK ({len(_body_core)}字, 日本語{_ja_ratio*100:.0f}%)")

    # 7. カテゴリ
    cat_slug = _detect_category_slug(title_final, body_html, kind)
    cat_id = _fetch_category_id(cat_slug)

    # 8. WP投稿
    data = {
        'title': title_final,
        'content': content,
        'excerpt': meta_desc,
        'status': 'publish',
    }
    if slug:
        data['slug'] = slug
    if cat_id:
        data['categories'] = [cat_id]
    if media_id:
        data['featured_media'] = media_id

    body_req = json.dumps(data).encode()
    req = urllib.request.Request(
        "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts",
        data=body_req,
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'},
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            result = json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode('utf-8', errors='replace')[:300]
        log.append(f"WP error: HTTP {e.code}")
        _log_publish({'success': False, 'log': log, 'error': err, 'kind': kind})
        return {'success': False, 'error': err, 'log': log}
    except Exception as e:
        log.append(f"WP error: {e}")
        _log_publish({'success': False, 'log': log, 'error': str(e), 'kind': kind})
        return {'success': False, 'error': str(e), 'log': log}

    post_id = result.get('id')
    post_url = result.get('link', '')
    log.append(f"post_id={post_id}")

    # 9. GSC Indexing
    if post_url and _gsc_notify(post_url):
        log.append("GSC OK")

    # 9b. X投稿
    if post_url and _x_post_tweet is not None:
        try:
            x_r = _x_post_tweet(title_final, post_url)
            if x_r.get('success'):
                log.append(f"X OK tid={x_r.get('tweet_id', '?')}")
            else:
                log.append(f"X skip: {x_r.get('error', '')[:60]}")
        except Exception as e:
            log.append(f"X error: {e}")

    # 10. ログ
    _log_publish({
        'success': True, 'ts': datetime.now().isoformat(),
        'post_id': post_id, 'post_url': post_url,
        'title': title_final, 'slug': slug,
        'kind': kind, 'confidence': confidence,
        'media_id': media_id, 'thumb_source': thumb.get('source') if thumb else None,
    })

    return {
        'success': True, 'post_id': post_id, 'post_url': post_url,
        'title': title_final, 'slug': slug, 'media_id': media_id, 'log': log,
    }


def _log_publish(entry):
    os.makedirs(os.path.dirname(PUBLISH_LOG), exist_ok=True)
    with open(PUBLISH_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    print("unified_publisher module OK")
