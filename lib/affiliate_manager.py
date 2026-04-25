#!/usr/bin/env python3
"""アフィリエイト4社統合管理 (A8/Amazon/楽天/Qoo10)"""
import os, json, urllib.parse
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

A8NET_MEDIA_ID = os.getenv('A8NET_MEDIA_ID', '')
AMAZON_ASSOCIATE_TAG = os.getenv('AMAZON_ASSOCIATE_TAG', '')

CONFIG_DIR = '/home/aiuser/kpop-ai-system/config/affiliate'
A8_MASTER_PATH = f'{CONFIG_DIR}/a8_master.json'
QOO10_PRODUCTS_PATH = f'{CONFIG_DIR}/qoo10_products.json'


def load_a8_master():
    with open(A8_MASTER_PATH, encoding='utf-8') as f:
        return json.load(f)


def load_qoo10_products():
    if not os.path.exists(QOO10_PRODUCTS_PATH):
        return {'products': []}
    with open(QOO10_PRODUCTS_PATH, encoding='utf-8') as f:
        return json.load(f)


def build_a8_link(program_key, click_text='詳細はこちら'):
    """A8アフィリリンク生成 (PID + MEDIA_ID)"""
    if not A8NET_MEDIA_ID:
        return None

    a8 = load_a8_master()
    prog = a8['programs'].get(program_key)
    if not prog:
        return None

    pid = prog['pid']
    return f"https://px.a8.net/svt/ejp?a8mat={A8NET_MEDIA_ID}&a8ejpredirect=&pid={pid}"


def build_a8_link_with_html(program_key, link_text=None):
    """A8リンクをHTMLとして生成 (画像impressionピクセル付き)"""
    if not A8NET_MEDIA_ID:
        return None

    a8 = load_a8_master()
    prog = a8['programs'].get(program_key)
    if not prog:
        return None

    pid = prog['pid']
    name = prog['name']
    text = link_text or f"▶ {name}"

    click_url = f"https://px.a8.net/svt/ejp?a8mat={A8NET_MEDIA_ID}&a8ejpredirect=https%3A%2F%2Fwww.a8.net%2Fp%2F{pid}%2F"
    pixel = f"https://www16.a8.net/0.gif?a8mat={A8NET_MEDIA_ID}&pid={pid}"

    html = f'''<a href="{click_url}" rel="nofollow sponsored" target="_blank" class="kpj-aff-a8" data-program="{program_key}">{text}</a>
<img border="0" width="1" height="1" src="{pixel}" alt="" style="display:none">'''
    return html


def build_amazon_search_link(query, link_text=None):
    """Amazonアフィリ検索リンク"""
    if not AMAZON_ASSOCIATE_TAG:
        return None

    encoded = urllib.parse.quote(query)
    url = f"https://www.amazon.co.jp/s?k={encoded}&tag={AMAZON_ASSOCIATE_TAG}"
    text = link_text or f"Amazonで「{query}」を検索"

    return f'<a href="{url}" rel="nofollow sponsored" target="_blank" class="kpj-aff-amazon">{text}</a>'


def build_amazon_product_link(asin, link_text=None):
    """Amazon商品個別リンク (ASIN指定)"""
    if not AMAZON_ASSOCIATE_TAG:
        return None

    url = f"https://www.amazon.co.jp/dp/{asin}/?tag={AMAZON_ASSOCIATE_TAG}"
    text = link_text or "Amazonで購入"
    return f'<a href="{url}" rel="nofollow sponsored" target="_blank" class="kpj-aff-amazon">{text}</a>'


def build_rakuten_search_link(query, link_text=None):
    """楽天検索リンク (A8経由)"""
    if not A8NET_MEDIA_ID:
        return None

    rakuten_url = f"https://search.rakuten.co.jp/search/mall/{urllib.parse.quote(query)}/"
    a8_redirect = urllib.parse.quote(rakuten_url, safe='')
    pid = "s00000011623001"

    url = f"https://px.a8.net/svt/ejp?a8mat={A8NET_MEDIA_ID}&pid={pid}&a8ejpredirect={a8_redirect}"
    text = link_text or f"楽天で「{query}」を検索"
    return f'<a href="{url}" rel="nofollow sponsored" target="_blank" class="kpj-aff-rakuten">{text}</a>'


def build_qoo10_link(product_id_or_url, link_text=None):
    """Qoo10商品リンク (個別マスターから)"""
    products = load_qoo10_products()

    matched = None
    for p in products.get('products', []):
        if p.get('id') == product_id_or_url or p.get('url') == product_id_or_url:
            matched = p
            break

    if matched:
        url = matched.get('url', '')
        if url and url != 'TODO':
            text = link_text or f"Qoo10で「{matched['name']}」を見る"
            return f'<a href="{url}" rel="nofollow sponsored" target="_blank" class="kpj-aff-qoo10">{text}</a>'

    return None


def get_program_metadata(program_key):
    """A8案件のメタデータ取得"""
    a8 = load_a8_master()
    return a8['programs'].get(program_key)


def list_programs_by_category(category):
    """カテゴリで案件を絞り込み"""
    a8 = load_a8_master()
    return [(k, v) for k, v in a8['programs'].items()
            if category in v.get('categories', [])]


def list_programs_by_tier(tier=1):
    """tier別 (1=最優先, 2=中, 3=補助)"""
    a8 = load_a8_master()
    return [(k, v) for k, v in a8['programs'].items() if v.get('tier') == tier]


if __name__ == '__main__':
    print("=== A8案件マスター ===")
    a8 = load_a8_master()
    print(f"案件数: {len(a8['programs'])}")
    print(f"\nTier 1案件:")
    for k, v in list_programs_by_tier(1):
        print(f"  - {k}: {v['name']}")

    print(f"\n=== サンプルリンク生成 ===")
    if A8NET_MEDIA_ID:
        link = build_a8_link_with_html('amazon_prime_video', 'Amazon Prime Videoで見る')
        print(f"A8 Prime Video: {link[:100] if link else 'None'}")
    if AMAZON_ASSOCIATE_TAG:
        link = build_amazon_search_link('BTS アルバム')
        print(f"Amazon BTS: {link[:100] if link else 'None'}")
    if A8NET_MEDIA_ID:
        link = build_rakuten_search_link('SEVENTEEN CD')
        print(f"楽天 SEVENTEEN: {link[:100] if link else 'None'}")
