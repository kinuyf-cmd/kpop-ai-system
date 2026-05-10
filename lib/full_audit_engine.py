#!/usr/bin/env python3
"""
完全監査エンジン - 全post type共通の16項目チェック

A. メタデータ完全性 (4): title長/slug/featured_media/category
B. SEO要件 (4): meta_description/OGP/JSON-LD/canonical
C. 本文品質 (3): 本文長+日本語比率/誤字蛇足/HTMLタグ閉じ
D. 配信完全性 (3): GSC Indexing/X投稿/internal_links
E. 自動回復 (2): rewrite判定/quarantine判定
"""
import re, json, os, urllib.request, base64
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode() if WP_USER else ''

CRITERIA = {
    'post': {
        'title_max': 50, 'title_min': 10,
        'slug_min': 20, 'slug_max': 60,
        'content_min': 1500, 'jp_ratio_min': 0.30,
        'meta_desc_min': 80, 'meta_desc_max': 160,
        'require_x_post': True,
        'require_gsc_indexing': True,
        'require_og_image': True,
        'min_internal_links': 2,
    },
    'matome': {
        'title_max': 50, 'title_min': 10,
        'slug_min': 5, 'slug_max': 40,
        'content_min': 500, 'jp_ratio_min': 0.30,
        'meta_desc_min': 50, 'meta_desc_max': 160,
        'require_x_post': False,
        'require_gsc_indexing': True,
        'require_og_image': True,
        'min_internal_links': 1,
    },
    'popup': {
        'title_max': 60, 'title_min': 10,
        'slug_min': 10, 'slug_max': 60,
        'content_min': 500, 'jp_ratio_min': 0.30,
        'meta_desc_min': 80, 'meta_desc_max': 160,
        'require_x_post': True,
        'require_gsc_indexing': True,
        'require_og_image': True,
        'min_internal_links': 1,
    },
    'chart': {
        'title_max': 50, 'title_min': 10,
        'slug_min': 10, 'slug_max': 60,
        'content_min': 800, 'jp_ratio_min': 0.15,  # 韓国語曲名・アーティスト名が多いため緩和
        'meta_desc_min': 50, 'meta_desc_max': 160,
        'require_x_post': True,
        'require_gsc_indexing': True,
        'require_og_image': True,
        'min_internal_links': 1,
    },
}

# まとめページ自動判定: slug末尾が -matome のpost
def _detect_post_type(post, post_type):
    """slugパターンからpost_typeを細分化（matome/chart等）"""
    if post_type == 'post':
        slug = post.get('slug', '')
        if slug.endswith('-matome'):
            return 'matome'
        # チャート記事: slugに "chart" を含む or カテゴリ71(K-POPチャート)
        if 'chart' in slug or 71 in post.get('categories', []):
            return 'chart'
    return post_type

# LLM捏造検出: 架空の店名・施設名パターン（"Cafe A", "Shop B", "Venue C"等）
FABRICATION_PATTERNS = [
    # アルファベット1文字の仮名（Cafe A, Shop B, Hotel C, Venue D etc.）
    r'(?:Cafe|Shop|Hotel|Store|Restaurant|Venue|Gallery|Studio|Bar|Lounge)\s+[A-Z](?=[^a-zA-Z]|$)',
    # 日本語版: 「カフェA」「ショップB」等
    r'(?:カフェ|ショップ|ホテル|レストラン|会場|ギャラリー|スタジオ|バー|ラウンジ)\s*[A-Z](?=[^a-zA-Z]|$)',
    # 「某○○」「とある○○」（LLMの曖昧表現）
    r'(?:某|とある)(?:カフェ|ショップ|レストラン|店舗|施設)',
]

