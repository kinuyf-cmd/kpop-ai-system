#!/usr/bin/env python3
"""
pre_publish_hook.py — 記事公開前品質ゲート
Phase2監査で発覚した問題の再発を防止する最終防衛ライン。

Usage:
  # パイプラインから呼び出し（公開前チェック）
  from pipeline.pre_publish_hook import pre_publish_check, PublishBlockedError
  try:
      result = pre_publish_check(post_data)
  except PublishBlockedError as e:
      # 公開ブロック → draft保存 + Discord通知
      ...

  # CLIテスト（WPの既存記事をチェック）
  python3 pipeline/pre_publish_hook.py --post-id 3045
  python3 pipeline/pre_publish_hook.py --test-all
"""
import re
import json
import os
import sys
import argparse
import subprocess
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

# Track C: AI語尾排除
try:
    from pipeline.post_write_sanitize import check_ai_phrases
except ImportError:
    # フォールバック: 相対インポート
    try:
        from post_write_sanitize import check_ai_phrases
    except ImportError:
        check_ai_phrases = None
LOGS = BASE / "logs"
JST = timezone(timedelta(hours=9))


class PublishBlockedError(Exception):
    """公開がブロックされた場合に発生"""
    def __init__(self, issues: dict):
        self.issues = issues
        super().__init__(json.dumps(issues, ensure_ascii=False))


def check_content_quality(content: str, title: str = "") -> tuple[list, list]:
    """本文・タイトルの品質チェック"""
    critical = []
    warnings = []

    # 1. \n リテラル残存
    if '\\n' in content:
        count = content.count('\\n')
        critical.append(f'\\n literal in content ({count} occurrences)')
    if '\\n' in title:
        critical.append('\\n literal in title')

    # 2. テンプレート残骸
    template_matches = re.findall(r'\{\{[^}]*\}\}|\}\}', content)
    if template_matches:
        critical.append(f'Template fragment: {template_matches[:3]}')

    # 3. JSON フラグメント混入
    if re.search(r'\{"[a-z_]+"\s*:', content):
        critical.append('JSON fragment detected in content')

    # 4. AdSense過剰（WP content内に広告を入れるべきでない）
    ad_count = content.count('adsbygoogle')
    if ad_count > 0:
        warnings.append(f'AdSense blocks in content: {ad_count} (frontend handles ads)')

    # 5. 重複文検出
    plain = re.sub(r'<[^>]+>', '', content)
    sentences = re.split(r'[。！？\n]', plain)
    counter = Counter(s.strip() for s in sentences if len(s.strip()) > 20)
    duplicates = [(s, c) for s, c in counter.items() if c >= 3]
    if duplicates:
        critical.append(f'Duplicate sentences: {len(duplicates)} types (e.g. "{duplicates[0][0][:40]}..." x{duplicates[0][1]})')

    # 6. HTMLエンティティ残存（タイトル内）
    if re.search(r'&#\d+;', title):
        critical.append(f'HTML entity in title: {re.findall(r"&#d+;", title)}')

    # 7. 文字化け U+FFFD
    if '\ufffd' in content:
        critical.append(f'Mojibake (U+FFFD) detected: {content.count(chr(0xFFFD))} occurrences')

    # 8. 本文が極端に短い
    plain_len = len(plain)
    if plain_len < 500:
        critical.append(f'Content too short: {plain_len} chars (min 500)')
    elif plain_len < 1000:
        warnings.append(f'Content short: {plain_len} chars')

    # 9. プレースホルダー残存
    placeholders = ['ここに本文', 'PLACEHOLDER', '[TODO]', 'FIXME', 'Lorem ipsum', '記事本文をここに']
    for ph in placeholders:
        if ph in content:
            critical.append(f'Placeholder text: {ph}')

    # 10. テンプレ変数 {{xxx}} 検出（CRITICAL）
    template_vars = re.findall(r'\{\{[^}]+\}\}', content + title)
    if template_vars:
        critical.append(f'Unresolved template variables: {template_vars[:5]}')

    # 11. LLM出力残骸検出（CRITICAL）— ファクトチェック/修正メタテキスト混入防止
    llm_residue_patterns = [
        r'\*\*主?な?修正箇所[:：]?\*\*',
        r'\*\*変更点[:：]?\*\*',
        r'修正後の本文を以下に出力',
        r'以下、修正後の本文です',
        r'ファクトチェック結果をまとめます',
        r'以下の問題を発見しました',
        # Phase 5 新規追加パターン
        r'ChatGPTとして',
        r'AIアシスタントとして',
        r'以下に修正案を',
        r'修正しました[。！]',
        r'### 修正箇所',
        r'## 変更点',
        r'お手伝いします',
        r'ご質問があれば',
    ]
    for pat in llm_residue_patterns:
        if re.search(pat, plain):
            critical.append(f'LLM output residue: matched "{pat}"')

    # 12. 内部タグ漏れ検出（CRITICAL）— LLMの制御トークン混入防止
    internal_tag_patterns = [
        r'<\|im_end\|>',
        r'<\|im_start\|>',
        r'<\|endoftext\|>',
        r'<\|system\|>',
        r'<\|user\|>',
        r'<\|assistant\|>',
        r'\[INST\]',
        r'\[/INST\]',
        r'<<SYS>>',
    ]
    for pat in internal_tag_patterns:
        if re.search(pat, content):
            critical.append(f'Internal LLM tag leaked: matched "{pat}"')

    # 13. 途中で切れた文章検出（WARNING）
    if plain and len(plain) > 500:
        last_200 = plain[-200:].strip()
        if last_200 and last_200[-1] not in '。！？」』）…♪\n' and not last_200.endswith('</'):
            if not re.search(r'[。！？」』）…♪]$', last_200):
                warnings.append(f'Content may be truncated: ends with "{last_200[-30:]}"')

    # 14. 不自然なAI生成文パターン（WARNING）— 頻出52件
    ai_gen_patterns = [
        r'(?:とても|非常に|大変)(?:とても|非常に|大変)',  # 副詞重複
        r'([^。]{5,})[。！？]\1',  # 同一文の直後繰り返し
    ]
    for pat in ai_gen_patterns:
        if re.search(pat, plain):
            warnings.append(f'Possible AI-generated text pattern: "{pat}"')

    # 15. 本文品質スコアチェック（overall_score < 80 → CRITICAL）
    # This is checked externally via proofread results when available

    # 16. h2見出し不足チェック（Phase 7 追加）
    h2_count = len(re.findall(r'<h2[^>]*>', content, re.IGNORECASE))
    if h2_count < 2:
        critical.append(f'h2不足: {h2_count}本（最低2本必要）')
    elif h2_count < 4:
        warnings.append(f'h2少なめ: {h2_count}本（推奨4本以上）')

    # 17. 内部リンク不足チェック（Phase 7 追加）
    internal_links = re.findall(r'<a\s+[^>]*href=["\']https?://(?:www\.)?kpopjournal\.tokyo[^"\']*["\']', content, re.IGNORECASE)
    if len(internal_links) == 0:
        critical.append(f'内部リンク不足: 0本（最低1本必要）')
    elif len(internal_links) < 2:
        warnings.append(f'内部リンク少なめ: {len(internal_links)}本（推奨2本以上）')

    return critical, warnings


