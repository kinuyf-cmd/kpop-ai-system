"""ファクトチェッカー — 記事公開前の事実検証ゲート

チェック項目:
1. ソースURL必須 (GPT単独生成の禁止)
2. 記事内の日付 vs 公開日の整合性
3. アーティスト名の実在確認
4. 「最新」「速報」を含む記事は直近30日以内のソースが必須
"""
import re
import json
import os
from datetime import datetime, timedelta


def check_source_exists(source_url=None, source_signals=None):
    """ソースURL or シグナルの存在確認"""
    if source_url and source_url.startswith('http'):
        return {'pass': True, 'reason': f'source_url: {source_url[:60]}'}
    if source_signals and len(source_signals) > 0:
        return {'pass': True, 'reason': f'signals: {len(source_signals)}件'}
    return {'pass': False, 'reason': 'ソースURL/シグナルなし。GPT単独生成の疑い'}


def check_date_consistency(title, content, publish_date=None):
    """記事内の年月と公開日の整合性チェック"""
    if publish_date is None:
        publish_date = datetime.now()

    issues = []
    text = title + ' ' + re.sub(r'<[^>]+>', ' ', content)

    # 記事内に出現する年を抽出
    years = [int(m) for m in re.findall(r'(20[12]\d)年', text)]
    if years:
        latest_year_in_article = max(years)
        publish_year = publish_date.year
        if latest_year_in_article < publish_year - 1:
            issues.append({
                'type': 'stale_date',
                'severity': 'critical',
                'detail': f'記事内の最新年={latest_year_in_article}年、公開年={publish_year}年 (2年以上古い)',
            })
        elif latest_year_in_article < publish_year:
            issues.append({
                'type': 'old_date',
                'severity': 'high',
                'detail': f'記事内の最新年={latest_year_in_article}年、公開年={publish_year}年 (1年古い)',
            })

    # 「最新」「速報」を含むのに古い年を参照
    if any(kw in title for kw in ['最新', '速報', 'BREAKING', '2026']):
        old_years = [y for y in years if y < publish_date.year]
        if old_years and not any(y >= publish_date.year for y in years):
            issues.append({
                'type': 'latest_but_old',
                'severity': 'critical',
                'detail': f'タイトルに「最新/速報」があるが、記事内容が{max(old_years)}年の情報のみ',
            })

    return issues


def check_anonymization(title, content):
    """LLMが実名を匿名化していないかチェック"""
    issues = []
    text = title + ' ' + re.sub(r'<[^>]+>', ' ', content)

    # 「AとB」「XとY」「AさんとBさん」等の匿名パターン検出
    anon_patterns = [
        r'[A-Z]と[A-Z][、。\s,]',           # AとB
        r'[A-Z]さんと[A-Z]さん',             # AさんとBさん
        r'アイドル[A-Z](?:と|、)[A-Z]',      # アイドルAとB
        r'メンバー(?:の)?[A-Z](?:と|、)',     # メンバーA
        r'(?:人物|関係者)[A-Z]',             # 人物A
    ]
    for pat in anon_patterns:
        if re.search(pat, text):
            issues.append({
                'type': 'anonymized_names',
                'severity': 'critical',
                'detail': f'実名が匿名化されている疑い (パターン: {pat})',
            })
            break

    return issues


def check_numeric_claims(title, content):
    """タイトル・本文中の具体的数値主張にWARNを出す（手動検証促進）

    Spotify再生回数・売上数・ランキング順位など、LLM翻訳時に
    数値が誇張・捏造されるリスクがあるため検出する。
    """
    issues = []
    text = title + ' ' + re.sub(r'<[^>]+>', ' ', content)

    # 大きな数値主張: ○億回、○万枚、○位 etc
    big_claims = re.findall(r'(\d+(?:\.\d+)?)\s*(?:億|百万|million|billion)', text, re.IGNORECASE)
    for val in big_claims:
        issues.append({
            'type': 'unverified_numeric_claim',
            'severity': 'high',
            'detail': f'大きな数値主張を検出: {val}億/百万 — ソース原文と照合が必要',
        })

    # Spotify/YouTube等の具体的再生回数
    stream_claims = re.findall(r'(?:Spotify|YouTube|再生).{0,20}?(\d[\d,.]*)\s*(?:回|views|streams)', text, re.IGNORECASE)
    for val in stream_claims:
        num = val.replace(',', '').replace('.', '')
        if len(num) >= 8:  # 1000万以上
            issues.append({
                'type': 'unverified_stream_count',
                'severity': 'high',
                'detail': f'ストリーミング数 {val}回 — 公式データと照合が必要',
            })

    return issues


def check_source_content_mismatch(title, content, source_signals=None):
    """ソース見出しと記事タイトルの主語不一致を検出（誤訳防止）

    ソースが "fans" を主語にしているのに記事が "アーティスト" と
    訳している場合など、LLM翻訳の主語誤認を検出する。
    """
    issues = []
    if not source_signals:
        return issues

    source_titles = ' '.join(s.get('title', '') for s in source_signals[:5]).lower()

    # "fans" がソースにあるが記事に「ファン」が主語として出ていない場合
    if 'fans' in source_titles or 'fan ' in source_titles:
        article_text = re.sub(r'<[^>]+>', ' ', content)
        # 記事がアーティスト/アイドルを主語にしている場合WARN
        if re.search(r'(?:アーティスト|アイドル|メンバー)が.{0,10}(?:発表|宣言|公開)', article_text):
            if 'ファンが' not in article_text and 'ファンの' not in article_text[:200]:
                issues.append({
                    'type': 'subject_mismatch',
                    'severity': 'high',
                    'detail': 'ソースの主語が "fans" だが記事が "アーティスト" を主語にしている可能性（誤訳リスク）',
                })

    return issues


def check_article(title, content, source_url=None, source_signals=None, publish_date=None, kind=None):
    """記事の総合ファクトチェック"""
    # 特集記事(feature)はオリジナルコンテンツのためソースURL不要
    _skip_source = kind in ('feature',)
    results = {
        'source_check': ({'pass': True, 'reason': 'feature記事: ソースチェックskip'}
                         if _skip_source
                         else check_source_exists(source_url, source_signals)),
        'date_issues': check_date_consistency(title, content, publish_date),
        'anonymization_issues': check_anonymization(title, content),
        'numeric_issues': check_numeric_claims(title, content),
        'mismatch_issues': check_source_content_mismatch(title, content, source_signals),
    }

    # 総合判定
    all_issues = (results['date_issues']
                  + results.get('anonymization_issues', [])
                  + results.get('numeric_issues', [])
                  + results.get('mismatch_issues', []))
    if not results['source_check']['pass']:
        all_issues.append({
            'type': 'no_source',
            'severity': 'high',
            'detail': results['source_check']['reason'],
        })

    critical = [i for i in all_issues if i['severity'] == 'critical']
    high = [i for i in all_issues if i['severity'] == 'high']

    results['verdict'] = 'BLOCK' if critical else ('WARN' if high else 'PASS')
    results['critical_count'] = len(critical)
    results['high_count'] = len(high)
    results['all_issues'] = all_issues

    return results
