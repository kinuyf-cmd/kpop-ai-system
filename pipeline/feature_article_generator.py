#!/usr/bin/env python3
"""
特集記事自動生成 v3 — トレンド駆動型
旧v2: テンプレートからランダム選択 → v3: SNSトレンド・auto_directivesから記事企画を生成

配分: トレンド記事70% / テンプレート記事30%(○選は週2本上限)
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

BASE_DIR = '/home/aiuser/kpop-ai-system'
STRATEGY_PATH = os.path.join(BASE_DIR, 'config/content_strategy.json')


def _load_gsc_high_imp_keywords():
    """GSCメトリクスからIMP上位のキーワードを抽出 (検索ボリュームの裏付け)"""
    gsc_path = os.path.join(BASE_DIR, 'data/gsc_metrics.jsonl')
    if not os.path.exists(gsc_path):
        return {}
    keywords = {}
    try:
        with open(gsc_path, encoding='utf-8') as f:
            for line in f:
                try:
                    p = json.loads(line)
                    slug = p.get('slug', '').lower().replace('-', ' ')
                    imp = p.get('impressions', 0)
                    if imp >= 30:
                        # slugからキーワードを抽出
                        for word in slug.split():
                            if len(word) >= 3 and not word.isdigit():
                                keywords[word] = max(keywords.get(word, 0), imp)
                except:
                    pass
    except Exception:
        pass
    return keywords


def load_strategy():
    """content_strategy.json を読み込み、テーマ配分と制限ルールを取得"""
    try:
        with open(STRATEGY_PATH, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def should_deprioritize(title, category_slug, strategy):
    """戦略に基づいてこの記事を生成すべきか判定。Falseなら生成スキップ"""
    rules = strategy.get('content_rules', {})

    # テンプレ比率チェック (by_source集計はmain内で行うためここでは対象外)

    # GPT単独ニュース禁止
    if rules.get('no_gpt_only_news') and category_slug == 'kpop-news':
        return True, 'GPT単独ニュース禁止(content_rules.no_gpt_only_news)'

    # ビューティー/スキンケア月次上限
    beauty_limit = rules.get('beauty_skincare_monthly_limit', 99)
    if category_slug == 'beauty':
        skin_kws = ['ガラス肌', '美肌', 'スキンケア', '肌ケア', 'CICA', 'PDRN']
        if any(k in title for k in skin_kws):
            # 直近30日の同テーマ記事数チェック (is_topic_duplicateで既に対応済みだが二重チェック)
            pass

    return False, ''


# ── カテゴリ定義 ──
CATEGORY_SLUGS = {
    'kpop-news': None,
    'beauty': None,
    'korea-travel': None,
    'oshikatsu': None,
    'kdrama-movie': None,
}

# ── テンプレート記事(フォールバック用、○選は週2本上限) ──
TEMPLATE_TOPICS = {
    'korea-travel': [
        {'tpl': '{city}聖地巡礼ガイド: {artist}ファン必訪のスポット',
         'city': ['ソウル', '弘大', '聖水', '江南', '明洞'],
         'artist': ['BTS', 'BLACKPINK', 'NewJeans', 'SEVENTEEN', 'aespa', 'IVE', 'LE SSERAFIM', 'TWICE', 'ENHYPEN']},
        {'tpl': 'ソウル{nights}泊{days}日のモデルコース: K-POPファン向け完全プラン',
         'nights': [2, 3, 4], 'days': [3, 4, 5]},
        {'tpl': '韓国旅行の{topic}完全ガイド',
         'topic': ['電圧・コンセント', 'Wi-Fi・SIM', '交通カード（T-money）', '両替', 'チップ・マナー']},
    ],
    'beauty': [
        {'tpl': '{artist}{member}風メイク完全コピー: {step}ステップで再現',
         'artist_member': [
             ('BLACKPINK', 'ジェニー'), ('BLACKPINK', 'ロゼ'),
             ('NewJeans', 'ハニ'), ('NewJeans', 'ミンジ'),
             ('aespa', 'カリナ'), ('aespa', 'ウィンター'),
             ('IVE', 'ウォニョン'), ('LE SSERAFIM', 'カズハ'),
             ('TWICE', 'サナ'), ('ITZY', 'リュジン'),
         ], 'step': [3, 5, 7]},
        {'tpl': '{skincare}ステップ完全ガイド: 韓国アイドル肌の作り方',
         'skincare': ['朝のスキンケア', '夜のスキンケア', 'デイリーケア', '毛穴ケア', '美白ケア']},
    ],
    'oshikatsu': [
        {'tpl': 'K-POPコンサート参戦準備リスト: {topic}',
         'topic': ['初心者向け', 'グッズの選び方', '会場での注意点', '韓国コンサート編', '日本コンサート編']},
        {'tpl': '{level}向け韓国語学習法: 推し活で学ぶ実践韓国語',
         'level': ['初心者', '中級者', 'ハングル未学習者']},
    ],
    'kdrama-movie': [
        {'tpl': '{artist}{member}主演ドラマ・映画の見どころ完全ガイド',
         'artist_member': [
             ('EXO', 'ディオ'), ('ASTRO', 'チャ・ウヌ'), ('2PM', 'テギョン'),
         ]},
    ],
}

# ── トレンド記事カテゴリマッピング ──
TREND_CATEGORY_MAP = {
    '速報': 'kpop-news',
    'カムバック': 'kpop-news',
    '来日公演': 'kpop-news',
    'SNSバズ': 'kpop-news',
    'YouTube番組': 'kpop-news',
    '音楽番組': 'kpop-news',
    '深掘り': 'kpop-news',
    'beauty': 'beauty',
    'travel': 'korea-travel',
    'oshikatsu': 'oshikatsu',
    'kdrama': 'kdrama-movie',
}

MAX_LISTICLE_PER_WEEK = 2


def get_category_id(slug):
    if CATEGORY_SLUGS.get(slug):
        return CATEGORY_SLUGS[slug]
    try:
        url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/categories?slug={slug}"
        req = urllib.request.Request(url)
        data = json.loads(urllib.request.urlopen(req, timeout=20).read())
        if data:
            CATEGORY_SLUGS[slug] = data[0]['id']
            return data[0]['id']
    except Exception as e:
        print(f"  category_id err {slug}: {e}")
    return None


# ── トレンドデータ読み込み ──

def load_focus_themes():
    """auto_directives.json の focus_themes を読み込み（期限内のみ）"""
    path = os.path.join(BASE_DIR, 'config/auto_directives.json')
    try:
        data = json.load(open(path, encoding='utf-8'))
        themes = data.get('focus_themes', [])
        today = datetime.now(JST).strftime('%Y-%m-%d')
        return [t for t in themes if t.get('expires_at', '9999-99-99') >= today]
    except Exception as e:
        print(f"  focus_themes読込失敗: {e}")
        return []


def load_recent_trend_signals(hours=48):
    """trend_signals.jsonl から直近のシグナルを読み込み"""
    path = os.path.join(BASE_DIR, 'data/trend_signals.jsonl')
    cutoff = datetime.now(JST) - timedelta(hours=hours)
    signals = []
    try:
        for line in open(path, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            try:
                s = json.loads(line)
                ts = s.get('timestamp', '')
                if ts:
                    parsed = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=JST)
                    if parsed >= cutoff:
                        signals.append(s)
            except (json.JSONDecodeError, ValueError):
                continue
    except FileNotFoundError:
        print("  trend_signals.jsonl not found")
    return signals


def load_comeback_calendar():
    """comeback_calendar.json から直近のカムバック・イベント情報を読み込み"""
    path = os.path.join(BASE_DIR, 'config/comeback_calendar.json')
    try:
        data = json.load(open(path, encoding='utf-8'))
        today = datetime.now(JST).strftime('%Y-%m-%d')
        window_end = (datetime.now(JST) + timedelta(days=14)).strftime('%Y-%m-%d')
        events = []
        for ev in data if isinstance(data, list) else data.get('events', data.get('comebacks', [])):
            date = ev.get('date', ev.get('start_date', ''))
            if today <= date <= window_end:
                events.append(ev)
        return events
    except Exception:
        return []


def count_listicles_this_week():
    """今週の「○選」記事数をカウント"""
    log_path = os.path.join(BASE_DIR, 'logs/feature_articles.jsonl')
    now = datetime.now(JST)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    week_start_utc = week_start.astimezone(timezone.utc)
    count = 0
    try:
        for line in open(log_path, encoding='utf-8'):
            try:
                entry = json.loads(line.strip())
                title = entry.get('title', '')
                pub = entry.get('published_at', '')
                if pub:
                    parsed = datetime.fromisoformat(pub.replace('Z', '+00:00'))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    if parsed >= week_start_utc and re.search(r'\d+選', title):
                        count += 1
            except (json.JSONDecodeError, ValueError):
                continue
    except FileNotFoundError:
        pass
    return count


def build_trend_article_plans(max_articles=4):
    """トレンドデータからファンが読みたい記事企画を生成"""
    themes = load_focus_themes()
    signals = load_recent_trend_signals(hours=48)
    comebacks = load_comeback_calendar()

    plans = []

    # 1. auto_directives focus_themes（バズスコア順）
    for theme in sorted(themes, key=lambda t: t.get('buzz_score', 0), reverse=True):
        topic = theme.get('topic', theme.get('title_hint', ''))
        if not topic:
            continue  # topic/title_hint両方なしはスキップ
        cat_suggest = theme.get('category_suggest', '速報')
        cat_slug = TREND_CATEGORY_MAP.get(cat_suggest, 'kpop-news')
        plans.append({
            'source': 'focus_theme',
            'title_hint': topic,
            'context': theme.get('hint', ''),
            'category_slug': cat_slug,
            'buzz_score': theme.get('buzz_score', 0),
        })

    # 2. trend_signals からエンゲージメントの高いものを集約
    keyword_groups = {}
    for sig in signals:
        kw = sig.get('keyword', '')
        if not kw:
            continue
        if kw not in keyword_groups:
            keyword_groups[kw] = {'titles': [], 'total_score': 0, 'sources': set(),
                                  'source_urls': []}
        keyword_groups[kw]['titles'].append(sig.get('title', ''))
        keyword_groups[kw]['total_score'] += sig.get('engagement_score', 1)
        keyword_groups[kw]['sources'].add(sig.get('source', ''))
        # ソースURLを収集（重複除去）
        sig_url = sig.get('url', '')
        if sig_url and sig_url not in keyword_groups[kw]['source_urls']:
            keyword_groups[kw]['source_urls'].append(sig_url)

    for kw, info in sorted(keyword_groups.items(), key=lambda x: x[1]['total_score'], reverse=True)[:10]:
        # focus_themesと重複するキーワードはスキップ
        if any(kw.lower() in t.get('topic', t.get('title_hint', '')).lower() for t in themes):
            continue
        top_titles = info['titles'][:3]
        plans.append({
            'source': 'trend_signal',
            'title_hint': f"{kw}が話題 — {top_titles[0]}" if top_titles else f"{kw}の最新動向",
            'context': f"関連ニュース: {' / '.join(top_titles[:3])}。ソース: {', '.join(info['sources'])}",
            'category_slug': 'kpop-news',
            'buzz_score': info['total_score'],
            'source_urls': info['source_urls'][:3],  # ソースURL（ファクトチェック用）
        })

    # 3. カムバックカレンダー連動
    for ev in comebacks[:3]:
        artist = ev.get('artist', ev.get('name', ''))
        event_type = ev.get('type', 'カムバック')
        date = ev.get('date', ev.get('start_date', ''))
        if artist:
            plans.append({
                'source': 'comeback_calendar',
                'title_hint': f"{artist}の{event_type}が間近 ({date})",
                'context': f"{artist} {event_type}: {ev.get('title', ev.get('description', ''))}",
                'category_slug': 'kpop-news',
                'buzz_score': 10,
            })

    # 4. 検索ボリュームブースト: GSCでIMPがあるキーワードを含む企画にボーナス
    gsc_keywords = _load_gsc_high_imp_keywords()
    if gsc_keywords:
        for plan in plans:
            hint = plan.get('title_hint', '').lower()
            for kw, imp in gsc_keywords.items():
                if kw in hint:
                    plan['buzz_score'] = plan.get('buzz_score', 0) + min(imp / 100, 10)
                    plan['_imp_boost'] = True
                    break

    # スコア順にソートして上位を返す
    plans.sort(key=lambda p: p.get('buzz_score', 0), reverse=True)
    return plans[:max_articles]


def generate_topic_title(topic_def):
    template = topic_def['tpl']
    filled = template
    if 'artist_member' in topic_def:
        pair = random.choice(topic_def['artist_member'])
        filled = filled.replace('{artist}', pair[0]).replace('{member}', pair[1])
    for key, val in topic_def.items():
        if key in ('tpl', 'artist_member'):
            continue
        if isinstance(val, list):
            filled = filled.replace('{' + key + '}', str(random.choice(val)))
    return filled


# K-POPニュースとして信頼できるドメイン（ここに載っていないソースは裏付けに使わない）
TRUSTED_SOURCE_DOMAINS = [
    # 韓国芸能メディア
    'soompi.com', 'allkpop.com', 'koreaboo.com', 'kpopstarz.com',
    'hellokpop.com', 'kpoppost.com', 'kstyle.com',
    # 韓国公式・大手
    'naver.com', 'daum.net', 'dispatch.co.kr', 'sportsseoul.com',
    'starnews.co.kr', 'newsen.com', 'osen.mt.co.kr', 'xsportsnews.com',
    'spotvnews.co.kr', 'entertain.naver.com', 'n.news.naver.com',
    'theqoo.net', 'pannchoa.com', 'netizenbuzz.blogspot.com',
    # 日本のK-POPメディア
    'kstyle.com', 'danmee.jp', 'kban.me', 'korecow.com',
    'wowkorea.jp', 'mottokorea.com', 'kpopmonster.jp',
    'kpop.co.jp', 'k-popdaebak.com',
    # 音楽・エンタメ
    'billboard.com', 'billboard.co.jp', 'oricon.co.jp',
    'melon.com', 'genie.co.kr', 'bugs.co.kr',
    # 公式
    'weverse.io', 'vlive.tv', 'hybe.co.kr', 'smtown.com',
    'ygent.com', 'jype.com', 'starshipent.com',
    # 百科事典
    'wikipedia.org', 'kpop.fandom.com', 'dbkpop.com', 'kprofiles.com',
    # 一般ニュース
    'reuters.com', 'apnews.com', 'variety.com', 'deadline.com',
    'bbc.com', 'nhk.or.jp', 'asahi.com', 'mainichi.jp',
    # 日本のエンタメ・旅行・美容（K-POP関連記事が掲載される信頼メディア）
    'gqjapan.jp', 'harpersbazaar.com', '25ans.jp', 'ellejapan.com',
    'cosmopolitan.com', 'vogue.co.jp', 'fashionpress.net',
    'modelpress.jp', 'mdpr.jp', 'natalie.mu', 'realsound.jp',
    'rollingstonejapan.com', 'barks.jp', 'musicman.co.jp',
    'hominis.media', 'cinemore.jp', 'cinemacafe.net',
    'futabanet.jp', 'tvguide.or.jp', 'thetv.jp',
    # 韓国観光・公式
    'visitseoul.net', 'visitkorea.or.kr', 'korean.visitkorea.or.kr',
    'konest.com', 'seoulnavi.com',
    # 旅行・チケット（実用情報ソースとして）
    'kkday.com', 'klook.com',
]


def _is_trusted_source(url: str) -> bool:
    """URLが信頼できるソースかどうかを判定"""
    url_lower = url.lower()
    return any(domain in url_lower for domain in TRUSTED_SOURCE_DOMAINS)


def _fetch_web_context(title: str, source_urls: list = None) -> tuple[str, list[dict]]:
    """信頼できるソースから事実情報を取得。信頼ソースなし＝記事生成不可。

    Args:
        title: 記事タイトル
        source_urls: シグナルに含まれるソースURL（Soompi等の元記事）

    Returns:
        (context_text, source_signals) — source_signalsはdict形式
        ※ source_signalsにtrusted=Trueのものがなければ生成を拒否すべき
    """
    context_parts = []
    source_signals = []

    # 1. ソースURLがあれば優先取得（元記事の内容を直接読む）
    if source_urls:
        from lib.source_reader import read_source
        for src_url in source_urls[:2]:
            text = read_source(src_url)
            if text:
                context_parts.append(f'- ソース記事({src_url[:40]}): {text[:800]}')
                source_signals.append({
                    'url': src_url,
                    'source_id': 'direct_source',
                    'title': title[:70],
                    'trusted': _is_trusted_source(src_url),
                })

    # 2. ソースURLで十分な情報が取れなければWeb検索で補完
    # 低品質ソースを除外（TikTok/YouTube/SNS等は事実の裏付けとして信頼性不足）
    _LOW_QUALITY_DOMAINS = [
        'tiktok.com', 'youtube.com', 'youtu.be', 'instagram.com',
        'facebook.com', 'twitter.com', 'x.com', 'reddit.com',
        'pinterest.com', 'ameblo.jp', 'note.com',
    ]
    if len(context_parts) < 2:
        # 2a. Tavily (優先)
        _tavily_ok = False
        try:
            tavily_key = os.environ.get('TAVILY_API_KEY', '')
            if tavily_key:
                from tavily import TavilyClient
                client = TavilyClient(api_key=tavily_key)
                response = client.search(
                    f'{title} K-POP 2026',
                    max_results=5,
                    search_depth='basic',
                    exclude_domains=['kpopjournal.tokyo'] + _LOW_QUALITY_DOMAINS,
                )
                results = response.get('results', [])
                existing_urls = {s['url'] for s in source_signals}
                for r in results[:3]:
                    r_url = r.get('url', '')
                    if r_url in existing_urls:
                        continue
                    if any(d in r_url for d in _LOW_QUALITY_DOMAINS):
                        continue
                    content_text = r.get('content', '')[:300]
                    r_title = r.get('title', '')
                    if content_text:
                        context_parts.append(f'- {r_title}: {content_text}')
                    if r_url:
                        source_signals.append({
                            'url': r_url,
                            'source_id': 'tavily',
                            'title': r_title[:70],
                            'trusted': _is_trusted_source(r_url),
                        })
                _tavily_ok = len(source_signals) > 0
        except Exception as _tavily_err:
            print(f"  [web_search] Tavily失敗: {_tavily_err}")

        # 2b. DuckDuckGo フォールバック（Tavilyがレート制限/失敗時）
        if not _tavily_ok and len(context_parts) < 2:
            try:
                from ddgs import DDGS
                with DDGS() as ddgs:
                    # タイトルから検索に最適なクエリを構築
                    _q_clean = re.sub(r'【[^】]*】|！|!|？|\?|完全ガイド|徹底解説|とは|の魅力|についての', '', title)
                    query = _q_clean.strip()[:50]
                    results = list(ddgs.text(query, max_results=5))
                    # 結果0件なら英語キーワードで再試行
                    if not results:
                        _en_words = re.findall(r'[A-Za-z][A-Za-z0-9\s]+', title)
                        if _en_words:
                            query2 = ' '.join(_en_words)[:40] + ' K-POP 2026'
                            results = list(ddgs.text(query2, max_results=5))
                existing_urls = {s['url'] for s in source_signals}
                for r in results[:4]:
                    r_url = r.get('href', '')
                    if not r_url or r_url in existing_urls:
                        continue
                    if any(d in r_url for d in _LOW_QUALITY_DOMAINS + ['kpopjournal.tokyo']):
                        continue
                    r_title = r.get('title', '')
                    content_text = r.get('body', '')[:300]
                    if content_text:
                        context_parts.append(f'- {r_title}: {content_text}')
                    if r_url:
                        source_signals.append({
                            'url': r_url,
                            'source_id': 'duckduckgo',
                            'title': r_title[:70],
                            'trusted': _is_trusted_source(r_url),
                        })
                if source_signals:
                    print(f"  [web_search] DuckDuckGo OK: {len(source_signals)}件")
            except Exception as _ddg_err:
                print(f"  [web_search] DuckDuckGo失敗: {_ddg_err}")

    context = '\n'.join(context_parts)
    return context, source_signals


def _verify_against_sources(article_html: str, source_context: str, title: str) -> str | None:
    """公開直後の即時検証: 記事内の固有名詞がソースに存在するか確認。

    ソースに存在しない楽曲名/ドラマ名/日付をLLMが創作していた場合にdraft化する。
    Returns: draft理由の文字列。問題なければNone。
    """
    import re as _re
    plain = _re.sub(r'<[^>]+>', ' ', article_html)
    plain = _re.sub(r'\s+', ' ', plain)

    # 記事内の「」で囲まれた固有名詞を抽出
    # ファンの感想コメント（長文・感情表現）は除外 — これらは記事構造上の引用であり捏造ではない
    _all_quoted = _re.findall(r'「([^」]{2,40})」', plain)
    quoted_names = []
    for _q in _all_quoted:
        # 感想・コメント系を除外（10文字以上で感情表現を含む）
        if len(_q) > 15:
            continue  # 長い引用はファンコメント
        if _re.search(r'(楽しみ|嬉しい|残念|期待|感動|最高|応援|好き|待って|素敵)', _q):
            continue  # 感情表現はファンコメント
        if _q.startswith('#'):
            continue  # ハッシュタグ
        quoted_names.append(_q)
    # 日付+イベント主張を抽出
    date_claims = _re.findall(r'(20\d{2}年\d{1,2}月\d{1,2}日)', plain)

    if not quoted_names and not date_claims:
        return None  # 固有名詞なし = ハウツー記事等 → OK

    # ソースコンテキストに含まれていない固有名詞を検出
    unsourced_names = []
    for name in quoted_names:
        # 一般的な表現はスキップ
        if len(name) <= 3 or name in ('未発表', '詳細未定', '時期未定', '確認中'):
            continue
        # タイトル内の語句はスキップ
        if name in title:
            continue
        # ソースに存在するか
        if name not in source_context and name.lower() not in source_context.lower():
            unsourced_names.append(name)

    # ソースにない固有名詞が3つ以上 → 捏造の可能性が高い
    if len(unsourced_names) >= 3:
        return f"ソースに存在しない固有名詞{len(unsourced_names)}件: {unsourced_names[:5]}"

    # 過去の日付を未来と偽っていないかチェック
    # （2022-2024年のコンテンツを2026年と書いているパターン）
    for date_str in date_claims:
        # ソースに同じ日付が含まれていない場合は警告
        if date_str not in source_context:
            # 2026年の日付でソースにないもの → 捏造の可能性
            if '2026年' in date_str:
                unsourced_names.append(f'日付: {date_str}')

    if len(unsourced_names) >= 3:
        return f"ソースに存在しない固有名詞/日付{len(unsourced_names)}件: {unsourced_names[:5]}"

    return None


def _draft_post(post_id: int):
    """記事をdraftに変更"""
    try:
        import requests, base64
        auth = base64.b64encode(
            f"{os.getenv('WP_USER','')}:{os.getenv('WP_PASS','')}".encode()
        ).decode()
        requests.post(
            f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}',
            headers={'Authorization': f'Basic {auth}', 'Content-Type': 'application/json'},
            json={'status': 'draft'},
            timeout=15,
        )
    except Exception as e:
        print(f"    draft_post err: {e}")


def generate_article_content(title, category_slug, trend_context=None, source_urls=None):
    """トレンドコンテキスト付き記事生成（信頼ソース必須）

    信頼できるソース(TRUSTED_SOURCE_DOMAINS)が1件もなければ生成を拒否する。
    メディアとして誤情報は許されない。ソースなき記事は書かない。
    """
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        return None

    contexts = {
        'korea-travel': '韓国旅行・聖地巡礼の専門家として、ファン目線で実用的な詳細記事',
        'beauty': 'K-POPメイクアップの専門家として、具体的なアイドルの名前と最新の話題を交えて',
        'oshikatsu': '推し活経験豊富なK-POPファンとして、実践的な情報を提供',
        'kdrama-movie': '韓国エンタメに精通した立場から、最新の話題と見どころを伝える',
        'kpop-news': 'K-POPの最新トレンドに詳しいエンタメライターとして、ファンが知りたい情報を具体的に',
    }

    today_str = datetime.now(JST).strftime('%Y年%m月%d日')
    year_month = datetime.now(JST).strftime('%Y年%m月')

    # Web検索で事実情報を取得（捏造防止）
    web_context, web_sources = _fetch_web_context(title, source_urls=source_urls)

    # ===== ソースゲート（最低1件のWeb情報源が必要） =====
    # 信頼ドメイン(soompi等)があればベスト。なくてもTavilyで1件以上あれば生成可
    trusted_sources = [s for s in web_sources if s.get('trusted')]
    if not web_sources:
        # Web検索結果が0件 = ソース皆無 → 生成不可
        print(f"  [feature] REJECT: Webソース0件。記事を生成しません: {title[:50]}")
        print(f"    TAVILY_API_KEY設定確認 or ネットワーク問題の可能性")
        return None, [], ''
    if not trusted_sources:
        # 信頼ドメインはないが一般ソースはある → WARNのみで生成続行
        print(f"  [feature] WARN: 信頼ドメインソース0件。一般ソース{len(web_sources)}件で生成続行")
        print(f"    ソース: {[s.get('url','')[:50] for s in web_sources[:3]]}")

    # トレンド記事用の追加コンテキスト
    # 内部施策用語をLLMプロンプトから除去（GSC横展開/CTR/IMP等はオペレーション用語で記事の題材ではない）
    trend_section = ""
    if trend_context:
        import re as _re_ctx
        _cleaned_context = trend_context
        # 内部施策用語を除去
        _internal_terms = [
            r'GSC横展開[：:]?\s*',
            r'GSCトップ記事/[^\s]+の横展開[。．]?\s*',
            r'GSCクリック\d+件/CTR[\d.]+%の横展開\s*',
            r'IMP=\d+\s*CTR=[\d.]+%',
            r'潜在\+\d+clicks[。．]?\s*',
            r'関連キーワードで横展開記事を作成[。．]?\s*',
            r'シグナル:\s*search_driven\s*',
            r'元記事/[^\s]+\s*',
        ]
        for _pat in _internal_terms:
            _cleaned_context = _re_ctx.sub(_pat, '', _cleaned_context)
        _cleaned_context = _cleaned_context.strip()

        if _cleaned_context:
            trend_section = f"""
