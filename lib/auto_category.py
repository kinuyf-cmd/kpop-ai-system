"""記事タイトル/本文からアーティスト名を検出し、WPカテゴリを自動設定する

全記事作成フローでこの関数を呼ぶことで、アーティストカテゴリ漏れを防ぐ。
"""
import json, os, re, urllib.request, base64
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode() if WP_USER else ''

_ARTIST_CAT_CACHE = None
_CACHE_PATH = '/home/aiuser/kpop-ai-system/config/artist_category_map.json'


def _load_artist_categories():
    """WPからアーティストカテゴリ(parent=26)を取得してキャッシュ"""
    global _ARTIST_CAT_CACHE
    if _ARTIST_CAT_CACHE:
        return _ARTIST_CAT_CACHE

    # キャッシュファイルがあればそこから
    if os.path.exists(_CACHE_PATH):
        try:
            data = json.load(open(_CACHE_PATH))
            # 2026-05-25: _disabled マーカーがあればアーティストカテゴリ自動付与を
            # 無効化(アーティスト正本は Idol Wiki CPT に一本化、壊れた map の再取得も抑止)。
            if isinstance(data, dict) and data.get('_disabled'):
                _ARTIST_CAT_CACHE = {}
                return {}
            if data:
                _ARTIST_CAT_CACHE = data
                return data
        except:
            pass

    # WP APIから取得
    try:
        url = 'https://www.kpopjournal.tokyo/wp-json/wp/v2/categories?parent=26&per_page=100'
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        cats = json.loads(urllib.request.urlopen(req, timeout=15).read())

        mapping = {}
        for c in cats:
            name = c['name']
            cat_id = c['id']
            # 名前の各種バリエーションをキーに
            for key in [name, name.lower(), name.upper(), name.replace(' ', ''),
                        name.replace(' ', '_'), name.lower().replace(' ', '_')]:
                mapping[key] = cat_id

        # キャッシュ保存
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        json.dump(mapping, open(_CACHE_PATH, 'w'), ensure_ascii=False, indent=2)
        _ARTIST_CAT_CACHE = mapping
        return mapping
    except Exception as e:
        print(f'[auto_category] WP取得失敗: {e}')
        return {}


def detect_artist_categories(title, content=''):
    """タイトル+本文からアーティスト名を検出し、対応するカテゴリIDリストを返す"""
    mapping = _load_artist_categories()
    if not mapping:
        return []

    text = title + ' ' + re.sub(r'<[^>]+>', ' ', content)[:2000]
    found = set()

    for name, cat_id in mapping.items():
        # 3文字以上のアーティスト名のみマッチ (短すぎると誤検出)
        if len(name) < 3:
            continue
        # 単語境界マッチ: "NCT"が"NCT WISH"の部分一致で誤検出するのを防止
        # 英字名は前後が英字でない場合のみマッチ (2026-05-01修正)
        if re.search(r'[A-Za-z]', name):
            pattern = r'(?<![A-Za-z])' + re.escape(name) + r'(?![A-Za-z\s][\w])'
            if re.search(pattern, text):
                found.add(cat_id)
        else:
            # 韓国語・日本語名はそのまま部分一致
            if name in text:
                found.add(cat_id)

    return list(found)


def ensure_artist_categories(post_id, title, content='', existing_categories=None):
    """記事にアーティストカテゴリが設定されていなければ自動追加"""
    if existing_categories is None:
        existing_categories = []

    detected = detect_artist_categories(title, content)
    if not detected:
        return existing_categories

    # 既存カテゴリとマージ
    merged = list(set(existing_categories + detected))
    if set(merged) == set(existing_categories):
        return existing_categories  # 変更なし

    # WP更新
    try:
        body = json.dumps({'categories': merged}).encode()
        req = urllib.request.Request(
            f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}',
            data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=15)
        added = set(merged) - set(existing_categories)
        print(f'[auto_category] post {post_id}: +{len(added)}カテゴリ追加 {added}')
    except Exception as e:
        print(f'[auto_category] post {post_id} 更新失敗: {e}')

    return merged
