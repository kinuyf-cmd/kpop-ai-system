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
# 日次生産上限(2026-05-23 量産設計・オーナー決定 全自動publish + 1日10本上限)。
# 暴走防止の歯止め。品質は pre_publish_gate(HARD_FAIL)で担保。新ドメイン初期は質優先。
# env DAILY_BREAKING_LIMIT で上書き可(段階調整用)。
DAILY_BREAKING_LIMIT = int(os.environ.get('DAILY_BREAKING_LIMIT', '20'))


def _log_breaking_skip(reason, *, artist=None, typ=None, title=None, url=None):
    """速報がskipされた事実を恒久記録する。
    成功時(BREAKING_LOG)と同ファイルに status="skipped" で追記し、
    cron log のローテーションで skip 履歴が消えるのを防ぐ(skip率の可観測化)。
    """
    try:
        os.makedirs(os.path.dirname(BREAKING_LOG), exist_ok=True)
        with open(BREAKING_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'date': datetime.now().date().isoformat(),
                'ts': datetime.now().isoformat(),
                'status': 'skipped',
                'skip_reason': reason,
                'artist': artist,
                'type': typ,
                'title': title,
                'source_url': url,
            }, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f"  [breaking] skip記録失敗(非致命): {e}")


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
    """本日の速報「公開」本数。draft は上限を消費しない(ゲートで止まった
    記事が上限を食い潰し公開余力が失われるのを防ぐ)。status 欠落の旧ログ行は
    後方互換で publish 扱い(カウント対象)。"""
    if not os.path.exists(BREAKING_LOG):
        return 0
    today = datetime.now().date().isoformat()
    n = 0
    for l in open(BREAKING_LOG, encoding='utf-8'):
        if not l.strip():
            continue
        d = json.loads(l)
        if d.get('date') != today:
            continue
        if d.get('status', 'publish') == 'publish':
            n += 1
    return n


def _recent_breaking_titles(hours: int = 3) -> list:
    """直近 hours 内に publish した breaking 記事のタイトル一覧を返す (WP search lag 回避)"""
    if not os.path.exists(BREAKING_LOG):
        return []
    cutoff = datetime.now() - timedelta(hours=hours)
    titles = []
    try:
        with open(BREAKING_LOG, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                ts_str = d.get('ts', '')
                if not ts_str:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_str)
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                t = d.get('title', '')
                if t:
                    titles.append(t)
    except Exception:
        pass
    return titles


# アーティスト/メンバー名の表記揺れ正規化 (英字 ⇔ カタカナ)
# V-Jimin 3重投稿 root cause (Jimin と ジミン が同一人物として認識されなかった事故) 対策
_NAME_NORMALIZE = {
    'Jimin': 'ジミン', 'jimin': 'ジミン', 'JIMIN': 'ジミン',
    'Jungkook': 'ジョングク', 'JUNGKOOK': 'ジョングク',
    'Jin': 'ジン', 'JIN': 'ジン',
    'Suga': 'シュガ', 'SUGA': 'シュガ',
    'V': 'V', 'テテ': 'V',  # V は英字短いが固有名詞として通す
    'RM': 'RM',
    'J-Hope': 'ジェイホープ', 'JHope': 'ジェイホープ',
    'Taehyung': 'V', 'TAEHYUNG': 'V', 'テヒョン': 'V',
    'BTS': 'BTS', '防弾少年団': 'BTS',
    'BLACKPINK': 'BLACKPINK', 'ブラックピンク': 'BLACKPINK',
    'Lisa': 'リサ', 'LISA': 'リサ',
    'Jennie': 'ジェニ', 'JENNIE': 'ジェニ',
    'Rose': 'ロゼ', 'ROSE': 'ロゼ', 'Rosé': 'ロゼ',
    'Jisoo': 'ジス', 'JISOO': 'ジス',
    'NewJeans': 'NewJeans', 'ニュージーンズ': 'NewJeans',
    'IVE': 'IVE', 'アイブ': 'IVE',
    'Wonyoung': 'ウォニョン', 'WONYOUNG': 'ウォニョン',
    'Yujin': 'ユジン', 'YUJIN': 'ユジン',
    'aespa': 'aespa', 'エスパ': 'aespa', 'Aespa': 'aespa',
    'Karina': 'カリナ', 'KARINA': 'カリナ',
    'Winter': 'ウィンター', 'WINTER': 'ウィンター',
    'Ningning': 'ニンニン', 'NINGNING': 'ニンニン',
    'Giselle': 'ジゼル', 'GISELLE': 'ジゼル',
}