TYPO_PATTERNS = [
    (r'こんにちは[、。!]', 'casual_greeting', 'medium'),
    (r'いかが(?:でしょうか|でしたか|ですか)[、。!？]?', 'casual_question', 'medium'),
    (r'お楽しみに[!。]', 'salesy_ending', 'medium'),
    (r'ぜひお越しください', 'salesy_cta', 'medium'),
    (r'(.)\1{4,}', 'repeated_char', 'low'),
    (r'(?:です|ます)。\s*(?:です|ます)。', 'broken_sentence', 'high'),
    (r'<h2></h2>|<p></p>|<div></div>', 'empty_tag', 'high'),
    (r'```|^##\s', 'markdown_leak', 'high'),
    (r'(?<![A-Za-z])(?:AI|ChatGPT|GPT-[34]|Claude)(?![A-Za-z])', 'ai_mention', 'high'),
    (r'(?<![0-9倍割])以上です(?!。[^。]*[0-9])|以下のように|参考になれば|まとめると|この記事では|ご参考ください', 'meta_phrase', 'high'),
    (r'(?:皆さん|みなさん)、', 'casual_address', 'medium'),
    (r'~?(?:した|されました)。\s*~?(?:した|されました)。\s*~?(?:した|されました)。', 'monotonous_ending', 'medium'),
]


def _get_title(post):
    t = post.get('title', '')
    return t.get('rendered', '') if isinstance(t, dict) else t


def _get_content(post):
    c = post.get('content', '')
    return c.get('rendered', '') if isinstance(c, dict) else c


def _get_excerpt(post):
    e = post.get('excerpt', '')
    return e.get('rendered', '') if isinstance(e, dict) else e


# === Individual checks ===

def check_title(post, criteria):
    issues = []
    title = _get_title(post)
    if len(title) > criteria['title_max']:
        issues.append({'type': 'title_long', 'severity': 'low', 'value': len(title)})
    if len(title) < criteria['title_min']:
        issues.append({'type': 'title_short', 'severity': 'high', 'value': len(title)})
    return issues


def check_slug(post, criteria):
    issues = []
    slug = post.get('slug', '')
    if not slug:
        issues.append({'type': 'no_slug', 'severity': 'high'})
        return issues
    if '%' in slug:
        issues.append({'type': 'slug_encoded', 'severity': 'high'})
    if re.match(r'^post-\d+$', slug) or re.match(r'^popup-\d+$', slug):
        issues.append({'type': 'slug_auto_generated', 'severity': 'high'})
    if '__trashed' in slug:
        issues.append({'type': 'slug_trashed', 'severity': 'high'})
    if not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$', slug) and len(slug) > 2:
        # Allow slugs that are all ASCII alphanumeric + hyphens
        if re.search(r'[^a-z0-9-]', slug):
            issues.append({'type': 'slug_non_ascii', 'severity': 'medium'})
    if len(slug) < criteria['slug_min']:
        issues.append({'type': 'slug_short', 'severity': 'medium', 'value': len(slug)})
    if len(slug) > criteria['slug_max']:
        issues.append({'type': 'slug_long', 'severity': 'low', 'value': len(slug)})
    return issues


def check_featured_media(post):
    fm = post.get('featured_media', 0)
    if not fm or fm == 0:
        return [{'type': 'no_thumbnail', 'severity': 'high'}]
    return []


def check_category(post, post_type):
    issues = []
    if post_type == 'post':
        if not post.get('categories'):
            issues.append({'type': 'no_category', 'severity': 'high'})
    elif post_type == 'popup':
        if not post.get('meta', {}).get('_popup_city'):
            issues.append({'type': 'no_city', 'severity': 'high'})

    # アーティストカテゴリ漏れ検出 (教訓#43)
    if post_type == 'post':
        title = post.get('title', {}).get('rendered', '') if isinstance(post.get('title'), dict) else ''
        cats = post.get('categories', [])
        ARTIST_PARENT_ID = 26
        has_artist_cat = any(c != 2 and c != 1 for c in cats)  # 2=news, 1=uncategorized以外
        try:
            from lib.auto_category import detect_artist_categories
            detected = detect_artist_categories(title)
            if detected and not has_artist_cat:
                issues.append({'type': 'no_artist_category', 'severity': 'medium',
                              'value': f'detected={detected} current={cats}'})
        except:
            pass
    return issues


