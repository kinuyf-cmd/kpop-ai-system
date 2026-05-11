#!/usr/bin/env python3
"""AI編集長: 毎時KPI監視+カテゴリバランス+遅延時強制生成

実行: 毎時00分
- 過去24hの投稿数集計
- KPI: 速報30+その他0 = 計30本/日 (2026-05-11 改定: 速報安定化フェーズ、SEO/その他は一旦停止)
- 残り時間と必要本数から動的maxを算出
- 大幅遅延時 → 即時生成
- 結果を data/editor_state.json に記録
"""
import os, sys, json, urllib.request, base64, subprocess
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

AUTH = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()
STATE = '/home/aiuser/kpop-ai-system/data/editor_state.json'
KPI_LOG = '/home/aiuser/kpop-ai-system/logs/daily_kpi.jsonl'

TARGET_DAILY_TOTAL = 30
TARGET_BREAKING = 30
TARGET_OTHER = 0


def count_posts_today():
    jst = timezone(timedelta(hours=9))
    today_start = datetime.now(jst).replace(hour=0, minute=0, second=0, microsecond=0)
    since = today_start.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')

    url = (
        f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"
        f"?after={since}&per_page=100&_fields=id,title,date"
    )
    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        posts = json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        print(f"count error: {e}")
        return {'total': 0, 'breaking': 0, 'other': 0}

    # 速報の判定: breaking_articles.jsonl の本日エントリpost_idと突合
    # （旧: タイトルの【速報】prefix → 2026-05-07にprefix廃止のため変更）
    breaking_ids = set()
    today_iso = datetime.now(jst).date().isoformat()
    log_path = '/home/aiuser/kpop-ai-system/logs/breaking_articles.jsonl'
    try:
        with open(log_path, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    if e.get('date') == today_iso and e.get('post_id'):
                        breaking_ids.add(int(e['post_id']))
                except Exception:
                    continue
    except FileNotFoundError:
        pass

    # フォールバック: 既存titleスキャン（過去公開分の互換性のため残す）
    legacy_breaking = sum(
        1 for p in posts
        if any(tag in (p.get('title', {}).get('rendered', '') if isinstance(p.get('title'), dict) else '')
               for tag in ['【速報】', '【韓国メディア速報】'])
    )
    new_breaking = sum(1 for p in posts if p.get('id') in breaking_ids)
    breaking = max(legacy_breaking, new_breaking)
    return {'total': len(posts), 'breaking': breaking, 'other': len(posts) - breaking}


def compute_state():
    stats = count_posts_today()

    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    hours_left = max(1.0, (midnight - now).total_seconds() / 3600)

    needed_breaking = max(0, TARGET_BREAKING - stats['breaking'])
    needed_other = max(0, TARGET_OTHER - stats['other'])
    needed_total = needed_breaking + needed_other

    per_hour_other = needed_other / hours_left

    # auto_event/comeback は 2時間毎実行想定
    auto_max = max(2, min(8, int(per_hour_other * 2.5)))

    if needed_total >= 10:
        urgency = 'high'
    elif needed_total >= 5:
        urgency = 'medium'
    else:
        urgency = 'normal'

    state = {
        'updated_at': now.isoformat(),
        'stats_today': stats,
        'hours_left_today': round(hours_left, 2),
        'needed_today': {
            'breaking': needed_breaking,
            'other': needed_other,
            'total': needed_total,
        },
        'recommended_max': {
            'auto_event': auto_max,
            'auto_comeback': auto_max,
        },
        'urgency': urgency,
    }

    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(state, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    os.makedirs(os.path.dirname(KPI_LOG), exist_ok=True)
    with open(KPI_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': now.isoformat(),
            'total': stats['total'],
            'breaking': stats['breaking'],
            'other': stats['other'],
            'urgency': urgency,
        }, ensure_ascii=False) + '\n')

    return state


def force_generate(state):
    urgency = state['urgency']
    if urgency == 'high':
        print(f"  HIGH urgency -> forcing generation (event+comeback+feature)")
        subprocess.run(
            ['python3', 'pipeline/auto_event_article.py', '--max', '4'],
            cwd='/home/aiuser/kpop-ai-system', timeout=600,
        )
        subprocess.run(
            ['python3', 'pipeline/auto_comeback_article.py', '--max', '3'],
            cwd='/home/aiuser/kpop-ai-system', timeout=600,
        )
        subprocess.run(
            ['python3', 'pipeline/feature_article_generator.py', '--max', '4'],
            cwd='/home/aiuser/kpop-ai-system', timeout=900,
        )
    elif urgency == 'medium':
        print(f"  MEDIUM urgency -> supplemental generation")
        subprocess.run(
            ['python3', 'pipeline/auto_event_article.py', '--max', '3'],
            cwd='/home/aiuser/kpop-ai-system', timeout=400,
        )
        subprocess.run(
            ['python3', 'pipeline/auto_comeback_article.py', '--max', '2'],
            cwd='/home/aiuser/kpop-ai-system', timeout=400,
        )
        subprocess.run(
            ['python3', 'pipeline/feature_article_generator.py', '--max', '3'],
            cwd='/home/aiuser/kpop-ai-system', timeout=600,
        )


def main():
    state = compute_state()
    stats = state['stats_today']
    print(
        f"[{state['updated_at'][:16]}] "
        f"today={stats['total']} (breaking={stats['breaking']}/other={stats['other']}) "
        f"hours_left={state['hours_left_today']}h "
        f"needed=+{state['needed_today']['total']} "
        f"urgency={state['urgency']} "
        f"rec_max={state['recommended_max']['auto_event']}"
    )
    force_generate(state)
    return state


if __name__ == '__main__':
    main()
