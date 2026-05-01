#!/usr/bin/env python3
"""
音楽番組ランキング監視 — 6大音楽番組の1位結果を検知しtrend_signalsに注入
RSS/ニュースサイトから1位結果を自動検知し、速報・週次まとめ記事の元データを作成
"""
import sys, os, json, urllib.request, urllib.parse, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

BASE_DIR = '/home/aiuser/kpop-ai-system'
JST = timezone(timedelta(hours=9))
SIGNALS_PATH = os.path.join(BASE_DIR, 'data/trend_signals.jsonl')
STATE_PATH = os.path.join(BASE_DIR, 'data/music_show_state.json')


def load_config():
    path = os.path.join(BASE_DIR, 'config/music_shows.json')
    return json.load(open(path, encoding='utf-8'))


def load_state():
    try:
        return json.load(open(STATE_PATH, encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return {'winners': [], 'last_weekly_summary': ''}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def search_rss_for_winner(show):
    """既存のtrend_signalsから音楽番組1位情報を検索"""
    try:
        signals = []
        for line in open(SIGNALS_PATH, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            try:
                sig = json.loads(line)
                title = sig.get('title', '').lower()
                # 各番組のキーワードでマッチ
                for kw in show['search_keywords']:
                    if kw.lower() in title:
                        signals.append(sig)
                        break
            except (json.JSONDecodeError, ValueError):
                continue
        return signals
    except FileNotFoundError:
        return []


def search_naver_news(keyword, max_results=5):
    """Naver News APIで音楽番組結果を検索（APIキー不要のRSS版）"""
    encoded = urllib.parse.quote(keyword)
    url = f"https://search.naver.com/search.naver?where=news&query={encoded}&sort=1"

    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; KpopJournal/1.0)',
        })
        html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8', errors='ignore')

        # タイトルから1位アーティスト名を抽出
        winners = []
        # パターン: 「○○, △△で1位」「○○が△△1位」
        patterns = [
            r'([A-Za-z가-힣\s]+)[,\s]+.+1위',
            r'([A-Za-z가-힣\s]+).*(?:1位|1위|win)',
        ]
        for pat in patterns:
            matches = re.findall(pat, html, re.IGNORECASE)
            if matches:
                winners.extend(matches[:3])

        return winners
    except Exception as e:
        print(f"  Naver search err: {e}")
        return []


def search_soompi_rss_for_winner(show):
    """Soompi RSSから音楽番組結果を検索"""
    try:
        import xml.etree.ElementTree as ET
        url = "https://www.soompi.com/feed"
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; KpopJournal/1.0)',
        })
        data = urllib.request.urlopen(req, timeout=15).read()
        root = ET.fromstring(data)

        results = []
        show_names = [show['name'].lower(), show['name_ko'].lower()]
        for item in root.iter('item'):
            title = (item.findtext('title') or '').lower()
            if any(n in title for n in show_names) and ('win' in title or '1st' in title):
                results.append({
                    'title': item.findtext('title'),
                    'url': item.findtext('link'),
                    'date': item.findtext('pubDate', ''),
                })

        return results
    except Exception as e:
        print(f"  Soompi RSS err for {show['name']}: {e}")
        return []