def check_meta_description(post, criteria):
    issues = []
    excerpt_plain = re.sub(r'<[^>]+>', '', _get_excerpt(post)).strip()
    # _aioseo_description も確認 (2026-05-06追加: excerptだけでは不十分)
    aioseo_desc = ''
    meta = post.get('meta', {})
    if isinstance(meta, dict):
        aioseo_desc = meta.get('_aioseo_description', '')
    elif isinstance(meta, list):
        # WP APIがmeta=[]で返す場合がある
        pass
    # excerpt と _aioseo_description の両方をチェック
    effective_desc = aioseo_desc or excerpt_plain
    if not effective_desc:
        issues.append({'type': 'no_meta_description', 'severity': 'high'})
    elif len(effective_desc) < criteria['meta_desc_min']:
        issues.append({'type': 'meta_desc_short', 'severity': 'medium', 'value': len(effective_desc)})
    elif len(effective_desc) > criteria['meta_desc_max']:
        issues.append({'type': 'meta_desc_long', 'severity': 'low', 'value': len(effective_desc)})
    # _aioseo_description が空なのにexcerptだけある場合 → SEO的に無効
    if excerpt_plain and not aioseo_desc and post.get('status') == 'publish':
        issues.append({'type': 'aioseo_desc_missing', 'severity': 'medium',
                       'detail': 'excerpt有だが_aioseo_descriptionが空。SEOメタ未設定'})
    return issues


def check_ogp(post, criteria):
    issues = []
    if criteria.get('require_og_image') and not post.get('featured_media'):
        issues.append({'type': 'no_og_image', 'severity': 'medium'})
    return issues


def check_content_quality(post, criteria):
    issues = []
    content = _get_content(post)
    plain = re.sub(r'<[^>]+>', '', content)

    if len(plain) < criteria['content_min']:
        issues.append({'type': 'content_short', 'severity': 'medium', 'value': len(plain)})

    jp_chars = len(re.findall(r'[\u3040-\u309F\u30A0-\u30FF\u4e00-\u9fff]', plain))
    if len(plain) > 0 and jp_chars / len(plain) < criteria['jp_ratio_min']:
        issues.append({'type': 'low_jp_ratio', 'severity': 'high', 'value': round(jp_chars / len(plain), 2)})

    for pattern, issue_type, severity in TYPO_PATTERNS:
        m = re.search(pattern, plain)
        if m:
            issues.append({'type': f'text_{issue_type}', 'severity': severity, 'sample': m.group(0)[:30]})

    # LLM捏造検出: 架空名称パターン
    for fp in FABRICATION_PATTERNS:
        fm = re.search(fp, plain)
        if fm:
            issues.append({'type': 'fabricated_name', 'severity': 'high',
                           'value': fm.group(0)[:40]})

    open_h2 = len(re.findall(r'<h2[^>]*>', content))
    close_h2 = len(re.findall(r'</h2>', content))
    if open_h2 != close_h2:
        issues.append({'type': 'unclosed_h2', 'severity': 'high'})

    open_p = len(re.findall(r'<p[^>]*>', content))
    close_p = len(re.findall(r'</p>', content))
    # WPのwpautopが<p>を自動挿入するため、2個以下の差分は正常
    if abs(open_p - close_p) > 4:
        issues.append({'type': 'unclosed_p', 'severity': 'medium', 'value': abs(open_p - close_p)})
    elif abs(open_p - close_p) > 2:
        issues.append({'type': 'unclosed_p', 'severity': 'low', 'value': abs(open_p - close_p)})


    # 日付整合性チェック (4/27追加)
    import re as _re2
    years_in_content = [int(m) for m in _re2.findall(r'(20[12]\d)年', plain)]
    if years_in_content:
        from datetime import datetime as _dt
        pub_year = _dt.now().year
        max_year = max(years_in_content)
        has_current_year = any(y >= pub_year - 1 for y in years_in_content)
        # 記事内に現在年付近の記述がなく、古い年のみの場合はhigh
        if max_year < pub_year - 1 and not has_current_year:
            issues.append({'type': 'stale_content_date', 'severity': 'high',
                          'value': f'content_year={max_year} pub_year={pub_year}'})

    return issues


