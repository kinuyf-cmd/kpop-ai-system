#!/usr/bin/env python3
"""韓国メディアsignalsからカムバック記事を自動生成+WP投稿

条件緩和 (C-Fix9 Block3): 単一ソースも許可、信頼度ラベル付与
"""
import sys, os, json
sys.path.insert(0, '/home/aiuser/kpop-ai-system')

from dotenv import load_dotenv
load_dotenv()

from lib.korean_translator import translate_ko_to_ja
from lib.unified_publisher import unified_publish
from lib.signal_deduplicator import deduplicate
from pipeline.auto_event_article import (
    load_signals, is_processed, mark_processed,
    OFFICIAL_KW, CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW,
)
from datetime import datetime

COMEBACK_KW = ['컴백', '신곡', '발매', '신보', '앨범', '미니앨범', '정규', '싱글']


def is_comeback_signal(sig):
    return any(kw in sig.get('title', '') for kw in COMEBACK_KW)


def _read_max_from_state(key, default=3):
    try:
        d = json.load(open('/home/aiuser/kpop-ai-system/data/editor_state.json', encoding='utf-8'))
        return d.get('recommended_max', {}).get(key, default)
    except Exception:
        return default


def main(dry_run=False, max_articles=None):
    try:
        from lib.staff_task_manager import begin_task, end_task as _end_task
        _STF_ID, _TSK_ID = "KPJ-0012", begin_task("KPJ-0012", "auto_comeback_article")
    except: _STF_ID = _TSK_ID = None
    if max_articles is None:
        max_articles = _read_max_from_state('auto_comeback', 3)
    signals_raw = load_signals(hours_back=24)
    signals, _dup_n, _ = deduplicate(signals_raw)
    cb_sigs = [s for s in signals if is_comeback_signal(s)]
    print(f"カムバック関連: {len(cb_sigs)} (dedup: -{_dup_n})")

    from lib.collectors.korean_base import is_kpop_related
    groups = {}
    for sig in cb_sigs:
        artists = is_kpop_related(sig['title'])
        if not artists:
            continue
        groups.setdefault(artists[0], []).append(sig)

    qualified = []
    for artist, sigs in groups.items():
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
        qualified.append((artist, sigs, confidence))

    print(f"記事化候補: {len(qualified)}")
    created = 0

    for artist, sigs, confidence in qualified[:max_articles]:
        best = max(sigs, key=lambda s: len(s['title']))
        print(f"\n=== {artist} (confidence={confidence}): {best['title'][:60]} ===")
        if dry_run:
            continue

        # 2026-05-12: ガベージイン対策。旧実装は headline 3本だけで GPT に投げており、
        # クラスタ偽陽性 (SHINee 記事に볼ボール選手 / Jo Kwon が混入する等) と
        # ソース本文未読での捏造記事を量産していた。breaking_news_detector の
        # publish_breaking と同じ source_reader + web_search 統合パターンに整合させる。
        from lib.source_reader import read_sources
        source_text = read_sources(sigs)
        if not source_text or len(source_text) < 200:
            print(f"  [auto_comeback] BLOCK: source_text 取得失敗 (200字未満)、捏造リスクで生成中止")
            continue

        # 関連性チェック: ソース本文に artist 名が含まれるか
        # 含まれない = cluster の偽陽性 (別アーティスト signal が混入) の可能性
        _artist_kw = str(artist).lower()
        if _artist_kw and _artist_kw not in source_text.lower() and \
           _artist_kw not in best['title'].lower():
            print(f"  [auto_comeback] BLOCK: artist '{artist}' がソース本文/タイトルに不在、クラスタ偽陽性")
            continue

        title_r = translate_ko_to_ja(best['title'], 'K-POPカムバック見出し')
        if not title_r['success']:
            continue
        raw_title = title_r['translated'].strip().strip('「」""')[:65]

        # Web 検索で補強事実 (breaking_news_detector の _enrich_with_web_search 再利用)
        try:
            from pipeline.breaking_news_detector import _enrich_with_web_search
            web_facts = _enrich_with_web_search(best['title'], sigs)
        except Exception as _we:
            print(f"  [auto_comeback] web_search 失敗、続行: {_we}")
            web_facts = ''

        combined = "\n".join([s['title'] for s in sigs[:3]])
        web_facts_section = f"\n\n【Web検索で取得した補足情報】\n{web_facts}" if web_facts else ''
        prompt = (
            f"以下のK-POPカムバック報道から1500-2000字の日本語HTML記事本文を事実ベースで作成。"
            f"h2セクション2つ以上。ソース記事に書かれていない事実は絶対に追加しない。"
            f"推測・SNS反応の捏造禁止。\n\n"
            f"【ソース記事ヘッドライン】\n{combined}\n\n"
            f"【ソース記事本文 (事実の根拠。ここに書かれている固有名詞/人名/日付を必ず記事に含める)】\n"
            f"{source_text[:1500]}"
            f"{web_facts_section}\n\n"
            f"5W1H (誰が・いつ・何を・どこで・なぜ) を明確に。ソースに書かれていないことは書かない。"
        )
        body_r = translate_ko_to_ja(prompt, 'K-POPカムバック記事')
        if not body_r['success']:
            continue

        body_html = f"<p>{body_r['translated']}</p>"
        r = unified_publish(
            raw_title=raw_title,
            body_html=body_html,
            source_url=best.get('url', ''),
            artist=artist,
            kind='comeback',
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
                                'wp_post_id': r['post_id'], 'kind': 'comeback', 'confidence': confidence})

    print(f"\n完了: {created}件")
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
