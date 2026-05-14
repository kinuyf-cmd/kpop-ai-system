#!/usr/bin/env python3
"""SIMPLE PUBLISH PIPELINE (2026-05-11) — source URL → 翻訳 → og:image → WP公開 を1関数で完結する canonical 実装。複雑な generator 13本を deprecate していくための原器。
Usage: r = simple_publish_from_source('https://www.koreaboo.com/news/sample/')  # → {'post_id', 'media_id', 'link'}
事前: .env に OPENAI_API_KEY/WP_USER/WP_PASS / lib.korean_translator.translate_ko_to_ja / lib.thumbnail_source_resolver.resolve_source_og_image"""
import os, sys, json, re, urllib.request, base64, tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).resolve().parent.parent / '.env'))

WP_BASE = 'https://www.kpopjournal.tokyo'
WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f'{WP_USER}:{WP_PASS}'.encode()).decode()
LOG_PATH = '/home/aiuser/kpop-ai-system/logs/simple_publish.jsonl'


# ── K-POP 関連性チェック (lib.kpop_relevance に extract、2026-05-14) ─
from lib.kpop_relevance import is_kpop_relevant  # noqa: E402


# ── 1. Source 取得 ──────────────────────────────────────────────
def fetch_source(url: str) -> dict:
    """sourceから title/body/og_image_url を抽出"""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 KPJ-SimplePub/1'})
    with urllib.request.urlopen(req, timeout=20) as r:
        html = r.read().decode('utf-8', errors='replace')

    def og(prop):
        m = re.search(rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)', html, re.I)
        return m.group(1) if m else ''

    title = og('og:title') or _extract_h1(html)
    desc = og('og:description')
    image = og('og:image') or og('twitter:image')
    body_text = _extract_article_body(html)
    return {'title': title.strip(), 'desc': desc.strip(), 'image_url': image, 'body': body_text, 'html': html}


def _extract_h1(html):
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.S | re.I); return re.sub(r'<[^>]+>', '', m.group(1)).strip() if m else ''


def _extract_article_body(html):
    """記事本文を抽出 (article/main/entry-content 等のクラスから)"""
    for pat in (r'<article[^>]*>(.*?)</article>',
                r'<main[^>]*>(.*?)</main>',
                r'<div[^>]+class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>\s*<(?:footer|aside)',
                r'<div[^>]+class="[^"]*post-content[^"]*"[^>]*>(.*?)</div>\s*<(?:footer|aside)'):
        m = re.search(pat, html, re.S | re.I)
        if m:
            text = re.sub(r'<script[^>]*>.*?</script>', '', m.group(1), flags=re.S)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.S)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 200:
                return text
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.S)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.S)
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()[:5000]


# ── 2. 翻訳 ──────────────────────────────────────────────────────
def translate(text: str, context: str = 'K-POP entertainment news') -> str:
    """既存 korean_translator を使って ko/en → ja"""
    from lib.korean_translator import translate_ko_to_ja
    r = translate_ko_to_ja(text, context=context)
    return r.get('translated', text) if r.get('success') else text


# ── 3. og:image 取得+検証 ────────────────────────────────────────
def fetch_og_image(image_url: str) -> str:
    """og:imageをダウンロードして 1200x675 にcrop。portrait/極小はBLOCK"""
    if not image_url:
        return ''
    if image_url.startswith('//'):
        image_url = 'https:' + image_url
    tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
    tmp.close()
    try:
        req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as r:
            with open(tmp.name, 'wb') as f:
                f.write(r.read())
    except Exception as e:
        print(f'  og:image fetch err: {e}')
        return ''
    # 検証
    from PIL import Image
    try:
        with Image.open(tmp.name) as im:
            w, h = im.size
            if h > w:
                print(f'  og:image rejected: portrait {w}x{h}')
                return ''
            if w < 600:
                print(f'  og:image rejected: too small {w}x{h}')
                return ''
            # 1200x675 (16:9) にcrop
            target_ratio = 1200 / 675
            cur_ratio = w / h
            if cur_ratio > target_ratio:
                new_w = int(h * target_ratio)
                x = (w - new_w) // 2
                im2 = im.crop((x, 0, x + new_w, h))
            elif cur_ratio < target_ratio:
                new_h = int(w / target_ratio)
                y = (h - new_h) // 2
                im2 = im.crop((0, y, w, y + new_h))
            else:
                im2 = im.copy()
            im2 = im2.convert('RGB').resize((1200, 675), Image.LANCZOS)
            im2.save(tmp.name, 'JPEG', quality=92)
            return tmp.name
    except Exception as e:
        print(f'  og:image validate err: {e}')
        return ''


# ── 4. WP公開 ────────────────────────────────────────────────────
def upload_media(image_path: str, alt_text: str, filename: str = '') -> int:
    if not image_path or not os.path.exists(image_path):
        return 0
    with open(image_path, 'rb') as f:
        body = f.read()
    fn = filename or f'simple_pub_{int(datetime.now().timestamp())}.jpg'
    req = urllib.request.Request(
        f'{WP_BASE}/wp-json/wp/v2/media', data=body,
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'image/jpeg',
                 'Content-Disposition': f'attachment; filename="{fn}"'},
        method='POST'
    )
    res = json.load(urllib.request.urlopen(req, timeout=60))
    mid = res.get('id', 0)
    if mid and alt_text:
        urllib.request.urlopen(urllib.request.Request(
            f'{WP_BASE}/wp-json/wp/v2/media/{mid}',
            data=json.dumps({'alt_text': alt_text}).encode(),
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'},
            method='POST'
        ), timeout=30).read()
    return mid