def check_internal_links(post, criteria):
    content = _get_content(post)
    internal = len(re.findall(r'href="https?://(?:www\.)?kpopjournal\.tokyo[^"]*"', content))
    if internal < criteria['min_internal_links']:
        return [{'type': 'few_internal_links', 'severity': 'medium', 'value': internal}]
    return []


def check_ogp_image_relevance(post):
    """サムネ画像が記事のアーティストと一致しているか検証

    検証方法:
    1. classifierでタイトルからアーティスト(subjects)を抽出
    2. サムネのファイル名からアーティスト名を抽出
    3. subjectsのアーティストがファイル名に含まれているか照合
    4. アイドル記事なのにDALL-E画像 or 別アーティスト画像なら検出

    2026-05-02教訓: ファイル名にアーティスト名が含まれないv6_artist_*.jpgパターンでは
    検出できないため、WP API経由でmediaのsource_urlからファイル名を取得する。
    """
    issues = []
    fm = post.get('featured_media', 0)
    if not fm:
        return issues

    title = _get_title(post)

    # classifierでタイトルのアーティストを取得
    try:
        import sys
        if '/home/aiuser/kpop-ai-system' not in sys.path:
            sys.path.insert(0, '/home/aiuser/kpop-ai-system')
        from lib.article_topic_classifier import classify
        c = classify(title)
        subjects = c.get('subjects', [])
        primary_artist = subjects[0] if subjects else ''
    except Exception:
        return issues  # classifierが使えなければスキップ

    if not primary_artist:
        return issues  # 汎用記事はチェック不要

    # WP APIでサムネのsource_urlを取得
    try:
        url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{fm}?_fields=source_url"
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {AUTH}"})
        media = json.loads(urllib.request.urlopen(req, timeout=10).read())
        source_url = media.get('source_url', '')
        fname = os.path.basename(source_url).lower()
    except Exception:
        return issues

    # ファイル名からアーティスト名を抽出
    artist_slug = re.sub(r'[^a-z0-9]+', '_', primary_artist.lower()).strip('_')

    # DALL-Eファイル名チェック (dalle, v6_dalle)
    is_dalle = 'dalle' in fname and artist_slug not in fname

    # アーティスト写真ファイル名チェック (yt_bts_, wiki_aespa_, etc.)
    has_artist_in_fname = artist_slug in fname

    # アイドル記事 + DALL-E画像 = 不一致
    if is_dalle:
        issues.append({
            'type': 'idol_article_dalle_thumbnail',
            'severity': 'high',
            'detail': f'アイドル記事(artist={primary_artist})にDALL-E画像: {fname[:50]}',
        })

    # アーティスト写真だがファイル名に別アーティスト名
    if not is_dalle and not has_artist_in_fname:
        # yt_bts_ でaespa記事 → 不一致の可能性
        known_slugs = [
            'bts', 'blackpink', 'aespa', 'ive', 'newjeans', 'le_sserafim',
            'seventeen', 'nct', 'txt', 'exo', 'twice', 'enhypen', 'itzy',
            'illit', 'riize', 'babymonster', 'g_i_dle', 'nmixx', 'ateez',
            'stray_kids', 'red_velvet', 'mamamoo', 'bigbang', 'got7',
        ]
        for slug in known_slugs:
            if slug in fname and slug != artist_slug and artist_slug not in slug:
                issues.append({
                    'type': 'thumbnail_artist_mismatch',
                    'severity': 'high',
                    'detail': f'記事={primary_artist} だがサムネに "{slug}" の画像: {fname[:50]}',
                })
                break

    return issues


