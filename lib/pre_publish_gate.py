"""統一公開前ゲート — 全パイプライン経路で WP POST 前に呼ぶ

BLOCKは壊滅レベル6種のみ。WARNを厚く。draft時はBLOCK不可。
既存の fact_checker / full_audit_engine のチェック関数を再利用し、ロジック重複なし。
"""
import re
import json
import os
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

# --- 既存チェック関数の再利用 ---
from lib.fact_checker import check_article as _fact_check
from lib.full_audit_engine import (
    CRITERIA, TYPO_PATTERNS,
    check_title, check_slug, check_featured_media,
    check_content_quality, check_meta_description,
    check_internal_links, check_category,
)

_JST = timezone(timedelta(hours=9))
_LOG_PATH = '/home/aiuser/kpop-ai-system/logs/pre_publish_gate.jsonl'

# 重複判定用キーワード抽出。ハングル(가-힣)を含めないと韓国語ソース/既存タイトルの
# 固有名詞(例:레드벨벳)が抽出されず、生成前 dedup をすり抜ける(2026-07-16 修理)。
# 生成前(新規側)と生成後(既存側)で同一パターンを使わないと overlap が成立しない。
KEYWORD_PATTERN = r'[A-Za-z]{2,}|[ァ-ヶー]{3,}|[一-龥]{2,}|[가-힣]{2,}'

# BLOCKすべきissue type（壊滅レベルのみ）
BLOCK_TYPES = frozenset({
    'content_empty',          # 本文 < 400字
    # content_short は kind別に判定 → _should_block_content_short() で制御
    'no_source_no_signal',    # ソースなし (feature/popup除く)
    'anonymized_names',       # fact_checker critical: 実名匿名化
    'latest_but_old',         # fact_checker critical: 速報なのに古い
    'stale_date',             # fact_checker critical: 2年以上古い
    'ai_mention',             # ChatGPT/Claude等が本文に混入
    'review_contamination',   # レビューレポート/エラーメッセージ混入
    # no_artist_category は公開後に自動修正可能 → BLOCK_TYPESから除外 (WARN扱い)
    'shop_no_practical_info', # 店舗紹介なのに住所/営業時間なし（架空店舗の疑い）
    'slug_short',             # slug短すぎはSEO壊滅 → BLOCK (2026-05-02追加)
    'no_thumbnail',           # サムネなしは公開禁止 (2026-05-02追加)
    'thumbnail_portrait',     # 縦長サムネはOGP壊滅 (2026-05-02追加)
    'thumbnail_letterbox',    # 縦長コンテンツのpadding/blurコピー検出 (2026-05-08追加)
    'artist_profile_mismatch', # メンバー人数/デビュー年の事実誤認 (2026-05-04追加)
    'template_placeholder',    # XX月/TBD等のテンプレ残存 (2026-05-04追加)
    'internal_ops_leak',       # GSC横展開/CTR/IMP等の内部施策用語混入 (2026-05-04追加)
    'meta_desc_empty',         # meta_description空で公開禁止 (2026-05-06追加)
    'duplicate_title',         # 同一/酷似タイトルの記事が既に公開済み (2026-05-06追加)
    'stale_year_in_title',     # タイトルに古い年号 (2026-05-06追加)
    'feature_no_source',       # ソースなしfeature記事 (2026-05-02追加)
    'css_leak',                # CSS生テキスト混入 (2026-05-06追加)
    'title_source_mismatch',   # タイトルがソースと乖離 (2026-05-06追加)
    'llm_factcheck_critical',  # Claude v2 factcheck CRITICAL — 事実捏造/主語逆転等 (2026-05-11追加)
    'non_kpop_topic',          # 非K-POPトピック(婚活リアリティ番組/政治/非アイドルゴシップ) (2026-05-29追加)
})

# fact_checker の critical → BLOCK にマッピングする type
_FC_CRITICAL_TYPES = frozenset({
    'anonymized_names', 'latest_but_old', 'stale_date',
})

# contamination パターン (post_guard.py 由来)
_CONTAMINATION_RE = [
    re.compile(r'(?:review|audit)\s*(?:report|result)', re.IGNORECASE),
    re.compile(r'Traceback \(most recent call'),
    re.compile(r'Error:|Exception:|ModuleNotFoundError'),
    re.compile(r'Claude\s+(?:Code|API)|Anthropic'),
]


def _build_post_dict(title, body_html, slug, featured_media, categories, excerpt):
    """full_audit_engine の check_* が期待する post dict を合成"""
    return {
        'title': {'rendered': title or ''},
        'content': {'rendered': body_html or ''},
        'excerpt': {'rendered': excerpt or ''},
        'slug': slug or '',
        'featured_media': featured_media or 0,
        'categories': categories or [],
    }


