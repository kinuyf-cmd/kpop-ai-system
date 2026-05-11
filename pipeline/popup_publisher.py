#!/usr/bin/env python3
"""popup_signals.jsonl から記事生成 → WP popup post type に投稿
   改修: 8項目構造化 + サムネOG取得 + extra_meta"""
import sys, os, json, re, urllib.request, base64
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from lib.cta_injector import inject_cta_into_content
from lib.popup_keyword_filter import KEYWORDS_2026_MAY
load_dotenv()

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
SIGNALS = '/home/aiuser/kpop-ai-system/data/popup_signals.jsonl'
PROCESSED = '/home/aiuser/kpop-ai-system/data/popup_processed.jsonl'
JST = timezone(timedelta(hours=9))


def is_processed(url):
    if not os.path.exists(PROCESSED):
        return False
    with open(PROCESSED, encoding='utf-8') as f:
        for line in f:
            try:
                if json.loads(line).get('url') == url:
                    return True
            except:
                pass
    return False


def mark_processed(url, post_id, status):
    with open(PROCESSED, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'url': url, 'post_id': post_id, 'status': status,
            'ts': datetime.now(JST).isoformat()
        }, ensure_ascii=False) + '\n')


def fetch_full_content(url):
    """記事URLから全文取得"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', errors='ignore')
        for pat in [r'<article[^>]*>(.*?)</article>',
                    r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>',
                    r'<div[^>]*class="[^"]*post-content[^"]*"[^>]*>(.*?)</div>']:
            m = re.search(pat, html, re.DOTALL)
            if m:
                content = m.group(1)
                text = re.sub(r'<[^>]+>', ' ', content)
                text = re.sub(r'\s+', ' ', text).strip()
                if len(text) > 200:
                    return text[:3000]
        return None
    except Exception as e:
        print(f"  fetch err: {e}")
        return None


POPUP_HUB_CTA = (
    '<div class="kpj-popup-hub-cta" style="margin:30px 0 20px;padding:16px 20px;'
    'background:linear-gradient(135deg,#fff0f3,#f8f0ff);border-radius:12px;'
    'text-align:center;border:1px solid #ffd6e0;">'
    '<p style="margin:0;font-size:1.05em;font-weight:700;">'
    '<a href="https://www.kpopjournal.tokyo/popup/" '
    'style="color:#FF1B6B;text-decoration:none;">'
    '\u2728 開催中の全ポップアップ情報はこちら \u2728</a></p></div>'
)


def inject_popup_hub_cta(content):
    """ポップアップ一覧ページへの動線CTAを記事末尾（disclaimer直前）に挿入"""
    if 'kpj-popup-hub-cta' in content:
        return content
    # disclaimer直前に挿入
    disclaimer_pat = '<p class="kpj-disclaimer">'
    if disclaimer_pat in content:
        return content.replace(disclaimer_pat, POPUP_HUB_CTA + '\n' + disclaimer_pat, 1)
    # disclaimerがない場合は末尾に追加
    return content.rstrip() + '\n' + POPUP_HUB_CTA


def extract_dates(text):
    """期間抽出"""
    patterns = [
        r'(\d{4})年(\d{1,2})月(\d{1,2})日.*?[~〜から至まで\-].*?(\d{1,2})月(\d{1,2})日',
        r'(\d{1,2})月(\d{1,2})日.*?[~〜\-].*?(\d{1,2})月(\d{1,2})日',
        r'(\d{4})/(\d{1,2})/(\d{1,2}).*?[~〜\-].*?(\d{4})/(\d{1,2})/(\d{1,2})',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            now = datetime.now(JST)
            year = now.year
            try:
                groups = m.groups()
                if len(groups) == 5:
                    sy = int(groups[0])
                    sm, sd, em, ed = map(int, groups[1:])
                    start = datetime(sy, sm, sd, tzinfo=JST)
                    end = datetime(sy, em, ed, tzinfo=JST)
                elif len(groups) == 6:
                    sy, sm, sd, ey, em, ed = map(int, groups)
                    start = datetime(sy, sm, sd, tzinfo=JST)
                    end = datetime(ey, em, ed, tzinfo=JST)
                else:
                    sm, sd, em, ed = map(int, groups[:4])
                    start = datetime(year, sm, sd, tzinfo=JST)
                    end = datetime(year, em, ed, tzinfo=JST)
                return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')
            except:
                pass
    return None, None


def determine_status(start_date, end_date):
    """開催予定/開催中/終了 判定"""
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


# === サムネ取得 ===

def fetch_og_image(url):
    """記事URLからOG画像取得"""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8', errors='ignore')
        m = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html)
        if not m:
            m = re.search(r'<meta\s+content=["\']([^"\']+)["\']\s+property=["\']og:image["\']', html)
        if not m:
            m = re.search(r'<meta\s+property=["\']og:image["\'][^>]*\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if not m:
            m = re.search(r'<meta[^>]*\s+content=["\']([^"\']+)["\'][^>]*\s+property=["\']og:image["\']', html, re.IGNORECASE)
        if m:
            return m.group(1)
    except:
        pass
    return None


def upload_image_to_wp(image_url, title):
    """画像URLをDLしてWP media libraryにアップロード"""
    try:
        req = urllib.request.Request(image_url, headers={'User-Agent': 'Mozilla/5.0'})
        img_data = urllib.request.urlopen(req, timeout=30).read()

        if len(img_data) < 1000 or len(img_data) > 5_000_000:
            return None

        # 縦長サムネ REJECT (2026-05-11: pre_publish_gate で 28件 BLOCK 発生中)
        # OGP表示が壊れるためアップロード前に弾く
        try:
            from io import BytesIO
            from PIL import Image
            with Image.open(BytesIO(img_data)) as _im:
                _w, _h = _im.size
                if _h > _w:
                    print(f"  upload skip: 縦長画像 ({_w}x{_h}) — OGP壊れる")
                    return None
        except Exception:
            pass  # PIL なし or 解析失敗時はそのまま続行 (gate側で再判定される)

        ext = 'jpg'
        if '.png' in image_url.lower():
            ext = 'png'
        # ASCII-safeなファイル名 (日本語はlatin-1でエンコード不可)
        safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', re.sub(r'[^\x00-\x7F]', '', title[:30]))
        if not safe_title:
            safe_title = f"popup_{int(datetime.now(JST).timestamp())}"
        filename = f"popup_{safe_title}.{ext}"

        req2 = urllib.request.Request(
            "https://www.kpopjournal.tokyo/wp-json/wp/v2/media",
            data=img_data, method='POST',
            headers={
                'Authorization': f'Basic {AUTH}',
                'Content-Type': f'image/{ext}',
                'Content-Disposition': f'attachment; filename="{filename}"',
            })
        r = json.loads(urllib.request.urlopen(req2, timeout=60).read())
        return r.get('id')
    except Exception as e:
        print(f"  upload err: {e}")
        return None


def get_thumbnail(signal):
    """OG画像取得"""
    og = fetch_og_image(signal['url'])
    if og:
        media_id = upload_image_to_wp(og, signal.get('title', 'popup'))
        if media_id:
            print(f"  サムネ: OG画像 media_id={media_id}")
            return media_id
    return 0


# === 記事生成 ===

def generate_article_with_gpt(signal, full_text):
    """GPTで構造化記事生成 (8項目対応)"""
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        print("  OPENAI_API_KEY未設定")
        return None, {}

    city = signal.get('city', '不明')
    country = '日本' if city in ('tokyo', 'osaka', 'nagoya', 'fukuoka', 'yokohama',
                                  'sapporo', 'sendai', 'hiroshima', 'kyoto', 'kobe') else '韓国'
    city_label = {
        'tokyo': '東京', 'osaka': '大阪', 'nagoya': '名古屋', 'fukuoka': '福岡',
        'yokohama': '横浜', 'sapporo': '札幌', 'sendai': '仙台', 'hiroshima': '広島',
        'kyoto': '京都', 'kobe': '神戸',
        'seoul-gangnam': 'ソウル江南', 'seoul-seongsu': 'ソウル聖水',
        'seoul-hongdae': 'ソウル弘大', 'seoul-myeongdong': 'ソウル明洞',
    }.get(city, city)

    _now = datetime.now(JST)
    prompt = f"""現在: {_now.year}年{_now.month}月{_now.day}日。