def check_distribution(post, post_type, criteria):
    """配信完全性: GSC Indexing + X投稿"""
    issues = []
    pid = post['id']
    date_str = post.get('date', '')
    if not date_str:
        return issues

    try:
        pub = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone(timedelta(hours=9)))
        age_h = (datetime.now(timezone.utc) - pub.astimezone(timezone.utc)).total_seconds() / 3600
    except:
        return issues

    if age_h < 24:
        return issues  # 投稿後24時間は猶予（X queue最大1日backlog + GSC indexing遅延考慮）

    # GSC（URLベースで照合 — GSCログにはpost_idがない）
    if criteria.get('require_gsc_indexing'):
        gsc_log = '/home/aiuser/kpop-ai-system/data/gsc_indexing_log.jsonl'
        post_link = post.get('link', '') or post.get('url', '')
        post_slug = post.get('slug', '')
        if not _find_in_log(pid, gsc_log, post_slug=post_slug, post_url=post_link):
            issues.append({'type': 'no_gsc_indexing', 'severity': 'high'})

    # X投稿: 有無 + 内容チェック
    if criteria.get('require_x_post'):
        x_log = '/home/aiuser/kpop-ai-system/logs/x_posts.jsonl'
        post_slug = post.get('slug', '')
        post_link = post.get('link', '') or post.get('url', '')
        x_entry = _find_in_log(pid, x_log, post_slug=post_slug, post_url=post_link)
        if x_entry is None:
            issues.append({'type': 'x_missing', 'severity': 'medium'})
        else:
            # X投稿内容の品質チェック
            x_text = x_entry.get('text', '')
            x_status = x_entry.get('status', '')
            x_tweet_id = x_entry.get('tweet_id', '')
            if x_status == 'error':
                issues.append({'type': 'x_post_error', 'severity': 'high',
                               'detail': x_entry.get('error', '')[:100]})
            elif not x_tweet_id:
                issues.append({'type': 'x_no_tweet_id', 'severity': 'medium'})
            # テキストに記事URLが含まれているか
            post_url = post.get('link', '') or post.get('url', '')
            post_slug = post.get('slug', '')
            if x_text and post_slug and post_slug not in x_text and post_url not in x_text:
                issues.append({'type': 'x_missing_url', 'severity': 'low',
                               'detail': f'X投稿にURLなし: {x_text[:60]}'})

    return issues


