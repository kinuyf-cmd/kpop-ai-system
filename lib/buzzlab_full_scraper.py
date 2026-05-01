#!/usr/bin/env python3
"""BUZZLAB全文+画像スクレイパー (オーナー許可済み, A+Fモード)
BUZZLABはSWELLテーマのカスタム投稿タイプ(popup_event)を使用。
構造: sp-info-block(基本情報) / sp-desc-section(詳細) / sp-reserve-box(予約・特典) / sp-image-wrap(画像)
"""
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

HEADERS = {'User-Agent': 'KPOPJournal/1.0 (+https://www.kpopjournal.tokyo)'}
BUZZLAB_BASE = 'https://kbuzzlab.com'
JST = timezone(timedelta(hours=9))


def _fetch(url):
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        return urllib.request.urlopen(req, timeout=20).read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"  fetch err ({url[:60]}): {e}")
        return ''


def scrape_buzzlab_article(url):
    """BUZZLAB popup_event記事を構造化データ+画像で取得"""
    html = _fetch(url)
    if not html:
        return None

    # mainタグ内を取得
    m = re.search(r'<main[^>]*>(.*?)</main>', html, re.DOTALL)
    if not m:
        return None
    main_html = m.group(1)

    # --- タイトル ---
    title = ''
    h1 = re.search(r'<h1[^>]*>(.*?)</h1>', main_html, re.DOTALL)
    if h1:
        title = re.sub(r'<[^>]+>', '', h1.group(1)).strip()
    if not title:
        og = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)', html)
        if og:
            title = og.group(1)

    if not title:
        return None

    # --- OG画像 ---
    images = []
    og_img = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)', html)
    if og_img:
        images.append(og_img.group(1))

    # メイン画像 (sp-image-wrap)
    img_wrap = re.search(r'<div class="sp-image-wrap">(.*?)</div>', main_html, re.DOTALL)
    if img_wrap:
        src = re.search(r'src=["\']([^"\']+)', img_wrap.group(1))
        if src:
            abs_url = urljoin(url, src.group(1))
            if abs_url not in images:
                images.append(abs_url)

    # --- 基本情報 (sp-info-block) ---
    # sp-info-value に itemprop 等の属性がつくケースがあるため [^>]* で許容
    info = {}
    for bm in re.finditer(
        r'<div class="sp-info-label">(.*?)</div>\s*<div class="sp-info-value"[^>]*>(.*?)</div>',
        main_html, re.DOTALL
    ):
        label = re.sub(r'<[^>]+>', '', bm.group(1)).strip()
        value = re.sub(r'<[^>]+>', ' ', bm.group(2)).strip()
        info[label] = value

    # --- イベント詳細 (sp-desc-section) ---
    description_html = ''
    desc = re.search(
        r'<div class="sp-desc-section"[^>]*>(.*?)</div>\s*(?=<div class="sp-sns|<div class="sp-reserve|<div class="sp-map|$)',
        main_html, re.DOTALL
    )
    if desc:
        # sp-info-label を除去して本文だけ取得
        inner = desc.group(1)
        inner = re.sub(r'<div class="sp-info-label">.*?</div>', '', inner, flags=re.DOTALL)
        description_html = inner.strip()

    # --- 予約・特典 (sp-reserve-box) ---
    reserves = []
    for rm in re.finditer(
        r'<div class="sp-reserve-title">(.*?)</div>\s*<div class="sp-reserve-body">(.*?)</div>',
        main_html, re.DOTALL
    ):
        rtitle = re.sub(r'<[^>]+>', '', rm.group(1)).strip()
        rbody = rm.group(2).strip()
        reserves.append({'title': rtitle, 'body': rbody})

    # --- 本文HTML組み立て ---
    body_parts = []

    # イベント詳細
    if description_html:
        body_parts.append(f'<h2>イベント詳細</h2>\n{description_html}')

    # 基本情報テーブル
    if info:
        rows = []
        for k, v in info.items():
            if k in ('イベント詳細', 'SNSチャンネル', 'マップ'):
                continue
            rows.append(f'<tr><th style="text-align:left;padding:8px;white-space:nowrap">{k}</th>'
                        f'<td style="padding:8px">{v}</td></tr>')
        if rows:
            body_parts.append(
                '<h2>開催情報</h2>\n'
                '<table style="width:100%;border-collapse:collapse;margin:16px 0">'
                + ''.join(rows) + '</table>'
            )

    # 予約・特典
    for r in reserves:
        body_parts.append(f'<h2>{r["title"]}</h2>\n{r["body"]}')

    body_html = '\n'.join(body_parts)

    # 本文内画像も収集
    for img_m in re.finditer(r'<img[^>]+(?:src|data-src)=["\']([^"\']+)', body_html):
        img_url = urljoin(url, img_m.group(1))
        if img_url not in images and 'kbuzzlab' in img_url:
            images.append(img_url)

    # 相対URL→絶対URL
    body_html = re.sub(
        r'(src|href)="(/[^"]+)"',
        lambda m: f'{m.group(1)}="{BUZZLAB_BASE}{m.group(2)}"',
        body_html,
    )

    # Markdownコードブロックマーカー除去 (```html等)
    body_html = re.sub(r'```\w*\s*\n?', '', body_html)
    body_html = re.sub(r'```\s*\n?', '', body_html)

    if len(re.sub(r'<[^>]+>', '', body_html)) < 50:
        return None

    # --- 日付抽出 ---
    start_date = ''
    end_date = ''
    period = info.get('開催期間', '')
    dm = re.search(r'(\d{4})年(\d{2})月(\d{2})日\s*[〜~\-]\s*(\d{4})年(\d{2})月(\d{2})日', period)
    if dm:
        start_date = f'{dm.group(1)}-{dm.group(2)}-{dm.group(3)}'
        end_date = f'{dm.group(4)}-{dm.group(5)}-{dm.group(6)}'

    return {
        'title': title,
        'url': url,
        'body_html': body_html,
        'images': images[:10],
        'info': info,
        'start_date': start_date,
        'end_date': end_date,
        'source': 'kbuzzlab_full',
        'scraped_at': datetime.now(JST).isoformat(),
    }


def fetch_buzzlab_latest_urls(limit=30):
    """BUZZLAB新着popup_event URLを取得"""
    urls = []
    for ep in ['/popup/', '/category/popup/', '/']:
        page_html = _fetch(BUZZLAB_BASE + ep)
        if not page_html:
            continue
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', page_html):
            href = m.group(1)
            abs_url = urljoin(BUZZLAB_BASE, href)
            if (BUZZLAB_BASE in abs_url
                    and abs_url not in urls
                    and '/category/' not in abs_url
                    and '/tag/' not in abs_url
                    and abs_url.rstrip('/') != BUZZLAB_BASE
                    and '/popup_event/' in abs_url):
                urls.append(abs_url)
                if len(urls) >= limit:
                    break
        if len(urls) >= limit:
            break
    return urls