def _normalize_keywords(words: set) -> set:
    """表記揺れを統一して比較可能にする (Jimin → ジミン 等)"""
    out = set()
    for w in words:
        out.add(_NAME_NORMALIZE.get(w, w))
    return out


def _is_duplicate_of_recent(candidate_title: str, recent_titles: list) -> bool:
    """候補タイトルが直近 publish 済記事と重複するかチェック (cluster duplicate 防止)

    V-Jimin 3重投稿 事故 (2026-05-12) を踏まえて以下を強化:
      - アーティスト/メンバー名の表記揺れ正規化 (Jimin↔ジミン 等)
      - 漢字熟語の包含関係チェック (写真投稿 ⊃ 写真)
    """
    import re as _re
    _stop = {'ガイド', '完全', '最新', '徹底', '紹介', '解説', 'まとめ', '速報', '必見',
             '発表', '公開', '判明', '披露', '批判', '反発', '受ける', '招く',
             '無視', '扱い'}

    def _extract_kw(t: str) -> set:
        kw = set(_re.findall(r'[A-Za-z]{2,}|[ァ-ヶー]{3,}|[一-龥]{2,}', t))
        kw = _normalize_keywords(kw)
        return kw - _stop

    def _has_substring_kanji_match(s1: set, s2: set) -> int:
        """漢字熟語の包含チェック: s1 中の漢字語が s2 中のどれかに含まれる/含むなら 1 個カウント"""
        count = 0
        kanji_s1 = {w for w in s1 if _re.match(r'^[一-龥]+$', w)}
        kanji_s2 = {w for w in s2 if _re.match(r'^[一-龥]+$', w)}
        matched = set()
        for w1 in kanji_s1:
            for w2 in kanji_s2:
                if w1 == w2 or w1 in w2 or w2 in w1:
                    if w1 not in matched:
                        matched.add(w1)
                        count += 1
                    break
        return count

    new_kw = _extract_kw(candidate_title)
    if not new_kw:
        return False
    for rt in recent_titles:
        rt_kw = _extract_kw(rt)
        if not rt_kw:
            continue
        exact_overlap = new_kw & rt_kw
        # 固有名詞 (英字 / カタカナ) の exact 一致
        proper_overlap = {w for w in exact_overlap
                          if _re.match(r'[A-Za-z]|[ァ-ヶー]', w)}
        # 漢字熟語の包含一致を追加カウント
        kanji_overlap = _has_substring_kanji_match(new_kw, rt_kw)
        total_overlap = len(exact_overlap) + max(0, kanji_overlap - len(exact_overlap & {w for w in exact_overlap if _re.match(r'^[一-龥]+$', w)}))

        # 固有名詞2個以上、または全体3個以上で同テーマ判定
        if len(proper_overlap) >= 2:
            return True
        # 固有名詞1個 + 漢字包含1個 でも同テーマ濃厚
        if len(proper_overlap) >= 1 and kanji_overlap >= 1:
            return True
        if len(exact_overlap) >= 3:
            return True
    return False


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


def _wp_basic_auth() -> str:
    """WP REST 用 Basic 認証を .env (WP_USER + WP_APP_PASS|WP_PASS) から組む。
    unified_publisher と同じ有効な kpop-publisher 資格情報を使う。
    旧実装は存在しない kpop-bot の平文 app password をハードコードしており
    必ず 401 になっていた (kpop-bot はこの WP install に不在)。"""
    user = os.environ.get('WP_USER', '')
    pw = os.environ.get('WP_APP_PASS') or os.environ.get('WP_PASS', '')
    if not (user and pw):
        # cron で .env 未ロードのケースに備え明示的に読む
        try:
            _env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
            with open(_env_path, encoding='utf-8') as _f:
                for _line in _f:
                    _line = _line.strip()
                    if not _line or _line.startswith('#') or '=' not in _line:
                        continue
                    _k, _, _v = _line.partition('=')
                    _k = _k.strip(); _v = _v.strip()
                    if _k == 'WP_USER' and not user:
                        user = _v
                    elif _k == 'WP_APP_PASS' and not pw:
                        pw = _v
                    elif _k == 'WP_PASS' and not pw:
                        pw = _v
        except Exception:
            pass
    if not (user and pw):
        return ''
    return base64.b64encode(f"{user}:{pw}".encode()).decode()


def _mark_breaking_stage(post_id, stage):
    """WP custom field _breaking_stage を記録 (1=速報、2=加筆済、3=完全版)"""
    _AUTH = _wp_basic_auth()
    if not _AUTH:
        print(f"  stage記録skip {post_id}: WP認証(.env WP_USER/WP_PASS)未設定")
        return
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


