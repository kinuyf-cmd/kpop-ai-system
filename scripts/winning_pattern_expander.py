#!/usr/bin/env python3
"""winning_pattern_expander.py — 柱1: 当たりパターンの自動横展開

Soompi RSS/trend_signalsから新ドラマ・イベント・番組を検知し、
実績のある記事パターン(キャスト表/ガイド/視聴方法)でauto_directivesに注入。

毎日8:30に実行。

Usage:
  python3 scripts/winning_pattern_expander.py
  python3 scripts/winning_pattern_expander.py --dry-run
"""
import sys, os, json, argparse, re, urllib.request
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

BASE = '/home/aiuser/kpop-ai-system'
DIRECTIVES = os.path.join(BASE, 'config/auto_directives.json')
SIGNALS = os.path.join(BASE, 'data/trend_signals.jsonl')
EXPAND_LOG = os.path.join(BASE, 'logs/winning_pattern_expander.jsonl')
JST = timezone(timedelta(hours=9))

# 実績のある当たりパターン (IMP効率100+)
WINNING_PATTERNS = [
    {
        'id': 'drama_cast',
        'detect_keywords': ['ドラマ', 'drama', '주연', '출연', 'cast', 'premiere', '初回', '放送開始'],
        'title_template': '{title} キャスト・相関図・登場人物まとめ【{year}年】',
        'category': '深掘り',
        'buzz_score': 18.0,
        'reason': 'demon-hunters型:IMP効率164, CTR6.5%',
    },
    {
        'id': 'event_guide',
        'detect_keywords': ['フェス', 'festival', 'concert', 'コンサート', 'ライブ', 'tour', 'ツアー', '来日', 'japan', 'fanmeeting', 'fan meeting', 'ファンミーティング', 'ファンミ', 'showcase', 'ショーケース'],
        'title_template': '{title} 日程・チケット・参加方法まとめ【{year}年】',
        'category': '速報',
        'buzz_score': 15.0,
        'reason': 'KCON型:IMP効率104, CTR6.5%',
    },
    {
        'id': 'how_to_watch',
        'detect_keywords': ['放送', 'broadcast', '配信', 'streaming', '視聴', 'watch'],
        'title_template': '{title}を日本から見る方法【{year}年最新】',
        'category': '深掘り',
        'buzz_score': 14.0,
        'reason': 'show-champion型:CTR7.1%, 実用情報',
    },
]


