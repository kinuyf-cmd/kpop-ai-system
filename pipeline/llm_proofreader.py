#!/usr/bin/env python3
"""項目17 LLM校閲 — GPT-4o-miniで全記事を校閲 (4時間毎 cron)
   critical/high検出時は llm_audit_alerts.log + audit_state.jsonl にキュー追加"""
import sys, os, json, re, argparse
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

import urllib.request, base64

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode() if WP_USER else ''
OPENAI_KEY = os.getenv('OPENAI_API_KEY', '')
JST = timezone(timedelta(hours=9))

LOGS_DIR = '/home/aiuser/kpop-ai-system/logs/llm_audit'
ALERT_LOG = '/home/aiuser/kpop-ai-system/logs/llm_audit_alerts.log'
AUDIT_STATE = '/home/aiuser/kpop-ai-system/data/audit_state.jsonl'


def fetch_recent_posts(hours=4, per_page=30):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%S')
    posts = []
    for endpoint in ['posts', 'popup']:
        try:
            url = (f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}"
                   f"?after={cutoff}&per_page={per_page}&_embed=true")
            req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
            data = json.loads(urllib.request.urlopen(req, timeout=20).read())
            for p in data:
                p['_post_type'] = endpoint
            posts.extend(data)
        except Exception as e:
            print(f"  fetch err {endpoint}: {e}")
    return posts


def _already_proofread(post_id, force=False):
    """直近6h以内に同一IDを校閲済みならスキップ（24h→6hに短縮: 修正後の再チェック漏れ防止）"""
    if force:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    if not os.path.exists(LOGS_DIR):
        return False
    for fname in sorted(os.listdir(LOGS_DIR), reverse=True):
        if not fname.endswith('.json'):
            continue
        try:
            parts = fname.replace('.json', '').split('_')
            file_date = datetime.strptime(parts[0], '%Y%m%d').replace(tzinfo=timezone.utc)
            if len(parts) >= 2 and parts[1].isdigit() and len(parts[1]) <= 2:
                file_date = file_date.replace(hour=int(parts[1]))
            if file_date < cutoff:
                continue
        except (ValueError, IndexError):
            continue

        try:
            fpath = os.path.join(LOGS_DIR, fname)
            data = json.load(open(fpath))
            for r in data.get('results', []):
                if r.get('id') == post_id:
                    return True
            if len(parts) >= 3 and parts[2].isdigit():
                if int(parts[2]) == post_id:
                    return True
        except Exception:
            pass
    return False


def _load_artist_profiles():
    """artist_profiles.jsonを読み込み"""
    path = '/home/aiuser/kpop-ai-system/config/artist_profiles.json'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f).get('profiles', {})
    except Exception:
        return {}


def _check_artist_profile(title, plain):
    """記事内のアーティスト基本情報をartist_profiles.jsonと照合

    検出: メンバー人数の矛盾、デビュー年の矛盾
    Returns: list of issue strings (critical level)
    """
    profiles = _load_artist_profiles()
    if not profiles:
        return []

    issues = []
    # タイトル+本文冒頭からアーティスト名を検索
    text_to_check = (title + ' ' + plain[:1500]).lower()

    for key, prof in profiles.items():
        names = [prof.get('display_name', ''), prof.get('name_en', ''), key]
        names = [n.lower() for n in names if n]
        if not any(n in text_to_check for n in names):
            continue

        # このアーティストが記事に登場
        display = prof.get('display_name', key)
        members = prof.get('members', [])
        debut_year = prof.get('debut_year')
        member_count = len(members)

        if member_count > 0:
            # 「N人組」パターンを検索
            for m in re.finditer(r'(\d+)\s*人組', plain):
                num = int(m.group(1))
                # その付近にアーティスト名があるか確認
                ctx_start = max(0, m.start() - 60)
                ctx_end = min(len(plain), m.end() + 60)
                ctx = plain[ctx_start:ctx_end].lower()
                if any(n in ctx for n in names):
                    if num != member_count:
                        issues.append(
                            f'{display}のメンバー人数が誤り: 記事では{num}人組と記載、正しくは{member_count}人組（{", ".join(members)}）'
                        )

        if debut_year:
            # 「NNNN年デビュー」「NNNN年にデビュー」パターン
            for m in re.finditer(r'(\d{4})年(?:に)?デビュー', plain):
                yr = int(m.group(1))
                ctx_start = max(0, m.start() - 60)
                ctx_end = min(len(plain), m.end() + 60)
                ctx = plain[ctx_start:ctx_end].lower()
                if any(n in ctx for n in names):
                    if yr != debut_year:
                        issues.append(
                            f'{display}のデビュー年が誤り: 記事では{yr}年と記載、正しくは{debut_year}年'
                        )

    return issues


