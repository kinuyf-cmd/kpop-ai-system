#!/usr/bin/env python3
"""速報検出→即時記事化

条件:
- urgency='high' のsignalが過去5分以内に発生
- または同一アーティストで過去5分以内に2ソース以上
- 1日最大10件
"""
import sys, os, json, urllib.request, base64
from datetime import datetime, timedelta

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

from lib.korean_translator import translate_ko_to_ja
from lib.unified_publisher import unified_publish
from lib.signal_deduplicator import deduplicate
from pipeline.auto_event_article import is_processed, mark_processed

SIGNALS_PATH = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'
BREAKING_LOG = '/home/aiuser/kpop-ai-system/logs/breaking_articles.jsonl'
DAILY_BREAKING_LIMIT = 100  # 上限実質なし (品質はpre_publish_gate+post_publish_hookで担保)


# 速報ソースとして不適切なソースタイプ（トレンド検知には使うが記事化しない）
_EXCLUDE_SOURCES = {'youtube', 'tiktok', 'gtrends'}

def load_recent(minutes=5):
    if not os.path.exists(SIGNALS_PATH):
        return []
    cutoff = datetime.now() - timedelta(minutes=minutes)
    result = []
    with open(SIGNALS_PATH, encoding='utf-8') as f:
        for line in f:
            try:
                sig = json.loads(line)
                # YouTube等のソースは速報候補から除外
                if sig.get('source', '') in _EXCLUDE_SOURCES:
                    continue
                ts = datetime.fromisoformat(sig.get('timestamp', '')[:19])
                if ts >= cutoff:
                    result.append(sig)
            except Exception:
                pass
    return result


def today_breaking_count():
    if not os.path.exists(BREAKING_LOG):
        return 0
    today = datetime.now().date().isoformat()
    return sum(1 for l in open(BREAKING_LOG, encoding='utf-8')
               if l.strip() and json.loads(l).get('date') == today)


def _is_stale_source(sig) -> bool:
    """ソースURLに含まれる日付が7日以上前ならTrue（古いニュースの速報化を防止）"""
    url = sig.get('url', '')
    import re as _re
    # URLに日付パターンが含まれるか (例: /20260414/, /2026/04/14/, /2026-04-14)
    m = _re.search(r'(\d{4})[-/]?(\d{2})[-/]?(\d{2})', url)
    if m:
        try:
            from datetime import datetime, timedelta
            article_date = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if article_date < datetime.now() - timedelta(days=7):
                return True
        except (ValueError, TypeError):
            pass
    return False


def _pick_artist(arts):
    """arts[0]が GENERIC_EVENT_KW (컴백/발매/데뷔等) や AGENCY_ONLY (SM/YG等) の場合は
    artist として採用しない。固有アーティスト名のみを返す。
    2026-05-07: queueに데뷔/발매/SM が"artist"として混入していた問題への対処。
    """
    from lib.collectors.korean_base import GENERIC_EVENT_KW, AGENCY_ONLY_KW
    for a in arts or []:
        if a not in GENERIC_EVENT_KW and a not in AGENCY_ONLY_KW:
            return a
    return None


