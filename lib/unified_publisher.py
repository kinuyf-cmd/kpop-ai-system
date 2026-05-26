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

# WP REST 認証(2026-05-23 移植: 旧サーバの application password ハードコードを撤去し
# env 化。CLAUDE.md「パスワード・APIキーをコード/ドキュメントにハードコードしない」準拠)。
# .env から WP_USER + WP_APP_PASS(無ければ WP_PASS)を読み Basic auth を組む。
def _load_wp_auth() -> str:
    try:
        from dotenv import load_dotenv
        load_dotenv('/home/aiuser/kpop-ai-system/.env')
    except Exception:
        pass
    user = os.environ.get('WP_USER', '')
    pw = os.environ.get('WP_APP_PASS') or os.environ.get('WP_PASS', '')
    if not user or not pw:
        # 認証未設定なら空。REST 呼び出しは 401 になるが import/構造は壊さない。
        print('WARN: WP_USER / WP_APP_PASS(or WP_PASS) 未設定 → REST 認証なし', file=sys.stderr)
        return ''
    return base64.b64encode(f"{user}:{pw}".encode()).decode()

AUTH = _load_wp_auth()
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


def _validate_thumbnail(image_path: str, expected_artist: str = '',
                        article_title: str = '') -> tuple[bool, str]:
    """公開前gate: サムネ画像の品質を検証 (2026-05-10完璧化)

    返却: (passed, reason)
    BLOCK条件:
      - 縦長画像 (height > width): 16:9枠で破綻
      - 極小サイズ (<300x200): 解像度不足
      - YouTube Shortsパターン (左右ブラー+縦コンテンツ)
      - Claude Vision: expected_artist が画像に写ってない (artist指定時のみ)
    """
    try:
        from PIL import Image
        img = Image.open(image_path).convert('RGB')
        w, h = img.size
        if h > w:
            return False, f"portrait image rejected ({w}x{h})"
        if w < 300 or h < 200:
            return False, f"too small ({w}x{h})"
        # Shorts pattern check
        try:
            import sys as _sys
            _sys.path.insert(0, '/home/aiuser/kpop-ai-system')
            from lib.thumbnail_source_resolver import _is_shorts_thumbnail
            if _is_shorts_thumbnail(image_path):
                return False, "YouTube Shorts pattern detected (vertical content with blurred sides)"
        except Exception:
            pass
        # Vision check (artist指定時のみ実行 — DALL-E art等のartist無し記事はskip)
        if expected_artist:
            try:
                from lib.thumbnail_vision_gate import vision_validate
                vision_ok, vision_reason = vision_validate(image_path, expected_artist, article_title)
                if not vision_ok:
                    return False, f"vision_gate: {vision_reason}"
            except Exception:
                pass  # FAIL OPEN: vision障害時は他のチェックだけ通す
        return True, "ok"
    except Exception as e:
        return False, f"validate err: {e}"