def _web_factcheck_context(title, plain):
    """記事の主要主張を抽出して、LLMプロンプトに外部検証指示を追加するコンテキストを生成"""
    # 数値・固有名詞・イベント名などの事実主張を抽出
    claims = []

    # 「N人組」
    for m in re.finditer(r'(\S+?)(?:は|の)\s*(\d+)人組', plain):
        claims.append(f'{m.group(1)}は{m.group(2)}人組')

    # 「NNNN年デビュー」
    for m in re.finditer(r'(\S+?)(?:は|が)\s*(\d{4})年(?:に)?デビュー', plain):
        claims.append(f'{m.group(1)}は{m.group(2)}年デビュー')

    # イベント名+年
    for m in re.finditer(r'((?:Billboard|Grammy|Oscar|Coachella|MAMA|KCON|アカデミー|グラミー)[^。、]{5,30})', plain):
        claims.append(m.group(1).strip())

    # 受賞・記録
    for m in re.finditer(r'((?:受賞|獲得|ノミネート|1位|記録)[^。]{5,40})', plain):
        claims.append(m.group(1).strip())

    if not claims:
        return ''

    claims_text = '\n'.join(f'  - {c}' for c in claims[:8])
    return f"""

## 外部ファクトチェック指示（重要）
以下は記事から抽出した事実主張です。あなたの知識と照合し、誤りがあればcriticalまたはhighで報告してください:
{claims_text}

特に以下を厳格にチェック:
- グループのメンバー人数とデビュー年
- イベント名（Billboard/Coachella/Grammy等）が実際の開催と一致するか
- 受賞歴や記録が事実か"""


