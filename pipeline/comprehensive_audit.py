#!/usr/bin/env python3
"""
総合監査 (comprehensive_audit.py) — 10:00 / 16:00 / 21:00 毎日実行
ファクトチェック + サムネイルチェック + 16項目監査 + 自動修正 + Discord報告

【処理フロー】
  1. 直近記事を取得 (post + popup)
  2. full_audit_engine で16項目監査 (サムネ含む)
  3. llm_proofreader でファクトチェック
  4. エラーがあれば:
     a. 原因追及 (issue typeとdetail分析)
     b. 修正 (audit_fixer_universal の自動修正 or Draft化)
     c. 再発防止 (error_patterns.json 登録)
  5. Discord報告 (原因, 修正内容/Draft化, 再発防止策, 1日のエラー件数と率)
"""
import sys
import os
import json
import re
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, '/home/aiuser/kpop-ai-system')

from lib.full_audit_engine import full_audit, fetch_posts, save_audit_state
from lib.discord_channel_router import send_to_channel, ChannelType

BASE = Path('/home/aiuser/kpop-ai-system')
JST = timezone(timedelta(hours=9))
AUDIT_STATE_PATH = BASE / 'data' / 'audit_state.jsonl'
ERROR_PATTERNS_PATH = BASE / 'config' / 'error_patterns.json'
DAILY_AUDIT_LOG = BASE / 'logs' / 'comprehensive_audit.jsonl'
LLM_AUDIT_DIR = BASE / 'logs' / 'llm_audit'

# 監査の時間帯ごとの遡及時間 (時間)
AUDIT_HOURS = {
    10: 14,  # 21時〜翌10時 (夜間+朝の記事)
    16: 6,   # 10時〜16時
    21: 5,   # 16時〜21時
}
DEFAULT_HOURS = 8


def get_audit_window_hours():
    """現在時刻に応じて遡及時間を決定"""
    now_hour = datetime.now(JST).hour
    return AUDIT_HOURS.get(now_hour, DEFAULT_HOURS)


def run_llm_factcheck(posts):
    """LLMファクトチェック — llm_proofreader.proofread_post を利用"""
    results = {}
    try:
        from pipeline.llm_proofreader import proofread_post, _already_proofread
        openai_key = os.getenv('OPENAI_API_KEY', '')
        if not openai_key:
            print("  [factcheck] OPENAI_API_KEY未設定、スキップ")
            return results

        for p in posts:
            pid = p['id']
            if _already_proofread(pid):
                continue
            try:
                r = proofread_post(p)
                nc = len(r.get('critical', []))
                nh = len(r.get('high', []))
                if nc > 0 or nh > 0:
                    results[pid] = {
                        'score': r.get('score', 0),
                        'critical': r.get('critical', []),
                        'high': r.get('high', []),
                        'medium': r.get('medium', []),
                    }
                    print(f"  [factcheck] id={pid} score={r.get('score',0)} C={nc} H={nh}")

                # Save to llm_audit directory
                LLM_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
                now = datetime.now(JST)
                out_file = LLM_AUDIT_DIR / f"{now.strftime('%Y%m%d_%H')}_{pid}.json"
                json.dump(r, open(out_file, 'w'), ensure_ascii=False, indent=2)

            except Exception as e:
                print(f"  [factcheck] id={pid} ERR: {e}")
    except ImportError as e:
        print(f"  [factcheck] import error: {e}")
    return results


def attempt_auto_fix(post_id, post_type, issues):
    """audit_fixer_universal のロジックで自動修正を試行"""
    try:
        from pipeline.audit_fixer_universal import (
            fetch_post, update_post, rewrite_with_gpt, FIXABLE_TYPES
        )
    except ImportError:
        return None, "auto_fix import失敗"

    fixable = [i for i in issues if i.get('type') in FIXABLE_TYPES]
    high_issues = [i for i in issues if i.get('severity') == 'high']

    if not fixable and len(high_issues) < 3:
        return None, "修正対象なし"

    post = fetch_post(post_id, post_type)
    if not post:
        return None, "記事取得失敗"

    # high 5件以上 → Draft化
    if len(high_issues) >= 5:
        try:
            update_post(post_id, post_type, {'status': 'draft'})
            return 'drafted', f"high={len(high_issues)}件でDraft化"
        except Exception as e:
            return 'draft_failed', str(e)

    # 修正可能な問題があれば GPT修正
    if fixable:
        try:
            new_content = rewrite_with_gpt(post, fixable, post_type)
            if new_content:
                update_post(post_id, post_type, {'content': new_content})
                return 'fixed', f"{len(fixable)}件修正"
            return None, "GPT修正結果なし"
        except Exception as e:
            return 'fix_failed', str(e)

    return None, "修正対象なし"