def _map_audit_issues(issues):
    """full_audit_engine の issue を gate の severity にマッピング"""
    mapped = []
    for i in issues:
        t = i.get('type', '')
        orig_sev = i.get('severity', 'low')
        # BLOCK_TYPES に含まれる issue は block に昇格
        if t == 'ai_mention' or (t.startswith('text_') and t == 'text_ai_mention'):
            gate_type = 'ai_mention'
            gate_sev = 'block'
        elif t in BLOCK_TYPES:
            gate_type = t
            gate_sev = 'block'
        else:
            gate_type = t
            gate_sev = 'warn' if orig_sev in ('high', 'medium') else 'info'
        mapped.append({
            'type': gate_type,
            'severity': gate_sev,
            'detail': i.get('detail', i.get('type', '')),
        })
    return mapped


_CODEBLOCK_MARKER_RE = re.compile(r'```(?:html|HTML|python|json|css|javascript|js)?[\s\n]')
_TEMPLATE_PLACEHOLDER_RE = re.compile(r'\[(?:ソース名|サイト名|メディア名|執筆者名|タイトル|未定|要確認|確認中|TBD|TODO)\]')


def _check_contamination(body_html):
    """レビューレポート/エラーメッセージ/Claudeメタ言及/codeblockマーカー/プレースホルダの混入検出"""
    issues = []
    raw = body_html or ''
    text = re.sub(r'<[^>]+>', ' ', raw)
    for pat in _CONTAMINATION_RE:
        m = pat.search(text)
        if m:
            issues.append({
                'type': 'review_contamination',
                'severity': 'block',
                'detail': f'本文にシステムメッセージ混入: "{m.group()[:50]}"',
            })
            break
    cb = _CODEBLOCK_MARKER_RE.search(raw)
    if cb:
        issues.append({
            'type': 'codeblock_marker',
            'severity': 'block',
            'detail': f'```マーカー混入: "{cb.group()}"',
        })
    ph = _TEMPLATE_PLACEHOLDER_RE.search(raw)
    if ph:
        issues.append({
            'type': 'template_placeholder',
            'severity': 'block',
            'detail': f'未置換プレースホルダ {ph.group()} が残存',
        })
    return issues


def _check_html_structure(body_html):
    """<p>/<div>等の open/close 不均衡を検出 (cta_injector A8 link事故の再発防止)"""
    issues = []
    if not body_html:
        return issues
    opens = len(re.findall(r'<p[\s>]', body_html))
    closes = body_html.count('</p>')
    if opens != closes:
        issues.append({
            'type': 'unclosed_p',
            'severity': 'warn',
            'detail': f'<p> open={opens} close={closes} 不均衡',
        })
    return issues


def normalize_html_for_publish(html):
    """BeautifulSoup(lxml) で <p>/<div> balance を自動修正して公開可能な HTML を返す"""
    if not html:
        return html or ''
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'lxml')
        body = soup.body
        if body is not None:
            return ''.join(str(c) for c in body.children)
        return str(soup)
    except Exception:
        return html


def _check_content_empty(body_html):
    """壊滅的に短い本文の検出 (< 400字 → BLOCK)"""
    text = re.sub(r'<[^>]+>', '', body_html or '').strip()
    # ソース表記・CTA・disclaimer を除外
    core = re.sub(r'※[^\n]*|情報ソース[\s\S]*|関連おすすめ[\s\S]*', '', text).strip()
    if len(core) < 400:
        return [{
            'type': 'content_empty',
            'severity': 'block',
            'detail': f'本文が壊滅的に短い ({len(core)}字、最低400字)',
        }]
    return []


# 店舗・スポット紹介記事に住所/営業時間等がない場合を検出するパターン
_SHOP_TITLE_RE = re.compile(
    r'(カフェ|レストラン|ショップ|グルメ|名店|店舗|スポット).*[0-9０-９]+選|'
    r'[0-9０-９]+選.*(カフェ|レストラン|ショップ|グルメ|名店|スポット)|'
    r'おすすめ.*(カフェ|レストラン|ショップ|グルメ)',
    re.IGNORECASE,
)
_PRACTICAL_INFO_RE = re.compile(
    r'住所|アクセス|営業時間|定休日|〒|\d{3}-\d{4}|'
    r'[0-9０-９]{1,2}:[0-9０-９]{2}|'
    r'号線.*駅|地下鉄.*駅|map\.naver|maps\.google|Google\s*Map',
    re.IGNORECASE,
)


def _check_shop_article_without_details(title, body_html):
    """店舗紹介記事なのに住所・営業時間等の実用情報がない場合はBLOCK"""
    if not _SHOP_TITLE_RE.search(title or ''):
        return []
    text = re.sub(r'<[^>]+>', ' ', body_html or '')
    if _PRACTICAL_INFO_RE.search(text):
        return []
    return [{
        'type': 'shop_no_practical_info',
        'severity': 'block',
        'detail': '店舗/スポット紹介記事に住所・営業時間・アクセス情報がありません。'
                  'LLMによる架空店舗の捏造の可能性があるためBLOCKします',
    }]