【トレンド情報（この情報をベースに記事を書くこと）】
{_cleaned_context}

【重要】上記のトレンド情報に基づいて、具体的なアーティスト名・日付・出来事を必ず含めて書くこと。
抽象的な「○○と言われています」は禁止。具体的な事実と数字で書くこと。"""
        else:
            # 内部用語を除去したら空になった → Web検索結果のみで生成
            print(f"  [feature] trend_context was internal-only metadata, stripped")

    if web_context:
        # Web検索結果の関連度チェック: タイトルのキーワードがソース内容に含まれているか
        _title_words = set(re.sub(r'[！!？?「」【】\s]+', ' ', title).split())
        _title_words -= {'の', 'と', 'で', 'に', 'は', 'を', 'が', 'も', 'や', 'から', 'まで', 'など'}
        _relevant_count = 0
        for _tw in _title_words:
            if len(_tw) >= 2 and _tw in web_context:
                _relevant_count += 1
        _relevance = _relevant_count / max(len(_title_words), 1)

        if _relevance < 0.1 and len(web_sources) > 0:
            print(f"  [feature] WARN: Web検索結果の関連度が低い ({_relevance:.0%})。ソースが記事テーマと無関係の可能性")
            # 信頼ソースが1件でもあれば生成続行（信頼ドメインの判定で十分）
            if not trusted_sources and (not trend_context or not trend_section):
                print(f"  [feature] BLOCK: 関連ソースなし+トレンドなし。捏造リスクが高いため生成中止: {title[:40]}")
                return None, [], ''

        trend_section += f"""