def try_fix_x_post(post_id, post_type, issues):
    """x_post_error / x_missing の自動修復: X投稿をリトライ"""
    x_issues = [i for i in issues if i.get('type') in ('x_post_error', 'x_missing')]
    if not x_issues:
        return None, "X問題なし"

    try:
        from lib.x_poster import post_tweet
        from lib.full_audit_engine import fetch_posts
    except ImportError:
        return None, "x_poster import失敗"

    # 記事のタイトルとURLを取得
    try:
        import urllib.request, base64
        auth = base64.b64encode(f"{os.getenv('WP_USER','')}:{os.getenv('WP_PASS','')}".encode()).decode()
        ep = 'posts' if post_type == 'post' else post_type
        url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{ep}/{post_id}?_fields=id,title,link,status"
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {auth}'})
        post = json.loads(urllib.request.urlopen(req, timeout=15).read())
        title = post.get('title', {}).get('rendered', '')
        link = post.get('link', '')
        if post.get('status') != 'publish':
            return None, "記事が非公開"
    except Exception as e:
        return None, f"記事取得失敗: {e}"

    if not title or not link:
        return None, "タイトル/URL不明"

    result = post_tweet(title, link, post_id=post_id)
    if result.get('success'):
        return 'fixed', f"X投稿リトライ成功 tid={result.get('tweet_id', '?')}"
    return None, f"X投稿リトライ失敗: {result.get('error', '')[:60]}"


