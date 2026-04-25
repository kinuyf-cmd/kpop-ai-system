#!/usr/bin/env python3
"""
特集記事自動生成 v2 - AI社員11部門目「特集記事担当」
高収益5ジャンルで週14本(毎日2本)を計画的に生成
"""
import sys, os, json, urllib.request, base64, random, re
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
JST = timezone(timedelta(hours=9))

# 5ジャンル × トピックテンプレート
FEATURE_SCHEDULES = {
    'korea_travel': {
        'category_slug': 'korea-travel',
        'category_id': None,
        'topics': [
            {'tpl': '{city}聖地巡礼ガイド: {artist}ファン必訪のスポット',
             'city': ['ソウル', '弘大', '聖水', '江南', '明洞'],
             'artist': ['BTS', 'BLACKPINK', 'NewJeans', 'SEVENTEEN', 'aespa', 'IVE', 'LE SSERAFIM', 'TWICE', 'ENHYPEN']},
            {'tpl': '{city}おすすめ韓国カフェ{n}選: 推し活と一緒に楽しめるスポット',
             'city': ['弘大', '聖水', '江南', '明洞'],
             'n': [5, 7, 10]},
            {'tpl': 'ソウル{nights}泊{days}日のモデルコース: K-POPファン向け完全プラン',
             'nights': [2, 3, 4],
             'days': [3, 4, 5]},
            {'tpl': '韓国旅行で外せない{type}まとめ: 失敗しない選び方',
             'type': ['お土産', '韓国グルメ', '観光スポット', '韓国カフェ', 'ショッピング', '韓国コスメ買い物リスト']},
            {'tpl': 'インチョン空港から{city}までの行き方完全ガイド',
             'city': ['ソウル中心部', '弘大', '江南', '明洞', '東大門']},
            {'tpl': '韓国で食べたい{food}{n}選: 現地で人気の絶品グルメ',
             'food': ['ストリートフード', 'スイーツ', 'カフェメニュー', 'B級グルメ', '韓定食'],
             'n': [5, 7, 10]},
            {'tpl': '{area}のおすすめ韓国料理レストラン: ローカルが通う名店',
             'area': ['江南', '弘大', '明洞', '聖水', '東大門']},
            {'tpl': '韓国の{drink}文化を楽しむ: ファンの聖地カフェ',
             'drink': ['コーヒー', 'タピオカ', 'スムージー', '韓国茶']},
        ],
    },
    'beauty_tutorial': {
        'category_slug': 'beauty',
        'category_id': None,
        'topics': [
            {'tpl': '{artist}{member}風メイク完全コピー: {step}ステップで再現',
             'artist': ['BLACKPINK', 'NewJeans', 'aespa', 'IVE', 'LE SSERAFIM', 'TWICE', 'ITZY'],
             'member': ['ジェニー', 'ロゼ', 'リサ', 'ジス', 'ハニ', 'ミンジ', 'ヘリン', 'カリナ', 'ウィンター', 'ジゼル'],
             'step': [3, 5, 7]},
            {'tpl': '{cosme}おすすめ{n}選: K-POPアイドルが愛用する優秀コスメ',
             'cosme': ['リップ', 'アイシャドウ', 'チーク', 'ベース', 'マスカラ', 'アイライナー', 'ハイライト'],
             'n': [5, 7, 10]},
            {'tpl': 'カラコンレビュー: {brand}の{color}が推し活に最適',
             'brand': ['OLENS', 'LILMOON', 'モラク', 'エンジェルカラー', 'POPLENS'],
             'color': ['ブラウン', 'グレー', 'ヘーゼル', 'ピンク', 'ハニー', 'オリーブ']},
            {'tpl': '韓国コスメ最新トレンド: {year}年版アイドル愛用ブランド{n}選',
             'year': [2026],
             'n': [5, 7, 10]},
            {'tpl': '{skincare}ステップ完全ガイド: 韓国アイドル肌の作り方',
             'skincare': ['朝のスキンケア', '夜のスキンケア', 'デイリーケア', '毛穴ケア', '美白ケア']},
        ],
    },
    'korean_language': {
        'category_slug': 'oshikatsu',
        'category_id': None,
        'topics': [
            {'tpl': '推しの言葉が分かる: {artist}がよく言う韓国語フレーズ{n}選',
             'artist': ['BTS', 'BLACKPINK', 'SEVENTEEN', 'NewJeans', 'aespa', 'IVE'],
             'n': [10, 15, 20]},
            {'tpl': 'K-POP歌詞によく出る韓国語: {n}単語でぐっと理解度アップ',
             'n': [10, 20, 30, 50]},
            {'tpl': '韓国コンサートで使えるファンチャント・応援フレーズ{n}選',
             'n': [10, 15, 20]},
            {'tpl': '韓国アイドルのファンサが分かる: 韓国語の{topic}',
             'topic': ['呼び方', '挨拶', 'SNSスラング', 'カムバック関連用語', 'ファン用語']},
            {'tpl': '{level}向け韓国語学習法: 推し活で学ぶ実践韓国語',
             'level': ['初心者', '中級者', 'ハングル未学習者']},
        ],
    },
    'oshikatsu_guide': {
        'category_slug': 'oshikatsu',
        'category_id': None,
        'topics': [
            {'tpl': '{artist}推し活グッズ{n}選: 公式グッズから自作アイテムまで',
             'artist': ['BTS', 'BLACKPINK', 'NewJeans', 'SEVENTEEN', 'aespa', 'IVE', 'TWICE', 'LE SSERAFIM'],
             'n': [10, 15, 20]},
            {'tpl': 'K-POPコンサート参戦準備リスト: {topic}',
             'topic': ['初心者向け', 'グッズの選び方', '会場での注意点', '韓国コンサート編', '日本コンサート編']},
            {'tpl': '推しの誕生日企画: {artist}{member}を祝うアイデア{n}選',
             'artist': ['BTS', 'NewJeans', 'aespa', 'SEVENTEEN'],
             'member': ['V', 'JIMIN', 'JUNGKOOK', 'ハニ', 'ミンジ', 'カリナ', 'ウィンター', 'ジョシュア'],
             'n': [5, 7, 10]},
            {'tpl': '推し活{tool}の選び方: {n}選を比較',
             'tool': ['ペンライト', '応援ボード', 'スローガン', 'トレカケース', 'アクスタ'],
             'n': [5, 7, 10]},
        ],
    },
    'kdrama_movie': {
        'category_slug': 'kdrama-movie',
        'category_id': None,
        'topics': [
            {'tpl': '{year}年話題の韓国ドラマ{n}選: K-POPアイドル出演作も網羅',
             'year': [2026, 2025],
             'n': [5, 7, 10]},
            {'tpl': '{artist}{member}主演ドラマ・映画の見どころ完全ガイド',
             'artist': ['EXO', 'BIGBANG', '2PM', 'INFINITE', 'ASTRO'],
             'member': ['EXO ディオ', 'EXO シウミン', '2PM テギョン', 'INFINITE エル', 'ASTRO チャ・ウヌ']},
            {'tpl': '韓国バラエティおすすめ{n}選: {topic}',
             'n': [5, 7, 10],
             'topic': ['推しが出演している番組', 'K-POPファン必見', 'メンバー間トーク', '初心者向け']},
            {'tpl': '{genre}韓国ドラマ名作{n}選: 一気見必至',
             'genre': ['ロマンス', 'サスペンス', '時代劇', 'ファンタジー', '社会派', 'コメディ'],
             'n': [5, 7, 10]},
            {'tpl': 'Netflix・Amazon Prime・U-NEXTで見れる{type}厳選{n}選',
             'type': ['韓国ドラマ', '韓国映画', 'K-POPドキュメンタリー', '韓国バラエティ'],
             'n': [5, 7, 10]},
            {'tpl': '韓国映画レビュー: {year}年に注目された作品{n}選',
             'year': [2025, 2024],
             'n': [5, 7, 10]},
        ],
    },
}

