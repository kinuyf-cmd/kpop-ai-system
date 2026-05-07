"""統一公開前ゲート — 全パイプライン経路で WP POST 前に呼ぶ

BLOCKは壊滅レベル6種のみ。WARNを厚く。draft時はBLOCK不可。
既存の fact_checker / full_audit_engine のチェック関数を再利用し、ロジック重複なし。
"""
import re
import json
import os
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

# BLOCKすべきissue type（壊滅レベルのみ）
BLOCK_TYPES = frozenset({
    'content_empty',          # 本文 < 400字
    'content_short',          # 本文 < 1500字 (基準未満は公開不可)
    'no_source_no_signal',    # ソースなし (feature/popup除く)
    'anonymized_names',       # fact_checker critical: 実名匿名化
    'latest_but_old',         # fact_checker critical: 速報なのに古い
    'stale_date',             # fact_checker critical: 2年以上古い
    'ai_mention',             # ChatGPT/Claude等が本文に混入
    'review_contamination',   # レビューレポート/エラーメッセージ混入
    'no_artist_category',     # アーティストカテゴリ未設定
    'shop_no_practical_info', # 店舗紹介なのに住所/営業時間なし（架空店舗の疑い）
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


def _check_contamination(body_html):
    """レビューレポート/エラーメッセージ/Claudeメタ言及の混入検出"""
    issues = []
    text = re.sub(r'<[^>]+>', ' ', body_html or '')
    for pat in _CONTAMINATION_RE:
        m = pat.search(text)
        if m:
            issues.append({
                'type': 'review_contamination',
                'severity': 'block',
                'detail': f'本文にシステムメッセージ混入: "{m.group()[:50]}"',
            })
            break  # 1件見つかれば十分
    return issues


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


def pre_publish_gate(
    title, body_html, post_type='post', kind='news',
    source_url=None, source_signals=None, slug=None,
    featured_media=None, categories=None, excerpt=None,
    status='publish',
):
    """統一公開前ゲート

    Returns:
        {
            'verdict': 'BLOCK' | 'WARN' | 'PASS',
            'issues': list[dict],
            'block_reasons': list[str],
            'warn_reasons': list[str],
        }
    """
    issues = []
    post_dict = _build_post_dict(title, body_html, slug, featured_media, categories, excerpt)
    criteria = CRITERIA.get(post_type, CRITERIA['post'])

    # --- 1. 壊滅チェック (BLOCK候補) ---

    # 1a. 本文空チェック
    issues.extend(_check_content_empty(body_html))

    # 1a2. 店舗紹介記事の実用情報チェック (住所/営業時間なしはBLOCK)
    issues.extend(_check_shop_article_without_details(title, body_html))

    # 1b. ソースなし (feature/popup は除外)
    if kind not in ('feature', 'popup'):
        has_source = (source_url and source_url.startswith('http')) or \
                     (source_signals and len(source_signals) > 0)
        if not has_source:
            issues.append({
                'type': 'no_source_no_signal',
                'severity': 'block',
                'detail': 'ソースURL/シグナルなし。GPT単独生成の疑い',
            })

    # 1c. contamination
    issues.extend(_check_contamination(body_html))

    # 1c1. ハングル混入検査 (translate_ko_to_ja の訳し漏れ検出)
    # タイトル/altに1字でもBLOCK / 本文20字超でBLOCK / 5字超でWARN
    try:
        from lib.translation_residue_check import assess_residue
        _plain_for_hangul = re.sub(r'<[^>]+>', '', body_html or '')
        _alt_collected = ''
        for _m in re.finditer(r'<img[^>]*\salt=["\']([^"\']*)["\']', body_html or ''):
            _alt_collected += ' ' + _m.group(1)
        _residue = assess_residue(title or '', _plain_for_hangul, _alt_collected)
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
    except Exception:
        pass

    # 1d. AI mention 直接検出 (TYPO_PATTERNSの\bが日本語境界で不発のため補完)
    _plain = re.sub(r'<[^>]+>', ' ', body_html or '')
    if re.search(r'(?:ChatGPT|GPT-[34]|Claude\s*(?:Code|API)?|Anthropic)', _plain, re.IGNORECASE):
        issues.append({
            'type': 'ai_mention',
            'severity': 'block',
            'detail': '本文にAI/LLMツール名が混入',
        })

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