SPEED_NEWS_CAT = 2  # WP cat 2 = 速報記事 (daily_editor の breaking 計測対象)
BREAKING_LOG = '/home/aiuser/kpop-ai-system/logs/breaking_articles.jsonl'


def publish_post(title: str, body_html: str, slug: str, media_id: int,
                 source_url: str, status: str = 'publish') -> dict:
    payload = {
        'title': title, 'content': body_html, 'slug': slug,
        'status': status, 'featured_media': media_id,
        'categories': [SPEED_NEWS_CAT],   # 2026-05-11: KPI 計測 + 速報カテゴリ表示
        'excerpt': body_html[:140].replace('<', ''),
        'meta': {'_aioseo_description': body_html[:140].replace('<', '')},
    }
    req = urllib.request.Request(
        f'{WP_BASE}/wp-json/wp/v2/posts', data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'},
        method='POST'
    )
    return json.load(urllib.request.urlopen(req, timeout=60))


def _log_breaking(post_id: int):
    """daily_editor の breaking 計測対象として logs/breaking_articles.jsonl に追加。
    publish=success かつ status=publish の simple_publish 由来記事を全て記録する。"""
    record = {'date': datetime.now().date().isoformat(), 'post_id': post_id,
              'source': 'simple_publish', 'ts': datetime.now(timezone.utc).isoformat()}
    os.makedirs(os.path.dirname(BREAKING_LOG), exist_ok=True)
    with open(BREAKING_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


# ── 5. メイン ────────────────────────────────────────────────────
def simple_publish_from_source(source_url: str, slug: str = '',
                                status: str = 'draft') -> dict:
    """1関数で完結: source → translate → og:image → publish

    デフォルト status='draft' で人手レビュー前提。'publish' は明示時のみ。
    """
    import html as _html
    print(f'\n=== simple_publish: {source_url[:80]} ===')
    src = fetch_source(source_url)
    if not src['title'] or len(src['body']) < 200:
        return {'success': False, 'reason': f'source薄い: title={bool(src["title"])} body={len(src["body"])}'}

    # html.unescape source text (RSS等の数値entity混入対策)
    src_title = _html.unescape(src['title'])

    # K-POP 関連性チェック (2026-05-11): og:title に K-POP artist 名が無ければ
    # off-topic とみなし publish しない。post 21729 のようなドラマ記事を防ぐ
    if not is_kpop_relevant(src_title):
        print(f'  off-topic skip: {src_title[:80]}')
        return {'success': False, 'reason': f'non-kpop content: {src_title[:60]}'}
    src_body = _html.unescape(src['body'])
    title_ja = _html.unescape(translate(src_title, context='K-POP entertainment news title'))
    body_excerpt = src_body[:2500]  # 翻訳context上限
    body_ja = _html.unescape(translate(body_excerpt))

    body_html = (
        f'<p>{body_ja}</p>\n'
        f'<h2>情報ソース</h2>\n'
        f'<ul><li><a rel="noopener" href="{source_url}" target="_blank">DIRECT_SOURCE</a>: 記事を見る</li></ul>\n'
        f'<p><em>※ 最新情報は各公式発表をご確認ください。</em></p>\n'
    )

    img_path = fetch_og_image(src['image_url'])
    media_id = 0
    if img_path:
        media_id = upload_media(img_path, alt_text=title_ja[:100], filename=f'simple_{slug or "post"}.jpg')

    if not slug:
        from lib.slug_generator import generate_slug
        slug = generate_slug(title_ja)

    if not media_id and status == 'publish':
        # サムネ取得失敗時: status = 'draft' は draft_auto_publisher の pre_publish_gate BLOCK → 3回で
        # auto-archive により失われるため、private (admin 可視/frontend 非公開) を採用する。
        print('  サムネ取得失敗 → status=private で保留 (draft_auto_publisher対象外)')
        status = 'private'

    # cluster duplicate gate (2026-05-14)
    # 23000/23006/23144 (KATSEYE) 等 短時間内の同テーマ重複 publish を直前で阻止
    if status == 'publish':
        from lib.cluster_dedup import cluster_dedup_check
        is_dup, matched = cluster_dedup_check(
            title_ja, hours=3, source='simple_publish_pipeline')
        if is_dup:
            print(f'  cluster_dup → status=draft (matched: {matched[:50]})')
            status = 'draft'

    res = publish_post(title_ja, body_html, slug, media_id, source_url, status=status)
    # KPI 計測のため breaking_articles.jsonl に追記 (status=publish のみ)
    if res.get('status') == 'publish' and res.get('id'):
        _log_breaking(int(res['id']))
        # WP indexing lag 吸収用 sliding-window buffer に title を記録
        try:
            from lib.cluster_dedup import record_publish
            record_publish(title_ja, post_id=int(res['id']),
                           source='simple_publish_pipeline')
        except Exception:
            pass
    record = {
        'ts': datetime.now(timezone.utc).isoformat(),
        'source_url': source_url, 'post_id': res.get('id'), 'media_id': media_id,
        'status': res.get('status'), 'link': res.get('link'),
        'title_ja': title_ja[:80], 'body_len': len(body_ja),
    }
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(f'  → post_id={res.get("id")} media={media_id} status={res.get("status")}')
    return record


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python3 lib/simple_publish_pipeline.py <source_url> [slug]')
        sys.exit(1)
    url = sys.argv[1]
    slug = sys.argv[2] if len(sys.argv) > 2 else ''
    print(json.dumps(simple_publish_from_source(url, slug=slug), ensure_ascii=False, indent=2))
