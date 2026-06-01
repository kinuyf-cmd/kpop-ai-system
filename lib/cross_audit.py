"""横断監査チェック群 - 既存audit infraに足りない検査を提供

既存(full_audit_engine/thumbnail_audit/x_post_audit)が個別記事/個別系統を
検査するのに対し、本モジュールは複数記事/複数系統を跨ぐ整合性を検査する。

提供する検査:
  - check_letterbox: featured_mediaの左右に縦長コンテンツ由来のletterboxがないか
  - check_thumb_duplicate: 同日内の他記事と featured_media URL が重複していないか
  - check_artist_triplet: title主語 ⇄ category名 ⇄ featured_mediaファイル名 三点整合
  - check_wp_xqueue: WP status と x_post_queue の整合(draft/trashが残ってないか)

2026-05-08新設(daily 9件監査で発見した6種違反のうち4種をカバー)。
"""
from __future__ import annotations
import json
import os
import re
import urllib.request
from io import BytesIO
from typing import Iterable

WP_BASE = 'https://www.kpopjournal.tokyo'
HOME = os.path.expanduser('~')

# Tier1アーティスト(make_thumbnail.pyと同じリストから抜粋)
ARTIST_KEYWORDS = {
    'BTS': ['BTS', '防弾', 'ジン', 'シュガ', 'JHOPE', 'J-HOPE', 'RM', 'ジミン', 'V', 'テテ', 'ジョングク'],
    'BLACKPINK': ['BLACKPINK', 'ブラックピンク', 'ジス', 'JISOO', 'ジェニー', 'JENNIE', 'ロゼ', 'ROSE', 'ROSÉ', 'リサ', 'LISA'],
    'TWICE': ['TWICE', 'トゥワイス', 'ナヨン', 'ジョンヨン', 'モモ', 'サナ', 'ジヒョ', 'ミナ', 'ダヒョン', 'チェヨン', 'ツウィ'],
    'AESPA': ['aespa', 'AESPA', 'エスパ', 'ジゼル', 'カリナ', 'ウィンター', 'ニンニン'],
    'NMIXX': ['NMIXX', 'リリー', 'ヘウォン', 'ベイ', 'ジウ', 'ソリュン', 'ソルリュン', 'キュジン'],
    'ITZY': ['ITZY', 'イェジ', 'リア', 'リュジン', 'チェリョン', 'ユナ'],
    'ILLIT': ['ILLIT', 'アイリット', 'ユナ', 'ミンジュ', 'モカ', 'ウォニ', 'イロハ'],
    'TXT': ['TXT', 'トゥモロー', 'ヨンジュン', 'スビン', 'ボムギュ', 'テヒョン', 'ヒュニンカイ'],
    'NEWJEANS': ['NewJeans', 'ニュージーンズ', 'ミンジ', 'ハニ', 'ダニエル', 'ヘリン', 'ヘイン'],
    'IVE': ['IVE', 'アイブ', 'ユジン', 'ガウル', 'レイ', 'ウォニョン', 'リズ', 'イソ'],
    'SNSD': ['少女時代', 'SNSD', 'ティファニー', 'ユナ', 'テヨン', 'ジェシカ', 'スヨン', 'ヒョヨン', 'サニー', 'ソヒョン', 'ユリ'],
    'TIFFANY': ['ティファニー', 'TIFFANY', '少女時代'],
    'HYBE': ['HYBE', 'バン・シヒョク', 'バンPD'],
}


def _wp_get(path: str, auth_curl: bool = True) -> dict | list | None:
    """WP REST APIから取得。auth_curl=Trueは ~/.wp_auth で認証。"""
    import subprocess
    cmd = ['curl', '-s', '-K', f'{HOME}/.wp_auth', f'{WP_BASE}{path}'] if auth_curl else \
          ['curl', '-s', f'{WP_BASE}{path}']
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


