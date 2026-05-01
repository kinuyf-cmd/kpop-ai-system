#!/usr/bin/env python3
"""統一記事投稿関数 - breaking/auto_event/auto_comeback 全てこれを使う

機能: タイトル最適化, スラッグ, メタDesc, サムネ(smart_crop), 引用, カテゴリ判定, GSC通知, ログ
"""
import os, sys, json, urllib.request, base64
from datetime import datetime

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from lib.cta_injector import inject_cta_into_content

from lib.title_optimizer import optimize_title, generate_slug, generate_meta_description, validate_slug
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


def _upload_media(image_path, alt_text=''):
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
            media_id = json.loads(r.read()).get('id')
        # ALTテキスト設定（空ALT防止）
        if media_id and alt_text:
            try:
                alt_body = json.dumps({'alt_text': alt_text}).encode()
                alt_req = urllib.request.Request(
                    f"https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{media_id}",
                    data=alt_body, method='POST',
                    headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
                urllib.request.urlopen(alt_req, timeout=30)
            except Exception:
                pass
        return media_id
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
    force_category_id: int = None,
) -> dict:
    """統一投稿関数"""
    log = []

    # 1. タイトル最適化
    optimized = optimize_title(raw_title, body_html[:500] if body_html else '')
    if kind == 'breaking' or confidence == 'low':
        prefix = '【速報】' if kind == 'breaking' else '【韓国メディア速報】'
        title_final = f"{prefix}{optimized}"[:42]  # 監査基準42字厳守
    else:
        title_final = optimized
    log.append(f"title: {title_final} ({len(title_final)}字)")

    # 2. スラッグ (検証ゲート付き: ASCII/適切長/非自動生成を保証)
    slug = force_slug or generate_slug(optimized)
    slug = validate_slug(slug) or generate_slug(title_final)  # 不合格時は再生成
    slug = validate_slug(slug) or f"article-{int(__import__('time').time())}"  # 最終フォールバック
    log.append(f"slug: {slug}")

    # 3. メタディスクリプション (80字未満フォールバック付き)
    import re as _re_meta
    meta_desc = generate_meta_description(title_final, body_html[:1000] if body_html else '')
    if not meta_desc or len(meta_desc) < 80:
        meta_desc = generate_meta_description(title_final, body_html[:2000] if body_html else '')
    if not meta_desc or len(meta_desc) < 80:
        # 本文から最初の2段落を抽出
        _paras = _re_meta.findall(r'<p[^>]*>(.*?)</p>', body_html or '', _re_meta.DOTALL)
        _plain = [_re_meta.sub(r'<[^>]+>', '', pp).strip() for pp in _paras if len(_re_meta.sub(r'<[^>]+>', '', pp).strip()) > 20]
        if _plain:
            meta_desc = '。'.join(_plain[:2])[:155]
        else:
            meta_desc = f"{title_final}の最新情報をK-POPジャーナルが詳しくお届け。ファン必見のニュース・イベント・カムバック情報を徹底解説します。"[:155]

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
        _src_alt = f"{title_final}のサムネイル画像"
        media_id = _upload_media(thumb['path'], alt_text=_src_alt)
        log.append(f"media_id: {media_id} ({thumb.get('source')})")
        if thumb.get('source') == 'source_site' and thumb.get('source_url'):
            attribution_html = (
                f'<p style="font-size:11px;color:#888;text-align:right;margin:8px 0;">'
                f'画像: <a href="{thumb["source_url"]}" target="_blank" rel="noopener">元記事より</a></p>\n'
            )

    # 5.1. サムネ未解決時のDALL-Eフォールバック
    if not media_id:
        try:
            from lib.dalle_thumbnail_gen import generate_thumbnail
            import tempfile
            # タイトルからアーティスト名を抽出してプロンプトに含める
            _artist_hint = artist or ''
            if not _artist_hint:
                import re as _re_artist
                _known_groups = [
                    'BTS', 'BLACKPINK', 'TWICE', 'aespa', 'NewJeans', 'IVE',
                    'LE SSERAFIM', 'Stray Kids', 'SEVENTEEN', 'ENHYPEN', 'NMIXX',
                    'ITZY', 'TXT', 'EXO', '2PM', 'BABYMONSTER', 'RIIZE', 'ILLIT',
                    'NCT', 'Red Velvet', 'BIGBANG', 'SHINee', 'GOT7', 'ASTRO',
                ]
                for _g in _known_groups:
                    if _g.lower() in title_final.lower() or _g.lower() in (body_html or '')[:500].lower():
                        _artist_hint = _g
                        break
            _artist_desc = f"related to K-pop group {_artist_hint}. " if _artist_hint else ""
            dalle_prompt = (
                f"A professional editorial thumbnail image for a K-pop article titled '{title_final}'. "
                f"{_artist_desc}"
                f"Modern, vibrant, magazine-quality illustration with Korean pop culture aesthetic, 1200x675 aspect ratio. "
                f"No text overlay, no watermarks. Abstract artistic representation that matches the article theme."
            )
            _thumb_alt = f"{title_final}のサムネイル画像"
            with tempfile.TemporaryDirectory(prefix='up_thumb_') as td:
                raw_path = os.path.join(td, 'dalle_raw.jpg')
                dr = generate_thumbnail(prompt=dalle_prompt, output_path=raw_path, size="1792x1024", quality="standard")
                if dr.get('success') and os.path.exists(raw_path):
                    from PIL import Image
                    resized = os.path.join(td, 'dalle_1200x675.jpg')
                    Image.open(raw_path).resize((1200, 675), Image.LANCZOS).save(resized, 'JPEG', quality=85)
                    media_id = _upload_media(resized, alt_text=_thumb_alt)
                    log.append(f"media_id: {media_id} (dalle_fallback, alt={_thumb_alt[:30]})")
                else:
                    log.append(f"dalle_fallback skip: {dr.get('reason', '?')}")
        except Exception as e:
            log.append(f"dalle_fallback err: {e}")

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

    # 6.2. テンプレートラベル除去 + 文字重複自動修正
    from lib.text_sanitizer import strip_template_labels, sanitize_gpt_html
    title_final = strip_template_labels(title_final)
    content = strip_template_labels(content)
    content = sanitize_gpt_html(content)

    # 6.3. CTA自動挿入 (Phase 14)
    try:
        content = inject_cta_into_content(title_final, content)
    except Exception as e:
        log.append(f"CTA inject err: {e}")

    # 6.3.1. 内部リンク自動挿入
    try:
        from lib.internal_links import insert_internal_links
        content = insert_internal_links(content, post_title=title_final)
        log.append("internal_links OK")
    except Exception as e:
        log.append(f"internal_links err: {e}")

    # 6.3.2. CTA/リンク挿入後に再サニタイズ (unclosed_p 再発防止)
    content = sanitize_gpt_html(content)

    # 6.3.3. カテゴリ解決 (ゲート前に必要)
    cat_ids = []
    if force_category_id:
        cat_ids = [force_category_id]
    else:
        cat_slug = _detect_category_slug(title_final, body_html, kind)
        base_cat = _fetch_category_id(cat_slug)
        if base_cat:
            cat_ids.append(base_cat)
    # アーティストカテゴリ自動付与
    try:
        _acm_path = '/home/aiuser/kpop-ai-system/config/artist_category_map.json'
        if os.path.exists(_acm_path):
            with open(_acm_path, encoding='utf-8') as _acf:
                _acm = json.load(_acf)
            _search_text = title_final + ' ' + (body_html[:500] if body_html else '')
            for _artist_name, _cat_id in _acm.items():
                if _artist_name in _search_text and _cat_id not in cat_ids:
                    cat_ids.append(_cat_id)
                    log.append(f"artist_cat: {_artist_name}→{_cat_id}")
                    break  # 1アーティストで十分
    except Exception as _ace:
        log.append(f"artist_cat err: {_ace}")

    # 6.4. 統一公開前ゲート (fact_check + 品質 + HTML + メタデータを一括判定)
    try:
        from lib.pre_publish_gate import pre_publish_gate as _gate
        _gate_r = _gate(
            title=title_final, body_html=content,
            post_type='post', kind=kind,
            source_url=source_url, source_signals=source_signals,
            slug=slug, featured_media=media_id,
            categories=cat_ids, excerpt=meta_desc,
            status='publish',
        )
        if _gate_r['verdict'] == 'BLOCK':
            log.append(f"\U0001f534 Gate BLOCK: {_gate_r['block_reasons']}")
            _log_publish({
                'success': False, 'ts': datetime.now().isoformat(),
                'title': title_final, 'kind': kind,
                'error': f'gate_block: {_gate_r["block_reasons"]}', 'log': log,
            })
            return {'success': False, 'error': f'Gate BLOCK: {_gate_r["block_reasons"]}', 'log': log}
        elif _gate_r['verdict'] == 'WARN':
            log.append(f"\u26a0\ufe0f Gate WARN ({len(_gate_r['warn_reasons'])}件): {_gate_r['warn_reasons'][:3]}")
        else:
            log.append("\u2705 Gate PASS")
    except Exception as _e:
        log.append(f"Gate skip: {_e}")

    import re as _re
    _body_text = _re.sub(r'<[^>]+>', '', body_html).strip()

    # 6.7. 薬機法チェック (コスメ/美容記事のみ)
    try:
        from lib.yakkihou_checker import check as _yakki_check, is_cosmetic_article as _is_cosme
        if _is_cosme(title_final):
            _yakki_issues = _yakki_check(title_final + ' ' + _body_text)
            _yakki_high = [i for i in _yakki_issues if i['severity'] == 'high']
            if _yakki_high:
                log.append(f"⚠️ 薬機法リスク: {len(_yakki_high)}件 ({', '.join(i['pattern'] for i in _yakki_high[:3])})")
            if len(_yakki_issues) > 0:
                log.append(f"薬機法チェック: {len(_yakki_issues)}件検出")
    except Exception as e:
        log.append(f"薬機法チェックskip: {e}")

    # 7. cat_id (カテゴリ初期化は 6.3.3 で実施済み)
    cat_id = cat_ids[0] if cat_ids else None

    # 8. WP投稿
    data = {
        'title': title_final,
        'content': content,
        'excerpt': meta_desc,
        'status': 'publish',
    }
    if slug:
        data['slug'] = slug
    if cat_ids:
        data['categories'] = cat_ids
    elif cat_id:
        data['categories'] = [cat_id]
    if media_id:
        data['featured_media'] = media_id
    else:
        log.append("⚠️ WARN: サムネなしで公開 (resolve/DALL-E全失敗)")

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
            x_r = _x_post_tweet(title_final, post_url, post_id=post_id)
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