def inject_winner_signal(show, artist, song=None, source_url=None):
    """1位結果をtrend_signalsとauto_directivesに注入"""
    today = datetime.now(JST).strftime('%Y-%m-%d')

    # trend_signalsに追加
    signal = {
        'timestamp': datetime.now(JST).isoformat(),
        'source': 'music_show',
        'source_id': show['id'],
        'keyword': artist,
        'title': f"{artist}が{show['name']}で1位獲得" + (f"「{song}」" if song else ""),
        'url': source_url or '',
        'engagement_score': 15.0,
        'language': 'ja',
        'raw_data': {
            'show_name': show['name'],
            'show_network': show['network'],
            'winner': artist,
            'song': song,
            'air_date': today,
        }
    }

    os.makedirs(os.path.dirname(SIGNALS_PATH), exist_ok=True)
    with open(SIGNALS_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(signal, ensure_ascii=False) + '\n')

    # auto_directivesに注入
    directives_path = os.path.join(BASE_DIR, 'config/auto_directives.json')
    try:
        directives = json.load(open(directives_path, encoding='utf-8'))
        theme = {
            'topic': f"{artist}が{show['name']}で1位",
            'hint': (
                f"{artist}が{today}の{show['name']}({show['network']})で1位を獲得。"
                + (f"楽曲「{song}」。" if song else "")
                + f"関連: {artist}。バズ予測スコア: 15.0。シグナル: music_show"
            ),
            'category_suggest': '音楽番組',
            'added_at': today,
            'source': 'music_show_monitor',
            'buzz_score': 15.0,
            'expires_at': (datetime.now(JST) + timedelta(days=3)).strftime('%Y-%m-%d'),
        }
        focus_themes = directives.get('focus_themes', [])
        # 同じ番組の古い結果を除去
        focus_themes = [t for t in focus_themes if show['name'] not in t.get('topic', '')]
        focus_themes.append(theme)
        directives['focus_themes'] = focus_themes

        with open(directives_path, 'w', encoding='utf-8') as f:
            json.dump(directives, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  auto_directives更新失敗: {e}")

    return signal


def check_today_shows(config, state):
    """今日放送の音楽番組の結果を確認"""
    weekday = datetime.now(JST).weekday()
    today = datetime.now(JST).strftime('%Y-%m-%d')
    new_winners = 0

    for show in config['shows']:
        if show['weekday'] != weekday:
            continue

        # 既に今日の結果を記録済みならスキップ
        already_recorded = any(
            w.get('show_id') == show['id'] and w.get('date') == today
            for w in state.get('winners', [])
        )
        if already_recorded:
            print(f"  {show['name']}: 今日の結果は記録済み")
            continue

        print(f"  {show['name']} ({show['network']}): 結果を検索中...")

        # Soompi RSS検索
        soompi_results = search_soompi_rss_for_winner(show)
        if soompi_results:
            result = soompi_results[0]
            # タイトルからアーティスト名を抽出（パターン: "Artist Takes 1st Win..."）
            title = result['title']
            artist_match = re.match(r"(.+?)(?:'s|Takes|Wins|Earns)", title)
            artist = artist_match.group(1).strip() if artist_match else title.split(' ')[0]

            print(f"    結果検知: {artist} が1位 (Soompi)")
            inject_winner_signal(show, artist, source_url=result.get('url'))
            state.setdefault('winners', []).append({
                'show_id': show['id'],
                'show_name': show['name'],
                'artist': artist,
                'date': today,
                'source': 'soompi',
            })
            new_winners += 1
            continue

        # 既存のtrend_signalsから検索
        existing_signals = search_rss_for_winner(show)
        recent_signals = [
            s for s in existing_signals
            if s.get('timestamp', '')[:10] == today
        ]
        if recent_signals:
            sig = recent_signals[0]
            artist = sig.get('keyword', '')
            print(f"    結果検知: {artist} (trend_signals)")
            state.setdefault('winners', []).append({
                'show_id': show['id'],
                'show_name': show['name'],
                'artist': artist,
                'date': today,
                'source': 'trend_signals',
            })
            new_winners += 1
            continue

        print(f"    結果未検知（放送前or情報未出）")

    return new_winners


def generate_weekly_summary_signal(state):
    """日曜夜に週次まとめシグナルを生成"""
    weekday = datetime.now(JST).weekday()
    if weekday != 6:  # 日曜日のみ
        return

    today = datetime.now(JST).strftime('%Y-%m-%d')
    if state.get('last_weekly_summary') == today:
        return

    # 今週のwinnerをまとめる
    week_start = (datetime.now(JST) - timedelta(days=6)).strftime('%Y-%m-%d')
    this_week_winners = [
        w for w in state.get('winners', [])
        if w.get('date', '') >= week_start
    ]

    if not this_week_winners:
        return

    # アーティストごとの獲得数をカウント
    win_counts = {}
    for w in this_week_winners:
        artist = w['artist']
        win_counts[artist] = win_counts.get(artist, 0) + 1

    top_artist = max(win_counts, key=win_counts.get)
    top_count = win_counts[top_artist]

    summary = (
        f"今週の音楽番組まとめ: {top_artist}が{top_count}冠達成。"
        + "、".join(f"{w['artist']}({w['show_name']})" for w in this_week_winners)
    )

    signal = {
        'timestamp': datetime.now(JST).isoformat(),
        'source': 'music_show_weekly',
        'source_id': 'weekly_summary',
        'keyword': top_artist,
        'title': f"今週の音楽番組まとめ — {top_artist}が{top_count}冠達成",
        'url': '',
        'engagement_score': 20.0,
        'language': 'ja',
        'raw_data': {
            'winners': this_week_winners,
            'top_artist': top_artist,
            'top_count': top_count,
            'week_start': week_start,
        }
    }

    with open(SIGNALS_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(signal, ensure_ascii=False) + '\n')

    state['last_weekly_summary'] = today
    print(f"  週次まとめシグナル生成: {top_artist}が{top_count}冠")


def main():
    config = load_config()
    state = load_state()

    print(f"=== music_show_monitor: {datetime.now(JST).strftime('%Y-%m-%d %H:%M (%a)')} ===")

    new_winners = check_today_shows(config, state)

    # 日曜日なら週次まとめも生成
    generate_weekly_summary_signal(state)

    # 古い記録を4週間分に制限
    cutoff = (datetime.now(JST) - timedelta(days=28)).strftime('%Y-%m-%d')
    state['winners'] = [w for w in state.get('winners', []) if w.get('date', '') >= cutoff]

    save_state(state)
    print(f"\n  新規1位結果: {new_winners}件")


if __name__ == '__main__':
    main()
