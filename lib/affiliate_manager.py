#!/usr/bin/env python3
"""アフィリエイト4社統合管理 v2 (HTML素材方式)"""
import os, json, urllib.parse, re
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

A8NET_MEDIA_ID = os.getenv('A8NET_MEDIA_ID', '')
AMAZON_ASSOCIATE_TAG = os.getenv('AMAZON_ASSOCIATE_TAG', '')
SAFE_MODE = os.getenv('AFFILIATE_SAFE_MODE', 'true').lower() == 'true'

CONFIG_DIR = '/home/aiuser/kpop-ai-system/config/affiliate'
A8_MASTER_PATH = f'{CONFIG_DIR}/a8_master.json'
A8_MATERIALS_PATH = f'{CONFIG_DIR}/a8_materials.json'
QOO10_PRODUCTS_PATH = f'{CONFIG_DIR}/qoo10_products.json'


def load_a8_master():
    with open(A8_MASTER_PATH, encoding='utf-8') as f:
        return json.load(f)


def load_a8_materials():
    if not os.path.exists(A8_MATERIALS_PATH):
        return {'programs': {}}
    with open(A8_MATERIALS_PATH, encoding='utf-8') as f:
        return json.load(f)


def has_a8_material(program_key):
    """A8 HTML素材が登録済かチェック"""
    mats = load_a8_materials()
    prog = mats.get('programs', {}).get(program_key)
    return bool(prog and prog.get('html_material'))


def build_a8_link(program_key, link_text=None):
    """A8リンク - HTML素材方式 (登録済のもののみ)"""
    if SAFE_MODE and not has_a8_material(program_key):
        return None

    mats = load_a8_materials()
    prog = mats.get('programs', {}).get(program_key)
    if not prog:
        return None

    html = prog.get('html_material', '')
    if not html:
        return None

    if link_text:
        html = re.sub(r'(<a [^>]+>)([^<]+)(</a>)', r'\1' + link_text + r'\3', html, count=1)

    if 'rel=' not in html.split('>')[0]:
        html = re.sub(r'(<a )', r'\1rel="nofollow sponsored" ', html, count=1)
    else:
        # 既存 rel に不足しているトークンだけを追加(nofollow/sponsored の重複防止)
        def _merge_rel(m):
            existing = m.group(2).split()
            for tok in ('nofollow', 'sponsored'):
                if tok not in existing:
                    existing.append(tok)
            return m.group(1) + ' '.join(existing) + m.group(3)
        html = re.sub(r'(rel=")([^"]*)(")', _merge_rel, html, count=1)

    if 'target=' not in html.split('>')[0]:
        html = re.sub(r'(<a )', r'\1target="_blank" ', html, count=1)

    return html


def build_a8_link_with_html(program_key, link_text=None):
    """build_a8_linkのエイリアス (後方互換)"""
    return build_a8_link(program_key, link_text)


def build_amazon_search_link(query, link_text=None):
    """Amazon検索リンク (タグ付き)"""
    if not AMAZON_ASSOCIATE_TAG:
        return None
    encoded = urllib.parse.quote(query)
    url = f"https://www.amazon.co.jp/s?k={encoded}&tag={AMAZON_ASSOCIATE_TAG}"
    text = link_text or f"Amazonで「{query}」を検索"
    return f'<a href="{url}" rel="nofollow sponsored" target="_blank" class="kpj-aff-amazon">{text}</a>'


def build_amazon_product_link(asin, link_text=None):
    if not AMAZON_ASSOCIATE_TAG:
        return None
    url = f"https://www.amazon.co.jp/dp/{asin}/?tag={AMAZON_ASSOCIATE_TAG}"
    text = link_text or "Amazonで購入"
    return f'<a href="{url}" rel="nofollow sponsored" target="_blank" class="kpj-aff-amazon">{text}</a>'


def build_rakuten_search_link(query, link_text=None):
    """楽天検索リンク (A8経由) - SAFE_MODE時は素材チェック"""
    if SAFE_MODE and not has_a8_material('rakuten_affiliate'):
        return None
    if not A8NET_MEDIA_ID:
        return None
    rakuten_url = f"https://search.rakuten.co.jp/search/mall/{urllib.parse.quote(query)}/"
    a8_redirect = urllib.parse.quote(rakuten_url, safe='')
    pid = "s00000011623001"
    url = f"https://px.a8.net/svt/ejp?a8mat={A8NET_MEDIA_ID}&pid={pid}&a8ejpredirect={a8_redirect}"
    text = link_text or f"楽天で「{query}」を検索"
    return f'<a href="{url}" rel="nofollow sponsored" target="_blank" class="kpj-aff-rakuten">{text}</a>'


def build_qoo10_link(product_id_or_url, link_text=None):
    """Qoo10商品リンク - 手動登録マスターから"""
    if not os.path.exists(QOO10_PRODUCTS_PATH):
        return None
    products = json.load(open(QOO10_PRODUCTS_PATH))
    matched = None
    for p in products.get('products', []):
        if p.get('id') == product_id_or_url or p.get('url') == product_id_or_url:
            matched = p
            break
    if matched:
        url = matched.get('url', '')
        if url and url != 'TODO' and url.startswith('http'):
            text = link_text or f"Qoo10で「{matched['name']}」を見る"
            return f'<a href="{url}" rel="nofollow sponsored" target="_blank" class="kpj-aff-qoo10">{text}</a>'
    return None


def get_program_metadata(program_key):
    a8 = load_a8_master()
    return a8['programs'].get(program_key)


def list_programs_by_category(category):
    a8 = load_a8_master()
    return [(k, v) for k, v in a8['programs'].items()
            if category in v.get('categories', [])]


def list_programs_by_tier(tier=1, only_with_material=False):
    """tier別。only_with_material=True で素材登録済のみ"""
    a8 = load_a8_master()
    programs = []
    for k, v in a8['programs'].items():
        if v.get('tier') == tier:
            if only_with_material and not has_a8_material(k):
                continue
            programs.append((k, v))
    return programs


if __name__ == '__main__':
    print(f"=== A8 affiliate_manager v2 (HTML素材方式) ===")
    print(f"SAFE_MODE: {SAFE_MODE}")
    mats = load_a8_materials()
    registered = len(mats.get('programs', {}))
    print(f"登録済HTML素材: {registered}件")
    a8 = load_a8_master()
    print(f"マスター登録: {len(a8['programs'])}件")
    print(f"未登録 (HTML素材待ち): {len(a8['programs']) - registered}件")