def check_thumbnail_text(thumb_text: str, article_title: str) -> tuple[list, list]:
    """サムネイルテキストの品質チェック（画像生成前）"""
    critical = []
    warnings = []

    if not thumb_text:
        warnings.append('No thumbnail text provided')
        return critical, warnings

    # \n リテラル
    if '\\n' in thumb_text or '\n' in thumb_text:
        critical.append(f'\\n in thumbnail text: {repr(thumb_text)}')

    # JSON フラグメント
    if re.search(r'[{}"\\]', thumb_text):
        critical.append(f'JSON/special chars in thumbnail text: {repr(thumb_text)}')

    # テキスト長（25文字超は切り詰め推奨）
    if len(thumb_text) > 30:
        warnings.append(f'Thumbnail text too long: {len(thumb_text)} chars')

    return critical, warnings


def pre_publish_check(post_data: dict) -> dict:
    """
    記事公開前の総合品質ゲート。

    Args:
        post_data: {
            'content': str,         # 記事本文HTML
            'title': str,           # 記事タイトル
            'thumbnail_text': str,  # サムネイルに焼き込むテキスト（任意）
            'featured_image_url': str,  # サムネイルURL（任意）
        }

    Returns:
        {'status': 'passed', 'warnings': [...]}

    Raises:
        PublishBlockedError: CRITICAL問題がある場合
    """
    content = post_data.get('content', '')
    title = post_data.get('title', '')
    thumb_text = post_data.get('thumbnail_text', '')
    thumbnail_score = post_data.get('thumbnail_score', None)
    overall_score = post_data.get('overall_score', None)

    all_critical = []
    all_warnings = []

    # 本文チェック
    c, w = check_content_quality(content, title)
    all_critical.extend(c)
    all_warnings.extend(w)

    # サムネイルテキストチェック
    if thumb_text:
        c, w = check_thumbnail_text(thumb_text, title)
        all_critical.extend(c)
        all_warnings.extend(w)

    # サムネイル品質スコアチェック（Vision APIスコア < 6 → CRITICAL）
    if thumbnail_score is not None and thumbnail_score < 6:
        all_critical.append(f'Thumbnail quality too low: score={thumbnail_score}/10 (min 6)')

    # サムネイル文字焼き込み検出（Phase 5 新規・最重要）
    # text_count > 2 は「意図しない文字焼き込み」として BLOCK
    thumbnail_text_count = post_data.get('thumbnail_text_count', None)
    if thumbnail_text_count is not None and thumbnail_text_count > 2:
        all_critical.append(f'Thumbnail has burned-in text: text_count={thumbnail_text_count} (max 2)')

    # 本文品質スコアチェック（overall_score < 80 → CRITICAL）
    if overall_score is not None and overall_score < 80:
        all_critical.append(f'Content quality too low: score={overall_score}/100 (min 80)')

    # 事実誤認フラグ（LLM判定、WARNING）
    fact_issues = post_data.get('fact_check_issues', [])
    if fact_issues:
        all_warnings.append(f'Possible fact issues: {len(fact_issues)} detected')

    # Track C: AI語尾排除チェック（WARNING、BLOCKERではない）
    if check_ai_phrases is not None and content:
        ai_result = check_ai_phrases(content)
        if ai_result['status'] != 'PASS':
            all_warnings.append(
                f'AI語尾検出 [{ai_result["status"]}]: '
                f'{ai_result["total_detected"]}個 '
                f'({", ".join(d["phrase"] for d in ai_result["detected"][:5])})'
            )
        if ai_result.get('warnings'):
            for w in ai_result['warnings']:
                all_warnings.append(f'AI sanitize: {w}')

    # Phase 10: 禁止タイトルパターン検出（考察記事氾濫抑制 — CRITICAL=公開ブロック）
    _BANNED_TITLE_PATTERNS = [
        r'の全貌', r'徹底解剖', r'\d+つの伏線', r'完全解説',
        r'の真相', r'衝撃の', r'必見', r'【保存版】',
        r'〜って知ってる', r'〜のすべて', r'ヤバい',
    ]
    if title:
        _matched_bans = [p for p in _BANNED_TITLE_PATTERNS if re.search(p, title)]
        if _matched_bans:
            all_critical.append(f'禁止タイトルパターン(考察記事): {_matched_bans} — タイトル書き換え必須')

    # ログ記録
    log_entry = {
        'timestamp': datetime.now(JST).isoformat(),
        'title': title[:80],
        'critical': all_critical,
        'warnings': all_warnings,
        'verdict': 'BLOCK' if all_critical else 'PASS',
    }
    log_path = LOGS / "pre_publish_hook.jsonl"
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

    if all_critical:
        raise PublishBlockedError({
            'critical': all_critical,
            'warnings': all_warnings,
        })

    return {'status': 'passed', 'warnings': all_warnings}