# 週次スケジュール (週14本=毎日2本)
WEEKLY_SCHEDULE = {
    0: ['korea_travel', 'beauty_tutorial'],     # 月
    1: ['oshikatsu_guide', 'kdrama_movie'],     # 火
    2: ['korean_language', 'korea_travel'],      # 水
    3: ['beauty_tutorial', 'kdrama_movie'],      # 木
    4: ['korea_travel', 'oshikatsu_guide'],      # 金
    5: ['beauty_tutorial', 'korean_language'],   # 土
    6: ['kdrama_movie', 'korea_travel'],         # 日
}


def get_category_id(slug):
    try:
        url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/categories?slug={slug}"
        req = urllib.request.Request(url)
        data = json.loads(urllib.request.urlopen(req, timeout=20).read())
        if data:
            return data[0]['id']
    except Exception as e:
        print(f"  category_id err {slug}: {e}")
    return None


def generate_topic_title(topic_def):
    template = topic_def['tpl']
    filled = template
    for key, val in topic_def.items():
        if key == 'tpl':
            continue
        if isinstance(val, list):
            filled = filled.replace('{' + key + '}', str(random.choice(val)))
    return filled


def generate_article_content(title, category):
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        return None

    contexts = {
        'korea_travel': '韓国旅行・聖地巡礼・韓国グルメの専門家として、実用的で旅行者の視点に立った詳細記事',
        'beauty_tutorial': 'K-POPメイクアップアーティスト視点で、初心者でも真似できる詳細ガイド',
        'korean_language': '韓国語学習の入門者向けに、推し活で使える実用韓国語を分かりやすく解説',
        'oshikatsu_guide': '推し活経験豊富な視点から、ファン目線で実用的な情報を提供',
        'kdrama_movie': '韓国ドラマ・映画・バラエティに精通した立場から、見どころと魅力を伝える',
    }

    prompt = f"""以下のタイトルでK-POPファン向けの特集記事を書いてください。

【タイトル】{title}
【視点】{contexts.get(category, '')}

【要件】
- 1200-1800字
- HTMLで記述、h2セクション最低3つ
- リード文 (5W1H骨子) → 詳細展開 → まとめ の三段構成
- 文末バリエーション (~した/~紹介する/~始まった/~人気/~注目)
- 「以上」「いかがでしょうか」「皆さん」等の口語的表現禁止
- 「AI」「ChatGPT」等のメタ言及禁止
- 末尾に <p class="kpj-disclaimer">※情報は変更になる場合があります。最新情報は公式サイトをご確認ください。</p>

【出力】HTML本文のみ。前置き・後書き不要"""

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.75,
        'max_tokens': 2500,
    }).encode()

    try:
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
            data=body, headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=120).read())
        content = r['choices'][0]['message']['content'].strip()
        content = re.sub(r'^```html\s*\n?', '', content, flags=re.IGNORECASE)
        content = re.sub(r'\n?```\s*$', '', content)
        return content.strip()
    except Exception as e:
        print(f"  GPT err: {e}")
        return None