【Web検索で取得した事実情報（この情報のみを事実として使うこと）】
{web_context}

【絶対厳守ルール — 違反した場合、記事は即座に削除されます】
1. 上記のWeb検索結果に含まれない情報を事実として書かないこと。ソースに書いていないことは存在しない。
2. 楽曲名・ドラマ名・イベント名・日付を自分で創作しないこと。ソースに記載がなければ「発表されていない」と書くこと。
3. 過去にリリース済みの楽曲やドラマを、未来の日付で「公開予定」「リリース予定」と書かないこと。
4. 別のグループ・アーティストの楽曲を、記事の主題アーティストの楽曲として書かないこと。
5. 確認できない日付は「時期未定」、確認できない事実は「詳細未発表」と明記すること。字数を稼ぐために未確認情報を追加することは絶対に禁止。"""
    elif not trend_context:
        # Web検索結果もトレンドコンテキストもない → 事実なしで記事を書かせない
        print(f"  [feature] BLOCK: Web検索結果なし+トレンドなし。捏造リスクが高いため生成中止: {title[:40]}")
        return None, [], ''

    # アーティスト基本情報をプロンプトに注入（メンバー人数/デビュー年の捏造防止）
    _profile_section = ''
    try:
        with open('/home/aiuser/kpop-ai-system/config/artist_profiles.json', 'r', encoding='utf-8') as _pf:
            _profiles = json.load(_pf).get('profiles', {})
        _title_lower = title.lower()
        _matched = []
        for _k, _prof in _profiles.items():
            _names = [_prof.get('display_name', ''), _prof.get('name_en', ''), _k]
            if any(_n.lower() in _title_lower for _n in _names if _n):
                _members = _prof.get('members', [])
                _matched.append(f"  - {_prof['display_name']}: {len(_members)}人組, "
                                f"{_prof.get('debut_year', '?')}年デビュー, "
                                f"メンバー: {', '.join(_members)}")
        if _matched:
            _profile_section = ("\n\n【アーティスト正式情報（これと矛盾する内容を絶対に書かないこと）】\n"
                                + '\n'.join(_matched))
    except Exception:
        pass

    prompt = f"""以下のタイトルでK-POPファン向けの記事を書いてください。

