#!/usr/bin/env python3
"""韓国メディアsignalsからイベント記事を自動生成+WP投稿

条件緩和 (C-Fix9 Block3): 単一ソースも許可、信頼度ラベル付与
"""
import sys, os, json, urllib.request, base64
from datetime import datetime, timedelta
from dotenv import load_dotenv

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
load_dotenv()

from lib.korean_translator import translate_ko_to_ja
from lib.unified_publisher import unified_publish
from lib.signal_deduplicator import deduplicate

SIGNALS = '/home/aiuser/kpop-ai-system/data/trend_signals.jsonl'
PROCESSED = '/home/aiuser/kpop-ai-system/data/auto_article_processed.jsonl'
WP_USER = 'kpop-bot'
WP_PASS = os.getenv('WP_APP_PASS', 'vl1H 1brV m4Pq Z1sm F8lZ 3nzh')
AUTH = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()

CONFIDENCE_HIGH = 'high'      # 2+ sources
CONFIDENCE_MEDIUM = 'medium'  # 1 source + official keyword
CONFIDENCE_LOW = 'low'        # 1 source only

EVENT_KW_KO = ['콘서트', '팬미팅', '투어', '공연', '라이브', '쇼케이스', '축제', '페스티벌']
OFFICIAL_KW = ['공식', '발표', '확정', '예정']


def load_signals(hours_back=24):
    if not os.path.exists(SIGNALS):
        return []
    cutoff = datetime.now() - timedelta(hours=hours_back)
    result = []
    with open(SIGNALS, encoding='utf-8') as f:
        for line in f:
            try:
                sig = json.loads(line)
                ts = datetime.fromisoformat(sig.get('timestamp', '')[:19])
                if ts >= cutoff and sig.get('source') in ('korean_media', 'japanese_media'):
                    result.append(sig)
            except Exception:
                pass
    return result


def is_event_signal(sig):
    return any(kw in sig.get('title', '') for kw in EVENT_KW_KO)


def is_processed(url):
    if not os.path.exists(PROCESSED):
        return False
    with open(PROCESSED, encoding='utf-8') as f:
        for line in f:
            try:
                if json.loads(line).get('source_url') == url:
                    return True
            except Exception:
                pass
    return False


def mark_processed(record):
    os.makedirs(os.path.dirname(PROCESSED), exist_ok=True)
    with open(PROCESSED, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def generate_article_content(sigs, translated_body):
    source_links = ''.join(
        f'<li><a href="{s["url"]}" target="_blank" rel="noopener">{s.get("source_id", "?").upper()}</a>: '
        f'記事を見る</li>'
        for s in sigs[:5]
    )
    return f"""<p>{translated_body}</p>

<h2>情報ソース</h2>
<ul>{source_links}</ul>

<p><em>※ 最新情報は各公式発表をご確認ください。</em></p>"""


def generate_article_content_v2(sigs, translated_body, confidence='high'):
    """信頼度別の記事本文生成"""
    confidence_note = {
        'high': '<p><em>※ 本記事は複数の韓国メディア報道を元に編集部が翻訳・編集しました。</em></p>',
        'medium': '<p><em>※ 本記事は韓国メディアの公式発表・一次報道を元に編集部が翻訳・編集しました。</em></p>',
        'low': ('<p style="background:#FFF9E6;padding:12px;border-left:4px solid #E8B86D;border-radius:4px;">'
                '<strong>単一メディア速報</strong><br/>'
                '本記事は韓国メディア1社の報道を元にしています。'
                '続報や公式発表で内容が変更される可能性があります。</p>'),
    }
    source_links = ''.join(
        f'<li><a href="{s["url"]}" target="_blank" rel="noopener noreferrer">'
        f'{s.get("source_id", "?").upper()}</a>: 記事を見る</li>'
        for s in sigs[:5]
    )
    return f"""<p>{translated_body}</p>

{confidence_note.get(confidence, confidence_note['low'])}

<h2>情報ソース</h2>
<ul>{source_links}</ul>

<p><em>※ 最新情報・詳細は各公式発表をご確認ください。</em></p>"""


def post_to_wp(title_ja, content_html, category_id=None):
    data = {'title': title_ja, 'content': content_html, 'status': 'publish'}
    if category_id:
        data['categories'] = [category_id]
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts",
        data=body,
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"WP post error: {e}")
        return None