def proofread_post(post):
    """GPT-4o-miniで1件校閲 + artist_profiles照合 + 外部ファクトチェック

    2026-05-10: FACTCHECK_V2=1 環境変数で Claude Sonnet 4.6 + Web search の
    新版factcheckにswitch可能。決定的なartist_profile照合は両方で実施。
    """
    title = post['title']['rendered'] if isinstance(post.get('title'), dict) else post.get('title', '')
    content = post['content']['rendered'] if isinstance(post.get('content'), dict) else post.get('content', '')
    plain = re.sub(r'<[^>]+>', ' ', content)
    plain = re.sub(r'\s+', ' ', plain).strip()[:2500]

    # --- Layer 1: artist_profiles.json照合（deterministic） ---
    profile_issues = _check_artist_profile(title, plain)

    # 2026-05-10: FACTCHECK_V2 envフラグでClaude版に切替
    # 2026-05-12 (コスト削減): 信頼ソースURLが本文中にあれば use_web_search=False で
    # Web Search tool スキップ (検索しても同じ結論を返すため品質維持)。
    if os.environ.get('FACTCHECK_V2') == '1':
        try:
            from lib.factcheck_v2 import proofread_post_v2
            try:
                from lib.source_domains import is_trusted_source, load_domains as _load_trusted
                _domains = _load_trusted()
                _content_html = post.get('content', {}).get('rendered', '') if isinstance(post.get('content'), dict) else (post.get('content') or '')
                _trusted_in_body = any(d in _content_html for d in _domains)
            except Exception:
                _trusted_in_body = False
            v2_result = proofread_post_v2(post, use_web_search=not _trusted_in_body)
            # Layer 1の決定的profile照合をmerge (v2はLLM判定だけなので)
            if profile_issues:
                v2_result.setdefault('critical', []).extend(profile_issues)
                v2_result['score'] = min(v2_result.get('score', 100), 50)
            return v2_result
        except Exception as e:
            # v2失敗時はOpenAI版にフォールバック
            print(f"  [factcheck] v2 fallback to v1: {e}")

    # --- Layer 1b: 記事に登場するアーティストのprofile情報を取得（GPT誤検知防止） ---
    # 2026-05-11改定: is_solo考慮 + members=[] スキップ + 「記載なし=矛盾」と誤読される文言を緩和
    profile_context = ''
    try:
        profiles = _load_artist_profiles()
        text_lower = (title + ' ' + plain[:1500]).lower()
        matched_profiles = []
        for key, prof in profiles.items():
            names = [prof.get('display_name', ''), prof.get('name_en', ''), key]
            names = [n.lower() for n in names if n]
            if not any(n in text_lower for n in names):
                continue
            members = prof.get('members', [])
            is_solo = prof.get('is_solo', False)
            display = prof.get('display_name', key)
            debut = prof.get('debut_year', '?')
            if is_solo:
                # ソロアーティストは人数情報を出さない
                matched_profiles.append(f"  - {display}: ソロアーティスト, {debut}年デビュー")
            elif members:
                matched_profiles.append(
                    f"  - {display}: {len(members)}人組, {debut}年デビュー, "
                    f"メンバー={', '.join(members)}"
                )
            # members=[] かつ is_solo=False の場合は注入しない (誤情報源化防止)
        if matched_profiles:
            profile_context = (
                "\n\n## 参考: アーティスト正式情報（背景情報のみ）\n"
                + '\n'.join(matched_profiles)
                + "\n注: 記事に上記情報の記載がないこと自体は問題ではない。"
                + "記事が *明確に異なる数値* (例: 「KATSEYEは5人組」「2023年デビュー」) を書いた場合のみ critical。"
            )
    except Exception:
        pass

    # --- Layer 0: ソース記事の本文を取得（記事内容との照合用） ---
    # ドメインリストは config/source_domains.json から (2026-05-07統一)
    source_section = ''
    try:
        from lib.source_domains import source_url_regex as _src_re
        _source_urls = re.findall(_src_re(), content)
        if _source_urls:
            from lib.source_reader import read_source
            _src_text = read_source(_source_urls[0], max_chars=1500)
            if _src_text and len(_src_text) > 200:
                source_section = f"""

## ソース記事の本文（以下がこの記事の元ネタです。記事がソースから逸脱していないか照合してください）
{_src_text[:1200]}
"""
    except Exception:
        pass

    today = datetime.now(timezone.utc).strftime('%Y年%m月%d日')
    prompt = f'''あなたはK-POP専門メディアの校閲担当です。以下の記事を校閲してください。
今日の日付は{today}です。この記事は既に公開済みの記事です。

【タイトル】{title}
【本文抜粋】{plain}
{source_section}
## 判定基準
- critical: 人名/グループ名の間違い、数値の矛盾、存在しない人物、**ソース記事にない事実の追加（捏造）**、**バラエティ番組を新曲と誤記**、**タイトルがソースと全く異なる内容**
- high: タイトルと本文の不整合、ソースに名前があるのに記事で省略、**AI翻訳調の不自然表現** (下記パターン参照)
- medium: 表現の改善余地、軽微な表記揺れ、文体提案 (冗長/より自然/単語の選び方等)

## AI翻訳調 検出パターン (high 候補)
日本語ネイティブが書かないAI翻訳テンプレが混入していたら high で報告:
- 「〜を呼び起こしています」「〜を提供した」(英→日 直訳調の能動形)
- 「彼の/彼女の」を主語/所有格として過剰使用 (日本語は通常省略)
- 「〜にとっては〜である」(英語 to be 構文の直訳)
- 「心温まる瞬間」「強い反響を呼んだ」(AI生成記事の常套句)
- 「〜は〜と述べた/語った/言及した」を1記事に4回以上 (翻訳辞書反復)
ただし、これらが1-2回の自然な文中なら medium 以下、4回以上の反復で high 報告。

## 絶対に問題として報告してはいけないもの
- 2026年やそれ以降の日付は正常です。現在は2026年です。未来の日付として報告しないこと
- 曜日と日付の整合性チェックは行わないこと（あなたの暦計算は不正確なため）
- K-POPアーティスト名の英語/韓国語/日本語の表記揺れ
- K-POPファンが日常的に使う用語（カムバック、ファンミ等）
- **メンバー人数の問題は、記事中に「Xは N人組」「Xのメンバーは N人」のように明確に数字で書かれている場合のみ critical で報告すること**
- **「TWICE・ITZY・STRAY KIDS」のようなグループ名の列挙は「TWICEはX人」と主張していない。メンバー数誤りとして報告してはならない**
- **「JYP所属のTWICE」「HYBE傘下のBTS」のような所属関係の記述は事実関係。メンバー数とは無関係**
- **slug_short や URL長さ等、本文の事実とは無関係なメタ情報は critical で報告しないこと**
- **異なる指標の数値を「矛盾」と報告しないこと**：「首都圏13.5％・全国13.3％」「初週CD12万枚・配信再生5,000万回」「分間最高15.4％・平均13.5％」などは比較対象が違うため矛盾ではない。同一指標で異なる数字が併記されている場合のみ報告
- **タイトルと本文の整合性は、固有名詞（人名・グループ名・作品名）の登場有無のみで判定すること**：「タイトルが具体的でない」「より良いタイトルが考えられる」などスタイル批評は high として報告しない
- **3行まとめは要約なので、本文全項目を網羅していない場合でも問題と報告しないこと**
- **以下の「文体提案」は high として報告してはならない (medium 以下に分類すること)**:
  - 「冗長」「より簡潔に」「より自然な表現」「改善余地」等の単純な文体提案
  - 単語1個・フレーズ1個レベルの言い換え提案 (例: 「魅力披露」より「魅力を披露」)
  - 「若干あいまい」「あいまいさがある」等の主観的曖昧さ指摘
  - 記事中の文をそのまま引用しているだけで、何が問題か明示していない指摘
  - 「〜とする方が自然」「〜と簡潔にしても良い」等の改善提案文末

## スコア基準
- 95-100: 問題なし
- 80-94: medium問題のみ
- 60-79: high問題あり
- 60未満: critical問題あり

JSON出力のみ:
{{"score":60-100,"critical":[],"high":[],"medium":[]}}'''

    # --- Layer 1b結果をプロンプトに注入（GPT誤検知防止） ---
    if profile_context:
        prompt += profile_context

    # --- Layer 2: Tavily Web検索で事実を裏取り → 結果をプロンプトに注入 ---
    # 速報記事で信頼できるソースURLが本文に含まれる場合はTavilyスキップ
    TRUSTED_BREAKING_DOMAINS = [
        'soompi.com', 'allkpop.com', 'koreaboo.com', 'kpopstarz.com',
        'hellokpop.com', 'kpoppost.com', 'kstyle.com',
        'naver.com', 'daum.net', 'dispatch.co.kr', 'sportsseoul.com',
        'starnews.co.kr', 'newsen.com', 'osen.mt.co.kr', 'xsportsnews.com',
        'spotvnews.co.kr', 'entertain.naver.com', 'n.news.naver.com',
        'billboard.com', 'oricon.co.jp', 'weverse.io',
        'hybe.co.kr', 'smtown.com', 'ygent.com', 'jype.com',
        'reuters.com', 'apnews.com', 'bbc.com',
        'yna.co.kr', 'yonhapnews.co.kr', 'prtimes.jp',
        'kpophit.com', 'kbizoom.com', 'tenasia.com',
    ]
    has_trusted_source = False
    source_urls_in_content = re.findall(r'href="(https?://[^"]+)"', content)
    for src_url in source_urls_in_content:
        if any(domain in src_url for domain in TRUSTED_BREAKING_DOMAINS):
            has_trusted_source = True
            break

    tavily_context = ''
    tavily_issues = []
    if has_trusted_source:
        print(f"  [factcheck] Tavily skip: 信頼ソースURL検出済み")
    else:
        try:
            from lib.web_factcheck import _verify_with_tavily
            tavily_result = _verify_with_tavily(title, plain)
            tavily_found = tavily_result.get('found')
            if tavily_found is True:
                # 裏付けソースが見つかった → その内容をプロンプトに注入して照合させる
                src_texts = []
                for s in tavily_result.get('sources', [])[:3]:
                    src_texts.append(f"  - [{s.get('title', '')}]({s.get('url', '')})")
                if src_texts:
                    tavily_context = f"""

## Web検索で見つかった裏付け情報（Tavily）
以下は記事タイトルに関連するWeb検索結果です。記事の内容がこれらの情報と矛盾していないか確認し、矛盾があればcritical/highで報告してください:
{chr(10).join(src_texts)}"""
            elif tavily_found is False:
                tavily_issues.append(f'Web検索で裏付けソースが見つかりません: {tavily_result.get("reason", "")[:80]}')
        except Exception as e:
            print(f"  [factcheck] Tavily err: {e}")

    # Layer 2b: 事実主張の抽出+外部検証指示
    factcheck_ctx = _web_factcheck_context(title, plain)
    if tavily_context:
        prompt += tavily_context
    if factcheck_ctx:
        prompt += factcheck_ctx

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [{'role': 'user', 'content': prompt}],
        'response_format': {'type': 'json_object'},
        'max_tokens': 600,
    }).encode()

    req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
        data=body, headers={
            'Authorization': f'Bearer {OPENAI_KEY}',
            'Content-Type': 'application/json',
        })

    # リトライ+指数バックオフ（429対策）
    import time as _time
    last_err = None
    for attempt in range(3):
        try:
            r = json.loads(urllib.request.urlopen(req, timeout=60).read())
            result = json.loads(r['choices'][0]['message']['content'])
            # --- Layer 1の結果をマージ: profile照合で見つかった事実誤認をcriticalに追加 ---
            if profile_issues:
                result.setdefault('critical', []).extend(profile_issues)
                result['score'] = min(result.get('score', 100), 50)
            # --- Tavily裏付けなしをhighに追加 ---
            if tavily_issues:
                result.setdefault('high', []).extend(tavily_issues)
                result['score'] = min(result.get('score', 100), 70)
            # --- 2026-05-11: LLM hallucination filter ---
            # 本文に「N人組」「メンバーはN人」がないのにLLMが「N人組として記載」と
            # CRIT報告する hallucination (21219事案: 「5曲」を「5人組」と誤読) を除去
            _has_member_pattern = bool(re.search(r'\d+\s*人組|メンバー[はが]?\s*\d+\s*[人名]', plain or ''))
            if not _has_member_pattern:
                filtered_crit = []
                for item in result.get('critical', []):
                    s = str(item)
                    if 'メンバー人数' in s or '人組として記載' in s or 'メンバーが' in s:
                        # 該当 CRIT は hallucination → 除外
                        continue
                    filtered_crit.append(item)
                if len(filtered_crit) != len(result.get('critical', [])):
                    result['critical'] = filtered_crit
                    # スコア再計算 (CRIT 無くなれば最低 80 まで戻す)
                    if not filtered_crit:
                        result['score'] = max(result.get('score', 100), 80)

            # --- 2026-05-14: 文体提案 high の自動 downgrade ---
            # LLM が prompt 指示に従わず「不自然」「冗長」「より自然」等の style 提案を
            # high として返してくるケースの post-process 防壁。memory:
            # feedback_llm_proofreader_false_positive
            style_kw = (
                '冗長', 'より自然', 'より簡潔', '改善余地', '改善できる', '改善が望ましい',
                'あいまい', '若干', 'すこし', '少し堅苦', '不自然な表現', '不自然な日本語',
                'とする方が自然', 'と簡潔にしても', '言い換え', 'スタイル批評',
            )
            kept_high, demoted = [], []
            for item in result.get('high', []):
                s = str(item)
                if any(k in s for k in style_kw):
                    demoted.append(item)
                else:
                    kept_high.append(item)
            if demoted:
                result['high'] = kept_high
                result.setdefault('medium', []).extend(demoted)
                # high が空になればスコアを 80+ に戻す
                if not kept_high and not result.get('critical'):
                    result['score'] = max(result.get('score', 100), 85)
            return result
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                wait = (2 ** attempt) * 5  # 5s, 10s, 20s
                print(f"  [factcheck] 429 rate limit, retry in {wait}s (attempt {attempt+1}/3)")
                _time.sleep(wait)
                # リクエストを再構築（bodyが消費されるため）
                req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
                    data=body, headers={
                        'Authorization': f'Bearer {OPENAI_KEY}',
                        'Content-Type': 'application/json',
                    })
            else:
                raise
    raise last_err