【今日の日付】{today_str}
【タイトル】{title}
【視点】{contexts.get(category_slug, '')}
{trend_section}{_profile_section}

【要件】
- 本文中に必ず現在の年月({year_month})を含めること
- 1500-3000字（HTMLタグ込み。事実に基づいた内容のみ。字数を稼ぐために未確認情報を追加しない）
- HTMLで記述、h2セクション最低4つ
- リード文 (5W1H骨子) → 詳細展開 → まとめ の三段構成
- 文末バリエーション (~した/~紹介する/~始まった/~人気/~注目)
- 「以上」「いかがでしょうか」「皆さん」等の口語的表現禁止
- 「AI」「ChatGPT」等のメタ言及禁止
- 末尾に <p class="kpj-disclaimer">※情報は{year_month}時点のものです。最新情報は公式サイトをご確認ください。</p>

【構造化要件（読者滞在率向上 — 必須）】
- 冒頭リード直後に「この記事で分かること」箇条書き（<ul>で3-5項目）
- 記事テーマに応じた比較表・一覧表を最低1つ<table>で挿入
  例) キャスト表/メンバープロフィール表/日程表/料金比較表/ランキング表
- 「よくある質問」FAQセクション（<h3>Q:形式で2問以上）を必ず含める
- ガイド系テーマにはステップバイステップ手順（<ol>番号付き）を含める