def detect_breaking(signals):
    from lib.collectors.korean_base import is_kpop_related
    candidates = []
    seen = set()

    # 1. urgency=high (音楽番組1位等)
    for s in signals:
        if s.get('urgency') != 'high':
            continue
        arts = is_kpop_related(s.get('title', ''))
        artist = _pick_artist(arts)
        if not artist or artist in seen:
            continue
        if is_processed(s['url']) or _is_stale_source(s):
            continue
        seen.add(artist)
        candidates.append((artist, [s], 'urgent'))

    # 2. 同一アーティスト+複数ソース
    by_artist = {}
    for s in signals:
        arts = is_kpop_related(s.get('title', ''))
        artist = _pick_artist(arts)
        if not artist:
            continue
        by_artist.setdefault(artist, []).append(s)

    for artist, sigs in by_artist.items():
        if artist in seen:
            continue
        sources = set(s.get('source_id', '') for s in sigs)
        # 古いソースを除外
        fresh_sigs = [s for s in sigs if not _is_stale_source(s)]
        if not fresh_sigs:
            continue
        sources = set(s.get('source_id', '') for s in fresh_sigs)
        if len(sources) >= 2 and not any(is_processed(s['url']) for s in fresh_sigs):
            seen.add(artist)
            candidates.append((artist, fresh_sigs, 'multi'))
        elif len(fresh_sigs) >= 2 and not any(is_processed(s['url']) for s in fresh_sigs):
            seen.add(artist)
            candidates.append((artist, sigs, 'single_multi'))

    # 3. 高engagement単独シグナル (2026-05-01追加)
    # engagement_score >= 2.0 かつ未処理のK-POP関連シグナルを速報候補に
    # 2026-05-10: 高活動artist (BABYMONSTER等) が17シグナル/日でも1件しか拾えない問題の対処
    # 同一artist 最大2件まで許容 (異なるangleの場合)
    MAX_PER_ARTIST = 2
    high_eng = sorted(
        [s for s in signals if s.get('engagement_score', 0) >= 2.0],
        key=lambda x: -x.get('engagement_score', 0)
    )
    artist_count = {}  # artist → 既選candidate数
    artist_titles = {}  # artist → 既選titles (重複検出用)
    for s in high_eng:
        arts = is_kpop_related(s.get('title', ''))
        artist = _pick_artist(arts)
        if not artist:
            continue
        if is_processed(s.get('url', '')):
            continue
        # 同一artistでもcountが上限未達なら通す
        cnt = artist_count.get(artist, 0)
        if artist in seen and cnt == 0:
            continue  # 既にmulti/urgentで選ばれてればhigh_engagementで重複させない
        if cnt >= MAX_PER_ARTIST:
            continue
        # 既選titleと類似 (共通名詞50%以上) なら却下
        title = s.get('title', '')
        if any(_titles_too_similar(title, t) for t in artist_titles.get(artist, [])):
            continue
        artist_count[artist] = cnt + 1
        artist_titles.setdefault(artist, []).append(title)
        seen.add(artist)
        candidates.append((artist, [s], 'high_engagement'))

    return candidates


def _titles_too_similar(t1: str, t2: str) -> bool:
    """2タイトルが意味的に類似してるか (共通4文字以上単語が3個以上)"""
    import re as _re
    # 4字以上のハングル/カタカナ/英単語を抽出
    words1 = set(_re.findall(r'[가-힯]{2,}|[ァ-ヶー]{3,}|[A-Za-z]{4,}', t1))
    words2 = set(_re.findall(r'[가-힯]{2,}|[ァ-ヶー]{3,}|[A-Za-z]{4,}', t2))
    if not words1 or not words2:
        return False
    common = words1 & words2
    return len(common) >= 3


def _inject_followup_theme(artist, ja_title, en_title):
    """速報記事のフォローアップテーマをauto_directivesに注入
    24-72h後にfeature_article_generatorが深掘り記事を自動生成する"""
    directives_path = os.path.join('/home/aiuser/kpop-ai-system', 'config/auto_directives.json')
    try:
        with open(directives_path, encoding='utf-8') as f:
            directives = json.load(f)

        now = datetime.now()
        followup = {
            'topic': f"{artist}速報の深掘り: {ja_title[:30]}",
            'hint': (
                f"速報「{ja_title}」の背景分析・ファン反応・今後の影響を深掘りする記事。"
                f"元ニュース: {en_title[:80]}。"
                f"関連: {artist}。バズ予測スコア: 12.0。シグナル: breaking_followup"
            ),
            'category_suggest': '深掘り',
            'added_at': now.strftime('%Y-%m-%d'),
            'source': 'breaking_followup',
            'buzz_score': 12.0,
            'expires_at': (now + timedelta(days=3)).strftime('%Y-%m-%d'),
        }
        focus = directives.get('focus_themes', [])
        # 同じアーティストの古いfollowupを除去
        focus = [t for t in focus if not (t.get('source') == 'breaking_followup' and artist in t.get('topic', ''))]
        focus.append(followup)
        directives['focus_themes'] = focus
        with open(directives_path, 'w', encoding='utf-8') as f:
            json.dump(directives, f, ensure_ascii=False, indent=2)
        print(f"  フォローアップテーマ注入: {followup['topic'][:40]}")
    except Exception as e:
        print(f"  followup inject err: {e}")


