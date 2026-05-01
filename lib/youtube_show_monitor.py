#!/usr/bin/env python3
"""
YouTube番組エピソード監視 — K-POPアイドルYouTubeオリジナル番組の新エピソード検知
検知したエピソードをtrend_signalsに注入し、feature_article_generatorのトレンド記事として記事化
"""
import sys, os, json, urllib.request, urllib.parse
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

BASE_DIR = '/home/aiuser/kpop-ai-system'
JST = timezone(timedelta(hours=9))
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY', '')
SIGNALS_PATH = os.path.join(BASE_DIR, 'data/trend_signals.jsonl')
STATE_PATH = os.path.join(BASE_DIR, 'data/youtube_show_state.json')


def load_config():
    path = os.path.join(BASE_DIR, 'config/youtube_shows.json')
    return json.load(open(path, encoding='utf-8'))


def load_state():
    try:
        return json.load(open(STATE_PATH, encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def youtube_search(query, published_after=None, max_results=5):
    """YouTube Data API v3 で動画を検索"""
    if not YOUTUBE_API_KEY:
        print("  YOUTUBE_API_KEY未設定")
        return []

    params = {
        'part': 'snippet',
        'q': query,
        'type': 'video',
        'order': 'date',
        'maxResults': max_results,
        'key': YOUTUBE_API_KEY,
        'regionCode': 'JP',
    }
    if published_after:
        params['publishedAfter'] = published_after

    url = f"https://www.googleapis.com/youtube/v3/search?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url)
        data = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return data.get('items', [])
    except Exception as e:
        print(f"  YouTube API err: {e}")
        return []


def get_video_stats(video_ids):
    """動画の再生回数を取得"""
    if not video_ids or not YOUTUBE_API_KEY:
        return {}

    url = (
        f"https://www.googleapis.com/youtube/v3/videos"
        f"?part=statistics&id={','.join(video_ids)}&key={YOUTUBE_API_KEY}"
    )
    try:
        req = urllib.request.Request(url)
        data = json.loads(urllib.request.urlopen(req, timeout=30).read())
        stats = {}
        for item in data.get('items', []):
            vid = item['id']
            s = item.get('statistics', {})
            stats[vid] = {
                'views': int(s.get('viewCount', 0)),
                'likes': int(s.get('likeCount', 0)),
                'comments': int(s.get('commentCount', 0)),
            }
        return stats
    except Exception as e:
        print(f"  Video stats err: {e}")
        return {}


def inject_trend_signal(show, video, stats):
    """trend_signalsにYouTube番組シグナルを追加"""
    video_id = video['id']['videoId']
    title = video['snippet']['title']
    channel_title = video['snippet']['channelTitle']
    published_at = video['snippet']['publishedAt']
    views = stats.get(video_id, {}).get('views', 0)
    likes = stats.get(video_id, {}).get('likes', 0)

    signal = {
        'timestamp': datetime.now(JST).isoformat(),
        'source': 'youtube_show',
        'source_id': show['id'],
        'keyword': show['group'],
        'title': f"[{show['name']}] {title}",
        'url': f"https://www.youtube.com/watch?v={video_id}",
        'engagement_score': min(100, views / 10000 + likes / 1000),
        'language': 'ja',
        'raw_data': {
            'show_name': show['name'],
            'group': show['group'],
            'video_id': video_id,
            'channel': channel_title,
            'published_at': published_at,
            'views': views,
            'likes': likes,
            'article_type': show.get('article_type', 'show_review'),
        }
    }

    os.makedirs(os.path.dirname(SIGNALS_PATH), exist_ok=True)
    with open(SIGNALS_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(signal, ensure_ascii=False) + '\n')

    return signal


def inject_to_auto_directives(show, video, stats):
    """auto_directives.jsonのfocus_themesにも追加"""
    video_id = video['id']['videoId']
    title = video['snippet']['title']
    views = stats.get(video_id, {}).get('views', 0)

    directives_path = os.path.join(BASE_DIR, 'config/auto_directives.json')
    try:
        directives = json.load(open(directives_path, encoding='utf-8'))
    except Exception:
        return

    theme = {
        'topic': f"{show['group']}の{show['name']}最新回が話題",
        'hint': (
            f"{show['name']}の最新エピソード「{title}」が公開。"
            f"再生回数{views:,}回。関連: {show['group']}。"
            f"URL: https://www.youtube.com/watch?v={video_id}。"
            f"バズ予測スコア: {min(50, views / 10000 + 10):.0f}。シグナル: youtube_show"
        ),
        'category_suggest': 'YouTube番組',
        'added_at': datetime.now(JST).strftime('%Y-%m-%d'),
        'source': 'youtube_show_monitor',
        'buzz_score': min(50, views / 10000 + 10),
        'expires_at': (datetime.now(JST) + timedelta(days=5)).strftime('%Y-%m-%d'),
    }

    focus_themes = directives.get('focus_themes', [])
    # 同じ番組の古いエントリを除去
    focus_themes = [t for t in focus_themes if show['name'] not in t.get('topic', '')]
    focus_themes.append(theme)
    directives['focus_themes'] = focus_themes

    with open(directives_path, 'w', encoding='utf-8') as f:
        json.dump(directives, f, ensure_ascii=False, indent=2)


def main():
    config = load_config()
    state = load_state()
    min_views = config.get('min_views_for_article', 50000)

    print(f"=== youtube_show_monitor: {datetime.now(JST).strftime('%Y-%m-%d %H:%M')} ===")
    print(f"  対象番組: {len(config['shows'])}件")

    new_episodes = 0

    for show in config['shows']:
        show_id = show['id']
        last_video_id = state.get(show_id, {}).get('last_video_id')
        last_check = state.get(show_id, {}).get('last_check', '')

        # 直近7日分を検索
        published_after = (datetime.now(timezone.utc) - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ')

        for keyword in show['search_keywords']:
            results = youtube_search(keyword, published_after=published_after, max_results=3)
            if not results:
                continue

            video_ids = [r['id']['videoId'] for r in results]
            stats = get_video_stats(video_ids)

            for video in results:
                vid = video['id']['videoId']
                if vid == last_video_id:
                    continue

                views = stats.get(vid, {}).get('views', 0)
                title = video['snippet']['title']

                # 番組名キーワードがタイトルに含まれているか確認
                title_lower = title.lower()
                is_match = any(kw.lower() in title_lower for kw in show['search_keywords'])
                if not is_match:
                    continue

                # 公式チャンネルチェック: channel_id指定あれば一致チェック
                if show.get('channel_id'):
                    snippet_channel = video['snippet'].get('channelId', '')
                    if snippet_channel != show['channel_id']:
                        continue  # 非公式チャンネルはスキップ

                # 極端に再生数が低いものはファンクリップの可能性が高いのでスキップ
                if views < 1000:
                    continue

                print(f"  新エピソード検知: [{show['name']}] {title} ({views:,}回再生)")

                # trend_signalsに注入
                inject_trend_signal(show, video, stats)

                # 再生回数が閾値以上ならauto_directivesにも注入
                if views >= min_views:
                    inject_to_auto_directives(show, video, stats)
                    print(f"    → auto_directives注入 (views={views:,} >= {min_views:,})")

                new_episodes += 1

                # 最新のvideo_idを記録
                state[show_id] = {
                    'last_video_id': vid,
                    'last_check': datetime.now(JST).isoformat(),
                    'last_title': title,
                }
                break  # 各番組は最新1件のみ

            if show_id in state and state[show_id].get('last_video_id') != last_video_id:
                break  # 新エピソード見つかったら次の番組へ

        # 検索結果なくてもlast_checkを更新
        if show_id not in state:
            state[show_id] = {}
        state[show_id]['last_check'] = datetime.now(JST).isoformat()

    save_state(state)
    print(f"\n  新エピソード: {new_episodes}件検知")


if __name__ == '__main__':
    main()