本文に書く年号は{_now.year}年または{_now.year - 1}年のみ。
{_now.year - 2}年以前の年号 (例: 2023年) は元情報にあっても絶対に書かない。
日付不明の項目は「日時調整中」とし、「XX月」「XX日」のような placeholder を残さないこと。

以下のポップアップ情報から、K-POPファン向けのSEO最適化記事を生成してください。

【元情報】
タイトル: {signal['title']}
本文抜粋: {(full_text[:2000] if full_text else 'なし')}
開催地: {city_label} ({country})
情報源: {signal.get('source', '不明')}

【出力要件】
- HTMLで本文500-900字
- 必須h2セクション:
  <h2>イベント概要</h2> (何のポップアップか、見どころ)
  <h2>開催詳細</h2> (期間/営業時間/会場)
  <h2>特典・限定アイテム</h2> (グッズ/購入特典/フォトスポット)
  <h2>アクセス</h2> (最寄り駅/徒歩時間)
- 文末バリエーション: ~開催/~オープン/~登場/~実施
- 末尾に必ず:
  <p class="kpj-disclaimer">※情報は変更になる場合があります。最新情報は公式SNSをご確認ください。</p>

加えて、以下JSON形式で構造化メタを抽出し、本文末尾に <!--META--> ブロックで埋め込んでください:
<!--META
{{"hours": "営業時間", "address": "住所", "reservation": "予約要否", "perks": "特典概要", "sns": "SNS情報"}}
-->