def notify_discord(message: str):
    """Discord通知（既存の通知機構を流用）"""
    notify_script = BASE / "kpop_notify.sh"
    if notify_script.exists():
        try:
            subprocess.run(
                ['bash', str(notify_script), 'error', 'pre_publish_hook', message],
                timeout=10, capture_output=True
            )
        except Exception:
            pass


# ===== CLI =====
def _test_wp_post(post_id: int):
    """既存WP記事をテスト"""
    import requests
    env = {}
    env_path = BASE / '.env'
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                env[k] = v.strip().strip('"').strip("'")

    auth = (env['WP_USER'], env['WP_PASS'])
    wp = 'https://www.kpopjournal.tokyo/wp-json/wp/v2'

    r = requests.get(f'{wp}/posts/{post_id}', auth=auth,
                     params={'context': 'edit'}, timeout=30)
    if r.status_code != 200:
        print(f"Failed to fetch post {post_id}: HTTP {r.status_code}")
        return

    post = r.json()
    title = post['title']['raw']
    content = post['content']['raw']

    print(f"Testing post ID={post_id}: {title[:60]}")
    print("-" * 60)

    try:
        result = pre_publish_check({'content': content, 'title': title})
        print(f"RESULT: PASS")
        if result['warnings']:
            for w in result['warnings']:
                print(f"  WARNING: {w}")
    except PublishBlockedError as e:
        issues = e.issues
        print(f"RESULT: BLOCKED")
        for c in issues['critical']:
            print(f"  CRITICAL: {c}")
        for w in issues.get('warnings', []):
            print(f"  WARNING: {w}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pre-publish quality gate')
    parser.add_argument('--post-id', type=int, help='Test a specific WP post')
    parser.add_argument('--test-all', action='store_true', help='Test all recent posts')
    args = parser.parse_args()

    if args.post_id:
        _test_wp_post(args.post_id)
    elif args.test_all:
        import requests
        env = {}
        with open(BASE / '.env') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    env[k] = v.strip().strip('"').strip("'")
        auth = (env['WP_USER'], env['WP_PASS'])
        wp = 'https://www.kpopjournal.tokyo/wp-json/wp/v2'
        r = requests.get(f'{wp}/posts', auth=auth, timeout=30,
                         params={'per_page': 10, 'context': 'edit', 'status': 'publish'})
        posts = r.json()
        blocked = 0
        for post in posts:
            pid = post['id']
            try:
                pre_publish_check({'content': post['content']['raw'], 'title': post['title']['raw']})
                print(f"  PASS  ID={pid} {post['title']['raw'][:50]}")
            except PublishBlockedError as e:
                blocked += 1
                print(f"  BLOCK ID={pid} {e.issues['critical'][0][:60]}")
        print(f"\nTotal: {len(posts)} tested, {blocked} would be blocked")
    else:
        parser.print_help()
