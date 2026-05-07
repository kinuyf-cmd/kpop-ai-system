#!/usr/bin/env python3
"""
検索駆動記事生成 — GSCデータから検索需要を特定し記事シグナルを自動生成

戦略v2 柱3: 検索ボリュームがある → 記事生成（逆はやらない）

処理フロー:
  1. GSC 28日データから「IMP高+CTR低」の既存記事を抽出 → 横展開候補
  2. GSC上昇クエリから「記事が存在しない検索キーワード」を抽出 → 新規記事候補
  3. auto_directives.json に focus_themes として注入
"""
import sys
import os
import json
import re

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv('/home/aiuser/kpop-ai-system/.env')

BASE = '/home/aiuser/kpop-ai-system'
JST = timezone(timedelta(hours=9))
GSC_METRICS = os.path.join(BASE, 'logs/gsc_metrics_latest.json')
DIRECTIVES = os.path.join(BASE, 'config/auto_directives.json')
SIGNALS_PATH = os.path.join(BASE, 'data/trend_signals.jsonl')

# 横展開のIMP/CTR閾値
MIN_IMP_FOR_EXPANSION = 200   # IMP 200以上
MAX_CTR_FOR_EXPANSION = 0.03  # CTR 3%以下（改善余地あり）
MAX_THEMES_PER_RUN = 5


def load_gsc_data():
    """GSC 28日データを読み込み"""
    try:
        return json.loads(open(GSC_METRICS, encoding='utf-8').read())
    except Exception:
        return {}


def load_existing_slugs():
    """既存記事のslugリストを取得（重複防止）"""
    try:
        import urllib.request
        import base64
        auth = base64.b64encode(
            f"{os.getenv('WP_USER', '')}:{os.getenv('WP_PASS', '')}".encode()
        ).decode()
        slugs = set()
        for page in range(1, 5):
            url = (f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
                   f"?per_page=100&page={page}&_fields=slug&status=publish")
            req = urllib.request.Request(url, headers={'Authorization': f'Basic {auth}'})
            try:
                posts = json.loads(urllib.request.urlopen(req, timeout=15).read())
                for p in posts:
                    slugs.add(p.get('slug', ''))
            except Exception:
                break
        return slugs
    except Exception:
        return set()


def find_expansion_opportunities(gsc_data):
    """IMP高+CTR低の記事から横展開候補を抽出"""
    pages = gsc_data.get('pages', [])
    opportunities = []

    for p in pages:
        imp = p.get('impressions', 0)
        ctr = p.get('ctr', 0)
        clicks = p.get('clicks', 0)
        url = p.get('url', '')

        # トップページやポップアップ一覧は除外
        if url.rstrip('/').endswith('kpopjournal.tokyo') or '/popup/' in url:
            continue
        if imp >= MIN_IMP_FOR_EXPANSION and ctr <= MAX_CTR_FOR_EXPANSION:
            # URLからスラッグ抽出
            slug = url.rstrip('/').split('/')[-1] if url else ''
            # 潜在クリック = IMP × (目標CTR 10% - 現CTR)
            potential = imp * (0.10 - ctr)

            opportunities.append({
                'url': url,
                'slug': slug,
                'impressions': imp,
                'ctr': ctr,
                'clicks': clicks,
                'potential_clicks': round(potential),
            })

    # 潜在クリック数順にソート
    opportunities.sort(key=lambda x: x['potential_clicks'], reverse=True)
    return opportunities[:10]


def find_unserved_queries(gsc_data, existing_slugs):
    """GSCクエリで記事が存在しない検索キーワードを抽出"""
    queries = gsc_data.get('queries', [])
    unserved = []

    for q in queries:
        query = q.get('query', '')
        imp = q.get('impressions', 0)
        clicks = q.get('clicks', 0)

        if imp < 10:
            continue

        # クエリのキーワードが既存slugに含まれるか
        query_slug = re.sub(r'[^a-z0-9]+', '-', query.lower()).strip('-')
        query_words = set(re.findall(r'[a-z0-9]+', query.lower()))

        # 既存slugとの部分一致チェック
        has_article = any(
            len(query_words & set(re.findall(r'[a-z0-9]+', s))) >= max(2, len(query_words) - 1)
            for s in existing_slugs if s
        )

        if not has_article and len(query) > 3:
            unserved.append({
                'query': query,
                'impressions': imp,
                'clicks': clicks,
            })

    unserved.sort(key=lambda x: x['impressions'], reverse=True)
    return unserved[:10]


