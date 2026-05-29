"""
Wikimedia Commons 画像取得モジュール

ライセンス安全な画像のみを取得し、ローカルキャッシュに保存する。
- API: https://commons.wikimedia.org/w/api.php
- 許可ライセンス: CC0, public domain, CC-BY, CC-BY-SA
- 拒否: All Rights Reserved, restricted, watermark付き
"""
import json
import os
import re
import re as _re
import hashlib
import urllib.parse
import urllib.request

API_URL = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "KPopJournal-ThumbnailBot/1.0 (https://www.kpopjournal.tokyo)"

# 許可ライセンス（小文字で比較）
SAFE_LICENSES = [
    "cc0", "public domain", "pd",
    "cc-by", "cc by",
    "cc-by-sa", "cc by-sa",
    "cc by-sa 2.0", "cc by-sa 3.0", "cc by-sa 4.0",
    "cc by 2.0", "cc by 3.0", "cc by 4.0",
]

# 拒否キーワード
DENY_KEYWORDS = [
    "all rights reserved", "©", "non-commercial", "noncommercial",
    "no derivatives", "nd", "fair use", "copyrighted",
]


def _http_get_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def search_artist_images(query, limit=10):
    """File: 名前空間で画像検索。タイトル一覧を返す"""
    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": query,
        "srnamespace": "6",  # File namespace
        "srlimit": str(limit),
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    try:
        data = _http_get_json(url)
        return [item["title"] for item in data.get("query", {}).get("search", [])]
    except Exception as e:
        print(f"[wikimedia] search error: {e}")
        return []