def _upload_media(image_path, alt_text=''):
    # 公開前gate: 不正サムネはアップロードしない
    ok, reason = _validate_thumbnail(image_path)
    if not ok:
        import sys as _sys
        _sys.stderr.write(f"[publisher] BLOCK upload: {image_path} ({reason})\n")
        return None
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
    auto_draft_reasons = []

    # 0. source_text 取得確認: news kind で <1500字 → draft化
    # memory: feedback_must_read_source.md
    if source_url and kind in ('news', 'breaking', 'feature'):
        try:
            from lib.source_reader import read_source as _read_source
            _src = _read_source(source_url) or {}
            _src_text = _src.get('text', '') if isinstance(_src, dict) else str(_src or '')
            if len(_src_text) < 1500:
                auto_draft_reasons.append('source_text_short')
                log.append(f"source_text_short: {len(_src_text)}字 (<1500) → 自動draft化")
        except Exception as _e:
            log.append(f"source_reader skip: {_e}")

    # 1. タイトル最適化
    # ユーザー指示 (2026-05-07): 速報タイトルの【速報】prefix廃止。低信頼度の【韓国メディア速報】は維持
    optimized = optimize_title(raw_title, body_html[:500] if body_html else '')
    if kind == 'breaking':
        title_final = optimized[:42]  # prefix無し、監査基準42字厳守
    elif confidence == 'low':
        title_final = f"【韓国メディア速報】{optimized}"[:42]
    else:
        title_final = optimized  # 通常記事は元の挙動どおり切り詰めなし
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

    # 5. サムネ解決 — artistが未指定でもタイトルから自動検出
    # 2026-05-07: タイトルの「主語」のみ採用 (本文/タイトル末尾に共起する別アーティストの誤採用を防止)
    #   例: "カン・ドンウォン、BTSのダンスチャレンジ希望" → 主語=カン・ドンウォン、BTSはサムネに不採用
    #   例: "ソ・イニョン、15kg減量..." (本文にTWICE言及) → 主語=ソ・イニョン非K-POP、TWICEは不採用
    thumb = None
    media_id = None
    attribution_html = ''
    if not artist:
        _known_groups = [
            'BTS', 'BLACKPINK', 'TWICE', 'aespa', 'NewJeans', 'IVE',
            'LE SSERAFIM', 'Stray Kids', 'SEVENTEEN', 'ENHYPEN', 'NMIXX',
            'ITZY', 'TXT', 'EXO', '2PM', 'BABYMONSTER', 'RIIZE', 'ILLIT',
            'NCT', 'Red Velvet', 'BIGBANG', 'SHINee', 'GOT7', 'ASTRO',
            '(G)I-DLE', 'ATEEZ', 'TREASURE', 'MONSTA X', 'DAY6',
            'THE BOYZ', 'KISS OF LIFE', 'BOYNEXTDOOR', 'TWS', 'TXT',
            'fromis_9', 'KEP1ER', 'STAYC', 'XG', 'P1Harmony',
        ]
        # 主語抽出: タイトル先頭部分 (最初の読点・句読点まで) のみ走査
        # 2026-05-10: \s を分割対象から除外 — "TOMORROW X TOGETHER"等の複数単語artist対応
        import re as _re_subj
        _title_subject = _re_subj.split(r'[、。「」!?！？]', title_final, maxsplit=1)[0]
        # alias map: フルネーム → 短い登録名 (TXTで統一する等)
        _alias_to_short = {
            'TOMORROW X TOGETHER': 'TXT',
        }
        # フルネーム → alias変換を先に試行 (順序重要: フルネームが短縮名より先にマッチ)
        for _full, _short in _alias_to_short.items():
            if _full.lower() in _title_subject.lower():
                artist = _short
                log.append(f"artist auto-detected (alias): {_full} → {_short}")
                break
        if not artist:
            for _g in _known_groups:
                if _g.lower() in _title_subject.lower():
                    artist = _g
                    log.append(f"artist auto-detected (subject): {artist}")
                    break
        # 主語に固有名詞がない場合は artist=空のまま (非K-POP記事の可能性)
        # 別アーティスト誤検出より、テーマ画像/abstract fallbackの方が安全

    # サムネ優先順位 (2026-05-10再修正: ソース先og:image最優先に戻す)
    # 速報/ニュース: ソースog:image → アーティスト写真 → DALL-E
    # 理由: 5/7修正で本人写真最優先化したが、artist識別ミス時に間違ったアーティスト写真が
    #       確定する事故が発生 (例: 18881チョ・スンヨン記事がBOYNEXTDOORに誤分類)。
    #       元記事のog:imageは少なくとも当該記事の文脈写真である可能性が高いため最優先。
    if not media_id and source_url:
        try:
            thumb = resolve_thumbnail(source_url, title_final, body_html[:500] if body_html else '', 0)
        except Exception as e:
            log.append(f"source_thumb error: {e}")
            thumb = None
        if thumb and thumb.get('path'):
            _src_alt = f"{title_final}のサムネイル画像"
            media_id = _upload_media(thumb['path'], alt_text=_src_alt)
            if media_id:
                log.append(f"media_id: {media_id} (source_og_primary: {thumb.get('source','')})")
                if thumb.get('source_url'):
                    attribution_html = (
                        f'<p style="font-size:11px;color:#888;text-align:right;margin:8px 0;">'
                        f'画像: <a href="{thumb["source_url"]}" target="_blank" rel="noopener">元記事より</a></p>\n'
                    )

    # ソース og:image が取得できなかった場合のフォールバック: アーティスト本人写真
    if not media_id and artist:
        try:
            from lib.thumbnail_source_resolver import resolve as _resolve_artist_thumb
            # 2026-05-12: 曲名 match で MV サムネを選定 (WDA 記事に THIRSTY MV 事故対策)
            _artist_thumb = _resolve_artist_thumb(artist_name=artist, article_type='concrete',
                                                  article_title=title_final)
            if _artist_thumb and _artist_thumb.get('image_path') and os.path.exists(_artist_thumb['image_path']):
                import tempfile as _tf
                with _tf.TemporaryDirectory(prefix='up_artist_') as _td:
                    _resized = os.path.join(_td, 'artist_thumb.jpg')
                    # 2026-05-15: portrait Instagram 写真の水平 stretch を防ぐためアスペクト保存 crop
                    from lib.image_utils import aspect_preserve_resize
                    aspect_preserve_resize(_artist_thumb['image_path'], _resized)
                    _thumb_alt = f"{title_final}のサムネイル画像"
                    media_id = _upload_media(_resized, alt_text=_thumb_alt)
                    if media_id:
                        log.append(f"media_id: {media_id} (artist_fallback: {_artist_thumb.get('source')})")
                        if _artist_thumb.get('source') == 'source_site' and _artist_thumb.get('source_url'):
                            attribution_html = (
                                f'<p style="font-size:11px;color:#888;text-align:right;margin:8px 0;">'
                                f'画像: <a href="{_artist_thumb["source_url"]}" target="_blank" rel="noopener">元記事より</a></p>\n'
                            )
        except Exception as e:
            log.append(f"artist_resolver error: {e}")

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
                    resized = os.path.join(td, 'dalle_1200x675.jpg')
                    # 2026-05-15: DALL-E 1792x1024 → 1200x675 へアスペクト保存 crop
                    from lib.image_utils import aspect_preserve_resize
                    aspect_preserve_resize(raw_path, resized)
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
            f'{s.get("source_id","?").upper()}</a>: 記事を見る</li>'
            for s in source_signals[:5]
        )
        # 出典は本文と同格の h2 でなく、末尾の控えめな aside にまとめる(オーナー
        # 指摘[2]「出典はまとめて下部に小さく」。CSS .kpop-sources で小サイズ表示)。
        sources_html = (f'\n<aside class="kpop-sources" aria-label="情報ソース">'
                        f'<p class="kpop-sources-label">情報ソース・出典</p>'
                        f'<ul class="kpop-sources-list">{items}</ul></aside>')
    elif source_url:
        sources_html = (f'\n<aside class="kpop-sources" aria-label="情報ソース">'
                        f'<p class="kpop-sources-label">出典: '
                        f'<a href="{source_url}" target="_blank" rel="noopener">{source_url[:60]}</a></p></aside>')

    content = f"{attribution_html}{body_html}\n\n{conf_note}\n{sources_html}"

    # 6.2. テンプレートラベル除去 + 文字重複自動修正
    from lib.text_sanitizer import strip_template_labels, sanitize_gpt_html
    title_final = strip_template_labels(title_final)
    content = strip_template_labels(content)
    content = sanitize_gpt_html(content)

    # 6.3.0. 内部リンク自動挿入(インラインのみ)を CTA より「先」に実行。
    # 注意1: insert_internal_links は末尾に <section class="related-articles">
    # を焼き付ける仕様。テンプレ側 B-4a が既に関連記事を描画するため、本文には
    # インラインリンクのみ挿入し末尾セクションは付けない。
    # 注意2: CTA より先に実行することで、CTA ブロック内テキスト(「ポップアップ」
    # 「韓国旅行」等)に内部リンクが混入するのを防ぐ(2026-05-26: 既存記事で
    # CTA 内に記事リンクが混入していた事故の根本対処)。
    try:
        from lib.internal_links import (
            _find_related_articles, _insert_inline_links, get_article_index)
        _idx = get_article_index()
        _related = _find_related_articles(content, title_final, _idx)
        content = _insert_inline_links(content, _related)
        log.append("internal_links(inline-only, pre-CTA) OK")
    except Exception as e:
        log.append(f"internal_links err: {e}")

    # 6.3. CTA自動挿入 (Phase 14) — 内部リンク挿入の「後」に行い CTA 内混入を防ぐ
    try:
        content = inject_cta_into_content(title_final, content)
    except Exception as e:
        log.append(f"CTA inject err: {e}")

    # 6.3.1b. K-POP Artist Profile への inline link 注入 (本文中の初出のみ)
    # (廃止 2026-05-26) inject_profile_inline_links は本文アーティスト名を
    # /artist-{slug}/(404)へリンクしていた。本文中アーティスト名のリンクは
    # テーマの kpop_inject_internal_links(/artists/{slug}/ 200)に一任。
    log.append("profile_link: disabled (broken /artist- url)")

    # 6.3.1c. (廃止 2026-05-26) K-POPカムバックカレンダーCTA注入。
    # オーナー指摘「カムバック・カレンダーは不要」。プロフィール導線は
    # テンプレ側 .kpop-idol-wiki-link CTA に、イベント導線は /events/ に一本化。
    # 本文への焼き付き注入を止める(既存42記事の焼き付きは別途DB除去)。
    log.append("calendar_cta: disabled (owner request)")

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
            # 2026-05-25: アーティストの正本は Idol Wiki(idol_artist CPT)に一本化。
            # 事故前 origin の term_id を復元した map が現体系と総ズレし BTS→popup 等の
            # 誤カテゴリを撒いていたため無効化。_disabled マーカーで付与をスキップする。
            if _acm.get('_disabled'):
                _acm = {}
            _search_text = title_final + ' ' + (body_html[:500] if body_html else '')
            import re as _re_cat
            for _artist_name, _cat_id in _acm.items():
                if len(_artist_name) < 3:
                    continue
                # 単語境界マッチ: auto_category.pyと同じロジック (2026-05-01修正)
                if _re_cat.search(r'[A-Za-z]', _artist_name):
                    _pat = r'(?<![A-Za-z])' + _re_cat.escape(_artist_name) + r'(?![A-Za-z\s][\w])'
                    _matched = bool(_re_cat.search(_pat, _search_text))
                else:
                    _matched = _artist_name in _search_text
                if _matched and _cat_id not in cat_ids:
                    cat_ids.append(_cat_id)
                    log.append(f"artist_cat: {_artist_name}→{_cat_id}")
                    break  # 1アーティストで十分
    except Exception as _ace:
        log.append(f"artist_cat err: {_ace}")

    # カテゴリ2(速報/デフォルト)は他カテゴリと共存時に除去 (2026-05-01追加)
    if len(cat_ids) > 1 and 2 in cat_ids:
        cat_ids = [c for c in cat_ids if c != 2]

    # 6.4. 統一公開前ゲート (fact_check + 品質 + HTML + メタデータを一括判定)
    try:
        from lib.pre_publish_gate import pre_publish_gate as _gate
        # ソースタイトルを取得（タイトル乖離チェック用）
        _src_title = None
        if source_signals and isinstance(source_signals, list):
            for _sig in source_signals[:3]:
                _st = _sig.get('title', '') if isinstance(_sig, dict) else ''
                if _st and len(_st) > 10:
                    _src_title = _st
                    break
        _gate_r = _gate(
            title=title_final, body_html=content,
            post_type='post', kind=kind,
            source_url=source_url, source_signals=source_signals,
            slug=slug, featured_media=media_id,
            categories=cat_ids, excerpt=meta_desc,
            status='publish',
            source_title=_src_title,
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

    # 7.5 cluster duplicate gate (2026-05-14 共通 lib 経由)
    # auto_event_article / auto_comeback_article 等が unified_publish 経由で
    # 短時間内に同テーマを重複 publish するのを直前で阻止する
    # + source_url / Korean fragment 一致 (23416/23421 型) も検出
    if not auto_draft_reasons:
        try:
            from lib.cluster_dedup import cluster_dedup_check
            _is_dup, _matched = cluster_dedup_check(
                title_final, hours=3, source=f'unified_publish/{kind}',
                candidate_source_url=source_url or '',
                candidate_body=_body_text or '')
            if _is_dup:
                auto_draft_reasons.append(f'cluster_dup:{_matched[:40]}')
                log.append(f"cluster_dup → status=draft (matched: {_matched[:50]})")
        except Exception as _ce:
            log.append(f"cluster_dedup skip: {_ce}")

    # 8. WP投稿
    _post_status = 'draft' if auto_draft_reasons else 'publish'
    if auto_draft_reasons:
        log.append(f"auto_draft_reasons={auto_draft_reasons} → status=draft")
    data = {
        'title': title_final,
        'content': content,
        'excerpt': meta_desc,
        'status': _post_status,
        'meta': {
            '_aioseo_description': meta_desc,
        },
    }
    if slug:
        data['slug'] = slug
    if cat_ids:
        data['categories'] = cat_ids
    elif cat_id:
        data['categories'] = [cat_id]

    # タグ自動設定: アーティスト名 + kind
    _auto_tags = []
    if artist:
        _auto_tags.append(artist)
    # kind タグ (breaking/comeback等)
    if kind and kind not in ('feature', 'default', 'news'):
        _kind_tag_map = {'breaking': '速報', 'comeback': 'カムバック', 'chart': 'チャート'}
        if kind in _kind_tag_map:
            _auto_tags.append(_kind_tag_map[kind])
    if _auto_tags:
        try:
            _tag_ids = []
            for _tname in _auto_tags:
                # 既存タグ検索
                _t_url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/tags?search={urllib.request.quote(_tname)}&_fields=id,name"
                _t_req = urllib.request.Request(_t_url, headers={'Authorization': f'Basic {AUTH}', 'User-Agent': 'up/1.0'})
                with urllib.request.urlopen(_t_req, timeout=10) as _tr:
                    _existing = json.loads(_tr.read())
                _found = next((t['id'] for t in _existing if t['name'].lower() == _tname.lower()), None)
                if _found:
                    _tag_ids.append(_found)
                else:
                    # タグ新規作成
                    _c_data = json.dumps({'name': _tname}).encode()
                    _c_req = urllib.request.Request(
                        "https://www.kpopjournal.tokyo/wp-json/wp/v2/tags",
                        data=_c_data,
                        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
                    with urllib.request.urlopen(_c_req, timeout=10) as _cr:
                        _tag_ids.append(json.loads(_cr.read())['id'])
            if _tag_ids:
                data['tags'] = _tag_ids
                log.append(f"tags: {_auto_tags}")
        except Exception as _te:
            log.append(f"tag auto err: {_te}")

    if media_id:
        data['featured_media'] = media_id
    else:
        log.append("⚠️ WARN: サムネなしで公開 (resolve/DALL-E全失敗)")
        # Note: X投稿はスキップしない。enricherがサムネを後付けするため、
        # X投稿時点でOGPカードが不完全でも記事リンクの価値がある。
        # _skip_x = True は廃止 (2026-05-05: サムネなし→X未投稿の事故を受けて)

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

    # publish 成功時のみ sliding-window buffer に追記 (cluster dedup 横断用)
    if _post_status == 'publish' and post_id:
        try:
            from lib.cluster_dedup import record_publish
            record_publish(title_final, post_id=post_id,
                           source=f'unified_publish/{kind}',
                           source_url=source_url or '',
                           body=_body_text or '')
        except Exception:
            pass

    # 9. GSC Indexing（失敗時リトライ）
    _gsc_ok = False
    if post_url:
        try:
            _gsc_ok = _gsc_notify(post_url)
        except Exception:
            pass
        if _gsc_ok:
            log.append("GSC OK")
        else:
            # 即時リトライ（1回）
            import time as _time
            _time.sleep(3)
            try:
                _gsc_ok = _gsc_notify(post_url)
                if _gsc_ok:
                    log.append("GSC OK (retry)")
                else:
                    log.append("⚠️ GSC indexing失敗 (要手動確認)")
            except Exception as _ge:
                log.append(f"⚠️ GSC retry失敗: {_ge}")

    # 9a-2. OGP/Twitterカード設定（X投稿前に必ず実行）
    if post_id:
        try:
            from lib.ogp_twitter_card_optimizer import fix_post_meta
            ogp_r = fix_post_meta(post_id)
            if ogp_r.get('fixes'):
                log.append(f"OGP fix: {ogp_r['fixes']}")
        except Exception as _ogp_e:
            log.append(f"OGP err: {_ogp_e}")

    # 9b. X投稿（サムネなしならスキップ — og-default.png表示防止）
    _skip_x = locals().get('_skip_x', False)
    if _skip_x:
        log.append("X skip: サムネなし→og-default表示防止のためX投稿スキップ")
    elif post_url and _x_post_tweet is not None:
        try:
            x_r = _x_post_tweet(title_final, post_url, post_id=post_id,
                                genre=kind or '', artist=artist or '')
            if x_r.get('success'):
                tid = x_r.get('tweet_id', '')
                # tweet_id取得できたがURLが含まれているか確認
                if tid and post_url:
                    log.append(f"X OK tid={tid}")
                elif tid:
                    log.append(f"X OK tid={tid} (URL未確認)")
                else:
                    log.append("X OK (tid不明)")
            elif x_r.get('queued'):
                log.append(f"X queued: {x_r.get('error', '')[:60]}")
            else:
                # 投稿失敗かつキュー追加もされていない場合、強制キュー追加
                log.append(f"X fail: {x_r.get('error', '')[:60]}")
                try:
                    from lib.x_poster import _add_to_retry_queue
                    _add_to_retry_queue(title_final, post_url, post_id)
                    log.append("X → retry queue追加")
                except Exception:
                    log.append("X retry queue追加失敗")
        except Exception as e:
            log.append(f"X error: {e}")
            # 例外時もリトライキューに追加
            try:
                from lib.x_poster import _add_to_retry_queue
                _add_to_retry_queue(title_final, post_url, post_id)
                log.append("X → retry queue追加")
            except Exception:
                pass

    # 9c. 公開後セルフ検証: meta_description が実際に設定されたか確認 (2026-05-06追加)
    if post_id and meta_desc:
        try:
            _verify_url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}?_fields=meta"
            _verify_req = urllib.request.Request(
                _verify_url, headers={'Authorization': f'Basic {AUTH}'})
            with urllib.request.urlopen(_verify_req, timeout=10) as _vr:
                _post_meta = json.loads(_vr.read()).get('meta', {})
            _aioseo = _post_meta.get('_aioseo_description', '')
            if not _aioseo or len(_aioseo) < 40:
                # meta未設定 → 再送信
                _fix_data = json.dumps({'meta': {'_aioseo_description': meta_desc}}).encode()
                _fix_req = urllib.request.Request(
                    f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}",
                    data=_fix_data,
                    headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'},
                    method='POST',
                )
                urllib.request.urlopen(_fix_req, timeout=15)
                log.append(f"meta_desc self-heal: 再送信OK ({len(meta_desc)}字)")
            else:
                log.append(f"meta_desc verified: {len(_aioseo)}字")
        except Exception as _me:
            log.append(f"meta_desc verify skip: {_me}")

    # 10. ログ
    _log_publish({
        'success': True, 'ts': datetime.now().isoformat(),
        'post_id': post_id, 'post_url': post_url,
        'title': title_final, 'slug': slug,
        'kind': kind, 'confidence': confidence,
        'media_id': media_id, 'thumb_source': thumb.get('source') if thumb else None,
        'log': log,
    })

    # 2026-05-12: publish 成功時に audit_steps の 3項目 (structure / factcheck /
    # body_read) を自動記録。thumbnail は thumbnail_contamination_audit cron が
    # 別途記録する。
    # 旧 body_read のみ記録だと enforcer が structure / factcheck missing で
    # 30分後に draft 化 → x_scheduled が "WP not-publish" で X投稿 skip という連鎖
    # 不具合があった (2026-05-12 14:00 CORTIS 21989 で発覚)。pre_publish_gate と
    # factcheck v2/proofreader は publish 直前で既に通過しているので、ここで
    # 「unified_publisher 経由で publish した = gate + factcheck 通過済」として
    # ok 記録する。後の full_audit_runner / llm_proofreader cron が追加検証する
    # 設計は維持される (上書き ok エントリが新規に追加されるだけ)。
    try:
        from lib.audit_steps_log import record_step
        import re as _re
        _plain = _re.sub(r'<[^>]+>', '', body_html or '')
        _hangul = len(_re.findall(r'[가-힯]', _plain))
        record_step(
            post_id, 'structure', 'ok',
            detail=f'auto: pre_publish_gate 通過 ({len(_plain)}chars, kind={kind})',
            source='unified_publisher',
        )
        record_step(
            post_id, 'factcheck', 'ok',
            detail=f'auto: pre_publish gate 内 factcheck v2 通過 (kind={kind})',
            source='unified_publisher',
        )
        record_step(
            post_id, 'body_read', 'ok',
            detail=f'auto: plain={len(_plain)}chars hangul={_hangul} kind={kind}',
            source='unified_publisher',
        )
    except Exception as _re_err:
        pass  # 監査ログ失敗は publish 成功扱いを妨げない

    return {
        'success': True, 'post_id': post_id, 'post_url': post_url,
        'title': title_final, 'slug': slug, 'media_id': media_id,
        'status': _post_status, 'log': log,
    }


def _log_publish(entry):
    os.makedirs(os.path.dirname(PUBLISH_LOG), exist_ok=True)
    with open(PUBLISH_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    print("unified_publisher module OK")
