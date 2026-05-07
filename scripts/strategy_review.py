#!/usr/bin/env python3
"""strategy_review.py — コンテンツ戦略の週次/月次レビュー

毎週月曜6:00に自動実行。GSC実績とKPIを分析し、
content_strategy.json のテーマ配分を実績ベースで更新。
Discord報告 + 戦略ファイル更新。

Usage:
  python3 scripts/strategy_review.py              # 週次レビュー
  python3 scripts/strategy_review.py --monthly     # 月次レビュー
"""
import sys, os, json, argparse, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

BASE = '/home/aiuser/kpop-ai-system'
STRATEGY_PATH = os.path.join(BASE, 'config/content_strategy.json')
GSC_METRICS = os.path.join(BASE, 'data/gsc_metrics.jsonl')
FEATURE_LOG = os.path.join(BASE, 'logs/feature_articles.jsonl')
REVIEW_LOG = os.path.join(BASE, 'logs/strategy_review.jsonl')
JST = timezone(timedelta(hours=9))

# テーマ判定キーワード (content_strategy.json と同期)
THEME_KEYWORDS = {
    'イベント/ライブ': ['kcon', 'concert', 'coachella', 'tour', 'events-japan', 'mama', 'asea', 'festival', 'fanmeeting'],
    'ドラマ/エンタメ': ['demon-hunters', 'swf3', 'kdrama', 'confidence-man', 'phantom', 'drama', 'movie'],
    'ビューティー': ['beauty', 'cosmetics', 'makeup', 'skincare', 'lip', 'skin', 'diet', 'glass-skin'],
    '旅行': ['seoul', 'hongdae', 'myeongdong', 'travel', 'gourmet', 'cafe', 'trip', 'pilgrimage'],
    'ポップアップ': ['popup', 'pop-up'],
    'チャート': ['chart', 'billboard', 'ranking', 'top10'],
    '音楽番組': ['music-bank', 'inkigayo', 'show-champion', 'm-countdown', 'music-core'],
    'アーティストガイド': ['guide', 'beginner', 'profile', 'members', 'matome'],
    'アーティスト速報': ['comeback', 'release', 'album', 'mv', 'win', 'controversy'],
    '推し活': ['lightstick', 'oshi', 'goods', 'ticket', 'penlight', 'korean-learning'],
}


def load_gsc_metrics():
    """GSCメトリクスをテーマ別に集計"""
    if not os.path.exists(GSC_METRICS):
        return {}
    pages = []
    with open(GSC_METRICS, encoding='utf-8') as f:
        for line in f:
            try:
                pages.append(json.loads(line))
            except:
                pass

    theme_stats = {}
    for theme, keywords in THEME_KEYWORDS.items():
        matching = [p for p in pages if any(k in p.get('slug', '').lower() for k in keywords)]
        if matching:
            clicks = sum(p.get('clicks', 0) for p in matching)
            imp = sum(p.get('impressions', 0) for p in matching)
            ctr = clicks / imp * 100 if imp else 0
            theme_stats[theme] = {
                'articles': len(matching),
                'clicks': clicks,
                'impressions': imp,
                'ctr': round(ctr, 1),
                'efficiency': round(clicks / len(matching), 1) if matching else 0,
            }
    return theme_stats