def get_image_info(file_title):
    """画像URL + ライセンス + サイズを取得"""
    params = {
        "action": "query",
        "format": "json",
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
        "titles": file_title,
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    try:
        data = _http_get_json(url)
        pages = data.get("query", {}).get("pages", {})
        for _, page in pages.items():
            ii = page.get("imageinfo", [])
            if ii:
                return ii[0]
    except Exception as e:
        print(f"[wikimedia] info error: {e}")
    return None


def is_license_safe(image_info):
    """ライセンス情報から安全かどうか判定"""
    if not image_info:
        return False
    meta = image_info.get("extmetadata", {})

    # LicenseShortName を確認
    license_short = (meta.get("LicenseShortName", {}) or {}).get("value", "").lower()
    license_name = (meta.get("License", {}) or {}).get("value", "").lower()
    license_url = (meta.get("LicenseUrl", {}) or {}).get("value", "").lower()
    usage = (meta.get("UsageTerms", {}) or {}).get("value", "").lower()
    restrictions = (meta.get("Restrictions", {}) or {}).get("value", "").lower()

    combined = " ".join([license_short, license_name, license_url, usage])

    # 拒否ワードチェック
    for deny in DENY_KEYWORDS:
        if deny in combined:
            return False
    if restrictions:  # 任意の制約があれば拒否
        return False

    # 許可ライセンスチェック
    for safe in SAFE_LICENSES:
        if safe in combined:
            return True

    return False


def download_image(url, dest_path, max_size_mb=5):
    """画像をダウンロード"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as res:
        # サイズ制限
        content = res.read(max_size_mb * 1024 * 1024 + 1)
        if len(content) > max_size_mb * 1024 * 1024:
            raise ValueError(f"image too large (>{max_size_mb}MB)")
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(content)
    return dest_path


def slugify(name):
    """アー名をファイル名向けのslugに"""
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", name.lower())
    return s.strip("_")[:40]


# wikimediaを叩いてはいけない汎用語（アーティスト名でない）
# これらが渡された場合は即座にNoneを返す
_INVALID_ARTIST_NAMES = {
    "pop", "kpop", "k-pop", "music", "song", "idol", "star", "news",
    "beauty", "fashion", "seoul", "genre", "korean", "japan", "asia",
    "top", "hit", "new", "hot", "best", "trend", "chart", "video",
    "the", "and", "for", "with", "from",
    # 音楽サービス・プラットフォーム（アーティストではない）
    "melon", "bugs", "genie", "spotify", "youtube", "itunes", "billboard",
    "gaon", "hanteo", "oricon",
}

# 誤マッチ排除用: これらが含まれるファイル名は拒否
NEGATIVE_KEYWORDS = [
    "merchandise", "logo", "chart", "diagram", "graph", "map",
    "poster", "sticker", "flag", "emblem", "icon", "wordmark",
    "signature", "infographic", "comparison",
    "flower", "plant", "animal", "landscape", "building", "architecture",
    "food", "cuisine", "restaurant", "street", "city", "airport",
    # 同名バンド/言葉対策
    "and also the trees", "stranger things",
]

# アーティスト名として最低限必要な文字数
_MIN_ARTIST_NAME_LEN = 2


def is_relevant_title(title, artist_name):
    """ファイル名にアー名が単語境界で含まれているかチェック"""
    title_lower = title.lower()
    artist_lower = artist_name.lower()

    # 汎用語は拒否
    if artist_lower in _INVALID_ARTIST_NAMES:
        return False

    # 短すぎるアーティスト名は誤マッチしやすい
    if len(artist_lower) < _MIN_ARTIST_NAME_LEN:
        return False

    # ネガティブキーワード除外
    for ng in NEGATIVE_KEYWORDS:
        if ng in title_lower:
            return False

    # アー名を単語境界で検索（数字の隣は除外）
    # 例: "TWICE 23" の TWICE は年号文脈なので拒否
    pattern = r"(?:^|[^a-z0-9])" + _re.escape(artist_lower) + r"(?:$|[^a-z0-9])"
    if not _re.search(pattern, title_lower):
        return False

    return True


def build_search_queries(artist_name):
    """検索クエリのバリエーションを生成（K-POP文脈を明示して精度向上）"""
    return [
        f"{artist_name} K-POP group",
        f"{artist_name} Korean idol",
        f"{artist_name} concert performance",
        artist_name,  # 最後の砦
    ]


def fetch_safe_image(artist_name, cache_dir, max_attempts=8, prefer_landscape=True):
    """
    高レベルAPI: 検索→関連性チェック→ライセンスチェック→ダウンロード→キャッシュ
    """
    # 汎用語・ジャンル名はアーティスト画像として取得しない
    if not artist_name or artist_name.lower() in _INVALID_ARTIST_NAMES:
        return None
    if len(artist_name) < _MIN_ARTIST_NAME_LEN:
        return None

    slug = slugify(artist_name)
    index_path = os.path.join(cache_dir, "index.json")
    index = {}
    if os.path.exists(index_path):
        try:
            with open(index_path) as f:
                index = json.load(f)
        except Exception:
            index = {}

    # 1) 既存キャッシュ優先
    if slug in index and index[slug].get("files"):
        for fname in index[slug]["files"]:
            fpath = os.path.join(cache_dir, fname)
            if os.path.exists(fpath):
                return fpath

    # 2) 複数クエリで検索
    seen_titles = set()
    candidates = []
    for q in build_search_queries(artist_name):
        for t in search_artist_images(q, limit=10):
            if t in seen_titles:
                continue
            seen_titles.add(t)
            # 関連性フィルター: ファイル名にアー名が含まれること
            if is_relevant_title(t, artist_name):
                candidates.append(t)
        if len(candidates) >= max_attempts * 2:
            break

    if not candidates:
        return None

    # 3) 各候補をライセンス + サイズ + アスペクトでスコアリング
    scored = []
    for title in candidates[:max_attempts * 2]:
        info = get_image_info(title)
        if not info:
            continue
        if not is_license_safe(info):
            continue
        mime = info.get("mime", "")
        if mime not in ("image/jpeg", "image/png"):
            continue
        w, h = info.get("width", 0), info.get("height", 0)
        if w < 800 or h < 500:
            continue
        # スコア: ランドスケープ優遇、解像度ボーナス
        aspect = w / max(h, 1)
        score = min(w, 4000) / 100  # 解像度
        if prefer_landscape and aspect >= 1.4:
            score += 30  # 横長ボーナス
        elif aspect < 0.8:
            score -= 20  # 縦長ペナルティ
        scored.append((score, title, info))

    scored.sort(key=lambda x: -x[0])

    # 4) スコア順にダウンロード試行
    for _, title, info in scored[:max_attempts]:
        url = info.get("url")
        if not url:
            continue
        ext = "jpg" if info.get("mime") == "image/jpeg" else "png"
        fname = f"{slug}_{hashlib.md5(title.encode()).hexdigest()[:8]}.{ext}"
        dest = os.path.join(cache_dir, fname)
        try:
            download_image(url, dest)
        except Exception as e:
            print(f"[wikimedia] download failed for {title}: {e}")
            continue

        if slug not in index:
            index[slug] = {"name": artist_name, "files": [], "sources": []}
        if fname not in index[slug]["files"]:
            index[slug]["files"].append(fname)
            index[slug].setdefault("sources", []).append({
                "file": fname,
                "wikimedia_title": title,
                "url": url,
                "license": (info.get("extmetadata", {}).get("LicenseShortName", {}) or {}).get("value", ""),
            })
        with open(index_path, "w") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

        return dest

    # 5) Wikidata P18 fallback: テキスト検索で取れない新人グループ向け
    # group→P18 で本人写真を確定的に得る ([[idol-wiki-images-wikidata-p18-method]])
    try:
        p18 = _wikidata_p18_image(artist_name)
        if p18:
            info = get_image_info(p18.get('title'))
            if info and is_license_safe(info) and info.get('mime') in ('image/jpeg','image/png'):
                url = info.get('url')
                ext = 'jpg' if info.get('mime') == 'image/jpeg' else 'png'
                fname = f"{slug}_{hashlib.md5(p18['title'].encode()).hexdigest()[:8]}.{ext}"
                dest = os.path.join(cache_dir, fname)
                try:
                    download_image(url, dest)
                    if slug not in index:
                        index[slug] = {"name": artist_name, "files": [], "sources": []}
                    if fname not in index[slug]["files"]:
                        index[slug]["files"].append(fname)
                        index[slug].setdefault("sources", []).append({
                            "file": fname,
                            "wikimedia_title": p18['title'],
                            "url": url,
                            "license": (info.get("extmetadata", {}).get("LicenseShortName", {}) or {}).get("value", ""),
                            "via": f"wikidata:P18:{p18['qid']}",
                        })
                    with open(index_path, "w") as f:
                        json.dump(index, f, ensure_ascii=False, indent=2)
                    print(f"[wikimedia] P18 fallback OK: {artist_name} → {p18['qid']} / {p18['title']}")
                    return dest
                except Exception as e:
                    print(f"[wikimedia] P18 download failed: {e}")
    except Exception as e:
        print(f"[wikimedia] P18 fallback error: {e}")

    return None


_KPOP_DESC_KW = (
    'k-pop', 'kpop', 'korean', 'south korean', 'boy band', 'girl group',
    'idol', 'boy group', 'girl band',
    'korean singer', 'korean rapper', 'korean musician', 'korean idol',
    'south korean musician', 'south korean singer',
)
_KPOP_DESC_JA = (
    '韓国', 'k-pop', 'kポップ', 'アイドル', 'ボーイズグループ', 'ガールズグループ',
    '男性アイドル', '女性アイドル', '歌手', 'ラッパー', '韓国の歌手',
)


def _wikidata_p18_image(artist_name):
    """Wikidata で artist_name を検索 → K-POP関連description で絞り込み →
    P18 (image) claim を返す。返却: {'qid':..., 'title':<File:...>} or None

    堅牢化: timeout=30, 想定外レスポンス形状/value型をガード
    """
    import urllib.parse as _up
    ua = 'KPOP-JOURNAL-Bot/1.0 (+https://kpopjournal.tokyo; citation-only)'
    def _get(url):
        req = urllib.request.Request(url, headers={'User-Agent': ua})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    # 検索: 日本語名("イ・ヒジュン")も拾うため ja を先に試し、ヒット無しなら en にfallback
    qid = None
    for _lang in ('ja', 'en'):
        try:
            sr = _get(f'https://www.wikidata.org/w/api.php?action=wbsearchentities&search={_up.quote(artist_name)}&language={_lang}&type=item&format=json&limit=8')
        except Exception:
            continue
        for hit in (sr.get('search') or []):
            if not isinstance(hit, dict):
                continue
            desc = (hit.get('description') or '').lower()
            if any(kw in desc for kw in _KPOP_DESC_KW) or any(kw in desc for kw in _KPOP_DESC_JA):
                qid = hit.get('id')
                break
        if qid:
            break
    if not qid:
        return None
    # P18 claim
    cl = _get(f'https://www.wikidata.org/w/api.php?action=wbgetclaims&entity={qid}&property=P18&format=json')
    claims = (cl.get('claims') or {}).get('P18') or []
    for c in claims:
        if not isinstance(c, dict):
            continue
        mainsnak = c.get('mainsnak') or {}
        dv = mainsnak.get('datavalue') or {}
        v = dv.get('value')
        # P18のvalueは通常 str(filename) だが将来仕様変更で dict 化する可能性
        if isinstance(v, str) and v:
            return {'qid': qid, 'title': f'File:{v}'}
    return None


# CLI テスト用
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 wikimedia.py <artist_name>")
        sys.exit(1)
    artist = sys.argv[1]
    cache_dir = "/home/aiuser/kpop-ai-system/assets/artist_cache"
    print(f"Fetching image for: {artist}")
    result = fetch_safe_image(artist, cache_dir)
    if result:
        print(f"OK: {result}")
    else:
        print("FAIL: no safe image found")
