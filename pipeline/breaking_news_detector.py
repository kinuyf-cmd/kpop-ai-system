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
DAILY_BREAKING_LIMIT = 9999  # 上限撤廃(KPI駆動)


def load_recent(minutes=5):
    if not os.path.exists(SIGNALS_PATH):
        return []
    cutoff = datetime.now() - timedelta(minutes=minutes)
    result = []
    with open(SIGNALS_PATH, encoding='utf-8') as f:
        for line in f:
            try:
                sig = json.loads(line)
                ts = datetime.fromisoformat(sig.get('timestamp', '')[:19])
                if ts >= cutoff:
                    result.append(sig)
            except Exception:
                pass
    return result


def today_breaking_count():
    if not os.path.exists(BREAKING_LOG):
        return 0
    today = datetime.now().date().isoformat()
    return sum(1 for l in open(BREAKING_LOG, encoding='utf-8')
               if l.strip() and json.loads(l).get('date') == today)


def detect_breaking(signals):
    from lib.collectors.korean_base import is_kpop_related
    candidates = []
    seen = set()

    # 1. urgency=high
    for s in signals:
        if s.get('urgency') != 'high':
            continue
        arts = is_kpop_related(s.get('title', ''))
        if not arts or arts[0] in seen:
            continue
        if is_processed(s['url']):
            continue
        seen.add(arts[0])
        candidates.append((arts[0], [s], 'urgent'))

    # 2. 同一アーティスト+複数ソース (15分以内)
    by_artist = {}
    for s in signals:
        arts = is_kpop_related(s.get('title', ''))
        if not arts:
            continue
        by_artist.setdefault(arts[0], []).append(s)

    for artist, sigs in by_artist.items():
        if artist in seen:
            continue
        sources = set(s.get('source_id', '') for s in sigs)
        if len(sources) >= 2 and not any(is_processed(s['url']) for s in sigs):
            seen.add(artist)
            candidates.append((artist, sigs, 'multi'))
        # 4/27緩和: 単一ソースでも記事が2件以上あれば候補化 (confidence=medium)
        elif len(sigs) >= 2 and not any(is_processed(s['url']) for s in sigs):
            seen.add(artist)
            candidates.append((artist, sigs, 'single_multi'))

    return candidates


def _mark_breaking_stage(post_id, stage):
    """WP custom field _breaking_stage を記録 (1=速報、2=加筆済、3=完全版)"""
    _AUTH = base64.b64encode(b"kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh").decode()
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


def publish_breaking(artist, sigs, typ):
    """unified_publish経由で速報投稿"""
    best = max(sigs, key=lambda s: len(s.get('title', '')))

    # 翻訳
    if best.get('language') == 'ko':
        title_r = translate_ko_to_ja(best['title'], 'K-POP速報見出し')
        if not title_r.get('success'):
            return None
        raw_title = title_r['translated'].strip().strip('「」""')
        combined = "\n".join([s['title'] for s in sigs[:3]])
        body_r = translate_ko_to_ja(
            f"今日は{datetime.now().strftime('%Y年%m月%d日')}です。以下のK-POP速報から800-1200字の日本語記事を事実ベースで。本文中に必ず現在の年月(例:{datetime.now().strftime('%Y年%m月')})を含めること。5W1H(誰が・いつ・何を・どこで・なぜ)を明確に。背景情報・関連する過去の出来事も含めて厚みのある記事にすること。【絶対厳禁】人名を「A」「B」等に匿名化しないこと。ソースに記載された実名(アーティスト名・グループ名)を必ずそのまま使用すること。複数の無関係なニュースが含まれる場合は最も重要な1件のみ記事化し、他は無視すること。推測禁止:\n\n{combined}",
            'K-POP速報記事',
        )
        body_html = _wrap_body(body_r.get('translated', ''), best['title'], body_r.get('success'))
    elif best.get('language') == 'ja':
        raw_title = best['title']
        combined = "\n".join([s['title'] for s in sigs[:3]])
        # 日本語ソース: translate_ko_to_jaの汎用LLM機能で速報本文を生成
        body_r = translate_ko_to_ja(
            f"今日は{datetime.now().strftime('%Y年%m月%d日')}です。以下のK-POP速報見出しから800-1200字の日本語速報記事を事実ベースで書いてください。本文中に必ず現在の年月(例:{datetime.now().strftime('%Y年%m月')})を含めること。5W1H(誰が・いつ・何を・どこで・なぜ)を明確に。背景情報・関連する過去の出来事も含めて厚みのある記事にすること。【絶対厳禁】人名を「A」「B」等に匿名化しないこと。ソースに記載された実名(アーティスト名・グループ名)を必ずそのまま使用すること。複数の無関係なニュースが含まれる場合は最も重要な1件のみ記事化し、他は無視すること。推測禁止:\n\n{combined}",
            'K-POP速報記事（日本語ソース）',
        )
        body_html = _wrap_body(body_r.get('translated', ''), best['title'], body_r.get('success'))
    else:
        # 英語ソース: 翻訳+本文生成
        combined = "\n".join([s['title'] for s in sigs[:3]])
        title_r = translate_ko_to_ja(best['title'], 'K-POP速報見出し（英語→日本語）')
        if title_r.get('success'):
            raw_title = title_r['translated'].strip().strip('「」""')
        else:
            raw_title = best['title']
        body_r = translate_ko_to_ja(
            f"今日は{datetime.now().strftime('%Y年%m月%d日')}です。以下の英語K-POP速報から800-1200字の日本語記事を事実ベースで。本文中に必ず現在の年月(例:{datetime.now().strftime('%Y年%m月')})を含めること。5W1H(誰が・いつ・何を・どこで・なぜ)を明確に。背景情報・関連する過去の出来事も含めて厚みのある記事にすること。【絶対厳禁】人名を「A」「B」等に匿名化しないこと。ソースに記載された実名(アーティスト名・グループ名)を必ずそのまま使用すること。複数の無関係なニュースが含まれる場合は最も重要な1件のみ記事化し、他は無視すること。推測禁止:\n\n{combined}",
            'K-POP速報記事',
        )
        body_html = _wrap_body(body_r.get('translated', ''), best['title'], body_r.get('success'))

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
            }) + '\n')
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

    signals_raw = load_recent(minutes=5)
    signals, _dup_n, _ = deduplicate(signals_raw)
    print(f"過去5分のsignals: {len(signals_raw)}件 (dedup: -{_dup_n})")

    candidates = detect_breaking(signals)
    print(f"速報候補: {len(candidates)}件")

    published = 0
    for artist, sigs, typ in candidates[:DAILY_BREAKING_LIMIT - count_today]:
        best = max(sigs, key=lambda s: len(s.get('title', '')))
        print(f"\n=== {artist} ({typ}): {best['title'][:60]} ===")
        if dry_run:
            continue
        r = publish_breaking(artist, sigs, typ)
        if r:
            print(f"  速報公開 ID={r.get('id')}")
            published += 1

    print(f"\n速報記事化: {published}件")
    return published


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    main(dry_run=args.dry_run)
