#!/usr/bin/env python3
"""high_imp_optimizer.py — 柱2: IMP上位+CTR低い既存記事の自動最適化

GSCメトリクスからIMP上位でCTR低い記事を検出し、
タイトル/メタディスクリプション/構造化データを自動改善。

毎週水曜6:00実行。

Usage:
  python3 scripts/high_imp_optimizer.py           # 実行
  python3 scripts/high_imp_optimizer.py --dry-run  # 確認のみ
  python3 scripts/high_imp_optimizer.py --limit 5  # 件数指定
"""
import sys, os, json, argparse, re, urllib.request, base64
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

BASE = '/home/aiuser/kpop-ai-system'
GSC_METRICS = os.path.join(BASE, 'data/gsc_metrics.jsonl')
OPTIMIZE_LOG = os.path.join(BASE, 'logs/high_imp_optimizer.jsonl')
JST = timezone(timedelta(hours=9))

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
WP_API = 'https://www.kpopjournal.tokyo/wp-json/wp/v2'


def load_candidates(min_imp=50, max_ctr=5.0, limit=10):
    """IMP上位+CTR低い記事を抽出"""
    if not os.path.exists(GSC_METRICS):
        return []
    pages = []
    with open(GSC_METRICS, encoding='utf-8') as f:
        for line in f:
            try:
                p = json.loads(line)
                if '#' in p.get('slug', ''):
                    continue
                if p.get('impressions', 0) >= min_imp and p.get('ctr', 0) < max_ctr:
                    p['potential'] = int(p['impressions'] * 0.10) - p.get('clicks', 0)
                    if p['potential'] > 0:
                        pages.append(p)
            except:
                pass
    # 既に最適化済みの記事を除外
    optimized = _load_optimized()
    pages = [p for p in pages if p.get('slug', '') not in optimized]
    pages.sort(key=lambda x: -x['potential'])
    return pages[:limit]


def _load_optimized():
    """最適化済みのslugを取得 (30日以内)"""
    slugs = set()
    if os.path.exists(OPTIMIZE_LOG):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        with open(OPTIMIZE_LOG, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if d.get('optimized_at', '') >= cutoff:
                        slugs.add(d.get('slug', ''))
                except:
                    pass
    return slugs


def fetch_post_by_slug(slug):
    """WP REST APIでslugから記事を取得"""
    try:
        url = f"{WP_API}/posts?slug={slug}&_fields=id,title,slug,excerpt,content&status=publish"
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        posts = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return posts[0] if posts else None
    except Exception as e:
        print(f"  fetch err: {e}")
        return None


def fetch_top_queries(slug, days=14):
    """対象記事のGSCトップクエリを取得 (検索意図を直接タイトルに反映)"""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        SA = '/home/aiuser/kpop-ai-system/google_metrics/service_account.json'
        SITE = 'https://www.kpopjournal.tokyo/'
        creds = service_account.Credentials.from_service_account_file(
            SA, scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
        service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
        from datetime import date as _date, timedelta as _td
        end = _date.today() - _td(days=2)
        start = end - _td(days=days)
        body = {
            "startDate": start.isoformat(), "endDate": end.isoformat(),
            "dimensions": ["query"],
            "dimensionFilterGroups": [{"filters": [{"dimension": "page", "operator": "equals",
                                                    "expression": f"{SITE}{slug}/"}]}],
            "rowLimit": 5,
        }
        res = service.searchanalytics().query(siteUrl=SITE, body=body).execute()
        return [(r['keys'][0], r['impressions'], r['clicks']) for r in res.get('rows', [])]
    except Exception:
        return []


def generate_improved_title(current_title, slug, impressions, ctr):
    """GPT-4o-miniで改善タイトルを生成 (実クエリ意図を反映)"""
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        return None

    # 実際のGSCクエリを取得して検索意図を可視化
    queries = fetch_top_queries(slug)
    query_block = '\n'.join(f'  - "{q}" ({imp} IMP / {clk} clk)' for q, imp, clk in queries[:5]) if queries else '  (取得不可)'

    current_year = datetime.now().year

    prompt = f"""以下のK-POP記事のタイトルを改善してください。

【現在のタイトル】{current_title}
【スラッグ】{slug}
【検索表示回数】{impressions}回
【クリック率】{ctr}% (低い=タイトルが検索意図に合っていない)

【実際の流入検索クエリ TOP5】
{query_block}

【改善要件】
1. 上記の実クエリの意図 (特に「いつ」「誰」「なぜ」等の疑問語) に直接応える
2. 具体的な情報を含める（年号、人数、比較対象、結論等）
3. 30-42文字以内（厳守）
4. **stale年度の禁止**: 過去の年号 ({current_year-1}年以前) は本文が当該年限定の場合のみ。
   現在 {current_year} 年なので、未来予定や継続事象なら {current_year} 年に更新
5. 煽り過ぎない、しかし疑問形・結論先出しで CTR を狙う
6. ローマ字検索が多い場合 (例: ojogang, illit) はタイトル冒頭に英字表記併記

【出力】改善後のタイトル1行のみ。前置き・解説不要。"""

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.7,
        'max_tokens': 100,
    }).encode()

    try:
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
            data=body, headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        result = r['choices'][0]['message']['content'].strip().strip('「」""')
        return result
    except Exception as e:
        print(f"  GPT err: {e}")
        return None