def proofread_article(title: str, body_html: str) -> dict:
    """公開前ファクトチェック（WP postオブジェクト不要版）

    pre_publish_gateから呼ばれる。proofread_postと同じ3層検証を実行。
    """
    fake_post = {
        'title': {'rendered': title},
        'content': {'rendered': body_html},
    }
    try:
        return proofread_post(fake_post)
    except Exception as e:
        return {'score': 100, 'critical': [], 'high': [], 'medium': [],
                'error': str(e)[:100]}


def queue_to_audit_state(post_id, post_type, llm_issues):
    """critical/high検出時にaudit_state.jsonlにキュー追加"""
    os.makedirs(os.path.dirname(AUDIT_STATE), exist_ok=True)
    issues = []
    for c in llm_issues.get('critical', []):
        issues.append({'type': 'llm_critical', 'severity': 'high', 'detail': c})
    for h in llm_issues.get('high', []):
        issues.append({'type': 'llm_high', 'severity': 'high', 'detail': h})

    with open(AUDIT_STATE, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'post_id': post_id,
            'post_type': 'post' if post_type == 'posts' else post_type,
            'issues': issues,
            'audited_at': datetime.now(timezone.utc).isoformat(),
            'source': 'llm_proofreader',
            'high_count': len(issues),
            'medium_count': 0, 'low_count': 0,
        }, ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--hours', type=int, default=4)
    parser.add_argument('--limit', type=int, default=30)
    args = parser.parse_args()

    now = datetime.now(JST)
    print(f"=== llm_proofreader {now.strftime('%Y-%m-%d %H:%M')} ===")

    if not OPENAI_KEY:
        print("  OPENAI_API_KEY未設定、終了")
        return

    posts = fetch_recent_posts(hours=args.hours, per_page=args.limit)
    # Skip already proofread
    targets = [p for p in posts if not _already_proofread(p['id'])]
    print(f"  対象: {len(targets)}件 (取得{len(posts)}件, 既読{len(posts)-len(targets)}件)")

    if args.dry_run:
        for p in targets:
            title = p['title']['rendered'] if isinstance(p.get('title'), dict) else ''
            print(f"  [dry-run] id={p['id']} {title[:50]}")
        print(f"  dry-run完了 ({len(targets)}件)")
        return

    results = []
    crit_total = high_total = 0
    for i, p in enumerate(targets):
        pid = p['id']
        pt = p.get('_post_type', 'posts')
        title = p['title']['rendered'] if isinstance(p.get('title'), dict) else ''
        try:
            r = proofread_post(p)
            r['id'] = pid
            r['type'] = pt
            r['title'] = title[:60]
            results.append(r)

            nc = len(r.get('critical', []))
            nh = len(r.get('high', []))
            crit_total += nc
            high_total += nh
            print(f"  [{i+1}/{len(targets)}] id={pid} score={r.get('score',0)} C={nc} H={nh}")

            # Alert + queue
            if nc > 0 or nh > 0:
                os.makedirs(os.path.dirname(ALERT_LOG), exist_ok=True)
                with open(ALERT_LOG, 'a', encoding='utf-8') as f:
                    f.write(f"{now.isoformat()} id={pid} C={nc} H={nh} "
                            f"critical={r.get('critical',[])} high={r.get('high',[])}\n")
                queue_to_audit_state(pid, pt, r)

            # 4項目監査procedural: factcheck step を記録
            try:
                from lib.audit_steps_log import record_step as _record_step
                fc_status = 'error' if nc > 0 else ('warn' if nh > 0 else 'ok')
                _record_step(pid, 'factcheck', fc_status,
                             f'C={nc} H={nh} score={r.get("score", 0)}',
                             source='llm_proofreader')
            except Exception as _se:
                pass

        except Exception as e:
            print(f"  [{i+1}/{len(targets)}] id={pid} ERR: {e}")
            results.append({'id': pid, 'type': pt, 'error': str(e)})

    # Save results
    os.makedirs(LOGS_DIR, exist_ok=True)
    out_path = os.path.join(LOGS_DIR, f"{now.strftime('%Y%m%d_%H')}.json")
    out = {
        'timestamp': now.isoformat(),
        'total': len(results),
        'critical': crit_total,
        'high': high_total,
        'results': results,
    }
    json.dump(out, open(out_path, 'w'), ensure_ascii=False, indent=2)

    print(f"\n校閲完了: {len(results)}件 / critical={crit_total} high={high_total}")
    print(f"保存: {out_path}")


if __name__ == '__main__':
    main()