def _mark_breaking_stage(post_id, stage):
    """WP custom field _breaking_stage を記録 (1=速報、2=加筆済、3=完全版)"""
    _AUTH = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()
    try:
        url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}"
        body = json.dumps({'meta': {'_breaking_stage': str(stage)}}).encode()
        req = urllib.request.Request(url, data=body, method='POST',
            headers={'Authorization': f'Basic {_AUTH}', 'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=20).read()
        print(f"  [breaking_stage={stage}] post_id={post_id}")
    except Exception as e:
        print(f"  stage記録失敗 {post_id}: {e}")


def _wrap_body(translated: str, fallback_title: str, success: bool) -> str:
    """GPT出力をbody_htmlにラップ。既にHTMLブロック要素を含む場合は二重<p>を避ける"""
    import re as _re
    if not success or not translated:
        return f"<p>{fallback_title}</p>"
    text = translated.strip()
    # GPT出力が既に<p>や<h2>等のブロック要素を含む場合はそのまま返す
    if _re.search(r'<(?:p|h[2-6]|div|ul|ol|table)[ >]', text):
        return text
    return f"<p>{text}</p>"


def _enrich_with_web_search(title, sigs):
    """速報記事生成前にWeb検索で事実を収集（捏造防止の根本対策）

    Tavily → DuckDuckGo のフォールバック。
    タイトルキーワードとの関連度フィルタ付き。
    """
    import re as _re
    # タイトルからキーワード抽出（関連度フィルタ用）
    _title_kw = set(_re.findall(r'[A-Za-z]{2,}|[ァ-ヶー]{3,}|[一-龥]{2,}', title.lower()))
    _title_kw -= {'the', 'and', 'for', 'with', 'new', 'ガイド', '完全', '最新', '速報'}

    def _is_relevant(result_title, result_content):
        """検索結果がタイトルのキーワードと関連するか"""
        combined = (result_title + ' ' + result_content).lower()
        hits = sum(1 for kw in _title_kw if kw in combined)
        return hits >= 1  # キーワード1つ以上一致

    parts = []

    # 1. Tavily (優先)
    try:
        tavily_key = os.environ.get('TAVILY_API_KEY', '')
        if tavily_key:
            from tavily import TavilyClient
            client = TavilyClient(api_key=tavily_key)
            query = f'{title} K-POP 2026'
            response = client.search(query, max_results=5, search_depth='basic',
                                     exclude_domains=['kpopjournal.tokyo'])
            for r in response.get('results', [])[:4]:
                content = r.get('content', '')[:400]
                r_title = r.get('title', '')
                if content and _is_relevant(r_title, content):
                    parts.append(f'【{r_title}】{content}')
            if parts:
                return '\n'.join(parts)
    except Exception as _te:
        print(f"  [web_search] Tavily失敗: {_te}")

    # 2. DuckDuckGo フォールバック
    if not parts:
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                # 英語タイトルは日本語キーワードを追加して検索精度向上
                _query_base = _re.sub(r'[！!？?\s]+', ' ', title)[:40]
                _has_ja = bool(_re.search(r'[\u3040-\u9fff]', _query_base))
                query = _query_base if _has_ja else f'{_query_base} K-POP 最新'
                results = list(ddgs.text(query, max_results=5))
                # 結果0件なら日本語翻訳キーワードで再試行
                if not results and not _has_ja:
                    # アーティスト名+主要キーワードで日本語検索
                    _en_words = _re.findall(r'[A-Z][a-zA-Z]+', title)
                    if _en_words:
                        query = ' '.join(_en_words[:3]) + ' 最新 速報'
                        results = list(ddgs.text(query, max_results=5))
            for r in results[:4]:
                body = r.get('body', '')[:400]
                r_title = r.get('title', '')
                if body and _is_relevant(r_title, body):
                    parts.append(f'【{r_title}】{body}')
            if parts:
                print(f"  [web_search] DuckDuckGo OK: {len(parts)}件")
        except Exception as _de:
            print(f"  [web_search] DuckDuckGo失敗: {_de}")

    return '\n'.join(parts)


def _get_artist_profile_context(artist, sigs=None):
    """アーティスト基本情報をプロンプトに注入（メンバー人数/デビュー年の捏造防止）

    sigisに含まれる全アーティスト名も検索して複数プロファイルを返す。
    """
    try:
        import json as _json
        with open('/home/aiuser/kpop-ai-system/config/artist_profiles.json', 'r', encoding='utf-8') as f:
            profiles = _json.load(f).get('profiles', {})

        # 検索対象: メインartist + sigs内の全タイトルから抽出
        search_names = {(artist or '').lower()}
        if sigs:
            for sig in sigs[:5]:
                title = sig.get('title', '')
                for key, prof in profiles.items():
                    names = [prof.get('display_name', ''), prof.get('name_en', ''), key]
                    if any(n and n.lower() in title.lower() for n in names):
                        search_names.add(key.lower())

        # 2026-05-11改定: is_solo考慮 + members=[] スキップ (0人組 注入で hallucination 誘発する事故対策)
        matched = []
        for key, prof in profiles.items():
            names = [prof.get('display_name', ''), prof.get('name_en', ''), key]
            if not any(n and n.lower() in search_names for n in names):
                continue
            members = prof.get('members', [])
            is_solo = prof.get('is_solo', False)
            display = prof['display_name']
            debut = prof.get('debut_year', '?')
            agency = prof.get('agency', '?')
            if is_solo:
                matched.append(f"- {display}: ソロアーティスト, {debut}年デビュー, 所属: {agency}")
            elif members:
                matched.append(
                    f"- {display}: {len(members)}人組, {debut}年デビュー, "
                    f"所属: {agency}, メンバー: {', '.join(members)}")
            # members=[] かつ is_solo=False は profile データ不完全 → 注入しない

        if matched:
            return ("\n【アーティスト正式情報（これと矛盾する内容を絶対に書かないこと）】\n"
                    + "\n".join(matched))
    except Exception:
        pass
    return ''


# 速報記事プロンプト: 「書く」のではなく「ソースを翻訳・要約する」
_BREAKING_PROMPT_TEMPLATE = """あなたはK-POP専門メディアの翻訳・編集者です。
以下のソース記事を日本語に翻訳・要約して、1500-2500字のHTML記事を作成してください。
今日は{today}です。本文中に現在の年月({year_month})を含めること。

【ソース記事ヘッドライン】
{combined}

{web_context_section}
{profile_context}

【あなたの仕事: 翻訳・要約（創作ではない）】
- ソース記事に書かれている事実をそのまま日本語に翻訳すること
- ソースに書かれている人名・日付・数字・引用は一字一句正確に訳すこと
- ソースに書かれていないことは絶対に追加しない
- 「背景情報」「過去の経緯」もソースに言及がある場合のみ書く
- 字数が足りなくても、ソースにない情報で埋めることは禁止

【記事構造（HTML）】
- 冒頭1文: 何が起きたかを結論として書く
- h2セクション2-3個（ソースの段落構成に従う）
- ソースに引用コメントがあれば日本語訳して含める
- 末尾に「今後の注目ポイント」3つを箇条書き
- 末尾に「※ 本記事は[ソース名]の報道を翻訳・編集したものです」と明記

【禁止事項 — 違反=即削除】
- ソースにない事実の追加（メンバー人数・デビュー年・楽曲名を自分の知識で補わない）
- 人名の匿名化（「A」「B」等にしない。ソースの実名をそのまま使う）
- SNSの反応の捏造（ソースに引用がなければ「SNSでも話題になっている」程度に留める）
- 同じ文やフレーズの繰り返し
- 「Run BTS」のようなバラエティ番組を「新曲」と誤記

5W1H(誰が・いつ・何を・どこで・なぜ)を明確に。ソースに書いていないことは書かない。"""


def publish_breaking(artist, sigs, typ):
    """unified_publish経由で速報投稿（ソース本文取得→Web検索→生成→公開）"""
    best = max(sigs, key=lambda s: len(s.get('title', '')))

    # Step 0: ソースURLから本文を直接取得（最も重要な事実の根拠）
    from lib.source_reader import read_sources
    source_text = read_sources(sigs)

    # Step 1: Web検索で補完事実を収集
    web_facts = _enrich_with_web_search(best['title'], sigs)

    web_context_section = ''
    if source_text:
        web_context_section = f"""【ソース記事の本文（この記事の事実の根拠。ここに書かれている固有名詞・人名・経緯を必ず記事に含めること）】
{source_text[:1500]}"""
        if web_facts:
            web_context_section += f"""

【Web検索で取得した補足情報】
{web_facts}"""
    elif web_facts:
        web_context_section = f"""【Web検索で取得した事実情報（この情報を優先的に使うこと）】
{web_facts}"""
    else:
        web_context_section = '【注意】Web検索で追加情報が見つかりませんでした。ヘッドラインの内容のみで簡潔に書くこと。背景情報の推測は禁止。'

    # アーティスト基本情報
    profile_context = _get_artist_profile_context(artist, sigs=sigs)

    today = datetime.now().strftime('%Y年%m月%d日')
    year_month = datetime.now().strftime('%Y年%m月')
    combined = "\n".join([s['title'] for s in sigs[:3]])

    prompt_text = _BREAKING_PROMPT_TEMPLATE.format(
        today=today, year_month=year_month, combined=combined,
        web_context_section=web_context_section, profile_context=profile_context,
    )

    # タイトル翻訳: ソースのヘッドラインを忠実に翻訳するだけ。煽り・意訳・要約禁止。
    _title_context = (
        'ニュース見出しの忠実翻訳。意味を変えない。煽らない。要約しない。'
        '元の見出しが言っていることだけを日本語にする。'
        '「出席禁止」「衝撃」等ソースにない語句を追加しない。'
    )
    # ユーザー指示 (2026-05-07): タイトル先頭の【速報】prefix は付けない
    if best.get('language') == 'ko':
        title_r = translate_ko_to_ja(best['title'], _title_context)
        if not title_r.get('success'):
            return None
        raw_title = title_r['translated'].strip().strip('「」""【】')
        body_r = translate_ko_to_ja(prompt_text, 'K-POP速報記事の翻訳・要約。ソースにない情報は絶対に追加しない')
        # 2026-05-12: body fail 時に元韓国タイトルでfallbackすると hangul が本文に残るため skip
        if not body_r.get('success'):
            print(f"  [breaking] body翻訳失敗でskip: {body_r.get('reason','')[:80]}")
            return None
        body_html = _wrap_body(body_r['translated'], best['title'], True)
    elif best.get('language') == 'ja':
        raw_title = best['title'].strip().strip('【】')
        body_r = translate_ko_to_ja(prompt_text, 'K-POP速報記事の要約。ソースにない情報は絶対に追加しない')
        if not body_r.get('success'):
            print(f"  [breaking] body翻訳失敗でskip: {body_r.get('reason','')[:80]}")
            return None
        body_html = _wrap_body(body_r['translated'], best['title'], True)
    else:
        # 英語ソース
        title_r = translate_ko_to_ja(best['title'], _title_context)
        if title_r.get('success'):
            raw_title = title_r['translated'].strip().strip('「」""【】')
        else:
            raw_title = best['title']
        body_r = translate_ko_to_ja(prompt_text, 'K-POP速報記事の翻訳・要約。ソースにない情報は絶対に追加しない')
        if not body_r.get('success'):
            print(f"  [breaking] body翻訳失敗でskip: {body_r.get('reason','')[:80]}")
            return None
        body_html = _wrap_body(body_r['translated'], best['title'], True)

    confidence = 'high' if typ == 'multi' else ('medium' if typ in ('urgent', 'single_multi') else 'low')

    r = unified_publish(
        raw_title=raw_title,
        body_html=body_html,
        source_url=best.get('url'),
        artist=artist,
        kind='breaking',
        confidence=confidence,
        source_signals=sigs,
        is_breaking=True,
    )

    if r and r.get('success'):
        _mark_breaking_stage(r.get('post_id'), 1)
        for s in sigs:
            mark_processed({
                'ts': datetime.now().isoformat(), 'source_url': s['url'],
                'wp_post_id': r.get('post_id'), 'kind': 'breaking',
                'confidence': confidence, 'type': typ,
            })
        os.makedirs(os.path.dirname(BREAKING_LOG), exist_ok=True)
        with open(BREAKING_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'date': datetime.now().date().isoformat(),
                'ts': datetime.now().isoformat(),
                'post_id': r.get('post_id'),
                'title': r.get('title'),
                'artist': artist,
                'type': typ,
            }) + '\n')

        # 速報→深掘り連鎖: auto_directivesにフォローアップテーマを注入
        _inject_followup_theme(artist, r.get('title', ''), best.get('title', ''))

        # 統一ポストパブリッシュフック (enricher+audit+factcheck+カテゴリ修正)
        try:
            from lib.post_publish_hook import run_post_publish
            run_post_publish(r['post_id'])
        except Exception as e:
            print(f"  post_publish_hook err: {e}")
        return {'id': r.get('post_id'), 'link': r.get('post_url')}

    # fact-checkブロック等でも同じURLの無限リトライを防止
    if r and not r.get('success'):
        for s in sigs:
            mark_processed({
                'ts': datetime.now().isoformat(), 'source_url': s['url'],
                'kind': 'breaking_blocked',
                'reason': r.get('error', 'unknown'),
                'type': typ,
            })
    return None