def load_recent_signals(hours=24):
    """直近N時間のシグナルを取得"""
    if not os.path.exists(SIGNALS):
        return []
    cutoff = datetime.now() - timedelta(hours=hours)
    signals = []
    with open(SIGNALS, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                ts = datetime.fromisoformat(d.get('timestamp', '')[:19])
                if ts >= cutoff:
                    signals.append(d)
            except:
                pass
    return signals


def load_soompi_rss():
    """Soompi RSSから最新記事タイトルを取得"""
    try:
        from xml.etree import ElementTree as ET
        url = "https://www.soompi.com/feed"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = urllib.request.urlopen(req, timeout=15).read()
        root = ET.fromstring(data)
        items = []
        for item in root.iter('item'):
            items.append({
                'title': item.findtext('title', ''),
                'url': item.findtext('link', ''),
            })
        return items
    except Exception as e:
        print(f"  Soompi RSS err: {e}")
        return []


def _already_expanded(topic_key):
    """同じトピックを既に展開済みか (30日以内)"""
    if not os.path.exists(EXPAND_LOG):
        return False
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    with open(EXPAND_LOG, encoding='utf-8') as f:
        for line in f:
            try:
                d = json.loads(line)
                if d.get('topic_key') == topic_key and d.get('expanded_at', '') >= cutoff:
                    return True
            except:
                pass
    return False


def detect_expansion_opportunities(signals, soompi_items):
    """当たりパターンに合致する新トピックを検出"""
    opportunities = []
    all_titles = [s.get('title', '') for s in signals] + [i.get('title', '') for i in soompi_items]

    for pattern in WINNING_PATTERNS:
        for title in all_titles:
            # パターンのキーワードにマッチするか
            matched_kw = [kw for kw in pattern['detect_keywords'] if kw.lower() in title.lower()]
            if not matched_kw:
                continue

            # アーティスト/番組名を抽出
            # Soompi形式: "Artist Does Something" or "New Drama Title Premiere"
            subject = title.split(' ')[0:3]
            subject_text = ' '.join(subject).strip()[:30]

            topic_key = f"{pattern['id']}:{subject_text[:15]}"
            if _already_expanded(topic_key):
                continue

            year = datetime.now(JST).year
            expanded_title = pattern['title_template'].format(
                title=subject_text, year=year
            )

            opportunities.append({
                'pattern_id': pattern['id'],
                'topic_key': topic_key,
                'source_title': title[:80],
                'expanded_title': expanded_title,
                'category': pattern['category'],
                'buzz_score': pattern['buzz_score'],
                'reason': pattern['reason'],
                'matched_keywords': matched_kw,
            })

    # 重複排除 + パターン別に枠確保 (1パターン×Nタイトルで他pattern_idが押し出されないよう)
    seen = set()
    by_pattern: dict[str, list] = {}
    for opp in opportunities:
        key = opp['topic_key']  # topic_key は既に pattern_id を含む
        if key in seen:
            continue
        seen.add(key)
        by_pattern.setdefault(opp['pattern_id'], []).append(opp)

    # 各パターンから最大2件、全体最大6件
    PER_PATTERN = 2
    TOTAL_CAP = 6
    result = []
    for pid, opps in by_pattern.items():
        result.extend(opps[:PER_PATTERN])
    return result[:TOTAL_CAP]


def inject_to_directives(opportunities, dry_run=False):
    """auto_directivesにfocus_themesとして注入"""
    if not opportunities:
        return 0

    try:
        with open(DIRECTIVES, encoding='utf-8') as f:
            directives = json.load(f)
    except:
        directives = {'focus_themes': []}

    focus = directives.get('focus_themes', [])
    injected = 0

    for opp in opportunities:
        theme = {
            'topic': opp['expanded_title'][:50],
            'hint': (
                f"当たりパターン横展開({opp['reason']})。"
                f"元ネタ: {opp['source_title'][:50]}。"
                f"バズ予測スコア: {opp['buzz_score']}。シグナル: winning_pattern"
            ),
            'category_suggest': opp['category'],
            'added_at': datetime.now(JST).strftime('%Y-%m-%d'),
            'source': 'winning_pattern',
            'buzz_score': opp['buzz_score'],
            'expires_at': (datetime.now(JST) + timedelta(days=7)).strftime('%Y-%m-%d'),
        }

        if dry_run:
            print(f"  [DRY-RUN] 注入: {theme['topic']}")
            injected += 1
            continue

        focus.append(theme)
        injected += 1

        # ログ
        os.makedirs(os.path.dirname(EXPAND_LOG), exist_ok=True)
        with open(EXPAND_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'topic_key': opp['topic_key'],
                'pattern_id': opp['pattern_id'],
                'expanded_title': opp['expanded_title'],
                'source_title': opp['source_title'][:80],
                'expanded_at': datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False) + '\n')

    if not dry_run:
        # 期限切れテーマ除去
        today = datetime.now(JST).strftime('%Y-%m-%d')
        focus = [t for t in focus if t.get('expires_at', '9999') >= today]
        directives['focus_themes'] = focus
        with open(DIRECTIVES, 'w', encoding='utf-8') as f:
            json.dump(directives, f, ensure_ascii=False, indent=2)

    return injected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    now = datetime.now(JST)
    print(f"=== 柱1: 当たりパターン横展開 {now.strftime('%Y-%m-%d %H:%M')} ===")

    signals = load_recent_signals(hours=24)
    soompi = load_soompi_rss()
    print(f"  signals: {len(signals)}件, Soompi: {len(soompi)}件")

    opportunities = detect_expansion_opportunities(signals, soompi)
    print(f"  横展開チャンス: {len(opportunities)}件")

    for opp in opportunities:
        print(f"  [{opp['pattern_id']}] {opp['expanded_title'][:50]}")
        print(f"    元ネタ: {opp['source_title'][:60]}")

    injected = inject_to_directives(opportunities, dry_run=args.dry_run)
    print(f"\n  注入: {injected}件")


if __name__ == '__main__':
    main()
