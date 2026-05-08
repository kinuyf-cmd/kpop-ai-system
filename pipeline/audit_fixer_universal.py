#!/usr/bin/env python3
"""audit_state.jsonl から修正対象を読み、自動修正実行 (post + popup共通)"""
import sys, os, json, re, urllib.request, base64
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

SKIP_LIST_PATH = '/home/aiuser/kpop-ai-system/data/audit_fixer_skip.json'
MAX_REWRITE_ATTEMPTS = 3

WP_USER = os.getenv('WP_USER', '')
WP_PASS = os.getenv('WP_PASS', '')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()

FIXABLE_TYPES = {
    'text_ai_mention', 'text_meta_phrase', 'text_markdown_leak',
    'text_casual_greeting', 'text_casual_question', 'text_salesy_ending',
    'text_salesy_cta', 'text_broken_sentence', 'text_empty_tag',
    'text_repeated_char', 'text_casual_address', 'text_monotonous_ending',
    'unclosed_h2', 'unclosed_p',
    'content_short', 'few_internal_links',
    'slug_encoded',
    'meta_desc_short', 'no_meta_description',
    'no_artist_category',  # 2026-05-01追加: カテゴリ自動検出・設定
}


def fetch_post(post_id, post_type):
    endpoint = 'posts' if post_type == 'post' else post_type
    url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}/{post_id}?_embed=true"
    try:
        req = urllib.request.Request(url, headers={'Authorization': f'Basic {AUTH}'})
        return json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        print(f"  fetch err: {e}")
        return None


def _is_factcheck_blocked(post_id):
    """捏造/架空でdraft化された記事のpublish復帰を防止"""
    blocked_path = '/home/aiuser/kpop-ai-system/data/factcheck_blocked.json'
    try:
        with open(blocked_path) as f:
            data = json.load(f)
        return post_id in data.get('blocked_ids', [])
    except Exception:
        return False


def update_post(post_id, post_type, payload):
    # 捏造ブロックリストの記事にstatusをpublishに変更する操作をブロック
    if _is_factcheck_blocked(post_id) and payload.get('status') == 'publish':
        print(f"  [{post_id}] BLOCKED: 捏造/架空でdraft化済み。publish復帰禁止")
        return False
    endpoint = 'posts' if post_type == 'post' else post_type
    url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/{endpoint}/{post_id}"
    body = json.dumps(payload).encode()
    try:
        req = urllib.request.Request(url, data=body, method='POST',
            headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=30)
        return True
    except Exception as e:
        print(f"  update err: {e}")
        return False


def _extract_balanced_div(content, class_name):
    """指定class名の<div>から開始し、対応する閉じdivまでを抽出。

    nested <div>のカウントをトラックして balanced match を返す。
    Returns: list of matched HTML strings.
    """
    matches = []
    pattern = re.compile(r'<div\s+class="' + re.escape(class_name) + r'"[^>]*>')
    for m in pattern.finditer(content):
        start = m.start()
        depth = 1
        i = m.end()
        while i < len(content) and depth > 0:
            nxt_open = content.find('<div', i)
            nxt_close = content.find('</div>', i)
            if nxt_close == -1:
                break
            if nxt_open != -1 and nxt_open < nxt_close:
                depth += 1
                i = nxt_open + 4
            else:
                depth -= 1
                i = nxt_close + 6
        if depth == 0:
            matches.append(content[start:i])
    return matches


def _extract_preserved_blocks(content):
    """内部リンク/CTA/プロフィール等の構造ブロックをcontentから抜き出す。

    GPT書き直し時に失われないよう、書き直し対象は本文部分のみとし、
    これらのブロックはそのまま末尾に再付与する。
    Returns: (main_content, preserved_blocks_html)
    """
    preserved = []
    main = content
    # CTA / プロフィール: balanced-div抽出
    for cls in ('kpj-cta-block', 'kpj-artist-profile'):
        for blk in _extract_balanced_div(main, cls):
            preserved.append(blk)
            main = main.replace(blk, '', 1)
    # 関連記事段落: <p>関連記事:...</p>
    for p in re.findall(r'<p>関連記事:\s*<a[^>]*kpopjournal\.tokyo[\s\S]*?</p>', main):
        preserved.append(p)
        main = main.replace(p, '', 1)
    # 関連記事 section: <section class="related-articles">...</section>
    for s in re.findall(r'<section class="related-articles"[\s\S]*?</section>', main):
        preserved.append(s)
        main = main.replace(s, '', 1)
    return main, '\n'.join(preserved)