【出力】HTML本文 + METAブロック (説明・前置き不要)。セクション識別子ラベル（リード文:, 導入文:, 本文:, セクション1: 等）は絶対に含めないこと"""

    from lib.agent_learning_loop import inject_lessons_to_prompt
    prompt = inject_lessons_to_prompt('popup_writer', prompt)

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.7,
        'max_tokens': 1800,
    }).encode()

    try:
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
            data=body, headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=90).read())
        content = r['choices'][0]['message']['content'].strip()

        # METAブロック抽出
        meta_match = re.search(r'<!--META\s*(\{.*?\})\s*-->', content, re.DOTALL)
        extra_meta = {}
        if meta_match:
            try:
                extra_meta = json.loads(meta_match.group(1))
            except:
                pass
            content = re.sub(r'<!--META.*?-->', '', content, flags=re.DOTALL).strip()

        return content, extra_meta
    except Exception as e:
        print(f"  GPT err: {e}")
        return None, {}


def _clean_prtimes_title(title):
    """PR TIMESタイトルから日時・プレスリリースID等のゴミを除去"""
    # 末尾の「2026年4月15日 10時49分」「6分前」等
    title = re.sub(r'\d{4}年\d{1,2}月\d{1,2}日\s*\d{1,2}時\d{1,2}分.*$', '', title).strip()
    title = re.sub(r'\d+分前$', '', title).strip()
    title = re.sub(r'\d+時間前$', '', title).strip()
    # 末尾の「…」で切れている場合はそのまま
    return title


def post_to_wp_popup(signal, content, status, extra_meta=None, featured_media=0):
    """WP popup post type に投稿 (拡張meta対応)"""
    from lib.text_sanitizer import strip_template_labels, sanitize_gpt_html
    from lib.title_optimizer import generate_slug, validate_slug
    title = _clean_prtimes_title(strip_template_labels(signal.get('title', '')))
    # ハングル残存対策 (2026-05-11): kbuzzlab等の韓国ソースは原題が韓国語のまま流入する。
    # pre_publish_gate の translation_residue で BLOCK されるため、ここで日本語化する。
    if re.search(r'[가-힯]', title):
        try:
            from lib.korean_translator import translate_ko_to_ja
            _r = translate_ko_to_ja(title, context='K-POP popup event title')
            if _r.get('success') and _r.get('translated'):
                _t2 = _r['translated'].strip().strip('「」"')
                if not re.search(r'[가-힯]', _t2):
                    print(f"  title翻訳: {title[:30]}... → {_t2[:30]}...")
                    title = _t2
        except Exception as _te:
            print(f"  title翻訳skip: {_te}")
    # 長すぎるタイトルは末尾を自然な区切りで切る (省略記号なし)
    if len(title) > 80:
        # 句読点・括弧・スペースで区切れる位置を探す
        for sep in ['。', '！', '、', '）', '」', ' ', '　']:
            idx = title.rfind(sep, 40, 80)
            if idx > 0:
                title = title[:idx + 1].rstrip()
                break
        else:
            title = title[:80]
    content = sanitize_gpt_html(strip_template_labels(content))

    # ASCIIスラッグ生成 (日本語エンコード防止 + 検証ゲート)
    slug = validate_slug(generate_slug(title))
    if not slug:
        slug = validate_slug(generate_slug(content[:200])) or f"popup-event-{int(datetime.now(JST).timestamp())}"

    meta = {
        '_popup_city': signal.get('city', ''),
        '_popup_official_url': signal.get('url', ''),
        '_popup_status': status,
    }
    if signal.get('start_date'):
        meta['_popup_start_date'] = signal['start_date']
    if signal.get('end_date'):
        meta['_popup_end_date'] = signal['end_date']

    if extra_meta:
        for key in ('hours', 'address', 'reservation', 'perks', 'sns'):
            val = extra_meta.get(key, '')
            if val:
                meta[f'_popup_{key}'] = val

    # 住所から緯度経度を自動取得
    if meta.get('_popup_address') and not meta.get('_popup_lat'):
        try:
            import urllib.parse as _up
            import time as _t
            city_prefix = {
                'tokyo': '東京都 ', 'osaka': '大阪府 ', 'nagoya': '名古屋市 ',
                'fukuoka': '福岡市 ', 'yokohama': '横浜市 ', 'sapporo': '札幌市 ',
                'sendai': '仙台市 ', 'hiroshima': '広島市 ', 'kyoto': '京都市 ',
                'kobe': '神戸市 ',
                'seoul-gangnam': '서울 강남 ', 'seoul-seongsu': '서울 성수 ',
                'seoul-hongdae': '서울 홍대 ', 'seoul-myeongdong': '서울 명동 ',
            }.get(signal.get('city', ''), '')
            addr = city_prefix + meta['_popup_address']
            geo_url = f"https://nominatim.openstreetmap.org/search?q={_up.quote(addr)}&format=json&limit=1"
            geo_req = urllib.request.Request(geo_url, headers={'User-Agent': 'KPOPJournal-Pub/1.0'})
            geo_data = json.loads(urllib.request.urlopen(geo_req, timeout=15).read())
            if geo_data:
                meta['_popup_lat'] = str(float(geo_data[0]['lat']))
                meta['_popup_lng'] = str(float(geo_data[0]['lon']))
                print(f"  geocode: ({geo_data[0]['lat']}, {geo_data[0]['lon']})")
            _t.sleep(1.2)
        except Exception as e:
            print(f"  geocode err: {e}")

    # 公開前ゲート
    try:
        from lib.pre_publish_gate import pre_publish_gate
        _gate = pre_publish_gate(
            title=title, body_html=content,
            post_type='popup', kind='popup',
            slug=slug, featured_media=featured_media,
            status='publish',
        )
        if _gate['verdict'] == 'BLOCK':
            print(f"  Gate BLOCK: {_gate['block_reasons']}")
            return None
        if _gate['verdict'] == 'WARN':
            print(f"  Gate WARN ({len(_gate['warn_reasons'])}件)")
    except Exception as e:
        print(f"  Gate skip: {e}")

    body_data = {
        'title': title,
        'content': content,
        'slug': slug,
        'status': 'publish',
        'meta': meta,
    }
    if featured_media:
        body_data['featured_media'] = featured_media

    body = json.dumps(body_data).encode()

    try:
        req = urllib.request.Request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup',
            data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        post_id = r.get('id')
        if not post_id:
            return None
        # slug が WP に反映されなかった場合は PATCH で上書き
        actual_slug = r.get('slug', '')
        if '%' in actual_slug or actual_slug != slug:
            try:
                patch_body = json.dumps({'slug': slug}).encode()
                patch_req = urllib.request.Request(
                    f'https://www.kpopjournal.tokyo/wp-json/wp/v2/popup/{post_id}',
                    data=patch_body, method='POST',
                    headers={'Authorization': f'Basic {AUTH}',
                             'Content-Type': 'application/json'})
                urllib.request.urlopen(patch_req, timeout=15)
                print(f"  slug patched: {slug}")
            except Exception as e:
                print(f"  slug patch err: {e}")
        return post_id
    except Exception as e:
        print(f"  WP err: {e}")
        return None


def main(max_articles=10):
    try:
        from lib.staff_task_manager import begin_task, end_task as _end_task
        _STF_ID, _TSK_ID = "KPJ-0040", begin_task("KPJ-0040", "popup_publisher")
    except: _STF_ID = _TSK_ID = None
    if not os.path.exists(SIGNALS):
        print("popup_signals.jsonl なし")
        return

    signals = []
    seen_urls = set()
    seen_titles = set()
    with open(SIGNALS, encoding='utf-8') as f:
        for line in f:
            try:
                s = json.loads(line)
                url = s['url']
                title_key = s.get('title', '').strip()[:40]  # タイトル先頭40字で重複判定
                if url not in seen_urls and title_key not in seen_titles and not is_processed(url):
                    seen_urls.add(url)
                    if title_key:
                        seen_titles.add(title_key)
                    signals.append(s)
            except:
                pass

    print(f"未処理signals: {len(signals)}件 (重複URL+タイトル除外済)")

    # K-POP/韓国関連度でソート (関連度低い記事は後回し)
    _RELEVANCE_KW = ['K-POP', 'KPOP', 'BTS', 'BLACKPINK', 'NewJeans', 'aespa', 'TWICE',
                     'SEVENTEEN', 'Stray Kids', 'IVE', 'LE SSERAFIM', 'ENHYPEN', 'ITZY',
                     'TXT', 'ATEEZ', 'NCT', 'RIIZE', '韓国', 'OLIVE YOUNG', 'BT21',
                     'LINE FRIENDS', 'ポップアップ', 'POP-UP', 'コスメ', 'ビューティー']
    def _relevance(s):
        return sum(1 for k in _RELEVANCE_KW if k.upper() in s.get('title', '').upper())
    signals.sort(key=_relevance, reverse=True)

    created = 0
    skipped_ended = 0
    skipped_irrelevant = 0
    for sig in signals[:max_articles * 2]:  # 候補を多めに見てフィルタ後max_articles件
        if created >= max_articles:
            break

        # K-POP関連度チェック (score=0はスキップ)
        if _relevance(sig) == 0:
            skipped_irrelevant += 1
            mark_processed(sig['url'], None, 'irrelevant')
            continue

        print(f"\n処理中: {sig['title'][:50]}")

        # シグナル品質ゲート (記事化前にURL存在確認)
        from lib.signal_validator import validate_signal
        vr = validate_signal(sig, check_url=True)
        if vr['reject']:
            print(f"  REJECT: {vr['reasons']}")
            mark_processed(sig['url'], None, f"signal_rejected: {'; '.join(vr['reasons'])}")
            continue
        if vr['warnings']:
            print(f"  WARN: {vr['warnings']}")

        full_text = fetch_full_content(sig['url'])

        start, end = extract_dates(f"{sig['title']} {full_text or ''}")
        if start:
            sig['start_date'] = start
        if end:
            sig['end_date'] = end
        status = determine_status(start, end)

        # 終了済みイベントはスキップ
        if status == 'ended':
            print(f"  スキップ: ended")
            skipped_ended += 1
            mark_processed(sig['url'], None, 'ended_skip')
            continue

        content, extra_meta = generate_article_with_gpt(sig, full_text)
        if content:
            try:
                content = inject_cta_into_content(sig.get('title', ''), content)
            except Exception as e:
                print(f"  CTA inject err: {e}")
            # 内部リンク自動挿入
            try:
                from lib.internal_links import insert_internal_links
                content = insert_internal_links(content, post_title=sig.get('title', ''))
            except Exception as e:
                print(f"  internal_links err: {e}")
            # ポップアップ一覧ページへの動線CTA
            content = inject_popup_hub_cta(content)
        if not content or len(content) < 200:
            print(f"  記事生成失敗、スキップ")
            mark_processed(sig['url'], None, 'gen_failed')
            continue

        featured_id = get_thumbnail(sig)

        # Pre-publish factcheck
        try:
            from lib.pre_publish_gate import pre_publish_gate
            gate_result = pre_publish_gate(
                sig.get('title', ''), content, post_type='popup', kind='popup',
                source_url=sig.get('url'), status=status,
            )
            if gate_result.get('verdict') == 'BLOCK':
                print(f"  [pre-publish] BLOCKED: {gate_result.get('block_reasons', [])}")
                status = 'draft'
            elif gate_result.get('verdict') == 'WARN':
                print(f"  [pre-publish] WARN: {gate_result.get('warnings', [])}")
        except Exception as e:
            print(f"  [pre-publish] gate error (continuing): {e}")

        post_id = post_to_wp_popup(sig, content, status,
                                   extra_meta=extra_meta, featured_media=featured_id)
        if post_id:
            print(f"  post_id={post_id} status={status} thumb={featured_id}")

            # OGP/Twitterカード設定（X投稿前に必ず実行）
            if featured_id:
                try:
                    from lib.ogp_twitter_card_optimizer import fix_post_meta
                    ogp_r = fix_post_meta(post_id)
                    if ogp_r.get('fixes'):
                        print(f"  OGP fix: {ogp_r['fixes']}")
                except Exception as e:
                    print(f"  OGP err: {e}")

            # 統一ポストパブリッシュフック
            try:
                from lib.post_publish_hook import run_post_publish
                run_post_publish(post_id, post_type='popup')
            except Exception as e:
                print(f"  post_publish_hook err: {e}")

            # GSC indexing + X投稿（正しいNext.jsルートURL）
            city = extra_meta.get('_popup_city', 'tokyo') if extra_meta else 'tokyo'
            popup_url = f'https://www.kpopjournal.tokyo/popup/{city}/{post_id}/'
            try:
                from lib.gsc_indexing import notify_url_updated
                if notify_url_updated(popup_url):
                    print(f"  GSC OK: {popup_url}")
                else:
                    print(f"  GSC FAIL: {popup_url}")
            except Exception as e:
                print(f"  GSC err: {e}")
            try:
                from lib.x_poster import post_tweet
                import time as _time
                title_text = sig.get('title', '')[:80]
                x_r = post_tweet(title_text, popup_url, post_id=post_id,
                                 genre='travel', artist='')
                if x_r.get('success'):
                    print(f"  X OK tid={x_r.get('tweet_id', '?')}")
                    _time.sleep(15)  # バースト防止: 15秒間隔で投稿
                elif x_r.get('queued'):
                    print(f"  X queued")
                else:
                    print(f"  X skip: {x_r.get('error', '')[:60]}")
            except Exception as e:
                print(f"  X err: {e}")

            mark_processed(sig['url'], post_id, 'published')
            created += 1
        else:
            mark_processed(sig['url'], None, 'wp_failed')

    print(f"\n公開: {created}件 (ended skip: {skipped_ended}, irrelevant skip: {skipped_irrelevant})")


try:
    if _TSK_ID and _STF_ID: _end_task(_STF_ID, _TSK_ID, "success")
except: pass

if __name__ == '__main__':
    main(max_articles=10)