def generate_themes(opportunities, unserved):
    """横展開候補+未記事化クエリからauto_directives用テーマを生成"""
    themes = []
    now = datetime.now(JST)

    # 1. 横展開テーマ（CTR改善用の関連記事）
    for opp in opportunities[:3]:
        slug = opp['slug']
        # slugから記事テーマを推定
        title_words = slug.replace('-', ' ').title()
        themes.append({
            'topic': f'{title_words} 関連ガイド・まとめ',
            'hint': (
                f"GSC横展開: 元記事/{slug}/ IMP={opp['impressions']} CTR={opp['ctr']:.1%}。"
                f"潜在+{opp['potential_clicks']}clicks。"
                f"関連キーワードで横展開記事を作成。シグナル: search_driven"
            ),
            'category_suggest': 'まとめ',
            'added_at': now.strftime('%Y-%m-%d'),
            'source': 'search_driven_expansion',
            'buzz_score': min(50, opp['potential_clicks'] / 5),
            'expires_at': (now + timedelta(days=14)).strftime('%Y-%m-%d'),
        })

    # 2. 未記事化クエリ（検索需要があるのに記事がない）
    for uq in unserved[:MAX_THEMES_PER_RUN - len(themes)]:
        themes.append({
            'topic': uq['query'],
            'hint': (
                f"検索需要あり: '{uq['query']}' IMP={uq['impressions']}。"
                f"該当記事なし。検索意図を満たす実用記事を生成。シグナル: search_driven"
            ),
            'category_suggest': 'K-POPニュース',
            'added_at': now.strftime('%Y-%m-%d'),
            'source': 'search_driven_query',
            'buzz_score': min(40, uq['impressions'] / 5),
            'expires_at': (now + timedelta(days=7)).strftime('%Y-%m-%d'),
        })

    return themes


def inject_to_directives(themes):
    """auto_directives.jsonのfocus_themesに注入"""
    try:
        data = json.loads(open(DIRECTIVES, encoding='utf-8').read())
    except Exception:
        data = {'focus_themes': []}

    existing_topics = {t.get('topic', '') for t in data.get('focus_themes', [])}
    injected = 0

    for theme in themes:
        if theme['topic'] in existing_topics:
            continue
        data.setdefault('focus_themes', []).append(theme)
        existing_topics.add(theme['topic'])
        injected += 1
        print(f"  注入: [{theme['source']}] {theme['topic'][:50]}")

    # 期限切れテーマの削除
    today = datetime.now(JST).strftime('%Y-%m-%d')
    before = len(data['focus_themes'])
    data['focus_themes'] = [
        t for t in data['focus_themes']
        if t.get('expires_at', '9999-12-31') >= today
    ]
    expired = before - len(data['focus_themes'])

    with open(DIRECTIVES, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return injected, expired


def main():
    now = datetime.now(JST)
    print(f"=== search_driven_generator: {now.strftime('%Y-%m-%d %H:%M')} ===")

    gsc_data = load_gsc_data()
    if not gsc_data.get('pages'):
        print("  GSCデータなし、スキップ")
        return

    print(f"  GSCデータ: {len(gsc_data.get('pages', []))}ページ")

    # 1. 横展開候補
    opportunities = find_expansion_opportunities(gsc_data)
    print(f"  横展開候補: {len(opportunities)}件")
    for o in opportunities[:3]:
        print(f"    {o['slug'][:40]} IMP={o['impressions']} CTR={o['ctr']:.1%} "
              f"potential=+{o['potential_clicks']}clicks")

    # 2. 未記事化クエリ
    existing_slugs = load_existing_slugs()
    unserved = find_unserved_queries(gsc_data, existing_slugs)
    print(f"  未記事化クエリ: {len(unserved)}件")
    for u in unserved[:3]:
        print(f"    '{u['query']}' IMP={u['impressions']}")

    # 3. テーマ生成+注入
    themes = generate_themes(opportunities, unserved)
    injected, expired = inject_to_directives(themes)
    print(f"\n  注入: {injected}件 / 期限切れ削除: {expired}件")


if __name__ == '__main__':
    main()
