#!/usr/bin/env python3
"""signal_validator.py — シグナル段階の品質ゲート (記事化前チェック)

3つのチェック:
  1. 鮮度ゲート: collected_at が MAX_AGE_DAYS 日超ならREJECT
  2. ソースURL存在確認: HTTP HEAD でステータス確認
  3. 日付抽出検証: ポップアップ/ライブの日時が抽出できなければWARN

Usage:
  from lib.signal_validator import validate_signal
  result = validate_signal(signal_dict)
  if result['reject']:
      print(f"REJECT: {result['reasons']}")
"""
import re
import urllib.request
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
MAX_AGE_DAYS = 30  # シグナル鮮度の上限
URL_CHECK_TIMEOUT = 10  # HTTP HEAD タイムアウト(秒)


def check_freshness(signal: dict) -> dict:
    """シグナルの鮮度チェック。MAX_AGE_DAYS超過ならreject"""
    collected = signal.get('collected_at', '')
    if not collected:
        return {'ok': False, 'reason': 'collected_at未設定'}

    try:
        # ISO形式のタイムスタンプをパース
        if '+' in collected or 'Z' in collected:
            dt = datetime.fromisoformat(collected.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(collected).replace(tzinfo=JST)
        age = datetime.now(JST) - dt.astimezone(JST)
        if age.days > MAX_AGE_DAYS:
            return {'ok': False, 'reason': f'鮮度超過: {age.days}日前 (上限{MAX_AGE_DAYS}日)'}
        return {'ok': True, 'age_days': age.days}
    except (ValueError, TypeError) as e:
        return {'ok': False, 'reason': f'collected_atパース失敗: {e}'}


def check_source_url(url: str) -> dict:
    """ソースURLがHTTP 200を返すか確認 (HEAD)"""
    if not url:
        return {'ok': False, 'reason': 'URLなし'}
    try:
        req = urllib.request.Request(url, method='HEAD', headers={
            'User-Agent': 'Mozilla/5.0 KPOPJournal-Validator/1.0'
        })
        resp = urllib.request.urlopen(req, timeout=URL_CHECK_TIMEOUT)
        code = resp.getcode()
        if code == 200:
            return {'ok': True, 'status': code}
        return {'ok': False, 'reason': f'HTTP {code}'}
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            # アクセス制限はURL自体は存在する
            return {'ok': True, 'status': e.code, 'note': 'アクセス制限あり'}
        return {'ok': False, 'reason': f'HTTP {e.code}'}
    except Exception as e:
        return {'ok': False, 'reason': f'接続エラー: {type(e).__name__}'}


def check_date_extractable(title: str) -> dict:
    """タイトルから日時情報が含まれるかチェック (WARN level)"""
    date_patterns = [
        r'\d{4}年\d{1,2}月',
        r'\d{1,2}月\d{1,2}日',
        r'\d{4}/\d{1,2}/\d{1,2}',
        r'\d{4}\.\d{1,2}\.\d{1,2}',
        r'GW|ゴールデンウィーク|夏|冬|春|秋',
        r'開催決定|開催中|期間限定',
    ]
    for pat in date_patterns:
        if re.search(pat, title):
            return {'ok': True, 'has_date_hint': True}
    return {'ok': True, 'has_date_hint': False, 'warn': '日時情報なし（本文から抽出を試行）'}


def validate_signal(signal: dict, check_url: bool = True) -> dict:
    """シグナル1件のバリデーション

    Args:
        signal: シグナル辞書 (url, title, collected_at等)
        check_url: ソースURL存在確認を実行するか (一括チェック時はFalseで高速化)

    Returns:
        {
            'reject': bool,      # Trueなら記事化禁止
            'warnings': list,    # 注意事項
            'reasons': list,     # reject理由
            'checks': dict,      # 各チェック結果
        }
    """
    result = {'reject': False, 'warnings': [], 'reasons': [], 'checks': {}}

    # 1. 鮮度チェック
    freshness = check_freshness(signal)
    result['checks']['freshness'] = freshness
    if not freshness['ok']:
        result['reject'] = True
        result['reasons'].append(freshness['reason'])

    # 2. ソースURL存在確認
    if check_url:
        url_check = check_source_url(signal.get('url', ''))
        result['checks']['source_url'] = url_check
        if not url_check['ok']:
            result['reject'] = True
            result['reasons'].append(f"ソースURL無効: {url_check['reason']}")

    # 3. 日付抽出チェック (WARNのみ、REJECTしない)
    date_check = check_date_extractable(signal.get('title', ''))
    result['checks']['date'] = date_check
    if date_check.get('warn'):
        result['warnings'].append(date_check['warn'])

    return result


def validate_signals_batch(signals: list, check_url: bool = False) -> dict:
    """シグナル一括バリデーション (URL確認はデフォルトOFF=高速)

    Returns:
        {
            'valid': list[dict],     # 通過したシグナル
            'rejected': list[dict],  # 除外されたシグナル + 理由
            'stats': {valid: N, rejected: N, warnings: N}
        }
    """
    valid = []
    rejected = []
    warn_count = 0

    for sig in signals:
        result = validate_signal(sig, check_url=check_url)
        if result['reject']:
            rejected.append({**sig, '_reject_reasons': result['reasons']})
        else:
            if result['warnings']:
                warn_count += 1
            valid.append(sig)

    return {
        'valid': valid,
        'rejected': rejected,
        'stats': {
            'valid': len(valid),
            'rejected': len(rejected),
            'warnings': warn_count,
        }
    }