def generate_improved_meta(title, content_html):
    """メタディスクリプションを改善"""
    plain = re.sub(r'<[^>]+>', '', content_html[:2000]).strip()
    # 最初の文から80-150字のメタを抽出
    sentences = re.split(r'[。！？]', plain)
    meta = ''
    for s in sentences:
        s = s.strip()
        if not s or len(s) < 10:
            continue
        meta += s + '。'
        if len(meta) >= 80:
            break
    return meta[:155] if len(meta) >= 80 else None


def update_post(post_id, updates):
    """WP REST APIで記事を更新"""
    try:
        body = json.dumps(updates).encode()
        url = f"{WP_API}/posts/{post_id}"
        req = urllib.request.Request(url, data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"  update err: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--limit', type=int, default=10)
    args = parser.parse_args()

    now = datetime.now(JST)
    print(f"=== 柱2: 既存記事最適化 {now.strftime('%Y-%m-%d %H:%M')} ===")

    candidates = load_candidates(min_imp=50, max_ctr=5.0, limit=args.limit)
    print(f"  最適化候補: {len(candidates)}件")

    optimized = 0
    for c in candidates:
        slug = c.get('slug', '')
        imp = c.get('impressions', 0)
        ctr = c.get('ctr', 0)
        potential = c.get('potential', 0)
        print(f"\n  [{slug[:40]}] IMP={imp} CTR={ctr}% potential=+{potential}")

        post = fetch_post_by_slug(slug)
        if not post:
            print(f"    WP記事取得失敗")
            continue

        pid = post['id']
        current_title = post['title']['rendered'] if isinstance(post['title'], dict) else post['title']
        content = post.get('content', {}).get('rendered', '') if isinstance(post.get('content'), dict) else ''

        updates = {}
        changes = []

        # タイトル改善
        new_title = generate_improved_title(current_title, slug, imp, ctr)
        if new_title and new_title != current_title and len(new_title) <= 42:
            updates['title'] = new_title
            changes.append(f"title: {current_title[:30]} → {new_title[:30]}")
            print(f"    タイトル改善: {new_title[:40]}")
        else:
            print(f"    タイトル: 変更なし")

        # メタディスクリプション改善
        excerpt = post.get('excerpt', {}).get('rendered', '') if isinstance(post.get('excerpt'), dict) else ''
        plain_excerpt = re.sub(r'<[^>]+>', '', excerpt).strip()
        if len(plain_excerpt) < 80:
            new_meta = generate_improved_meta(current_title, content)
            if new_meta:
                updates['excerpt'] = new_meta
                changes.append(f"meta: {len(plain_excerpt)}→{len(new_meta)}字")
                print(f"    メタ改善: {len(new_meta)}字")

        if not updates:
            print(f"    最適化対象なし")
            continue

        if args.dry_run:
            print(f"    [DRY-RUN] 変更: {', '.join(changes)}")
            continue

        if update_post(pid, updates):
            optimized += 1
            # ログ記録
            os.makedirs(os.path.dirname(OPTIMIZE_LOG), exist_ok=True)
            with open(OPTIMIZE_LOG, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    'post_id': pid,
                    'slug': slug,
                    'changes': changes,
                    'before_ctr': ctr,
                    'impressions': imp,
                    'potential': potential,
                    'optimized_at': datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False) + '\n')

    print(f"\n=== 完了: {optimized}/{len(candidates)}件 最適化 ===")


if __name__ == '__main__':
    main()