def register_prevention(issue_type, detail, post_id):
    """再発防止策をerror_patterns.jsonに登録"""
    try:
        patterns = {}
        if ERROR_PATTERNS_PATH.exists():
            patterns = json.loads(ERROR_PATTERNS_PATH.read_text(encoding='utf-8'))

        key = issue_type
        if key not in patterns:
            patterns[key] = {
                'count': 0,
                'first_seen': datetime.now(JST).isoformat(),
                'last_seen': None,
                'example_post_ids': [],
                'prevention': _get_prevention_rule(issue_type),
            }

        patterns[key]['count'] = patterns[key].get('count', 0) + 1
        patterns[key]['last_seen'] = datetime.now(JST).isoformat()
        if post_id not in patterns[key].get('example_post_ids', []):
            patterns[key]['example_post_ids'] = (
                patterns[key].get('example_post_ids', []) + [post_id]
            )[-5:]  # 最新5件のみ保持

        ERROR_PATTERNS_PATH.write_text(
            json.dumps(patterns, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
    except Exception as e:
        print(f"  [prevention] err: {e}")


def _get_prevention_rule(issue_type):
    """issue typeに応じた再発防止策を返す"""
    rules = {
        'no_thumbnail': 'post_thumbnail_generator で自動生成。生成失敗時は DALL-E フォールバック',
        'ogp_image_artist_mismatch': 'thumbnail_source_resolver でアーティスト照合を強化',
        'content_short': 'LLM生成時の最低文字数指定を2000字以上に',
        'no_meta_description': 'unified_publisher でexcerpt自動生成を必須化',
        'meta_desc_short': 'excerpt生成プロンプトの最低文字数を80字に',
        'few_internal_links': 'post_publish_enricher で内部リンク2本以上を保証',
        'text_ai_mention': 'text_sanitizer のAIメンション除去パターン強化',
        'text_markdown_leak': 'text_sanitizer のMarkdownコードブロック検出強化',
        'llm_critical': 'LLMプロンプトにfact-check指示を追加。事実誤認検出時はDraft化',
        'llm_high': 'LLM校閲のhigh検出時にaudit_fixer_universalキューに追加',
        'slug_encoded': 'unified_publisher でslug生成時にASCII変換を必須化',
        'no_slug': 'unified_publisher でslug必須チェックを追加',
        'unclosed_h2': 'text_sanitizer でHTML閉じタグ検証を追加',
        'stale_date': 'LLMプロンプトに現在日付を必ず含める',
        'text_casual_greeting': 'text_sanitizer のカジュアル表現除去パターン拡充',
        'no_x_post': 'X投稿連動を必須化。失敗時はx_retry_queueに追加',
    }
    return rules.get(issue_type, f'{issue_type}: パターン分析して共通lib化で再発防止')


def count_daily_errors():
    """本日のエラー件数と率を集計"""
    today = datetime.now(JST).strftime('%Y-%m-%d')
    total_audited = 0
    error_posts = set()

    if AUDIT_STATE_PATH.exists():
        with open(AUDIT_STATE_PATH, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    ts = rec.get('audited_at', '')
                    if today not in ts:
                        continue
                    total_audited += 1
                    if rec.get('high_count', 0) > 0 or len(rec.get('issues', [])) > 0:
                        error_posts.add(rec.get('post_id'))
                except (json.JSONDecodeError, KeyError):
                    continue

    error_count = len(error_posts)
    error_rate = (error_count / total_audited * 100) if total_audited > 0 else 0
    return total_audited, error_count, error_rate


def build_discord_report(audit_results, factcheck_results, fix_actions,
                         total_audited, error_count, error_rate):
    """Discord報告メッセージを構築"""
    now = datetime.now(JST)
    time_label = now.strftime('%H:%M')

    # エラー記事のサマリー
    error_lines = []
    for pid, data in audit_results.items():
        issues = data.get('issues', [])
        if not issues:
            continue
        title = data.get('title', '')[:40]
        types = ', '.join(set(i.get('type', '?') for i in issues[:5]))
        fix = fix_actions.get(pid, {})
        fix_label = fix.get('action', '未修正')
        fix_detail = fix.get('detail', '')
        prevention = fix.get('prevention', '')

        line = (f"**[{pid}] {title}**\n"
                f"  原因: {types}\n"
                f"  対応: {fix_label} — {fix_detail}\n"
                f"  再発防止: {prevention}")
        error_lines.append(line)

    # ファクトチェック結果
    fc_lines = []
    for pid, fc in factcheck_results.items():
        crits = fc.get('critical', [])
        highs = fc.get('high', [])
        if crits or highs:
            fc_lines.append(
                f"  id={pid} score={fc.get('score',0)} "
                f"CRITICAL: {crits[:2]} HIGH: {highs[:2]}"
            )

    # 本文組み立て
    body_parts = [
        f"**{now.strftime('%Y-%m-%d')} {time_label} 総合監査レポート**\n",
        f"監査対象: {total_audited}件",
        f"エラー件数: **{error_count}件** (率: **{error_rate:.1f}%**)\n",
    ]

    if error_lines:
        body_parts.append("--- エラー詳細 ---")
        body_parts.extend(error_lines[:10])

    if fc_lines:
        body_parts.append("\n--- ファクトチェック ---")
        body_parts.extend(fc_lines[:5])

    if not error_lines and not fc_lines:
        body_parts.append("問題なし")

    body = '\n'.join(body_parts)
    return body


def main():
    from dotenv import load_dotenv
    load_dotenv(BASE / '.env')

    try:
        from lib.staff_task_manager import begin_task, end_task
        stf_id, tsk_id = "KPJ-0033", begin_task("KPJ-0033", "comprehensive_audit")
    except Exception:
        stf_id = tsk_id = None

    now = datetime.now(JST)
    print(f"=== 総合監査 {now.strftime('%Y-%m-%d %H:%M')} ===")

    hours = get_audit_window_hours()
    print(f"  遡及時間: {hours}時間")

    # 1. 記事取得
    all_posts = []
    for pt in ['post', 'popup']:
        posts = fetch_posts(pt, hours=hours, per_page=50)
        for p in posts:
            p['_post_type'] = pt
        all_posts.extend(posts)
    print(f"  取得: {len(all_posts)}件")

    # 2. full_audit (16項目 + サムネイルチェック)
    audit_results = {}
    by_severity = {'high': 0, 'medium': 0, 'low': 0}
    by_type = {}

    for p in all_posts:
        pid = p['id']
        pt = p.get('_post_type', 'post')
        title = p['title']['rendered'] if isinstance(p['title'], dict) else p['title']
        issues = full_audit(p, pt)
        save_audit_state(pid, pt, issues)

        audit_results[pid] = {
            'title': title,
            'post_type': pt,
            'issues': issues,
        }

        for i in issues:
            sev = i.get('severity', 'low')
            by_severity[sev] = by_severity.get(sev, 0) + 1
            by_type[i['type']] = by_type.get(i['type'], 0) + 1

        if issues:
            types_str = ', '.join(i['type'] for i in issues[:5])
            print(f"  [{pid}] {title[:35]}: {len(issues)}件 ({types_str})")

    print(f"\n  severity: H={by_severity['high']} M={by_severity['medium']} L={by_severity['low']}")

    # 3. LLMファクトチェック
    print("\n--- ファクトチェック ---")
    factcheck_results = run_llm_factcheck(all_posts)

    # ファクトチェック結果もaudit_resultsにマージ
    for pid, fc in factcheck_results.items():
        if pid in audit_results:
            for c in fc.get('critical', []):
                audit_results[pid]['issues'].append({
                    'type': 'llm_critical', 'severity': 'high', 'detail': c
                })
            for h in fc.get('high', []):
                audit_results[pid]['issues'].append({
                    'type': 'llm_high', 'severity': 'high', 'detail': h
                })

    # 4. エラー修正 + 再発防止
    print("\n--- 修正・再発防止 ---")
    fix_actions = {}
    error_posts = {pid: d for pid, d in audit_results.items() if d.get('issues')}

    for pid, data in error_posts.items():
        issues = data['issues']
        pt = data['post_type']

        # 自動修正を試行
        action, detail = attempt_auto_fix(pid, pt, issues)

        # X投稿問題の修復（attempt_auto_fixで対応できない場合）
        x_types = {i.get('type') for i in issues} & {'x_post_error', 'x_missing'}
        if x_types and action != 'fixed':
            x_action, x_detail = try_fix_x_post(pid, pt, issues)
            if x_action == 'fixed':
                action = action or 'fixed'
                detail = f"{detail}; {x_detail}" if detail and detail != "修正対象なし" else x_detail

        prevention_rules = []

        # 再発防止策をerror_patternsに登録
        for i in issues:
            itype = i.get('type', 'unknown')
            register_prevention(itype, i.get('detail', ''), pid)
            prevention_rules.append(_get_prevention_rule(itype))

        # ユニーク化
        prevention_rules = list(dict.fromkeys(prevention_rules))[:3]

        fix_actions[pid] = {
            'action': action or '要手動確認',
            'detail': detail,
            'prevention': ' / '.join(prevention_rules),
        }

        action_label = action or '未修正'
        print(f"  [{pid}] {action_label}: {detail}")

    # 5. 1日のエラー件数と率を集計
    daily_total, daily_errors, daily_rate = count_daily_errors()

    # 6. Discord報告
    print("\n--- Discord報告 ---")
    report_body = build_discord_report(
        error_posts, factcheck_results, fix_actions,
        daily_total, daily_errors, daily_rate
    )

    severity = "CRITICAL" if by_severity['high'] > 0 else "WARNING" if error_posts else ""
    if error_posts or factcheck_results:
        title = f"総合監査 {now.strftime('%H:%M')} | エラー{daily_errors}件 ({daily_rate:.1f}%)"
        results = send_to_channel(
            ChannelType.ALERT, title, report_body,
            severity=severity or "WARNING"
        )
        for r in results:
            print(f"  Discord [{r['physical_channel']}]: {r['result']}")
    else:
        title = f"総合監査 {now.strftime('%H:%M')} | 問題なし"
        results = send_to_channel(
            ChannelType.DAILY_REPORT, title, report_body
        )
        for r in results:
            print(f"  Discord [{r['physical_channel']}]: {r['result']}")

    # 7. ログ保存
    DAILY_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    log_entry = {
        'timestamp': now.isoformat(),
        'hours': hours,
        'total_posts': len(all_posts),
        'error_posts': len(error_posts),
        'by_severity': by_severity,
        'top_types': dict(sorted(by_type.items(), key=lambda x: -x[1])[:10]),
        'factcheck_issues': len(factcheck_results),
        'fixes_attempted': {k: v['action'] for k, v in fix_actions.items()},
        'daily_total': daily_total,
        'daily_errors': daily_errors,
        'daily_error_rate': round(daily_rate, 1),
    }
    with open(DAILY_AUDIT_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

    print(f"\n=== 完了 | 本日累計: {daily_errors}/{daily_total}件 ({daily_rate:.1f}%) ===")

    if stf_id and tsk_id:
        try:
            end_task(stf_id, tsk_id, "success")
        except Exception:
            pass


if __name__ == '__main__':
    main()
