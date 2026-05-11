#!/usr/bin/env python3
"""chart_article_generator.py — Circle Chart週次データから記事を自動生成

scrape_circle_chart.py の後に実行。
chart_weekly_manual.json のデータを元に「今週のK-POPチャートTOP10」記事を生成・公開。

Usage:
  python3 scripts/chart_article_generator.py
  python3 scripts/chart_article_generator.py --dry-run
"""
import sys, os, json, argparse, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

CHART_DATA = '/home/aiuser/kpop-ai-system/data/chart_weekly_manual.json'
PUBLISH_LOG = '/home/aiuser/kpop-ai-system/logs/chart_article.jsonl'
CHART_CATEGORY_ID = 71  # K-POPチャート
JST = timezone(timedelta(hours=9))


def load_chart():
    with open(CHART_DATA, encoding='utf-8') as f:
        return json.load(f)


def is_already_published(week_label):
    """同じ週のチャート記事が既に公開済みか"""
    if not os.path.exists(PUBLISH_LOG):
        return False
    with open(PUBLISH_LOG, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                if d.get('week_label') == week_label:
                    return True
            except:
                pass
    return False


ARTIST_JA = {
    '투모로우바이투게더': 'TXT',
    '포레스텔라': 'Forestella',
    '악뮤': 'AKMU',
    '동해': 'DONGHAE(東海)',
    '화사': 'HWASA(ファサ)',
    '손태진': 'ソン・テジン',
    '박지훈': 'パク・ジフン',
    '넥스지': 'NEXZ',
    '투어스': 'TWS',
}


def _to_ja(name):
    """韓国語アーティスト名を日本語表記に変換"""
    # 「English (Korean)」形式なら先頭英語部分を採用
    m = re.match(r'^([A-Za-z][\w\s\.\-&]*?)\s*\([^A-Za-z]*\)\s*$', name)
    if m:
        return m.group(1).strip()
    # マッピング辞書
    for ko, ja in ARTIST_JA.items():
        if ko in name:
            return ja
    # 英語名が括弧内にあればそれを使用
    m = re.search(r'\(([A-Za-z][\w\s]+)\)', name)
    if m:
        return m.group(1)
    return name


def build_article(chart):
    """チャートデータから記事HTML + タイトルを生成"""
    entries = chart['entries']
    week_label = chart.get('week_label', '')
    source = chart.get('source', 'Circle Chart')
    now = datetime.now(JST)

    # 1位アーティスト (日本語表記に変換)
    top = entries[0]
    top_artist = _to_ja(top['artist'])
    top_title = top['title']

    # ランキング変動分析
    new_entries = []
    rising = []
    for e in entries:
        prev = e.get('prevRank')
        if prev is None:
            new_entries.append(e)
        elif prev > e['rank']:
            rising.append(e)

    # タイトル生成
    title = f"{top_artist}が首位｜K-POPチャートTOP10【{week_label}】"
    if len(title) > 42:
        title = f"{top_artist}首位｜K-POPチャートTOP10【{week_label}】"
    if len(title) > 42:
        title = f"K-POPチャートTOP10速報｜{week_label}"

    # HTML生成
    parts = []

    # 3行まとめ (enricherのgenerate_summaryに任せるとテーブルが混入するため自前で生成)
    second_artist = _to_ja(entries[1]['artist']) if len(entries) > 1 else ''
    multi_preview = [f'{_to_ja(a)}({c}曲)' for a, c in
                     sorted({e['artist']: sum(1 for x in entries if x['artist'] == e['artist']) for e in entries}.items(),
                            key=lambda x: -x[1]) if c >= 2]
    summary_lines = [
        f'{source} {week_label}のストリーミングチャートTOP10速報',
        f'1位は{top_artist}「{top_title}」、2位は{second_artist}',
    ]
    if multi_preview:
        summary_lines.append(f'{", ".join(multi_preview[:2])}が複数曲ランクイン')
    else:
        summary_lines.append(f'{len(new_entries)}曲が新規ランクイン')

    parts.append('<div class="kpj-summary">')
    parts.append('<h4>この記事の3行まとめ</h4>')
    parts.append('<ul>')
    for line in summary_lines[:3]:
        parts.append(f'<li>{line}</li>')
    parts.append('</ul>')
    parts.append('</div>')

    # リード文
    parts.append(
        f'<p>{now.strftime("%Y年%m月%d日")}更新の{source}ストリーミングチャートをお届けします。'
        f'今週の1位は<strong>{top_artist}</strong>の「{top_title}」です。</p>'
    )

    # ランキングテーブル
    parts.append('<h2>今週のK-POPチャートTOP10</h2>')
    parts.append('<table class="kpj-chart-table">')
    parts.append('<thead><tr><th>順位</th><th>曲名</th><th>アーティスト</th><th>前週</th></tr></thead>')
    parts.append('<tbody>')
    for e in entries:
        rank = e['rank']
        prev = e.get('prevRank')
        if prev is None:
            change = '<span style="color:#e53e3e;">NEW</span>'
        elif prev > rank:
            change = f'<span style="color:#38a169;">{prev}位→{rank}位 ↑</span>'
        elif prev < rank:
            change = f'<span style="color:#e53e3e;">{prev}位→{rank}位 ↓</span>'
        else:
            change = f'{prev}位→'
        parts.append(
            f'<tr><td><strong>{rank}</strong></td>'
            f'<td>「{e["title"]}」</td>'
            f'<td>{_to_ja(e["artist"])}</td>'
            f'<td>{change}</td></tr>'
        )
    parts.append('</tbody></table>')

    # 分析セクション
    parts.append('<h2>今週の注目ポイント</h2>')

    # 1位コメント
    parts.append(f'<p><strong>{top_artist}</strong>が「{top_title}」で今週も首位を獲得しました。</p>')

    # 同一アーティストの複数ランクイン
    artist_counts = {}
    for e in entries:
        a = e['artist']
        artist_counts[a] = artist_counts.get(a, 0) + 1
    multi = {a: c for a, c in artist_counts.items() if c >= 2}
    if multi:
        for a, c in sorted(multi.items(), key=lambda x: -x[1]):
            songs = [e['title'] for e in entries if e['artist'] == a]
            ja_name = _to_ja(a)
            parts.append(
                f'<p><strong>{ja_name}</strong>はTOP10に{c}曲同時ランクイン'
                f'（{", ".join(f"「{s}」" for s in songs)}）。チャートを席巻しています。</p>'
            )

    # NEWエントリー
    if new_entries:
        parts.append('<p>今週の新規ランクインは')
        news = [f'{_to_ja(e["artist"])}「{e["title"]}」（{e["rank"]}位）' for e in new_entries]
        parts.append('、'.join(news) + 'です。</p>')

    # データソース
    parts.append(
        f'<p class="kpj-chart-source">出典: {source} '
        f'({chart.get("week", "")})</p>'
    )

    # 内部リンク
    parts.append(
        '<p>K-POPチャートの最新情報は'
        '<a href="https://www.kpopjournal.tokyo/category/kpop-chart/">チャート一覧ページ</a>'
        'でもご覧いただけます。</p>'
    )

    body = '\n'.join(parts)
    return title, body


def publish(title, body, chart, dry_run=False):
    """unified_publishで公開"""
    from lib.unified_publisher import unified_publish

    if dry_run:
        print(f'[DRY-RUN] タイトル: {title}')
        print(f'[DRY-RUN] 本文: {len(body)}文字')
        return None

    result = unified_publish(
        raw_title=title,
        body_html=body,
        source_url='https://circlechart.kr/page_chart/onoff.circle?serviceGbn=S1020',
        kind='news',
        confidence='high',
        force_category_id=CHART_CATEGORY_ID,
    )

    post_id = result.get('post_id')
    if post_id:
        print(f'公開完了: post_id={post_id}')
        # ログ記録
        os.makedirs(os.path.dirname(PUBLISH_LOG), exist_ok=True)
        with open(PUBLISH_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'post_id': post_id,
                'week_label': chart.get('week_label', ''),
                'week': chart.get('week', ''),
                'title': title,
                'published_at': datetime.now(JST).isoformat(),
            }, ensure_ascii=False) + '\n')
    else:
        print(f'公開失敗: {result}')

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    if not os.path.exists(CHART_DATA):
        print('chart_weekly_manual.json が見つかりません')
        return

    chart = load_chart()
    week_label = chart.get('week_label', '')
    print(f'=== チャート記事生成: {week_label} ===')

    if is_already_published(week_label):
        print(f'この週の記事は公開済みです: {week_label}')
        return

    entries = chart.get('entries', [])
    if len(entries) < 5:
        print(f'エントリ不足: {len(entries)}件')
        return

    title, body = build_article(chart)
    print(f'タイトル: {title} ({len(title)}字)')
    print(f'本文: {len(body)}文字')

    result = publish(title, body, chart, dry_run=args.dry_run)
    if result and result.get('post_id'):
        # 統一ポストパブリッシュフック
        try:
            from lib.post_publish_hook import run_post_publish
            run_post_publish(result['post_id'])
        except Exception as e:
            print(f'hook err: {e}')


if __name__ == '__main__':
    main()
