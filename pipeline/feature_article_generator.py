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
        cat_suggest = theme.get('category_suggest', '速報')
        cat_slug = TREND_CATEGORY_MAP.get(cat_suggest, 'kpop-news')
        plans.append({
            'source': 'focus_theme',
            'title_hint': theme['topic'],
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
            keyword_groups[kw] = {'titles': [], 'total_score': 0, 'sources': set()}
        keyword_groups[kw]['titles'].append(sig.get('title', ''))
        keyword_groups[kw]['total_score'] += sig.get('engagement_score', 1)
        keyword_groups[kw]['sources'].add(sig.get('source', ''))

    for kw, info in sorted(keyword_groups.items(), key=lambda x: x[1]['total_score'], reverse=True)[:10]:
        # focus_themesと重複するキーワードはスキップ
        if any(kw.lower() in t.get('topic', '').lower() for t in themes):
            continue
        top_titles = info['titles'][:3]
        plans.append({
            'source': 'trend_signal',
            'title_hint': f"{kw}が話題 — {top_titles[0]}" if top_titles else f"{kw}の最新動向",
            'context': f"関連ニュース: {' / '.join(top_titles[:3])}。ソース: {', '.join(info['sources'])}",
            'category_slug': 'kpop-news',
            'buzz_score': info['total_score'],
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


def generate_article_content(title, category_slug, trend_context=None):
    """トレンドコンテキスト付き記事生成"""
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

    # トレンド記事用の追加コンテキスト
    trend_section = ""
    if trend_context:
        trend_section = f"""
【トレンド情報（この情報をベースに記事を書くこと）】
{trend_context}

【重要】上記のトレンド情報に基づいて、具体的なアーティスト名・日付・出来事を必ず含めて書くこと。
抽象的な「○○と言われています」は禁止。具体的な事実と数字で書くこと。"""

    prompt = f"""以下のタイトルでK-POPファン向けの記事を書いてください。

【今日の日付】{today_str}
【タイトル】{title}
【視点】{contexts.get(category_slug, '')}
{trend_section}

【要件】
- 本文中に必ず現在の年月({year_month})を含めること
- 2000-3000字（HTMLタグ込み。短すぎると不採用になるため必ず2000字以上書くこと）
- HTMLで記述、h2セクション最低4つ
- リード文 (5W1H骨子) → 詳細展開 → まとめ の三段構成
- 文末バリエーション (~した/~紹介する/~始まった/~人気/~注目)
- 「以上」「いかがでしょうか」「皆さん」等の口語的表現禁止
- 「AI」「ChatGPT」等のメタ言及禁止
- 末尾に <p class="kpj-disclaimer">※情報は{year_month}時点のものです。最新情報は公式サイトをご確認ください。</p>

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
        'max_tokens': 4000,
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

        # ファクトチェック
        try:
            from lib.fact_checker import check_article
            title_text = post['title']['rendered'] if isinstance(post['title'], dict) else post['title']
            body_text = re.sub('<[^>]+>', '', post['content']['rendered'] if isinstance(post['content'], dict) else post['content'])[:2000]
            fc = check_article(title_text, body_text)
            if isinstance(fc, dict) and fc.get('verdict') == 'BLOCK':
                criticals.append({'severity': 'critical', 'type': 'fact_check_block', 'detail': str(fc.get('issues', ''))[:100]})
        except Exception as e:
            print(f"    fact_check err: {e}")

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


def post_to_wp(title, content, category_id, artist=None):
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
        content = generate_article_content(title, cat_slug)
        if not content or len(content) < 1500:
            print(f"  生成失敗 or 短すぎ ({len(content) if content else 0}字)")
            continue

        try:
            from lib.cta_injector import inject_cta_into_content
            content = inject_cta_into_content(title, content)
        except Exception as e:
            print(f"  CTA inject warn: {e}")

        if as_draft:
            post_id = post_to_wp_draft(title, content, category_id)
            status_label = 'draft'
        else:
            post_id = post_to_wp(title, content, category_id)
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
        if title[:30] in recent_titles:
            print(f"  重複スキップ: {title[:40]}...")
            continue

        category_slug = plan['category_slug']
        category_id = get_category_id(category_slug)

        print(f"\n  [{plan['source']}] {title}")
        content = generate_article_content(title, category_slug, trend_context=plan.get('context'))
        if not content or len(content) < 1500:
            print(f"    生成失敗 or 短すぎ ({len(content) if content else 0}字)")
            continue

        try:
            from lib.cta_injector import inject_cta_into_content
            content = inject_cta_into_content(title, content)
        except Exception as e:
            print(f"    CTA inject warn: {e}")

        if args.as_draft:
            post_id = post_to_wp_draft(title, content, category_id)
        else:
            post_id = post_to_wp(title, content, category_id)

        if post_id:
            status = 'draft' if args.as_draft else 'publish'
            print(f"    post_id={post_id} {status} ({len(content)}字)")
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
            if title[:30] not in recent_titles:
                break
        else:
            print(f"  {cat_slug} 重複多すぎ、スキップ")
            continue

        # ○選の週次上限チェック
        if re.search(r'\d+選', title) and listicle_count >= MAX_LISTICLE_PER_WEEK:
            print(f"  ○選上限到達({listicle_count}/{MAX_LISTICLE_PER_WEEK})、スキップ: {title[:40]}")
            continue

        print(f"\n  [template] {title}")
        content = generate_article_content(title, cat_slug)
        if not content or len(content) < 1500:
            print(f"    生成失敗 or 短すぎ ({len(content) if content else 0}字)")
            continue

        try:
            from lib.cta_injector import inject_cta_into_content
            content = inject_cta_into_content(title, content)
        except Exception as e:
            print(f"    CTA inject warn: {e}")

        if args.as_draft:
            post_id = post_to_wp_draft(title, content, category_id)
        else:
            post_id = post_to_wp(title, content, category_id)

        if post_id:
            status = 'draft' if args.as_draft else 'publish'
            print(f"    post_id={post_id} {status} ({len(content)}字)")
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