def load_article_output(days=7):
    """直近N日の記事出力を集計"""
    if not os.path.exists(FEATURE_LOG):
        return {'total': 0, 'by_source': {}, 'by_category': {}}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    total = 0
    by_source = {}
    by_category = {}
    with open(FEATURE_LOG, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                if d.get('published_at', '') >= cutoff:
                    total += 1
                    src = d.get('source', 'unknown')
                    cat = d.get('category', 'unknown')
                    by_source[src] = by_source.get(src, 0) + 1
                    by_category[cat] = by_category.get(cat, 0) + 1
            except:
                pass
    return {'total': total, 'by_source': by_source, 'by_category': by_category}


def load_kpi_actuals():
    """直近のKPI実績を取得"""
    try:
        with open(os.path.join(BASE, 'google_metrics/metrics_yesterday.json'), encoding='utf-8') as f:
            m = json.load(f)
        ga = m.get('ga4', {}).get('summary', {})
        adsense = m.get('adsense', {})
        gsc = m.get('gsc', {})
        return {
            'date': m.get('date', ''),
            'pv': int(ga.get('pageviews', 0)),
            'sessions': int(ga.get('sessions', 0)),
            'revenue_yen': int(adsense.get('ESTIMATED_EARNINGS', 0)),
            'rpm': int(adsense.get('PAGE_VIEWS_RPM', 0)),
            'gsc_clicks': sum(p.get('clicks', 0) for p in gsc.get('top_pages', [])),
        }
    except Exception:
        return {}


def calculate_tier(theme_stats):
    """テーマ別にS/A/B/Cティアを再計算"""
    tiers = {'tier_s': {}, 'tier_a': {}, 'tier_b': {}, 'tier_c': {}}
    for theme, stats in theme_stats.items():
        eff = stats['efficiency']
        ctr = stats['ctr']
        if eff >= 7 or (eff >= 4 and ctr >= 6):
            tiers['tier_s'][theme] = stats
        elif ctr >= 5 or (eff >= 2 and ctr >= 4):
            tiers['tier_a'][theme] = stats
        elif eff >= 1.5 or ctr >= 3:
            tiers['tier_b'][theme] = stats
        else:
            tiers['tier_c'][theme] = stats
    return tiers


def compare_with_baseline(current_stats):
    """前週のベースラインと比較して成長/後退を判定"""
    try:
        with open(STRATEGY_PATH, encoding='utf-8') as f:
            strategy = json.load(f)
        baseline = strategy.get('baseline_metrics', {})
        comparisons = []
        if baseline.get('imp_per_day') and current_stats.get('imp_per_day'):
            diff = current_stats['imp_per_day'] - baseline['imp_per_day']
            pct = diff / baseline['imp_per_day'] * 100 if baseline['imp_per_day'] else 0
            direction = "↑" if diff > 0 else "↓"
            comparisons.append(f"IMP/日: {current_stats['imp_per_day']} ({direction}{abs(pct):.0f}% vs baseline {baseline['imp_per_day']})")
        if baseline.get('clicks_per_day') and current_stats.get('clicks_per_day'):
            diff = current_stats['clicks_per_day'] - baseline['clicks_per_day']
            direction = "↑" if diff > 0 else "↓"
            comparisons.append(f"clicks/日: {current_stats['clicks_per_day']} ({direction}{abs(diff)} vs baseline {baseline['clicks_per_day']})")
        return comparisons
    except Exception:
        return []


def generate_recommendations(tiers, article_output):
    """ティア分析+3本柱チェックからアクション項目を生成"""
    recs = []

    # 3本柱の実施状況チェック
    by_cat = article_output.get('by_category', {})
    total = article_output.get('total', 0)

    # Pillar 1: 当たり横展開 (ドラマ/イベント/視聴ガイド) は生成されているか
    winning_cats = sum(by_cat.get(c, 0) for c in ['kpop-news', 'kdrama-movie', 'kdrama_movie'])
    if total > 0 and winning_cats / total < 0.3:
        recs.append(f"[柱1不足] 当たり横展開(ドラマ/イベント/ガイド)が{winning_cats}/{total}件={winning_cats/total*100:.0f}%。目標30%以上")

    # Pillar 2: 既存記事更新は実施されているか
    # (feature_articlesログからsource='rewrite'を検出)
    rewrite_count = by_cat.get('rewrite', 0) + by_cat.get('update', 0)
    if rewrite_count < 5:
        recs.append(f"[柱2不足] 既存記事リライト={rewrite_count}件/週。目標10件/週")

    # Pillar 3: テンプレ偏重チェック
    template_count = article_output.get('by_source', {}).get('template', 0)
    if total > 0 and template_count / total > 0.5:
        recs.append(f"[柱3警告] テンプレート比率={template_count/total*100:.0f}%。検索駆動記事を増やすべき")

    # Tier S: 増産推奨
    for theme in tiers.get('tier_s', {}):
        recs.append(f"[増産] {theme}: 効率{tiers['tier_s'][theme]['efficiency']}。記事数を増やす価値あり")

    # Tier C: 削減推奨
    for theme in tiers.get('tier_c', {}):
        stats = tiers['tier_c'][theme]
        if stats['articles'] > 10:
            recs.append(f"[削減] {theme}: {stats['articles']}記事でCTR{stats['ctr']}%。量産を停止し質を改善")

    # カテゴリ偏り検出
    if total > 0:
        for cat, count in by_cat.items():
            ratio = count / total * 100
            if ratio > 40:
                recs.append(f"[偏り] {cat}が{ratio:.0f}% ({count}/{total}件)。分散を検討")

    return recs


def update_strategy(tiers, recommendations):
    """content_strategy.json を更新"""
    with open(STRATEGY_PATH, encoding='utf-8') as f:
        strategy = json.load(f)

    now = datetime.now(JST)
    strategy['last_reviewed'] = now.strftime('%Y-%m-%d')
    strategy['next_review'] = (now + timedelta(days=7)).strftime('%Y-%m-%d')

    # ティア更新
    for tier_name, themes in tiers.items():
        strategy['theme_performance'][tier_name] = {}
        comments = {
            'tier_s': '高効率・高CTR。増産すべき',
            'tier_a': 'CTR高いが記事少ない。伸びしろ大',
            'tier_b': '記事数多いが効率低い。質の改善必要',
            'tier_c': '効率最低。量を減らすか方針転換',
        }
        strategy['theme_performance'][tier_name]['_comment'] = comments.get(tier_name, '')
        for theme, stats in themes.items():
            strategy['theme_performance'][tier_name][theme] = stats

    with open(STRATEGY_PATH, 'w', encoding='utf-8') as f:
        json.dump(strategy, f, ensure_ascii=False, indent=2)

    return strategy


def build_report(tiers, article_output, kpi, recommendations, is_monthly=False):
    """Discord報告用テキスト生成"""
    period = "月次" if is_monthly else "週次"
    lines = [f"## コンテンツ戦略{period}レビュー"]

    # KPI
    if kpi:
        lines.append(f"\n**KPI実績** (最新: {kpi.get('date', '?')})")
        lines.append(f"- PV: {kpi.get('pv', '?')}/日 (目標1,000)")
        lines.append(f"- 収益: ¥{kpi.get('revenue_yen', '?')}/日 (目標¥300)")
        lines.append(f"- GSCクリック: {kpi.get('gsc_clicks', '?')}/日")

    # 記事出力
    lines.append(f"\n**記事出力** (直近7日)")
    lines.append(f"- 合計: {article_output.get('total', 0)}件")
    for src, cnt in sorted(article_output.get('by_source', {}).items(), key=lambda x: -x[1]):
        lines.append(f"  - {src}: {cnt}件")

    # ティア
    lines.append("\n**テーマ別ティア** (GSC実績ベース)")
    for tier_name, label in [('tier_s', 'S(増産)'), ('tier_a', 'A(伸びしろ)'),
                              ('tier_b', 'B(要改善)'), ('tier_c', 'C(要削減)')]:
        themes = tiers.get(tier_name, {})
        if themes:
            theme_list = ', '.join(f"{t}(効率{s['efficiency']})" for t, s in themes.items())
            lines.append(f"- {label}: {theme_list}")

    # ベースライン比較
    comparisons = compare_with_baseline(kpi)
    if comparisons:
        lines.append("\n**前週比較**")
        for c in comparisons:
            lines.append(f"- {c}")

    # 推奨アクション
    if recommendations:
        lines.append("\n**推奨アクション**")
        for r in recommendations[:7]:
            lines.append(f"- {r}")

    # 週次チェックリスト
    try:
        with open(STRATEGY_PATH, encoding='utf-8') as f:
            strategy = json.load(f)
        checklist = strategy.get('weekly_review_checklist', []) if not is_monthly else strategy.get('monthly_review_checklist', [])
        if checklist:
            lines.append(f"\n**確認事項**")
            for item in checklist:
                lines.append(f"- [ ] {item}")
    except Exception:
        pass

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--monthly', action='store_true', help='月次レビュー')
    args = parser.parse_args()

    now = datetime.now(JST)
    period = "月次" if args.monthly else "週次"
    days = 30 if args.monthly else 7
    print(f"=== コンテンツ戦略{period}レビュー: {now.strftime('%Y-%m-%d %H:%M')} ===")

    # 1. データ収集
    theme_stats = load_gsc_metrics()
    article_output = load_article_output(days=days)
    kpi = load_kpi_actuals()

    print(f"  テーマ別データ: {len(theme_stats)}テーマ")
    print(f"  記事出力: {article_output['total']}件 ({days}日間)")

    # 2. ティア再計算
    tiers = calculate_tier(theme_stats)
    for tier_name, themes in tiers.items():
        if themes:
            print(f"  {tier_name}: {', '.join(themes.keys())}")

    # 3. 推奨アクション生成
    recommendations = generate_recommendations(tiers, article_output)
    for r in recommendations:
        print(f"  {r}")

    # 4. 戦略ファイル更新
    strategy = update_strategy(tiers, recommendations)
    print(f"\n  content_strategy.json 更新完了 (next_review: {strategy['next_review']})")

    # 5. レポート生成
    report = build_report(tiers, article_output, kpi, recommendations, is_monthly=args.monthly)
    print(f"\n{report}")

    # 6. Discord報告
    try:
        from lib.discord_channel_router import send_to_channel, ChannelType
        title = f"コンテンツ戦略{period}レビュー {now.strftime('%m/%d')}"
        results = send_to_channel(ChannelType.DAILY_REPORT, title, report)
        for r in results:
            print(f"  Discord [{r['physical_channel']}]: {r['result']}")
    except Exception as e:
        print(f"  Discord送信失敗: {e}")

    # 7. ログ保存
    os.makedirs(os.path.dirname(REVIEW_LOG), exist_ok=True)
    with open(REVIEW_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'reviewed_at': now.isoformat(),
            'period': period,
            'theme_stats': theme_stats,
            'tiers': {k: list(v.keys()) for k, v in tiers.items()},
            'recommendations': recommendations,
            'kpi': kpi,
            'article_output': article_output,
        }, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