def find_duplicate_published(keywords):
    """公開済み記事に同テーマ(キーワード重複)があれば {'id','title'} を返す。無ければ None。

    keywords: 正規化済みキーワードのリスト(英字2+/カタカナ3+/漢字2+)。
    判定: 固有名詞(英字/カタカナ)が2語以上一致、または overlap>=2 かつ overlap率>40%。
    APIエラー時は None(=重複なし扱い。ブロックしない=従来1g挙動を踏襲)。
    """
    if not keywords:
        return None
    try:
        search_q = ' '.join(keywords[:3])
        wp_api = os.environ.get('WP_API_URL', 'https://www.kpopjournal.tokyo/wp-json/wp/v2')
        search_url = (
            f'{wp_api}/posts?search={urllib.parse.quote(search_q)}'
            f'&status=publish&per_page=5&_fields=id,title'
        )
        req = urllib.request.Request(search_url, headers={'User-Agent': 'KPJ-Gate/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            existing = json.loads(resp.read())
        new_kw = set(k.lower() for k in keywords)
        for ep in existing:
            et = ep.get('title', {})
            et_text = et.get('rendered', '') if isinstance(et, dict) else str(et)
            ex_kw = set(re.findall(KEYWORD_PATTERN, et_text.lower()))
            overlap = new_kw & ex_kw
            proper_overlap = {w for w in overlap if re.match(r'[a-z]', w) or re.match(r'[ァ-ヶー]', w) or re.match(r'[가-힣]', w)}
            if len(proper_overlap) >= 2 or (len(overlap) >= 2 and len(overlap) / max(len(new_kw), 1) > 0.4):
                return {'id': ep.get('id'), 'title': et_text}
    except Exception:
        return None
    return None


def pre_publish_gate(
    title, body_html, post_type='post', kind='news',
    source_url=None, source_signals=None, slug=None,
    featured_media=None, categories=None, excerpt=None,
    status='publish', source_text_length=None,
    source_title=None,
    skip_llm_factcheck=False,
    structural_only=False,
):
    """統一公開前ゲート

    Returns:
        {
            'verdict': 'BLOCK' | 'WARN' | 'PASS',
            'issues': list[dict],
            'block_reasons': list[str],
            'warn_reasons': list[str],
        }

    structural_only=True のとき:
      内部リンク数 / HTML タグ均衡 など「最終(注入後)本文でないと正しく検査できない
      構造系」だけを評価する軽量パス。LLM factcheck / 重複タイトル WP クエリ /
      web 検査 などのコンテンツ系・高コスト処理は一切行わない。
      これらの構造検査は全て WARN 止まり(BLOCK_TYPES 非含)なので BLOCK は生まれない。
      コンテンツ/事実の判定は別途「注入前 raw 本文」に対する通常パスで行う想定
      (unified_publisher が 2 パスでマージ)。
    """
    issues = []
    post_dict = _build_post_dict(title, body_html, slug, featured_media, categories, excerpt)
    criteria = CRITERIA.get(post_type, CRITERIA['post'])

    if structural_only:
        s_issues = []
        # check_content_quality は length/typo/fabrication 等のコンテンツ信号も返すため、
        # タグ均衡(unclosed_h2 / unclosed_p)だけを抽出する。
        for ci in check_content_quality(post_dict, criteria):
            if ci.get('type') in ('unclosed_h2', 'unclosed_p'):
                s_issues.extend(_map_audit_issues([ci]))
        s_issues.extend(_map_audit_issues(check_internal_links(post_dict, criteria)))
        s_issues.extend(_check_html_structure(body_html))
        if status == 'draft':
            for i in s_issues:
                if i['severity'] == 'block':
                    i['severity'] = 'warn'
        block_issues = [i for i in s_issues if i['severity'] == 'block']
        warn_issues = [i for i in s_issues if i['severity'] == 'warn']
        verdict = 'BLOCK' if block_issues else ('WARN' if warn_issues else 'PASS')
        # 注: jsonl ログ(section 5)より前に return = ゲートログは記事1件につき1行を維持。
        return {
            'verdict': verdict, 'issues': s_issues,
            'block_reasons': [i['detail'] for i in block_issues],
            'warn_reasons': [i['detail'] for i in warn_issues],
        }

    # --- 1. 壊滅チェック (BLOCK候補) ---

    # 1a0. 非K-POPトピック判定 (news/breaking のみ。タイトル+本文で照合)
    #   『나는 SOLO』婚活番組・政治論争・非アイドルゴシップの記事化を停止 (2026-05-29)
    if kind in ('news', 'breaking'):
        try:
            from lib.kpop_topic_filter import classify_non_kpop_topic
            _topic_text = f"{title or ''} {re.sub(r'<[^>]+>', ' ', body_html or '')}"
            _ng = classify_non_kpop_topic(_topic_text)
            if _ng:
                issues.append({
                    'type': 'non_kpop_topic',
                    'severity': 'block',
                    'detail': f'K-POPと無関係なトピック({_ng})。'
                              '婚活リアリティ番組の一般人/政治/非アイドルゴシップは記事化しません',
                })
        except Exception:
            pass  # フィルタ障害でゲート全体を止めない

    # 1a. 本文空チェック
    issues.extend(_check_content_empty(body_html))

    # 1a2. 店舗紹介記事の実用情報チェック (住所/営業時間なしはBLOCK)
    issues.extend(_check_shop_article_without_details(title, body_html))

    # 1b. ソースURL/シグナルの有無判定（全kind共通）
    has_source = (source_url and source_url.startswith('http')) or \
                 (source_signals and len(source_signals) > 0)

    # 1b0. ソース本文の取得確認（ソースURLがあるのに本文を読んでいない場合はWARN）
    if has_source and source_text_length is not None and source_text_length < 100:
        issues.append({
            'type': 'source_not_read',
            'severity': 'warn',
            'detail': f'ソースURLは存在するがソース本文の取得に失敗({source_text_length}字)。'
                      'GPTが推測で記事を書いた可能性。固有名詞の正確性を人手で確認してください',
        })

    # 1b1. news/breaking でソースなし → BLOCK
    if kind not in ('feature', 'popup') and not has_source:
        issues.append({
            'type': 'no_source_no_signal',
            'severity': 'block',
            'detail': 'ソースURL/シグナルなし。GPT単独生成の疑い',
        })

    # 1b2. feature でソースなし → BLOCK（2026-05-02 捏造18%判明を受けて全面停止）
    if kind == 'feature' and not has_source:
        issues.append({
            'type': 'feature_no_source',
            'severity': 'block',
            'detail': 'ソースなしのfeature記事は公開禁止。LLM単独生成は捏造率18%',
        })

    # 1b3. Web検索ファクトチェック（ソースなし記事の裏取り）
    if not has_source and kind not in ('popup',):
        try:
            from lib.web_factcheck import verify_article as _web_verify
            _wf = _web_verify(title, body_html, kind=kind, source_url=source_url)
            if _wf['verdict'] == 'BLOCK':
                issues.append({
                    'type': 'web_factcheck_failed',
                    'severity': 'block',
                    'detail': f'Web検索ファクトチェック不合格: {_wf["issues"][0]["detail"][:80] if _wf["issues"] else "裏付けソースなし"}',
                })
            elif _wf['verdict'] == 'WARN':
                issues.append({
                    'type': 'web_factcheck_warn',
                    'severity': 'warn',
                    'detail': f'Web検索ファクトチェック警告: 確信度{_wf["confidence"]:.0%}',
                })
        except Exception as _wfe:
            issues.append({
                'type': 'web_factcheck_error',
                'severity': 'warn',
                'detail': f'Web検索ファクトチェックスキップ: {_wfe}',
            })

    # 1c. contamination
    issues.extend(_check_contamination(body_html))

    # 1c0. CSS生テキスト混入チェック（WPが<style>除去→CSS文字列が可視化）
    _plain_css_check = re.sub(r'<[^>]+>', '', body_html or '')
    if re.search(r'\.kpj-[a-z-]+\{|@keyframes|@media\(', _plain_css_check):
        issues.append({
            'type': 'css_leak',
            'severity': 'block',
            'detail': 'CSSスタイル文字列が本文に混入。<style>タグがWPに除去された可能性',
        })

    # 1c1. ハングル混入検査 (translate_ko_to_ja の訳し漏れ検出)
    # タイトル/altに1字でも → BLOCK / 本文20字超 → BLOCK / 5字超 → WARN
    try:
        from lib.translation_residue_check import assess_residue
        _plain_body = re.sub(r'<[^>]+>', '', body_html or '')
        _alt_for_check = ''
        # alt は呼び出し元から渡されないことが多いので body 中の <img alt=> も拾う
        for _m in re.finditer(r'<img[^>]*\salt=["\']([^"\']*)["\']', body_html or ''):
            _alt_for_check += ' ' + _m.group(1)
        _residue = assess_residue(title, _plain_body, _alt_for_check)
        if _residue['verdict'] == 'BLOCK':
            issues.append({
                'type': 'translation_residue_block',
                'severity': 'block',
                'detail': f"翻訳残存ハングル: {_residue['reason']} samples={_residue['samples'][:2]}",
            })
        elif _residue['verdict'] == 'WARN':
            issues.append({
                'type': 'translation_residue_warn',
                'severity': 'warn',
                'detail': f"翻訳残存ハングル: {_residue['reason']}",
            })
    except Exception as _trre:
        pass

    # 1c3. 内部施策用語がタイトル/本文に混入していないか検出
    _internal_ops_terms = [
        (r'GSC横展開', 'GSC横展開(内部施策用語)が混入'),
        (r'(?<!\w)CTR[\s]*[\d]+\.?\d*%', 'CTR数値(内部指標)が混入'),
        (r'(?<!\w)IMP\s*=\s*\d+', 'IMP値(内部指標)が混入'),
        (r'潜在\+\d+clicks', '潜在clicks(内部指標)が混入'),
        (r'(?<!\w)GSC(?:の|を|で|と)', 'GSC(内部ツール名)が混入'),
        (r'横展開', '横展開(内部用語)が混入'),
        (r'(?<!\w)RPM[\s]*[\d]', 'RPM(内部指標)が混入'),
        (r'A8\.net|アフィリエイト戦略', 'アフィリエイト関連の内部用語が混入'),
    ]
    _check_text = f"{title or ''} {re.sub(r'<[^>]+>', ' ', body_html or '')}"
    for _ops_pat, _ops_label in _internal_ops_terms:
        if re.search(_ops_pat, _check_text):
            issues.append({
                'type': 'internal_ops_leak',
                'severity': 'block',
                'detail': _ops_label,
            })

    # 1c2. テンプレ残存・プレースホルダ検出 (XX月/TBD/要確認 等)
    _plain_sanitize = re.sub(r'<[^>]+>', ' ', body_html or '')
    _template_blockers = [
        (r'XX[月日年時分]', 'XX月/XX日テンプレ残存'),
        (r'〇〇[月日年]', '〇〇テンプレ残存'),
        (r'(?<!\w)TBD(?!\w)', 'TBD残存'),
        (r'\[要確認\]|\[未定\]|\[確認中\]', '要確認マーカー残存'),
        (r'```(?:html|python|json|css|javascript)', 'コードブロックマーカー混入'),
        (r'INSERT_.*?_HERE|PLACEHOLDER', '英語プレースホルダ残存'),
    ]
    for _tp, _tl in _template_blockers:
        _tm = re.findall(_tp, _plain_sanitize)
        if _tm:
            issues.append({
                'type': 'template_placeholder',
                'severity': 'block',
                'detail': f'{_tl}: {", ".join(_tm[:3])}',
            })

    # 1d. AI mention 直接検出 (TYPO_PATTERNSの\bが日本語境界で不発のため補完)
    _plain = re.sub(r'<[^>]+>', ' ', body_html or '')
    if re.search(r'(?:ChatGPT|GPT-[34]|Claude\s*(?:Code|API)?|Anthropic)', _plain, re.IGNORECASE):
        issues.append({
            'type': 'ai_mention',
            'severity': 'block',
            'detail': '本文にAI/LLMツール名が混入',
        })

    # 1e. アーティスト基本情報照合（メンバー人数/デビュー年の矛盾 → BLOCK）
    try:
        from pipeline.llm_proofreader import _check_artist_profile
        _plain_text = re.sub(r'<[^>]+>', ' ', body_html or '')
        _profile_issues = _check_artist_profile(title or '', _plain_text)
        for _pi in _profile_issues:
            issues.append({
                'type': 'artist_profile_mismatch',
                'severity': 'block',
                'detail': _pi,
            })
    except Exception:
        pass  # profile照合失敗は投稿をブロックしない

    # 1f. meta_description空チェック (2026-05-06追加: unified_publisherバグの再発防止)
    _excerpt = (excerpt or '').strip()
    if status == 'publish' and post_type == 'post' and len(_excerpt) < 40:
        issues.append({
            'type': 'meta_desc_empty',
            'severity': 'block',
            'detail': f'meta_description(excerpt)が{len(_excerpt)}字。80字以上必須。SEO壊滅を防止',
        })

    # 1g. 重複記事チェック (2026-05-06追加 / 2026-06-16 find_duplicate_published に集約)
    if status == 'publish' and title:
        _norm_title = re.sub(r'[【\[\(][^】\]\)]*[】\]\)]|！|!|？|\?', '', title).strip()
        _keywords = re.findall(KEYWORD_PATTERN, _norm_title)
        _keywords = [k for k in _keywords if k not in ('ガイド', '完全', '最新', '徹底', '紹介', '解説', 'まとめ', '速報', '必見')]
        _dup = find_duplicate_published(_keywords)
        if _dup:
            issues.append({
                'type': 'duplicate_title',
                'severity': 'block',
                'detail': f'類似テーマの記事が公開済み (ID={_dup["id"]}): {str(_dup["title"])[:40]}',
            })

    # 1g2. 本文内フレーズ重複チェック（GPTハルシネーション検出）
    if body_html:
        _plain_dup = re.sub(r'<[^>]+>', '', body_html)
        _sentences = re.findall(r'[^。！!？?\n]{10,}[。！!？?]', _plain_dup)
        # 「」で囲まれた引用フレーズの重複を検出
        _quotes = re.findall(r'「([^」]{5,30})」', _plain_dup)
        _quote_counts = {}
        for _q in _quotes:
            _quote_counts[_q] = _quote_counts.get(_q, 0) + 1
        for _q, _c in _quote_counts.items():
            if _c >= 2:
                issues.append({
                    'type': 'duplicate_phrase',
                    'severity': 'warn',
                    'detail': f'同一引用フレーズが{_c}回出現: 「{_q}」',
                })
                break
        # 文全体の重複（先頭20字一致）
        _seen_heads = {}
        for _s in _sentences:
            _head = _s.strip()[:20]
            if _head in _seen_heads:
                issues.append({
                    'type': 'duplicate_phrase',
                    'severity': 'warn',
                    'detail': f'類似文が複数回出現: 「{_head}…」',
                })
                break
            _seen_heads[_head] = True

    # 1h00. タイトルとソースヘッドラインの乖離チェック
    # 記事タイトルにソースにない固有名詞が追加されていたらBLOCK
    if source_title and title:
        # 2026-05-12: 한국어 ソース見出し中の artist/group hangul を英字 alias に
        # 展開してから比較。「아일릿→ILLIT」等の **正しい翻訳** を「ソースにない語句が
        # 追加」誤検知して OSEN/MyDaily 系の publish を 24h で 0 件まで落とした事故
        # への根治。korean_proper_nouns.json の members+groups+labels を共有辞書として
        # 使うことで translator と一貫性を保つ。
        try:
            from lib.korean_translator import apply_proper_noun_dict
            _src_normalized, _ = apply_proper_noun_dict(source_title)
        except Exception:
            _src_normalized = source_title
        # 2026-05-23: 照合対象を source_title だけでなく記事本文(=翻訳済みソース本文)にも
        # 拡張。ソース本文に根拠のある固有名詞(例: WOODZ の曲名 "Drowning")をタイトルに
        # 使っても「ソースにない語句」と誤判定して過剰BLOCKしていた事故への根治。
        # 本文(title 候補の出所)に存在する語句は通し、本文にもタイトルにも無い語句のみ
        # BLOCK する(捏造防止は維持)。
        _body_plain = re.sub(r'<[^>]+>', ' ', body_html or '')
        _src_text = (_src_normalized + ' ' + _body_plain).lower()
        # 記事タイトルの英字固有名詞を抽出
        _title_proper = set(re.findall(r'[A-Z][A-Za-z]{2,}', title))
        _title_proper -= {'速報', 'KPOP'}
        # ソース(タイトル+本文)のどこにも無い固有名詞を検出
        _added = {p for p in _title_proper if p.lower() not in _src_text}
        # 一般的な翻訳追加語を除外
        _added -= {'COUNTDOWN', 'JOURNAL'}
        if _added:
            # 追加された固有名詞がニュースのキーワード（Met Gala等の捏造を検出）
            _suspicious = {w for w in _added if len(w) >= 3
                          and w not in {'BTS', 'YG', 'SM', 'JYP', 'HYBE', 'MBC', 'SBS', 'KBS', 'Mnet'}}
            if _suspicious:
                issues.append({
                    'type': 'title_source_mismatch',
                    'severity': 'block',
                    'detail': f'タイトルにソースにない語句が追加: {_suspicious}。'
                              f'ソース: {source_title[:40]}',
                })

    # 1h0. タイトル年号チェック（現在年と矛盾する年号をBLOCK）
    if title:
        _current_year = datetime.now(_JST).year
        _year_matches = re.findall(r'(20[0-9]{2})年?', title)
        for _ym in _year_matches:
            _y = int(_ym)
            if _y < _current_year:
                issues.append({
                    'type': 'stale_year_in_title',
                    'severity': 'block',
                    'detail': f'タイトルに過去の年号({_y}年)。現在{_current_year}年',
                })
                break

    # 1h. サムネイル品質ゲート（有無だけでなく縦長・alt空もBLOCK）
    if featured_media and featured_media > 0:
        try:
            import urllib.request
            wp_api = os.environ.get('WP_API_URL', 'https://www.kpopjournal.tokyo/wp-json/wp/v2')
            media_url = f'{wp_api}/media/{featured_media}'
            req = urllib.request.Request(media_url, headers={'User-Agent': 'KPJ-Gate/1.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                media_data = json.loads(resp.read())
            # 縦長チェック
            img_w = media_data.get('media_details', {}).get('width', 0)
            img_h = media_data.get('media_details', {}).get('height', 0)
            if img_w > 0 and img_h > img_w:
                issues.append({
                    'type': 'thumbnail_portrait',
                    'severity': 'block',
                    'detail': f'サムネイルが縦長 ({img_w}x{img_h})。OGP表示が壊れます',
                })
            # alt空チェック
            alt = media_data.get('alt_text', '').strip()
            if not alt:
                issues.append({
                    'type': 'thumbnail_alt_empty',
                    'severity': 'warn',
                    'detail': 'サムネイルのalt_textが空',
                })

            # サムネ-記事整合性チェック: タイトルのアーティスト名がサムネに含まれるか
            _thumb_text = (alt + ' ' + media_data.get('source_url', '') +
                           ' ' + media_data.get('title', {}).get('rendered', '')).lower()
            _ARTIST_NAMES_CHECK = [
                'BTS', 'BLACKPINK', 'TWICE', 'aespa', 'NewJeans', 'IVE',
                'LE SSERAFIM', 'Stray Kids', 'SEVENTEEN', 'ENHYPEN', 'ITZY',
                'BABYMONSTER', 'RIIZE', 'EXO', 'NCT', 'TXT', 'NMIXX',
                'Red Velvet', 'BIGBANG', '(G)I-DLE', 'ATEEZ', 'TREASURE',
            ]
            _title_artist = None
            for _an in _ARTIST_NAMES_CHECK:
                if _an.lower() in (title or '').lower():
                    _title_artist = _an
                    break
            if _title_artist and _title_artist.lower() not in _thumb_text:
                # サムネにアーティスト名がない → 別人の写真の可能性
                issues.append({
                    'type': 'thumbnail_artist_mismatch',
                    'severity': 'warn',
                    'detail': f'サムネにタイトルのアーティスト名({_title_artist})が含まれない。別人の写真の可能性',
                })

            # letterbox/縦長コンテンツpadding 検出 (2026-05-08追加: 18762/18779事案)
            try:
                _media_url = media_data.get('source_url', '')
                if _media_url:
                    from lib.cross_audit import check_letterbox
                    _lb = check_letterbox(_media_url)
                    if _lb.get('is_letterbox'):
                        issues.append({
                            'type': 'thumbnail_letterbox',
                            'severity': 'block',
                            'detail': f"letterbox検出 (mode={_lb.get('mode')} L_sim={_lb.get('left_color_sim')})",
                        })
            except Exception:
                pass  # letterbox検査失敗時は通す
        except Exception:
            pass  # メディアAPI取得失敗は投稿をブロックしない

    # --- 2. fact_checker (既存を再利用) ---
    try:
        fc = _fact_check(title, body_html,
                         source_url=source_url,
                         source_signals=source_signals,
                         kind=kind)
        for fi in fc.get('all_issues', []):
            ft = fi.get('type', '')
            if ft in _FC_CRITICAL_TYPES:
                sev = 'block'
            elif fi.get('severity') == 'critical':
                sev = 'block'
            else:
                sev = 'warn'
            issues.append({
                'type': ft,
                'severity': sev,
                'detail': fi.get('detail', ft),
            })
    except Exception as e:
        issues.append({
            'type': 'fact_check_error',
            'severity': 'info',
            'detail': f'fact_check skip: {e}',
        })

    # --- 2b. LLMファクトチェック (公開前の捏造検出) ---
    # 2026-05-11: publish時は Claude Sonnet 4.6 + web search 版 (factcheck_v2)
    # を常時強制使用。env FACTCHECK_V2 未設定でも publish パスでは v2 必須
    # (v1 OpenAI版は web search なしでCRIT検出力が弱く、過去181件CRIT通過した)
    #
    # 2026-05-12 (コスト削減):
    # - skip_llm_factcheck=True で外部LLM呼出を完全 skip (post_publish_hook 再ゲート等)
    # - 信頼ソースURLありなら use_web_search=False で Web Search tool スキップ
    #   (検索しても同じ結論を返すため品質維持)
    # - KPJ_TEST_MODE 環境変数 (conftest.py 設定) でも skip
    #
    # 2026-07-21 (コスト削減): ここまでの安価な検査(本文長/サムネ/letterbox/meta/
    #   slug/ハングル残留 等)で既に BLOCK が確定している記事は、factcheck の結果に
    #   関わらず公開されない。にもかかわらず早期 return が無く factcheck(1コール
    #   約9円)を必ず呼んでいたため、7月実測で 813件/月 が丸損だった。
    #   verdict 決定(section 4)と同じ基準で「BLOCK 確定済みか」を先に判定して skip する。
    #   - draft は section 4 で block→warn に格下げされるので BLOCK 確定にはならない
    #   - content_short は kind 別に severity が変わるため同じ調整を適用してから判定
    _test_mode = os.environ.get('KPJ_TEST_MODE') == '1'
    _already_blocked = False
    if status != 'draft':
        for _i in issues:
            _sev = _i.get('severity')
            if _i.get('type') == 'content_short':
                _sev = 'warn' if kind in ('breaking', 'popup') else 'block'
            if _sev == 'block':
                _already_blocked = True
                break
    if _already_blocked:
        issues.append({
            'type': 'llm_factcheck_skipped_blocked',
            'severity': 'info',
            'detail': 'BLOCK確定済みのためLLM factcheckをskip (コスト削減)',
        })
    if (status == 'publish' and kind not in ('popup',) and not skip_llm_factcheck
            and not _test_mode and not _already_blocked):
        try:
            from lib.factcheck_v2 import proofread_post_v2
            from lib.source_domains import is_trusted_source
            fake_post = {'title': {'rendered': title or ''},
                         'content': {'rendered': body_html or ''}}
            # 2026-05-15: pre_publish では WP pid が無いため Layer 1 (pid_cache) が
            # 完全 skip され factcheck cost が膨らんでいた。source_url を pseudo-id
            # として渡し、同じ source を 24h 内に再 gate するケースを dedup する。
            # factcheck は「source の事実が正しいか」判定なので、translation 文体差を
            # 超えて同一 source = 同一判定で妥当。
            if source_url:
                fake_post['id'] = f'src:{source_url}'
            _trusted = bool(source_url) and is_trusted_source(source_url)
            pr = proofread_post_v2(fake_post, use_web_search=not _trusted)
        except Exception as _e_v2:
            # v2失敗時のみv1にフォールバック
            try:
                from pipeline.llm_proofreader import proofread_article
                pr = proofread_article(title or '', body_html or '')
            except ImportError:
                pr = None
            except Exception as e:
                issues.append({
                    'type': 'llm_factcheck_error',
                    'severity': 'warn',
                    'detail': f'LLM factcheck error: {str(e)[:60]}',
                })
                pr = None

        if pr:
            for c in pr.get('critical', []):
                issues.append({
                    'type': 'llm_factcheck_critical',
                    'severity': 'block',
                    'detail': str(c)[:100],
                })
            for h in pr.get('high', []):
                issues.append({
                    'type': 'llm_factcheck_high',
                    'severity': 'warn',  # highはWARN（BLOCKは壊滅レベルのcriticalのみ）
                    'detail': str(h)[:100],
                })

    # --- 3. audit_engine チェック (既存を再利用) ---
    # 各 check_* は list[dict] を返す
    audit_checks = [
        check_title(post_dict, criteria),
        check_slug(post_dict, criteria),
        check_featured_media(post_dict),
        check_content_quality(post_dict, criteria),
        check_meta_description(post_dict, criteria),
        check_internal_links(post_dict, criteria),
        check_category(post_dict, post_type),
    ]
    for check_result in audit_checks:
        issues.extend(_map_audit_issues(check_result))

    # --- 4. verdict 決定 ---

    # content_short の severity を kind 別に制御
    # breaking/popup: 短い本文は許容（翻訳ベース/イベント情報のため）→ WARN
    # feature/news: 短い本文は品質不足 → BLOCK
    for i in issues:
        if i.get('type') == 'content_short':
            if kind in ('breaking', 'popup'):
                i['severity'] = 'warn'
            else:
                i['severity'] = 'block'

    if status == 'draft':
        # draft は BLOCK しない — 全てWARNに格下げ
        for i in issues:
            if i['severity'] == 'block':
                i['severity'] = 'warn'

    block_issues = [i for i in issues if i['severity'] == 'block']
    warn_issues = [i for i in issues if i['severity'] == 'warn']

    if block_issues:
        verdict = 'BLOCK'
    elif warn_issues:
        verdict = 'WARN'
    else:
        verdict = 'PASS'

    result = {
        'verdict': verdict,
        'issues': issues,
        'block_reasons': [i['detail'] for i in block_issues],
        'warn_reasons': [i['detail'] for i in warn_issues],
    }

    # --- 5. ログ記録 ---
    try:
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        with open(_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                'ts': datetime.now(_JST).isoformat(),
                'title': (title or '')[:60],
                'kind': kind,
                'post_type': post_type,
                'status': status,
                'verdict': verdict,
                'block_count': len(block_issues),
                'warn_count': len(warn_issues),
                'issues': [{'type': i['type'], 'severity': i['severity']} for i in issues],
            }, ensure_ascii=False) + '\n')
    except Exception:
        pass

    return result