def upload_media_to_wp(image_path, post_id=0):
    """画像をWPにアップロードしてmedia_idを返す"""
    try:
        with open(image_path, 'rb') as f:
            data = f.read()
    except Exception:
        return None
    ext = os.path.splitext(image_path)[1][1:].lower() or 'jpg'
    ct = 'image/png' if ext == 'png' else 'image/jpeg'
    req = urllib.request.Request(
        "https://www.kpopjournal.tokyo/wp-json/wp/v2/media",
        data=data,
        headers={
            'Authorization': f'Basic {AUTH}',
            'Content-Type': ct,
            'Content-Disposition': f'attachment; filename="thumb_post{post_id}.{ext}"',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read()).get('id')
    except Exception as e:
        print(f"  upload error: {e}")
        return None


def post_to_wp_with_thumb(title, content, cat_id, source_url=None, post_id=0):
    """サムネ2段fallback + WP投稿"""
    from lib.thumbnail_resolver import resolve_thumbnail
    thumb = resolve_thumbnail(source_url, title, content[:500] if content else '', post_id)

    media_id = None
    if thumb and thumb.get('path'):
        media_id = upload_media_to_wp(thumb['path'], post_id)
        if thumb.get('source') == 'source_site' and thumb.get('source_url'):
            src = thumb['source_url']
            content = (f'<p style="font-size:11px;color:#888;text-align:right;margin-top:8px;">'
                       f'画像: <a href="{src}" target="_blank" rel="noopener">元記事より</a></p>\n') + content

    data = {'title': title, 'content': content, 'status': 'publish'}
    if cat_id:
        data['categories'] = [cat_id]
    if media_id:
        data['featured_media'] = media_id

    body = json.dumps(data).encode()
    req = urllib.request.Request(
        "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts",
        data=body,
        headers={'Authorization': f'Basic {AUTH}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"WP post error: {e}")
        return None


def fetch_category_id(slug='event'):
    try:
        req = urllib.request.Request(
            f"https://www.kpopjournal.tokyo/wp-json/wp/v2/categories?slug={slug}&_fields=id",
            headers={'Authorization': f'Basic {AUTH}'},
        )
        return json.loads(urllib.request.urlopen(req, timeout=20).read())[0]['id']
    except Exception:
        return None


def _read_max_from_state(key, default=3):
    """daily_editorのeditor_state.jsonから推奨max取得"""
    try:
        d = json.load(open('/home/aiuser/kpop-ai-system/data/editor_state.json', encoding='utf-8'))
        return d.get('recommended_max', {}).get(key, default)
    except Exception:
        return default


def main(dry_run=False, max_articles=None):
    try:
        from lib.staff_task_manager import begin_task, end_task as _end_task
        _STF_ID, _TSK_ID = "KPJ-0010", begin_task("KPJ-0010", "auto_event_article")
    except: _STF_ID = _TSK_ID = None
    if max_articles is None:
        max_articles = _read_max_from_state('auto_event', 3)
    signals_raw = load_signals(hours_back=24)
    signals, _dup_n, _ = deduplicate(signals_raw)
    event_sigs = [s for s in signals if is_event_signal(s)]
    print(f"過去24h signals: {len(signals_raw)}, dedup後: {len(signals)} (-{_dup_n}), イベント関連: {len(event_sigs)}")

    from lib.collectors.korean_base import is_kpop_related
    groups = {}
    for sig in event_sigs:
        artists = is_kpop_related(sig['title'])
        if not artists:
            continue
        event_type = next((kw for kw in EVENT_KW_KO if kw in sig['title']), 'other')
        key = f"{artists[0]}-{event_type}"
        groups.setdefault(key, []).append(sig)

    qualified = []
    for key, sigs in groups.items():
        if any(is_processed(s['url']) for s in sigs):
            continue
        sources = set(s.get('source_id', '') for s in sigs)
        has_multi = len(sources) >= 2
        has_official = any(any(kw in s['title'] for kw in OFFICIAL_KW) for s in sigs)
        if has_multi:
            confidence = CONFIDENCE_HIGH
        elif has_official:
            confidence = CONFIDENCE_MEDIUM
        else:
            confidence = CONFIDENCE_LOW
        qualified.append((key, sigs, confidence))

    print(f"記事化候補: {len(qualified)}")
    cat_id = fetch_category_id('event')
    created = 0

    for key, sigs, confidence in qualified[:max_articles]:
        best = max(sigs, key=lambda s: len(s['title']))
        print(f"\n=== {key} (confidence={confidence}): {best['title'][:60]} ===")
        if dry_run:
            continue

        # 2026-05-12: memo feedback_pipeline_must_use_source_reader に従い、
        # auto_comeback_article / breaking_news_detector と同じ source_reader +
        # web_search 統合パターンに移行。headline だけで GPT に投げる旧実装は捏造の温床。
        from lib.source_reader import read_sources
        source_text = read_sources(sigs)
        if not source_text or len(source_text) < 200:
            print(f"  [auto_event] BLOCK: source_text 取得失敗 (200字未満)、捏造リスクで生成中止")
            continue

        _artist_name = key.split('-')[0] if '-' in key else key
        _artist_kw = str(_artist_name).lower()
        if _artist_kw and _artist_kw not in source_text.lower() and \
           _artist_kw not in best['title'].lower():
            print(f"  [auto_event] BLOCK: artist '{_artist_name}' がソース本文/タイトルに不在、クラスタ偽陽性")
            continue

        try:
            from pipeline.breaking_news_detector import _enrich_with_web_search
            web_facts = _enrich_with_web_search(best['title'], sigs)
        except Exception as _we:
            print(f"  [auto_event] web_search 失敗、続行: {_we}")
            web_facts = ''

        title_r = translate_ko_to_ja(best['title'], 'K-POPイベント見出し')
        if not title_r['success']:
            continue
        raw_title = title_r['translated'].strip().strip('「」""')[:65]

        combined = "\n".join([s['title'] for s in sigs[:3]])
        web_facts_section = f"\n\n【Web検索で取得した補足情報】\n{web_facts}" if web_facts else ''
        prompt = (
            f"以下のK-POPイベント報道から1500-2000字の日本語HTML記事本文を事実ベースで作成。"
            f"h2セクション2つ以上。ソース記事に書かれていない事実は絶対に追加しない。"
            f"推測・SNS反応の捏造禁止。\n\n"
            f"【ソース記事ヘッドライン】\n{combined}\n\n"
            f"【ソース記事本文 (事実の根拠。ここに書かれている固有名詞/人名/日付を必ず記事に含める)】\n"
            f"{source_text[:1500]}"
            f"{web_facts_section}\n\n"
            f"5W1H (誰が・いつ・何を・どこで・なぜ) を明確に。ソースに書かれていないことは書かない。"
        )
        body_r = translate_ko_to_ja(prompt, 'K-POPイベント記事')
        if not body_r['success']:
            continue

        body_html = f"<p>{body_r['translated']}</p>"
        r = unified_publish(
            raw_title=raw_title,
            body_html=body_html,
            source_url=best.get('url', ''),
            artist=key.split('-')[0] if '-' in key else key,
            kind='event',
            confidence=confidence,
            source_signals=sigs,
        )
        if r and r.get('success'):
            print(f"  WP公開 ID={r['post_id']}")
            # Post-publish hook
            try:
                from lib.post_publish_hook import run_post_publish
                run_post_publish(r['post_id'], post_type='post')
            except Exception as hook_e:
                print(f"  [post-publish] hook error: {hook_e}")
            created += 1
            for s in sigs:
                mark_processed({'ts': datetime.now().isoformat(), 'source_url': s['url'],
                                'wp_post_id': r['post_id'], 'kind': 'event', 'confidence': confidence})

    print(f"\n完了: {created}件記事化")
    return created


try:
    if _TSK_ID and _STF_ID: _end_task(_STF_ID, _TSK_ID, "success")
except: pass

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--max', type=int, default=None)
    args = ap.parse_args()
    main(dry_run=args.dry_run, max_articles=args.max)