def rewrite_with_gpt(post, issues, post_type):
    """GPT-4o-miniで本文修正"""
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        return None

    title = post.get('title', {}).get('rendered', '') if isinstance(post.get('title'), dict) else ''
    content = post.get('content', {}).get('rendered', '') if isinstance(post.get('content'), dict) else ''
    issue_types = list(set(i['type'] for i in issues if i['type'] in FIXABLE_TYPES))

    # 2026-05-08: 構造ブロック保護(18781の内部リンク6→0剥離事案修正)
    main_content, preserved_html = _extract_preserved_blocks(content)

    if post_type == 'popup':
        structure = """必須h2: イベント概要/開催詳細/特典・限定アイテム/アクセス
末尾必須: <p class="kpj-disclaimer">※情報は変更になる場合があります。最新情報は公式SNSをご確認ください。</p>"""
    else:
        structure = "リード→詳細→まとめ三段構成、h2見出し2つ以上"

    # 記事種別判定（ビジュアル要素挿入用）
    is_popup = post_type == 'popup'
    is_artist = bool(re.search(
        r'BTS|BLACKPINK|TWICE|aespa|NewJeans|IVE|LE SSERAFIM|Stray Kids|SEVENTEEN|ENHYPEN|'
        r'NMIXX|ITZY|TXT|EXO|BABYMONSTER|RIIZE|ILLIT|NCT|Red Velvet|BIGBANG|SHINee|'
        r'GOT7|\(G\)I-DLE|ATEEZ|TREASURE|MONSTA X|DAY6|2PM',
        title, re.IGNORECASE
    ))

    visual_instructions = """
【ビジュアル要素の挿入ルール】
- 重要な事実やデータは <div class="kpj-info-box">...</div> で囲む（開催日時、メンバー情報、数字データ等）
- 特に注目すべい引用・統計は <div class="kpj-highlight">...</div> で囲む
- 比較やリスト形式のデータは <table> を使用（<th>ヘッダー必須）
- 画像が欲しい箇所にプレースホルダーを挿入: <!-- IMAGE: 画像の説明 -->"""

    if is_popup:
        visual_instructions += """
- 会場情報がある場合: <!-- MAP: 会場名, 住所 --> を挿入（1記事に1つまで）"""
    if is_artist:
        visual_instructions += """
- アーティストのMV/パフォーマンス映像の参考として: <!-- YOUTUBE: アーティスト名 MV --> を挿入（1記事に1つまで）"""

    prompt = f"""以下のK-POP記事を問題を解消した自然な記事に書き直してください。

【タイトル】{title}
【現在の本文】{main_content[:2500]}
【検出問題】{', '.join(issue_types)}

【修正要件】
- 「以上です」「いかがでしょうか」「お楽しみに」「皆さん」等の蛇足削除
- AI/ChatGPT/Claude等メタ言及完全除去
- HTMLタグ閉じ修正
- 文末バリエーション (同じ語尾3連続禁止)
- 内部リンク2本: <a href="https://www.kpopjournal.tokyo/category/news/">最新ニュース</a> 等
- {structure}
- 800-1200字
{visual_instructions}

【出力】HTML本文のみ。セクション識別子ラベル（リード文:, 導入文:, 本文: 等）は含めないこと"""

    from lib.agent_learning_loop import inject_lessons_to_prompt
    prompt = inject_lessons_to_prompt('unknown', prompt)

    body = json.dumps({
        'model': 'gpt-4o-mini',
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.6,
        'max_tokens': 2000,
    }).encode()

    try:
        req = urllib.request.Request('https://api.openai.com/v1/chat/completions',
            data=body, headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
        r = json.loads(urllib.request.urlopen(req, timeout=90).read())
        result = r['choices'][0]['message']['content'].strip()
        # コードブロック除去 (複数パターン対応)
        result = re.sub(r'```html\s*\n?', '', result, flags=re.IGNORECASE)
        result = re.sub(r'\n?```\s*$', '', result)
        result = re.sub(r'^```\s*\n', '', result)
        # markdown見出しリーク対応
        result = re.sub(r'^##\s+(.+?)$', r'<h2>\1</h2>', result, flags=re.MULTILINE)
        result = re.sub(r'^###\s+(.+?)$', r'<h3>\1</h3>', result, flags=re.MULTILINE)
        # 保護ブロック(CTA/プロフィール/関連記事)を末尾に再付与
        if preserved_html:
            result = result.strip() + '\n\n' + preserved_html
        return result.strip()
    except Exception as e:
        print(f"  GPT err: {e}")
        return None


def generate_meta_description(post):
    content = post.get('content', {}).get('rendered', '') if isinstance(post.get('content'), dict) else ''
    plain = re.sub(r'<[^>]+>', '', content).strip()
    plain = re.sub(r'\s+', ' ', plain)
    if len(plain) > 150:
        m = re.search(r'^(.{80,150}?[。!?])', plain)
        if m:
            return m.group(1)
        return plain[:140] + '...'
    return plain[:150]


def _load_already_fixed():
    """audit_fixed.jsonl からリライト済みpost_idを取得"""
    fixed_path = '/home/aiuser/kpop-ai-system/logs/audit_fixed.jsonl'
    already = {}  # post_id -> count
    if os.path.exists(fixed_path):
        with open(fixed_path, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    pid = d.get('post_id')
                    if pid:
                        already[pid] = already.get(pid, 0) + 1
                except:
                    pass
    return already


def _load_skip_list():
    """永続スキップリストを読み込む (post_id -> {reason, skipped_at, attempts})"""
    if os.path.exists(SKIP_LIST_PATH):
        try:
            with open(SKIP_LIST_PATH, encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_skip_list(skip_list):
    """永続スキップリストを保存"""
    os.makedirs(os.path.dirname(SKIP_LIST_PATH), exist_ok=True)
    with open(SKIP_LIST_PATH, 'w', encoding='utf-8') as f:
        json.dump(skip_list, f, ensure_ascii=False, indent=2)


def _record_attempt(skip_list, post_id, issue_types):
    """リライト試行を記録し、上限超えならスキップリストに追加。Trueならスキップ対象"""
    pid_key = str(post_id)
    entry = skip_list.get(pid_key, {'attempts': 0, 'issues': [], 'skipped': False})
    entry['attempts'] = entry.get('attempts', 0) + 1
    entry['issues'] = issue_types
    entry['last_attempt'] = datetime.now(timezone.utc).isoformat()
    if entry['attempts'] >= MAX_REWRITE_ATTEMPTS:
        entry['skipped'] = True
        entry['skipped_at'] = datetime.now(timezone.utc).isoformat()
        entry['reason'] = f"{MAX_REWRITE_ATTEMPTS}回リライト試行後も未解決"
    skip_list[pid_key] = entry
    return entry.get('skipped', False)


# content_short はGPTリライトでは解決できない（ソース情報不足）
# GPTリライト対象から除外し、別のアプローチ（手動補強）に回す
GPT_REWRITE_TYPES = FIXABLE_TYPES - {'content_short', 'no_artist_category'}


def main(max_fixes=30):
    try:
        from lib.staff_task_manager import begin_task, end_task as _end_task
        _STF_ID, _TSK_ID = "KPJ-0034", begin_task("KPJ-0034", "audit_fixer_universal")
    except: _STF_ID = _TSK_ID = None
    audit_log = '/home/aiuser/kpop-ai-system/data/audit_state.jsonl'
    if not os.path.exists(audit_log):
        print("audit_state.jsonl なし")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    already_fixed = _load_already_fixed()
    skip_list = _load_skip_list()
    skipped_count = 0
    targets = {}

    with open(audit_log, encoding='utf-8') as f:
        for line in f:
            try:
                rec = json.loads(line)
                audited = datetime.fromisoformat(rec['audited_at'].replace('Z', '+00:00'))
                if audited < cutoff:
                    continue
                pid = rec['post_id']
                # 永続スキップリストに登録済みならスキップ
                pid_key = str(pid)
                if skip_list.get(pid_key, {}).get('skipped', False):
                    skipped_count += 1
                    continue
                # 3回以上リライト済みはスキップ（無限ループ防止）
                if already_fixed.get(pid, 0) >= MAX_REWRITE_ATTEMPTS:
                    skip_list[pid_key] = {
                        'attempts': already_fixed[pid],
                        'skipped': True,
                        'skipped_at': datetime.now(timezone.utc).isoformat(),
                        'reason': f"audit_fixed.jsonlに{already_fixed[pid]}回記録済み",
                    }
                    skipped_count += 1
                    continue
                # BUG FIX: content_short のみの記事はGPTでは解決不能なので対象外
                # GPT_REWRITE_TYPES を使ってフィルタリング
                fixable = [i for i in rec['issues'] if i['type'] in GPT_REWRITE_TYPES
                           or i['type'] in ('slug_encoded', 'meta_desc_short', 'no_meta_description', 'no_artist_category')]
                if fixable:
                    key = (pid, rec.get('post_type', 'post'))
                    targets[key] = fixable
            except:
                pass

    # 新しい記事（未リライト）を優先するソート
    sorted_targets = sorted(
        targets.items(),
        key=lambda x: already_fixed.get(x[0][0], 0)
    )

    print(f"自動修正対象: {len(sorted_targets)}件 (スキップ済: {skipped_count}件)")

    fixed = 0
    for (pid, ptype), issues in sorted_targets[:max_fixes]:
        issue_types = [i['type'] for i in issues]

        # 試行回数チェック＆記録
        should_skip = _record_attempt(skip_list, pid, issue_types)
        if should_skip:
            attempts = skip_list[str(pid)]['attempts']
            print(f"  SKIP id={pid}: {MAX_REWRITE_ATTEMPTS}回試行済み、永続スキップに追加 (issues: {issue_types})")
            continue

        post = fetch_post(pid, ptype)
        if not post:
            continue

        title = post.get('title', {}).get('rendered', '') if isinstance(post.get('title'), dict) else ''
        rewrite_count = already_fixed.get(pid, 0)
        print(f"\n[{ptype}] id={pid} (rewrite#{rewrite_count+1}): {title[:40]}")

        update_payload = {}

        # slug修正 (GPTでASCIIスラッグ生成)
        if any(i['type'] in ('slug_encoded', 'slug_auto_generated') for i in issues):
            try:
                from lib.title_optimizer import generate_slug, validate_slug
                new_slug = validate_slug(generate_slug(title))
                if new_slug:
                    update_payload['slug'] = new_slug
                else:
                    # フォールバック: タイムスタンプ付き
                    from datetime import datetime as _dt
                    update_payload['slug'] = f"kpop-popup-{int(_dt.now().timestamp())}"
            except Exception as _e:
                print(f"  slug gen err: {_e}")
                from datetime import datetime as _dt
                update_payload['slug'] = f"kpop-popup-{int(_dt.now().timestamp())}"

        # カテゴリ修正 (no_artist_category)
        if any(i['type'] == 'no_artist_category' for i in issues):
            try:
                from lib.auto_category import detect_artist_categories
                detected = detect_artist_categories(title)
                if detected:
                    current_cats = post.get('categories', [])
                    new_cats = list(set(current_cats + detected))
                    update_payload['categories'] = new_cats
                    print(f"  カテゴリ修正: {current_cats} -> {new_cats}")
            except Exception as e:
                print(f"  カテゴリ検出エラー: {e}")

        # 本文修正 (content_shortはGPT_REWRITE_TYPESから除外済み)
        text_issues = [i for i in issues if i['type'].startswith('text_')
                       or i['type'] in ('unclosed_h2', 'unclosed_p', 'few_internal_links')]
        if text_issues:
            new_content = rewrite_with_gpt(post, text_issues, ptype)
            if new_content and len(new_content) > 200:
                update_payload['content'] = new_content

        # excerpt生成
        if any(i['type'] in ('meta_desc_short', 'no_meta_description') for i in issues):
            update_payload['excerpt'] = generate_meta_description(post)

        if update_payload:
            if update_post(pid, ptype, update_payload):
                fixed += 1
                print(f"  修正完了: {list(update_payload.keys())}")
                fix_log = '/home/aiuser/kpop-ai-system/logs/audit_fixed.jsonl'
                os.makedirs(os.path.dirname(fix_log), exist_ok=True)
                with open(fix_log, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({
                        'post_id': pid, 'post_type': ptype,
                        'fixed_keys': list(update_payload.keys()),
                        'fixed_at': datetime.now(timezone.utc).isoformat(),
                    }, ensure_ascii=False) + '\n')

    # 永続スキップリストを保存
    _save_skip_list(skip_list)
    print(f"\n{fixed}/{len(sorted_targets)}件 自動修正完了")


try:
    if _TSK_ID and _STF_ID: _end_task(_STF_ID, _TSK_ID, "success")
except: pass

if __name__ == '__main__':
    main()


# --- Top11-30 fix helpers (4/26夜追加) ---
def fix_meta_desc_bounds(meta_desc, content=''):
    """メタ説明の長さを80-160字に調整"""
    import re
    if not meta_desc and content:
        plain = re.sub(r'<[^>]+>', '', content[:500]).strip()
        meta_desc = plain[:158]
    if len(meta_desc) > 160:
        return meta_desc[:157] + '...'
    return meta_desc

def fix_title_bounds(title, max_len=42):
    """タイトル長を上限に収める"""
    if len(title) > max_len:
        return title[:max_len - 1] + '…'
    return title

def fix_unclosed_tags(html):
    """<p>/<h2>の開閉数を合わせる"""
    for tag in ['p', 'h2', 'h3']:
        open_n = html.count(f'<{tag}') - html.count(f'</{tag}>')
        if open_n > 0:
            html += f'</{tag}>' * open_n
    return html