【具体性ルール（厳守）】
- アーティスト名・メンバー名を必ず実名で書くこと。「人気グループ」「あるメンバー」等の曖昧表現禁止
- 日付・数字を具体的に書くこと。「最近」「近年」「多くの」は禁止 → 「2026年4月25日」「55万人」「8億回再生」
- 「～と言われています」「～と話題です」だけで終わらない。何がどう話題なのか具体的に書く
- SNSの反応を記事に織り込むこと（「Xでは「○○」がトレンド入り」「ファンからは「○○」との声」等）
- 架空の情報を絶対に書かない。確認できない事実は「未発表」「詳細は追って発表予定」と明記

【絶対厳禁】
- 人名を「A」「B」「Xさん」等に匿名化しない
- kpopjournal.tokyo への内部リンクを絶対に書かない
- 「あわせて読みたい」「関連記事」「詳しくはこちら」セクション禁止
- 架空のURLやページへのリンク禁止
- 全ての <a> タグ禁止（リンクは別工程で挿入）
- 架空の店舗名・施設名を絶対に捏造しない

【出力】HTML本文のみ。前置き・後書き不要。セクション識別子ラベル禁止"""

    from lib.agent_learning_loop import inject_lessons_to_prompt
    prompt = inject_lessons_to_prompt('feature_article_writer', prompt)

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.7,
        'max_tokens': 6000,
    }).encode()

    try:
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
            data=body, headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=120).read())
        content = r['choices'][0]['message']['content'].strip()
        content = re.sub(r'^```html\s*\n?', '', content, flags=re.IGNORECASE)
        content = re.sub(r'\n?```\s*$', '', content)
        # Web検索ソースURL+ソーステキストも返す（即時検証用）
        return content.strip(), web_sources, web_context
    except Exception as e:
        print(f"  GPT err: {e}")
        return None, [], ''


def generate_trend_title(plan):
    """トレンドプランからGPTでタイトルを生成"""
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        return plan['title_hint']

    prompt = f"""以下のトレンド情報から、K-POPファンがクリックしたくなる日本語の記事タイトルを1つだけ生成してください。

トレンド: {plan['title_hint']}
詳細: {plan.get('context', '')}