def _find_in_log(post_id, log_path, post_slug=None, post_url=None):
    """ログからpost_idまたはslug/URLに一致するエントリを返す（最新を優先）"""
    if not os.path.exists(log_path):
        return None
    found = None
    with open(log_path, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                pid = d.get('post_id') or d.get('wp_post_id')
                # post_id直接一致
                if pid == post_id:
                    found = d
                    continue
                # URL/slugベースの照合（x_posts.jsonlはpost_id未記録のため）
                entry_url = d.get('url', '')
                if post_url and entry_url and post_url.rstrip('/') == entry_url.rstrip('/'):
                    found = d
                elif post_slug and entry_url and f'/{post_slug}/' in entry_url:
                    found = d
                # popup記事: GSCログURL(/popup/{city}/{id}/)にpost_idが含まれるケース
                elif post_id and entry_url and f'/{post_id}/' in entry_url:
                    found = d
            except:
                pass
    return found


def _is_in_log(post_id, log_path, key='post_id'):
    return _find_in_log(post_id, log_path) is not None


# === Integrated audit ===

def full_audit(post, post_type='post'):
    """投稿1件の16+項目フル監査"""
    # post objectのtype fieldから自動検出 (popup等のCPTに対応)
    if post_type == 'post' and post.get('type') and post.get('type') != 'post':
        post_type = post['type']
    effective_type = _detect_post_type(post, post_type)
    criteria = CRITERIA.get(effective_type, CRITERIA['post'])
    issues = []

    # 0. ステータス異常検出
    status = post.get('status', 'publish')
    if status not in ('publish',):
        issues.append({'type': 'status_not_publish', 'severity': 'high', 'value': status})

    # A. メタデータ完全性
    issues.extend(check_title(post, criteria))
    issues.extend(check_slug(post, criteria))
    issues.extend(check_featured_media(post))
    issues.extend(check_category(post, effective_type if effective_type != 'matome' else 'post'))

    # B. SEO要件
    issues.extend(check_meta_description(post, criteria))
    issues.extend(check_ogp(post, criteria))
    issues.extend(check_ogp_image_relevance(post))

    # C. 本文品質
    issues.extend(check_content_quality(post, criteria))

    # D. 配信完全性
    issues.extend(check_distribution(post, effective_type, criteria))
    issues.extend(check_internal_links(post, criteria))

    # F. LLM校閲結果の統合 (直近24h)
    llm_result = _get_recent_llm_result(post['id'])
    if llm_result:
        for c in llm_result.get('critical', []):
            issues.append({'type': 'llm_critical', 'severity': 'high', 'detail': c})
        for h in llm_result.get('high', []):
            issues.append({'type': 'llm_high', 'severity': 'high', 'detail': h})

    # E. 自動回復判定
    high_count = sum(1 for i in issues if i.get('severity') == 'high')
    if high_count >= 3:
        issues.append({'type': 'rewrite_target', 'severity': 'info', 'reason': f'high_issues={high_count}'})
    if high_count >= 5:
        issues.append({'type': 'quarantine_target', 'severity': 'info', 'reason': f'high_issues={high_count}'})

    return issues


def get_x_post_summary(post_id, post_slug=None, post_url=None):
    """記事のX投稿サマリを取得（監査レポート用）

    Returns:
        dict with keys: posted (bool), tweet_id, text, status, error, ts
        or None if no log entry
    """
    x_log = '/home/aiuser/kpop-ai-system/logs/x_posts.jsonl'
    entry = _find_in_log(post_id, x_log, post_slug=post_slug, post_url=post_url)
    if entry is None:
        return {'posted': False, 'tweet_id': None, 'text': None, 'status': 'not_posted'}
    return {
        'posted': entry.get('status') == 'ok',
        'tweet_id': entry.get('tweet_id'),
        'text': entry.get('text', '')[:120],
        'status': entry.get('status', 'unknown'),
        'error': entry.get('error'),
        'ts': entry.get('ts'),
    }


def _get_recent_llm_result(post_id):
    """直近のLLM校閲結果を取得 (24h以内)"""
    llm_dir = '/home/aiuser/kpop-ai-system/logs/llm_audit'
    if not os.path.exists(llm_dir):
        return None
    for fname in sorted(os.listdir(llm_dir), reverse=True)[:6]:
        if not fname.endswith('.json'):
            continue
        try:
            data = json.load(open(os.path.join(llm_dir, fname)))
            for r in data.get('results', []):
                if r.get('id') == post_id:
                    return r
        except:
            pass
    return None


def fetch_posts(post_type='post', hours=12, per_page=20):
    """直近のpostを取得"""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
    endpoint = 'posts' if post_type == 'post' else post_type
    url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}?after={cutoff}&per_page={per_page}&_embed=true"
    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        print(f"  fetch err {post_type}: {e}")
        return []


def save_audit_state(post_id, post_type, issues):
    out = '/home/aiuser/kpop-ai-system/data/audit_state.jsonl'
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'post_id': post_id,
            'post_type': post_type,
            'issues': issues,
            'audited_at': datetime.now(timezone.utc).isoformat(),
            'high_count': sum(1 for i in issues if i.get('severity') == 'high'),
            'medium_count': sum(1 for i in issues if i.get('severity') == 'medium'),
            'low_count': sum(1 for i in issues if i.get('severity') == 'low'),
        }, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    for pt in ['post', 'popup']:
        posts = fetch_posts(pt, hours=24, per_page=5)
        print(f"\n=== {pt}: {len(posts)}件 ===")
        for p in posts:
            issues = full_audit(p, pt)
            title = _get_title(p)
            print(f"  id={p['id']} {title[:40]}: {len(issues)} issues")
            for i in issues[:5]:
                print(f"    [{i['severity']}] {i['type']}")