def main(dry_run=False):
    count_today = today_breaking_count()
    print(f"本日の速報記事: {count_today}/{DAILY_BREAKING_LIMIT}")
    if count_today >= DAILY_BREAKING_LIMIT:
        print("本日の速報上限到達")
        return 0

    signals_raw = load_recent(minutes=180)  # 3時間ウィンドウ (RSSバッチ取得に合わせる)
    signals, _dup_n, _ = deduplicate(signals_raw)
    print(f"過去5分のsignals: {len(signals_raw)}件 (dedup: -{_dup_n})")

    candidates = detect_breaking(signals)
    print(f"速報候補: {len(candidates)}件")

    published = 0
    import time as _time
    for artist, sigs, typ in candidates[:DAILY_BREAKING_LIMIT - count_today]:
        best = max(sigs, key=lambda s: len(s.get('title', '')))
        print(f"\n=== {artist} ({typ}): {best['title'][:60]} ===")
        if dry_run:
            continue
        r = publish_breaking(artist, sigs, typ)
        if r:
            print(f"  速報公開 ID={r.get('id')}")
            published += 1
            # バースト防止: 記事間に30秒待機（X投稿がスケジューラーキューに入るため短縮可能）
            _time.sleep(30)

    print(f"\n速報記事化: {published}件")
    return published


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    main(dry_run=args.dry_run)