ルール:
- 具体的なアーティスト名・数字・出来事を含めること
- 「○選」「まとめ」は使わない（トレンド記事なので）
- 疑問形、感嘆、数字入りで注目を引く
- 50文字以内
- タイトル文字列のみ出力。説明・番号・引用符不要"""

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.8,
        'max_tokens': 100,
    }).encode()

    try:
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
            data=body, headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        title = r['choices'][0]['message']['content'].strip()
        title = title.strip('"\'「」『』')
        return title if len(title) > 5 else plan['title_hint']
    except Exception:
        return plan['title_hint']


def post_publish_audit(post_id):
    """公開後の必須監査 — BLOCK判定ならdraft化"""
    import urllib.request as _req
    try:
        url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}"
        req = _req.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        post = json.loads(_req.urlopen(req, timeout=30).read())

        from lib.full_audit_engine import full_audit
        issues = full_audit(post, post_type='post')
        if isinstance(issues, dict):
            issues = issues.get('issues', [])

        criticals = [i for i in issues if isinstance(i, dict) and i.get('severity') in ('critical', 'high')]

        # サムネイル関連性チェック
        media_id = post.get('featured_media', 0)
        if not media_id:
            criticals.append({'severity': 'critical', 'type': 'no_thumbnail', 'detail': 'サムネイルなし'})
        else:
            try:
                m_url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/media/{media_id}?_fields=alt_text"
                m_req = _req.Request(m_url, headers={'Authorization': f'Basic {AUTH}'})
                m_data = json.loads(_req.urlopen(m_req, timeout=15).read())
                if not m_data.get('alt_text'):
                    issues.append({'severity': 'medium', 'type': 'empty_alt', 'detail': 'サムネALT空'})
            except Exception:
                pass

        # ファクトチェック（浅いチェック）
        try:
            from lib.fact_checker import check_article
            title_text = post['title']['rendered'] if isinstance(post['title'], dict) else post['title']
            body_text = re.sub('<[^>]+>', '', post['content']['rendered'] if isinstance(post['content'], dict) else post['content'])[:2000]
            fc = check_article(title_text, body_text)
            if isinstance(fc, dict) and fc.get('verdict') == 'BLOCK':
                criticals.append({'severity': 'critical', 'type': 'fact_check_block', 'detail': str(fc.get('issues', ''))[:100]})
        except Exception as e:
            print(f"    fact_check err: {e}")

        # LLMファクトチェック（深いチェック — 公開前に捏造を検出）
        try:
            from pipeline.llm_proofreader import proofread_post
            pr = proofread_post(post)
            pr_score = pr.get('score', 100)
            pr_critical = pr.get('critical', [])
            pr_high = pr.get('high', [])
            if pr_critical:
                for c in pr_critical:
                    criticals.append({'severity': 'critical', 'type': 'llm_factcheck_critical',
                                     'detail': str(c)[:100]})
                print(f"    LLM factcheck: score={pr_score} CRITICAL={len(pr_critical)}")
            elif pr_high:
                # HIGHはWARN扱い（draft化しない）。CRITICALのみdraft化
                print(f"    LLM factcheck: score={pr_score} HIGH={len(pr_high)} (WARN — draft化せず)")
            else:
                print(f"    LLM factcheck: score={pr_score} PASS")
        except Exception as e:
            print(f"    llm_factcheck err: {e}")

        if criticals:
            # BLOCK: draft化
            try:
                draft_body = json.dumps({'status': 'draft'}).encode()
                draft_req = _req.Request(url, data=draft_body, method='POST',
                    headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
                _req.urlopen(draft_req, timeout=30)
                print(f"    ⛔ 監査BLOCK → draft化 (理由: {', '.join(c.get('type','?') for c in criticals)})")
            except Exception:
                print(f"    ⛔ 監査BLOCK検知 but draft化失敗")
            return False

        warn_count = len([i for i in issues if isinstance(i, dict) and i.get('severity') in ('medium', 'low')])
        print(f"    ✅ 監査PASS (warn={warn_count})")
        return True

    except Exception as e:
        print(f"    監査エラー: {e}")
        return True  # 監査自体の失敗では公開を止めない


def _detect_artist(title, content=''):
    """タイトル/本文からアーティスト名を検出"""
    known = [
        'BTS', 'BLACKPINK', 'TWICE', 'aespa', 'NewJeans', 'IVE',
        'LE SSERAFIM', 'Stray Kids', 'SEVENTEEN', 'ENHYPEN', 'NMIXX',
        'ITZY', 'TXT', 'EXO', '2PM', 'BABYMONSTER', 'RIIZE', 'ILLIT',
        'NCT', 'Red Velvet', 'BIGBANG', 'SHINee', 'GOT7', 'ASTRO',
        '(G)I-DLE', 'ATEEZ', 'TREASURE', 'MONSTA X', 'DAY6',
    ]
    search = (title + ' ' + content[:300]).lower()
    for g in known:
        if g.lower() in search:
            return g
    return None


def post_to_wp(title, content, category_id, artist=None, source_url=None, source_signals=None):
    """unified_publish 経由で投稿 + 公開後監査"""
    from lib.unified_publisher import unified_publish
    # アーティスト名を自動検出（未指定時）
    if not artist:
        artist = _detect_artist(title, content)
    try:
        r = unified_publish(
            raw_title=title,
            body_html=content,
            kind='feature',
            confidence='high',
            force_category_id=category_id,
            artist=artist,
            source_url=source_url,
            source_signals=source_signals,
        )
        if r and r.get('success'):
            post_id = r.get('post_id')
            # 公開後の必須監査
            if post_id:
                audit_ok = post_publish_audit(post_id)
                if not audit_ok:
                    return None  # 監査NGならpost_id返さない(生成失敗扱い)
            return post_id
        else:
            print(f"  unified_publish fail: {r.get('error', 'unknown') if r else 'None'}")
            return None
    except Exception as e:
        print(f"  unified_publish err: {e}")
        return None


def post_to_wp_draft(title, content, category_id):
    """draft状態でWPに投稿"""
    from lib.text_sanitizer import strip_template_labels, sanitize_gpt_html
    title = strip_template_labels(title)
    content = sanitize_gpt_html(content)

    try:
        from lib.pre_publish_gate import pre_publish_gate
        gate = pre_publish_gate(
            title=title, body_html=content,
            kind='feature', status='draft',
            categories=[category_id] if category_id else [],
        )
        if gate['issues']:
            print(f"  Draft gate: {gate['verdict']} ({len(gate['issues'])}件)")
    except Exception as e:
        print(f"  Draft gate skip: {e}")

    body_data = {
        'title': title,
        'content': content,
        'status': 'draft',
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
        print(f"  WP draft err: {e}")
        return None


def load_feature_topics():
    """config/feature_topics.json からトピック一覧を読み込み"""
    path = os.path.join(BASE_DIR, 'config/feature_topics.json')
    try:
        data = json.load(open(path))
        return {t['id']: t for t in data.get('topics', [])}
    except Exception:
        return {}


def log_article(post_id, title, category_slug, category_id, source='template', topic_id=None, status='publish'):
    """記事生成ログを記録"""
    log_path = os.path.join(BASE_DIR, 'logs/feature_articles.jsonl')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    entry = {
        'post_id': post_id, 'title': title,
        'category': category_slug, 'category_id': category_id,
        'source': source, 'status': status,
        'published_at': datetime.now(timezone.utc).isoformat(),
    }
    if topic_id:
        entry['topic_id'] = topic_id
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def run_topic_mode(topic_ids, as_draft=False):
    """--topics で指定されたトピックを生成"""
    topics_map = load_feature_topics()
    if not topics_map:
        print("feature_topics.json が空またはロード失敗")
        return

    success = 0
    results = []
    for tid in topic_ids:
        topic = topics_map.get(tid)
        if not topic:
            print(f"  トピック未登録: {tid}")
            continue

        title = topic['title']
        cat_slug = topic.get('category', 'oshikatsu')
        category_id = get_category_id(cat_slug)

        print(f"\n生成中: [{cat_slug}] {title}")
        result = generate_article_content(title, cat_slug)
        content, web_sources, web_context = (result + ('',))[:3] if isinstance(result, tuple) else (result, [], '')
        if not content or len(content) < 1500:
            print(f"  生成失敗 or 短すぎ ({len(content) if content else 0}字)")
            continue

        try:
            from lib.cta_injector import inject_cta_into_content
            content = inject_cta_into_content(title, content)
        except Exception as e:
            print(f"  CTA inject warn: {e}")

        source_url = (web_sources[0].get('url') if isinstance(web_sources[0], dict) else web_sources[0]) if web_sources else None
        if as_draft:
            post_id = post_to_wp_draft(title, content, category_id)
            status_label = 'draft'
        else:
            post_id = post_to_wp(title, content, category_id, source_url=source_url,
                                 source_signals=web_sources)
            status_label = 'publish'

        if post_id:
            print(f"  post_id={post_id} {status_label} ({len(content)}字)")
            success += 1
            results.append({'topic_id': tid, 'post_id': post_id, 'title': title, 'status': status_label})
            log_article(post_id, title, cat_slug, category_id, source='topic_mode', topic_id=tid, status=status_label)

    print(f"\n{success}/{len(topic_ids)}件 特集記事生成")
    return results


def get_recent_titles():
    """直近30日のタイトルセット取得（重複防止用）"""
    recent = set()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S')
        url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?after={cutoff}&per_page=100&_fields=title"
        req = urllib.request.Request(url)
        for p in json.loads(urllib.request.urlopen(req, timeout=20).read()):
            t = p['title']['rendered'] if isinstance(p['title'], dict) else p['title']
            recent.add(t[:30])
    except Exception:
        pass
    return recent


# トピック類似度キーワード (同じセットに2語以上マッチ→同テーマと判定)
_TOPIC_KEYWORD_SETS = [
    {'ガラス肌', '美肌', 'スキンケア', '肌ケア', '肌', 'ブルーム肌', 'クラウドグロウ', '神肌', 'CICA', 'PDRN'},
    {'聖地巡礼', '聖地', 'ファンスポット', '訪問'},
    {'コンサート', '参戦', 'ライブ', 'グッズ'},
    {'ライトスティック', 'ペンライト', '公式グッズ'},
    {'チャート', 'ランキング', 'TOP10', 'Billboard'},
    {'韓国語', '学習', 'フレーズ'},
    {'ダイエット', '食事', '体型'},
    {'空港', 'コーデ', 'ファッション'},
    {'MV', '再生回数', 'YouTube'},
]


def _extract_topic_keys(title: str) -> set:
    """タイトルからトピックキーワードセットを抽出"""
    matched = set()
    for kw_set in _TOPIC_KEYWORD_SETS:
        hits = {kw for kw in kw_set if kw in title}
        if hits:
            matched.update(hits)
    return matched


def is_topic_duplicate(title: str, recent_titles: set) -> bool:
    """タイトルが既存記事とトピックレベルで重複しているか判定

    先頭30字一致に加え、キーワード重複・WP API検索の3段チェック。
    同一テーマの記事が1件でもあればTrue（重複ゼロ方針）。
    """
    # 1. 先頭30字一致 (従来ロジック)
    if title[:30] in recent_titles:
        return True

    # 2. トピックキーワード類似度チェック
    new_keys = _extract_topic_keys(title)
    if not new_keys:
        # キーワード抽出できない場合は単語分割で比較
        import re as _re
        _words = set(_re.findall(r'[A-Za-z]{2,}|[ァ-ヶー]{2,}|[一-龥]{2,}', title))
        _words -= {'ガイド', '完全', '最新', '徹底', '紹介', '解説', 'まとめ'}
        for existing in recent_titles:
            _ex_words = set(_re.findall(r'[A-Za-z]{2,}|[ァ-ヶー]{2,}|[一-龥]{2,}', existing))
            overlap = len(_words & _ex_words)
            if overlap >= 2 and overlap / max(len(_words), 1) > 0.4:
                return True
        return False

    matching_sets = []
    for kw_set in _TOPIC_KEYWORD_SETS:
        if len(new_keys & kw_set) >= 1:
            matching_sets.append(kw_set)

    if not matching_sets:
        return False

    # 直近記事のうち同じセットに属するものをカウント
    for existing in recent_titles:
        for kw_set in matching_sets:
            existing_hits = {kw for kw in kw_set if kw in existing}
            if len(existing_hits) >= 1:
                return True  # 同テーマ1件でも重複（0→1に厳格化）

    # 3. WP APIで公開済み記事を検索（cron跨ぎの重複防止）
    try:
        import urllib.request, urllib.parse
        _search_q = re.sub(r'[！!？?\s]+', ' ', title)[:25]
        _api = os.environ.get('WP_API_URL', 'https://www.kpopjournal.tokyo/wp-json/wp/v2')
        _url = f'{_api}/posts?search={urllib.parse.quote(_search_q)}&status=publish&per_page=3&_fields=id,title&after={_seven_days_ago()}'
        _req = urllib.request.Request(_url, headers={'User-Agent': 'dup-check/1.0'})
        with urllib.request.urlopen(_req, timeout=10) as _resp:
            _existing = json.loads(_resp.read())
        if _existing:
            return True
    except Exception:
        pass

    return False


def _seven_days_ago():
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone(timedelta(hours=9))) - timedelta(days=7)).strftime('%Y-%m-%dT00:00:00')


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--topics', type=str, default=None,
                        help='カンマ区切りのトピックID (feature_topics.jsonから)')
    parser.add_argument('--as_draft', action='store_true',
                        help='draft状態で投稿')
    parser.add_argument('--max', type=int, default=6,
                        help='1回の実行で生成する最大記事数')
    args = parser.parse_args()

    try:
        from lib.staff_task_manager import begin_task, end_task as _end_task
        _STF_ID, _TSK_ID = "KPJ-0002", begin_task("KPJ-0002", "feature_article_generator")
    except Exception:
        _STF_ID = _TSK_ID = None

    # --topics モード
    if args.topics:
        topic_ids = [t.strip() for t in args.topics.split(',')]
        run_topic_mode(topic_ids, as_draft=args.as_draft)
        return

    # 戦略ファイル読み込み
    strategy = load_strategy()
    if strategy:
        print(f"  戦略v{strategy.get('version', '?')} loaded (reviewed: {strategy.get('last_reviewed', '?')})")
    else:
        print("  WARNING: content_strategy.json 読み込み失敗、デフォルト配分で実行")

    print(f"=== feature_article_generator v3 (トレンド駆動): {datetime.now(JST).strftime('%Y-%m-%d %H:%M')} ===")

    recent_titles = get_recent_titles()
    listicle_count = count_listicles_this_week()
    print(f"  今週の○選記事: {listicle_count}/{MAX_LISTICLE_PER_WEEK}")

    success = 0
    max_articles = args.max

    # ── Phase 1: トレンド記事（70%枠）──
    trend_slots = max(1, int(max_articles * 0.7))
    trend_plans = build_trend_article_plans(max_articles=trend_slots + 2)

    print(f"\n── Phase 1: トレンド記事 (最大{trend_slots}本) ──")
    if not trend_plans:
        print("  トレンドデータなし → テンプレートにフォールバック")

    trend_generated = 0
    for plan in trend_plans:
        if trend_generated >= trend_slots:
            break

        title = generate_trend_title(plan)
        if is_topic_duplicate(title, recent_titles):
            print(f"  トピック重複スキップ: {title[:40]}...")
            continue

        category_slug = plan['category_slug']
        category_id = get_category_id(category_slug)

        print(f"\n  [{plan['source']}] {title}")
        result = generate_article_content(title, category_slug,
                                          trend_context=plan.get('context'),
                                          source_urls=plan.get('source_urls'))
        if isinstance(result, tuple) and len(result) == 3:
            content, web_sources, web_context = result
        elif isinstance(result, tuple):
            content, web_sources = result
            web_context = ''
        else:
            content, web_sources, web_context = result, [], ''
        if not content or len(content) < 1500:
            print(f"    生成失敗 or 短すぎ ({len(content) if content else 0}字)")
            continue

        try:
            from lib.cta_injector import inject_cta_into_content
            content = inject_cta_into_content(title, content)
        except Exception as e:
            print(f"    CTA inject warn: {e}")

        source_url = (web_sources[0].get('url') if isinstance(web_sources[0], dict) else web_sources[0]) if web_sources else None
        if args.as_draft:
            post_id = post_to_wp_draft(title, content, category_id)
        else:
            post_id = post_to_wp(title, content, category_id, source_url=source_url,
                                 source_signals=web_sources)

        if post_id:
            status = 'draft' if args.as_draft else 'publish'
            print(f"    post_id={post_id} {status} ({len(content)}字)")
            # === 公開直後の即時検証 ===
            # ソースに存在しない事実主張がないかチェック（公開後最大14時間の被害を防ぐ）
            if status == 'publish' and web_context:
                try:
                    _draft_reason = _verify_against_sources(content, web_context, title)
                    if _draft_reason:
                        print(f"    即時DRAFT化: {_draft_reason}")
                        _draft_post(post_id)
                        status = 'draft'
                except Exception as _ve:
                    print(f"    verify err (続行): {_ve}")
            # 統一ポストパブリッシュフック
            if status == 'publish':
                try:
                    from lib.post_publish_hook import run_post_publish
                    hook_r = run_post_publish(post_id)
                    if hook_r.get('status') == 'draft':
                        status = 'draft'
                except Exception as e:
                    print(f"    hook err: {e}")
            success += 1
            trend_generated += 1
            recent_titles.add(title[:30])
            log_article(post_id, title, category_slug, category_id, source=plan['source'], status=status)

    # ── Phase 2: テンプレート記事（30%枠、○選は週2本上限）──
    template_slots = max_articles - trend_generated
    if template_slots <= 0:
        template_slots = 1

    print(f"\n── Phase 2: テンプレート記事 (最大{template_slots}本) ──")

    cat_slugs = list(TEMPLATE_TOPICS.keys())
    random.shuffle(cat_slugs)

    template_generated = 0
    for cat_slug in cat_slugs:
        if template_generated >= template_slots:
            break

        topics = TEMPLATE_TOPICS[cat_slug]
        if not topics:
            continue

        category_id = get_category_id(cat_slug)
        if not category_id:
            print(f"  カテゴリID取得失敗: {cat_slug}")
            continue

        title = None
        for _ in range(3):
            topic_def = random.choice(topics)
            title = generate_topic_title(topic_def)
            if not is_topic_duplicate(title, recent_titles):
                break
        else:
            print(f"  {cat_slug} トピック重複多すぎ、スキップ")
            continue

        # ○選の週次上限チェック
        if re.search(r'\d+選', title) and listicle_count >= MAX_LISTICLE_PER_WEEK:
            print(f"  ○選上限到達({listicle_count}/{MAX_LISTICLE_PER_WEEK})、スキップ: {title[:40]}")
            continue

        # 戦略ベースの抑制チェック
        if strategy:
            skip, reason = should_deprioritize(title, cat_slug, strategy)
            if skip:
                print(f"  戦略スキップ: {reason}")
                continue

        print(f"\n  [template] {title}")
        result = generate_article_content(title, cat_slug)
        content, web_sources, web_context = (result + ('',))[:3] if isinstance(result, tuple) else (result, [], '')
        if not content or len(content) < 1500:
            print(f"    生成失敗 or 短すぎ ({len(content) if content else 0}字)")
            continue

        try:
            from lib.cta_injector import inject_cta_into_content
            content = inject_cta_into_content(title, content)
        except Exception as e:
            print(f"    CTA inject warn: {e}")

        source_url = (web_sources[0].get('url') if isinstance(web_sources[0], dict) else web_sources[0]) if web_sources else None
        if args.as_draft:
            post_id = post_to_wp_draft(title, content, category_id)
        else:
            post_id = post_to_wp(title, content, category_id, source_url=source_url,
                                 source_signals=web_sources)

        if post_id:
            status = 'draft' if args.as_draft else 'publish'
            print(f"    post_id={post_id} {status} ({len(content)}字)")
            # 統一ポストパブリッシュフック
            if status == 'publish':
                try:
                    from lib.post_publish_hook import run_post_publish
                    hook_r = run_post_publish(post_id)
                    if hook_r.get('status') == 'draft':
                        status = 'draft'
                except Exception as e:
                    print(f"    hook err: {e}")
            success += 1
            template_generated += 1
            recent_titles.add(title[:30])
            if re.search(r'\d+選', title):
                listicle_count += 1
            log_article(post_id, title, cat_slug, category_id, source='template', status=status)

    print(f"\n=== 完了: {success}本生成 (トレンド{trend_generated}+テンプレート{template_generated}) ===")


try:
    if _TSK_ID and _STF_ID:
        _end_task(_STF_ID, _TSK_ID, "success")
except Exception:
    pass

if __name__ == '__main__':
    main()