def post_to_wp(title, content, category_id):
    body_data = {
        'title': title,
        'content': content,
        'status': 'publish',
        'categories': [category_id] if category_id else [],
    }
    body = json.dumps(body_data).encode()
    try:
        req = urllib.request.Request(
            'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts',
            data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=60).read())
        return r.get('id')
    except Exception as e:
        print(f"  WP err: {e}")
        return None


def main():
    weekday = datetime.now(JST).weekday()
    today_categories = WEEKLY_SCHEDULE.get(weekday, [])

    if not today_categories:
        print(f"今日は特集記事生成日ではない (weekday={weekday})")
        return

    print(f"=== feature_article_generator v2: {datetime.now(JST).strftime('%Y-%m-%d (%a)')} ===")
    print(f"今日の対象: {today_categories}")

    # 重複防止 (直近30日のタイトルチェック)
    recent_titles = set()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S')
        url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?after={cutoff}&per_page=100&_fields=title"
        req = urllib.request.Request(url)
        for p in json.loads(urllib.request.urlopen(req, timeout=20).read()):
            t = p['title']['rendered'] if isinstance(p['title'], dict) else p['title']
            recent_titles.add(t[:30])
    except Exception:
        pass

    success = 0
    for cat_key in today_categories:
        sched = FEATURE_SCHEDULES.get(cat_key)
        if not sched:
            continue

        if not sched['category_id']:
            sched['category_id'] = get_category_id(sched['category_slug'])
            if not sched['category_id']:
                print(f"  カテゴリID取得失敗: {sched['category_slug']}")
                continue

        # ランダムにトピック選択 (重複回避3回まで試行)
        title = None
        for attempt in range(3):
            topic_def = random.choice(sched['topics'])
            title = generate_topic_title(topic_def)
            if title[:30] not in recent_titles:
                break
        else:
            print(f"  {cat_key} 重複多すぎ、スキップ")
            continue

        print(f"\n生成中: [{cat_key}] {title}")
        content = generate_article_content(title, cat_key)
        if not content or len(content) < 800:
            print(f"  生成失敗 or 短すぎ ({len(content) if content else 0}字)")
            continue

        # CTA挿入
        try:
            from lib.cta_injector import inject_cta_into_content
            content = inject_cta_into_content(title, content)
        except Exception as e:
            print(f"  CTA inject warn: {e}")

        post_id = post_to_wp(title, content, sched['category_id'])
        if post_id:
            print(f"  post_id={post_id} 公開 ({len(content)}字)")
            success += 1

            log = '/home/aiuser/kpop-ai-system/logs/feature_articles.jsonl'
            os.makedirs(os.path.dirname(log), exist_ok=True)
            with open(log, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    'post_id': post_id, 'title': title, 'category': cat_key,
                    'category_id': sched['category_id'],
                    'published_at': datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False) + '\n')

    print(f"\n{success}/{len(today_categories)}件 特集記事公開")


if __name__ == '__main__':
    main()