# ─── 検査1: letterbox(縦長コンテンツがpadされて横長アップ) ────────────
def check_letterbox(image_url: str, threshold: float = 0.18) -> dict:
    """画像左右の単色/低分散領域から縦長コンテンツ由来のletterboxを検出。

    Returns: {'is_letterbox': bool, 'left_uniform_ratio': float, ...}
    threshold: 左右のuniform領域が画像幅の何%以上ならletterboxとみなすか
    """
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return {'is_letterbox': False, 'error': 'PIL/numpy not available'}

    try:
        # 2026-06-01: UA なしだと allkpop 等が 403 を返し、画像取得失敗で
        # is_letterbox=False(error)→ 段階1 で別経路の誤ブロックに繋がっていた。
        # _download_image と同じ Chrome UA を付けて 403 を回避する。
        _req = urllib.request.Request(image_url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) '
                          'Chrome/125.0.0.0 Safari/537.36',
        })
        with urllib.request.urlopen(_req, timeout=15) as r:
            img = Image.open(BytesIO(r.read())).convert('RGB')
    except Exception as e:
        return {'is_letterbox': False, 'error': str(e)[:100]}

    arr = np.asarray(img)
    h, w, _ = arr.shape
    if w < 200 or h < 100:
        return {'is_letterbox': False, 'reason': 'image too small'}

    # 信号1: 左右の極めて単色なpadding(伝統的letterbox)
    # 自然な空/白背景は除外するため high_var_threshold を 30 まで下げて厳密に
    col_var = arr.astype(float).var(axis=(0, 2))
    strict_solid_threshold = 30.0
    left_uniform = 0
    for x in range(w // 2):
        if col_var[x] < strict_solid_threshold:
            left_uniform += 1
        else:
            break
    right_uniform = 0
    for x in range(w - 1, w // 2, -1):
        if col_var[x] < strict_solid_threshold:
            right_uniform += 1
        else:
            break
    left_uni = left_uniform / w
    right_uni = right_uniform / w
    uniform_letterbox = (left_uni + right_uni) > 0.30 and left_uni > 0.10 and right_uni > 0.10

    # 信号2: ぼかしpadding(縦長動画→横長合成)
    # 真のletterbox-blurは側帯が高分散(ぼかされた画像)+低エッジ。
    # 自然な空/白背景は低分散+低エッジで除外できる。
    gray = arr.mean(axis=2)
    dx = np.abs(np.diff(gray, axis=1))
    edge_per_col = dx.mean(axis=0)
    cx0, cx1 = int(w * 0.35), int(w * 0.65)
    lx0, lx1 = 0, int(w * 0.20)
    rx0, rx1 = int(w * 0.80), w - 1
    center_edge = float(edge_per_col[cx0:cx1].mean())
    left_edge = float(edge_per_col[lx0:lx1].mean())
    right_edge = float(edge_per_col[rx0:rx1].mean())
    left_var = float(col_var[lx0:lx1].mean())
    right_var = float(col_var[rx0:rx1].mean())
    if center_edge > 1.5:
        left_sharp_ratio = left_edge / center_edge
        right_sharp_ratio = right_edge / center_edge
    else:
        left_sharp_ratio = right_sharp_ratio = 1.0
    # blur_letterbox: 側帯がぼかし(低エッジ)+ 中央と色が類似(=中央の流用padding)
    # 自然な空/壁背景は中央コンテンツと色が大きく異なるので除外できる。
    def _color_hist(region):
        """64-bin RGB histogram normalized."""
        h, _ = np.histogramdd(
            region.reshape(-1, 3),
            bins=(4, 4, 4), range=((0, 256), (0, 256), (0, 256)))
        return h.flatten() / max(h.sum(), 1)

    center_region = arr[:, cx0:cx1, :]
    left_region = arr[:, lx0:lx1, :]
    right_region = arr[:, rx0:rx1, :]
    c_hist = _color_hist(center_region)
    l_hist = _color_hist(left_region)
    r_hist = _color_hist(right_region)
    # cosine similarity (1=同色構成, 0=別色構成)
    def _cos(a, b):
        n = (np.linalg.norm(a) * np.linalg.norm(b))
        return float(a.dot(b) / n) if n > 0 else 0.0
    left_color_sim = _cos(l_hist, c_hist)
    right_color_sim = _cos(r_hist, c_hist)

    blur_letterbox = (
        left_sharp_ratio < 0.50 and right_sharp_ratio < 0.50 and
        center_edge > 2.5 and
        left_var > 100 and right_var > 100 and
        # 左右が中央と色構成上類似(=同じコンテンツの流用ぼかし)
        left_color_sim > 0.65 and right_color_sim > 0.65
    )

    is_letterbox = uniform_letterbox or blur_letterbox

    return {
        'is_letterbox': is_letterbox,
        'mode': 'uniform' if uniform_letterbox else ('blur' if blur_letterbox else 'none'),
        'left_uniform_ratio': round(left_uni, 3),
        'right_uniform_ratio': round(right_uni, 3),
        'left_sharp_ratio': round(left_sharp_ratio, 3),
        'right_sharp_ratio': round(right_sharp_ratio, 3),
        'left_var': round(left_var, 1),
        'right_var': round(right_var, 1),
        'left_color_sim': round(left_color_sim, 3),
        'right_color_sim': round(right_color_sim, 3),
        'image_size': (w, h),
    }


# ─── 検査2: 同日内サムネ重複 ──────────────────────────────────────────
def check_thumb_duplicate_today(post_ids: list[int]) -> list[dict]:
    """指定postsのfeatured_media URLで重複を検出。

    Returns: [{'post_ids': [a, b], 'media_url': '...'}, ...]
    """
    media_to_posts: dict[str, list[int]] = {}
    for pid in post_ids:
        p = _wp_get(f'/wp-json/wp/v2/posts/{pid}?_fields=id,featured_media&context=edit')
        if not isinstance(p, dict):
            continue
        fm = p.get('featured_media', 0)
        if not fm:
            continue
        m = _wp_get(f'/wp-json/wp/v2/media/{fm}?_fields=id,source_url&context=edit')
        if isinstance(m, dict) and m.get('source_url'):
            media_to_posts.setdefault(m['source_url'], []).append(pid)

    return [{'post_ids': pids, 'media_url': url}
            for url, pids in media_to_posts.items() if len(pids) > 1]


# ─── 検査3: artist三点整合(title ⇄ category ⇄ featured_media filename) ──
def detect_title_artist(title: str) -> str | None:
    """タイトル先頭から主語アー名を抽出。"""
    title_upper = title.upper()
    # 先頭40字に限定(後半の周辺アー名巻き込み防止)
    head = title[:40]
    head_upper = head.upper()
    candidates = []
    for canon, kws in ARTIST_KEYWORDS.items():
        for kw in kws:
            if kw.upper() in head_upper:
                candidates.append((canon, head_upper.find(kw.upper())))
    if not candidates:
        return None
    # 最も先頭に近いものを優先
    candidates.sort(key=lambda x: x[1])
    return candidates[0][0]


def check_artist_triplet(post_id: int) -> dict:
    """タイトル主語 vs カテゴリ名 vs featured_mediaファイル名 三点整合。

    全て一致 OR title主語が無い  → OK
    1点でも別アー名を指す       → MISMATCH
    """
    p = _wp_get(f'/wp-json/wp/v2/posts/{post_id}?context=edit')
    if not isinstance(p, dict):
        return {'verdict': 'ERROR', 'reason': 'post not found'}

    title = (p.get('title') or {}).get('raw') or (p.get('title') or {}).get('rendered', '')
    cats = p.get('categories', [])
    fm = p.get('featured_media', 0)

    title_artist = detect_title_artist(title)

    # category names
    cat_names = []
    for cid in cats:
        c = _wp_get(f'/wp-json/wp/v2/categories/{cid}?_fields=id,name,slug')
        if isinstance(c, dict):
            cat_names.append(c.get('name', '').upper())

    # fm filename + alt
    fm_signal = ''
    if fm:
        m = _wp_get(f'/wp-json/wp/v2/media/{fm}?_fields=id,source_url,alt_text&context=edit')
        if isinstance(m, dict):
            fm_signal = (m.get('source_url', '') + ' ' + m.get('alt_text', '')).upper()

    # タイトルに含まれる全エンティティ(主語以外も含む)を集める
    title_upper = title.upper()
    title_entities = set()
    for canon, kws in ARTIST_KEYWORDS.items():
        if any(k.upper() in title_upper for k in kws):
            title_entities.add(canon)

    mismatches = []
    if title_artist:
        ta_kws = ARTIST_KEYWORDS[title_artist]
        ta_kws_upper = [k.upper() for k in ta_kws]
        # category check: タイトルに登場しないエンティティのカテゴリが付いていないか
        for cn in cat_names:
            for other_canon, other_kws in ARTIST_KEYWORDS.items():
                if other_canon in title_entities:
                    continue  # タイトル内で言及されるカテゴリはOK
                if cn in [k.upper() for k in other_kws]:
                    mismatches.append(f'category={cn} not in title entities {title_entities}')
        # fm check: ファイル名/altがタイトルに無い別アー名を含む
        # まずタイトル内エンティティのいずれかをfmが含むなら OK
        title_entity_in_fm = any(
            any(k.upper() in fm_signal for k in ARTIST_KEYWORDS[ent])
            for ent in title_entities
        )
        if fm_signal and not title_entity_in_fm:
            for other_canon, other_kws in ARTIST_KEYWORDS.items():
                if other_canon in title_entities:
                    continue
                if any(k.upper() in fm_signal for k in other_kws):
                    mismatches.append(f'fm signal contains {other_canon} (not in title)')
                    break

    return {
        'verdict': 'MISMATCH' if mismatches else 'OK',
        'title_artist': title_artist,
        'cat_names': cat_names,
        'fm_signal_excerpt': fm_signal[:120],
        'mismatches': mismatches,
    }


# ─── 検査4.5: 同タイトル重複記事検出 ──────────────────────────────────
def check_duplicate_titles(posts: list[dict], normalize: bool = True) -> list[dict]:
    """post listのうち同一タイトルが複数件あるグループを返す。

    normalize=Trueでタイトルを正規化(全角半角・スペース除去)してから比較。
    Returns: [{'title': '...', 'post_ids': [a, b], 'dates': [...]}]
    """
    import unicodedata
    by_title: dict[str, list[dict]] = {}
    for p in posts:
        raw = (p.get('title') or {}).get('rendered') or (p.get('title') or {}).get('raw', '')
        if not raw:
            continue
        if normalize:
            key = unicodedata.normalize('NFKC', raw).replace(' ', '').strip()
        else:
            key = raw
        by_title.setdefault(key, []).append(p)

    dups = []
    for title, plist in by_title.items():
        if len(plist) >= 2:
            plist_sorted = sorted(plist, key=lambda x: x.get('date', ''))
            dups.append({
                'title': title,
                'post_ids': [p['id'] for p in plist_sorted],
                'dates': [p.get('date', '') for p in plist_sorted],
                'keep_id': plist_sorted[0]['id'],
                'trash_ids': [p['id'] for p in plist_sorted[1:]],
            })
    return dups


# ─── 検査4: WP ⇄ X queue 整合 ──────────────────────────────────────
def check_wp_xqueue_consistency(queue_path: str = None) -> dict:
    """x_post_queue.json内のpost_idとWP status を突合。

    違反: status≠publishのものがqueueに残存。
    """
    queue_path = queue_path or os.path.join(
        os.path.dirname(__file__), '..', 'config', 'x_post_queue.json')
    queue_path = os.path.abspath(queue_path)

    try:
        q = json.load(open(queue_path))
    except Exception as e:
        return {'error': f'queue load fail: {e}'}

    items = q if isinstance(q, list) else (q.get('queue') or q.get('items') or [])
    if not items:
        return {'queue_size': 0, 'violations': []}

    post_ids = [int(i.get('post_id') or 0) for i in items if i.get('post_id')]
    # batch fetch
    import subprocess
    statuses = {}
    chunks = [post_ids[i:i+30] for i in range(0, len(post_ids), 30)]
    for chunk in chunks:
        inc = ','.join(map(str, chunk))
        r = subprocess.run(
            ['curl', '-s', '-K', f'{HOME}/.wp_auth',
             f'{WP_BASE}/wp-json/wp/v2/posts?include={inc}&status=any&per_page=100&_fields=id,status'],
            capture_output=True, text=True, timeout=30)
        try:
            for d in json.loads(r.stdout):
                statuses[d['id']] = d.get('status', '?')
        except Exception:
            pass

    violations = []
    for it in items:
        pid = int(it.get('post_id') or 0)
        st = statuses.get(pid, 'unknown')
        if st != 'publish':
            violations.append({
                'post_id': pid, 'wp_status': st,
                'queue_title': it.get('title', '')[:60],
                'queue_artist': it.get('artist', ''),
            })

    # artist フィールドとtitle主語の乖離
    artist_mismatches = []
    for it in items:
        artist = it.get('artist', '')
        title = it.get('title', '')
        if not artist or not title:
            continue
        ta = detect_title_artist(title)
        if ta and artist.upper().replace(' ', '') != ta.replace(' ', ''):
            # "BLACKPINK" vs "JISOO" は許容(同グループ)
            ta_kws = [k.upper() for k in ARTIST_KEYWORDS.get(ta, [])]
            if artist.upper() not in ta_kws:
                artist_mismatches.append({
                    'post_id': it.get('post_id'),
                    'queue_artist': artist,
                    'title_artist': ta,
                    'title': title[:60],
                })

    return {
        'queue_size': len(items),
        'wp_status_violations': violations,
        'artist_field_mismatches': artist_mismatches,
    }