# 2026-05-12: Tavily quota exhausted 後の連続失敗ログを抑制するための process-local flag
_TAVILY_QUOTA_EXHAUSTED = False


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
    # 2026-05-12: 同一 process 内で quota exhausted エラーが一度出たら以後 skip。
    # 毎回 Tavily API を叩いてエラーで落ちる無駄を防ぐ (cron 起動ごとには再試行)。
    global _TAVILY_QUOTA_EXHAUSTED
    if not _TAVILY_QUOTA_EXHAUSTED:
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
            _msg = str(_te).lower()
            if 'usage limit' in _msg or 'plan' in _msg or 'quota' in _msg or '429' in _msg:
                _TAVILY_QUOTA_EXHAUSTED = True
                print(f"  [web_search] Tavily quota exhausted → DuckDuckGo に固定 fallback")
            else:
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
- セクション見出しは必ず <h2>見出し文</h2> の HTML タグで出力。「h2: 見出し文」のような plain text プレフィックスは絶対に使わない
- h2セクション2-3個（ソースの段落構成に従う）
- ソースに引用コメントがあれば日本語訳して含める
- 末尾に「今後の注目ポイント」3つを箇条書き

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
            _log_breaking_skip(f"body_translate_fail: {body_r.get('reason','')[:120]}",
                               artist=artist, typ=typ, title=best.get('title'), url=best.get('url'))
            return None
        body_html = _wrap_body(body_r['translated'], best['title'], True)
    elif best.get('language') == 'ja':
        raw_title = best['title'].strip().strip('【】')
        body_r = translate_ko_to_ja(prompt_text, 'K-POP速報記事の要約。ソースにない情報は絶対に追加しない')
        if not body_r.get('success'):
            print(f"  [breaking] body翻訳失敗でskip: {body_r.get('reason','')[:80]}")
            _log_breaking_skip(f"body_translate_fail: {body_r.get('reason','')[:120]}",
                               artist=artist, typ=typ, title=best.get('title'), url=best.get('url'))
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
            _log_breaking_skip(f"body_translate_fail: {body_r.get('reason','')[:120]}",
                               artist=artist, typ=typ, title=best.get('title'), url=best.get('url'))
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
                'status': r.get('status', 'publish'),
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

    # 直近 3h の publish 履歴と同テーマの候補を pre-filter
    # (cluster duplicate 防止: V-Jimin 4重投稿 root cause 対策、2026-05-12)
    # 2026-05-14: lib.cluster_dedup の共通 sliding-window buffer も併用し、
    # 他 publisher (simple_publish/cluster_generator) との横断 dedup を実現
    recent_titles = _recent_breaking_titles(hours=3)
    try:
        from lib.cluster_dedup import _read_recent_buffer as _shared_buf
        recent_titles = recent_titles + _shared_buf(hours=3)
    except Exception:
        pass

    published = 0
    just_published_titles = []  # この回 cron 内での publish ガード
    import time as _time
    for artist, sigs, typ in candidates[:DAILY_BREAKING_LIMIT - count_today]:
        best = max(sigs, key=lambda s: len(s.get('title', '')))
        print(f"\n=== {artist} ({typ}): {best['title'][:60]} ===")
        # 直近 publish 履歴 + 今回 cron 内 publish 済とのテーマ重複チェック
        cand_title = best.get('title', '')
        all_recent = recent_titles + just_published_titles
        if _is_duplicate_of_recent(cand_title, all_recent):
            print(f"  [dedup] 直近3h publish 済 cluster と重複 → skip")
            continue
        if dry_run:
            continue
        r = publish_breaking(artist, sigs, typ)
        if r:
            print(f"  速報公開 ID={r.get('id')}")
            published += 1
            just_published_titles.append(r.get('title', cand_title))
            # 共通 sliding-window buffer にも記録 (他 publisher との横断 dedup 用)
            # 2026-05-14: source_url + body も渡し、後段の Korean fragment/URL match を可能に
            try:
                from lib.cluster_dedup import record_publish
                _src_url = ''
                if sigs and isinstance(sigs, list):
                    _src_url = sigs[0].get('url', '') if isinstance(sigs[0], dict) else ''
                record_publish(r.get('title', cand_title),
                               post_id=r.get('id'),
                               source='breaking_news_detector',
                               source_url=_src_url,
                               body=r.get('body_plain') or '')
            except Exception:
                pass
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
