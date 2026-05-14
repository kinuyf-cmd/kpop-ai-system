"""draft自動publish — 品質ゲートPASS記事を自動公開 (毎時20分)"""
import requests, os, json, re, sys, unicodedata, hashlib
sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')
from datetime import datetime
from pathlib import Path
from lib.full_audit_engine import full_audit

BLOCK_HISTORY_PATH = Path('/home/aiuser/kpop-ai-system/data/draft_block_history.json')
MAX_BLOCK_COUNT = 3  # この回数BLOCKされたらアーカイブ

AUTH = (os.getenv('WP_USER', ''), os.getenv('WP_PASS', ''))


def _load_block_history() -> dict:
    if BLOCK_HISTORY_PATH.exists():
        try:
            return json.loads(BLOCK_HISTORY_PATH.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


AUDIT_STEPS_LOG = Path('/home/aiuser/kpop-ai-system/logs/audit_steps.jsonl')


def _latest_audit_thumbnail_fail(pid: int) -> tuple[bool, str]:
    """直近の thumbnail step が fail かどうかを判定。
    2026-05-14: pre_publish_gate は vision check を含まないので、過去の
    auto-auditor が VISION_MISMATCH (サムネが記事と無関係) で fail した
    記事を draft_auto_publisher が再 publish してしまう事故への根治。

    Returns: (is_fail, detail_short)
    """
    if not AUDIT_STEPS_LOG.exists():
        return False, ''
    pid_marker = f'"post_id": {pid},'
    latest_status = ''
    latest_detail = ''
    try:
        with open(AUDIT_STEPS_LOG, encoding='utf-8') as f:
            for line in f:
                if pid_marker not in line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get('post_id') != pid or d.get('step') != 'thumbnail':
                    continue
                latest_status = d.get('status', '')
                latest_detail = d.get('detail', '')[:120]
    except OSError:
        return False, ''
    return latest_status == 'fail', latest_detail


def _save_block_history(history: dict):
    BLOCK_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    BLOCK_HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')


def _archive_draft(pid: int, reasons: list):
    """MAX_BLOCK_COUNT超過のドラフトをゴミ箱に移動 + キャッシュパージ + X tweet削除"""
    try:
        r = requests.delete(
            f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{pid}',
            auth=AUTH, timeout=15)
        if r.status_code == 200:
            print(f"  draft {pid} AUTO-ARCHIVE: {MAX_BLOCK_COUNT}回BLOCK超過 reasons={reasons[:2]}")
            # Next.js ISRキャッシュをパージ (soft-404防止)
            slug = r.json().get('slug', '')
            if slug:
                try:
                    from lib.frontend_cache import purge_post
                    purge_post(slug)
                    print(f"  draft {pid} cache purge: /{slug}/")
                except Exception:
                    pass
            # 2026-05-07: 紐づくXツイートも自動削除 (broken link防止)
            try:
                from lib.x_tweet_manager import delete_tweets_for_post
                results = delete_tweets_for_post(pid)
                deleted = sum(1 for r in results if r.get('deleted'))
                if results:
                    print(f"  draft {pid} X tweets deleted: {deleted}/{len(results)}")
            except Exception as e:
                print(f"  draft {pid} X delete err: {e}")
        else:
            print(f"  draft {pid} archive失敗: HTTP {r.status_code}")
    except Exception as e:
        print(f"  draft {pid} archive失敗: {e}")


def _fix_slug_if_needed(pid, slug, title):
    """slugが汎用的/短すぎる場合にタイトルから意味あるslugを生成して更新"""
    # 意味のあるslugかチェック: 英単語3語以上あればOK
    words = re.findall(r'[a-z]{2,}', slug.lower())
    if len(words) >= 3:
        return slug

    # タイトルからslugを生成
    # 日本語タイトルからアーティスト名・英語キーワードを抽出
    en_words = re.findall(r'[A-Za-z][A-Za-z0-9]+', title)
    if not en_words:
        # 日本語のみ → romanize は難しいのでそのまま
        return slug

    new_slug = '-'.join(w.lower() for w in en_words[:6])
    new_slug = re.sub(r'-+', '-', new_slug).strip('-')
    if len(new_slug) < 10:
        new_slug += '-' + datetime.now().strftime('%Y%m%d')

    try:
        r = requests.post(
            f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{pid}',
            json={'slug': new_slug}, auth=AUTH, timeout=15)
        if r.status_code == 200:
            actual = r.json().get('slug', new_slug)
            print(f"  slug修正: {slug} → {actual}")
            return actual
    except Exception:
        pass
    return slug

def main():
    all_drafts = []
    for page in range(1, 5):
        r = requests.get(
            f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts?status=draft&per_page=100&page={page}&_embed=true',
            auth=AUTH, timeout=20)
        if r.status_code != 200 or not isinstance(r.json(), list) or not r.json():
            break
        all_drafts.extend(r.json())

    if not all_drafts:
        print(f"[{datetime.now().isoformat()}] draft: 0件")
        return

    from lib.pre_publish_gate import pre_publish_gate

    block_history = _load_block_history()
    pub = rew = archived = err = 0
    # 捏造/架空でdraft化された記事のpublish復帰を防止
    try:
        import json as _json
        _blocked = set(_json.load(open('/home/aiuser/kpop-ai-system/data/factcheck_blocked.json')).get('blocked_ids', []))
    except Exception:
        _blocked = set()

    for d in all_drafts:
        pid = d['id']
        pid_str = str(pid)

        # ファクトチェックブロックリストに含まれる記事は絶対にpublishしない
        if pid in _blocked:
            print(f"  [{pid}] SKIP: 捏造/架空でブロック済み")
            continue

        # 2026-05-14: 直近 audit_steps の thumbnail=fail を skip (VISION_MISMATCH 等)
        # pre_publish_gate は vision check を含まないため、手動 draft 化された
        # サムネ事故記事 (23132 ALL DAY RELIEF 等) を draft_auto_publisher が
        # 再 publish してしまう事故を防ぐ
        _thumb_fail, _thumb_detail = _latest_audit_thumbnail_fail(pid)
        if _thumb_fail:
            print(f"  [{pid}] SKIP: audit_steps.thumbnail=fail ({_thumb_detail})")
            continue

        try:
            title = d.get('title', {}).get('rendered', '')
            content = d.get('content', {}).get('rendered', '')
            excerpt = d.get('excerpt', {}).get('rendered', '')
            slug = d.get('slug', '')
            fm = d.get('featured_media', 0)
            cats = d.get('categories', [])

            # カテゴリからkindを推定: 速報(2)以外はfeatureとして扱う
            NEWS_CATS = {2, 7, 58}  # 速報記事, 出演情報, 今日話題のニュース
            _kind = 'news' if set(cats) & NEWS_CATS else 'feature'

            # ソース取得を試行（feature記事のBLOCK回避）
            _source_url = None
            _source_signals = None

            # まず本文に既に埋め込まれた信頼ソースリンクを抽出 (2026-05-07追加)
            # config/source_domains.json 参照で全collectorsドメインに対応
            try:
                import re as _re_dap
                from lib.source_domains import source_url_regex as _src_re_dap
                _embedded_urls = _re_dap.findall(_src_re_dap(), content)
                if _embedded_urls:
                    _source_url = _embedded_urls[0]
                    _source_signals = [{'url': u, 'title': ''} for u in _embedded_urls[:3]]
                    print(f"  [factcheck] 本文埋込ソース: {len(_embedded_urls)}件")
            except Exception as _se:
                print(f"  [factcheck] embed source extract skip: {_se}")

            # 本文に無ければ feature記事はTavily検索でフォールバック
            if not _source_url and _kind == 'feature':
                try:
                    from pipeline.feature_article_generator import _fetch_web_context
                    _, _web_sources = _fetch_web_context(title)
                    if _web_sources:
                        _source_url = _web_sources[0].get('url')
                        _source_signals = _web_sources
                        print(f"  [factcheck] Tavily OK: {len(_web_sources)}件取得")
                    else:
                        print(f"  [factcheck] Tavily skip: ソース取得失敗")
                except Exception as _fe:
                    print(f"  [factcheck] Tavily skip: {_fe}")

            # 2026-05-12: content_hash で BLOCK 永続化 (gate の stochastic な PASS で
            # 過去 BLOCK 済記事が通過する事故を防ぐ)。22027 / 22024 hallucination 公開の
            # root cause: 同 content で BLOCK 1/3 → BLOCK 2/3 → 3 回目に gate が偶発的に
            # PASS を返して publish された。
            content_hash = hashlib.sha256(
                (title + content[:5000]).encode('utf-8', errors='ignore')
            ).hexdigest()[:16]
            prior = block_history.get(pid_str, {})
            if prior.get('content_hash') == content_hash and prior.get('count', 0) >= 1:
                # 同 content で過去に BLOCK 済 → gate 再実行せず BLOCK 維持
                gate = {
                    'verdict': 'BLOCK',
                    'block_reasons': prior.get('reasons', ['同content_hashで過去BLOCK済 (stochastic-PASS回避)']),
                }
            else:
                gate = pre_publish_gate(
                    title=title, body_html=content,
                    post_type='post', kind=_kind,
                    slug=slug, featured_media=fm,
                    categories=cats, excerpt=excerpt,
                    status='publish',
                    source_url=_source_url,
                    source_signals=_source_signals,
                )
            if gate['verdict'] != 'BLOCK':
                # publish前にslugを検証・修正
                slug = _fix_slug_if_needed(pid, slug, title)
                u = requests.post(
                    f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{pid}',
                    json={'status': 'publish'}, auth=AUTH, timeout=15)
                if u.status_code == 200:
                    pub += 1
                    # Post-publish hook
                    try:
                        from lib.post_publish_hook import run_post_publish
                        run_post_publish(pid, post_type='post')
                    except Exception as hook_e:
                        print(f"  [post-publish] hook error (pid={pid}): {hook_e}")
                    # publishできたらblock履歴から削除
                    block_history.pop(pid_str, None)
            else:
                reasons = gate.get('block_reasons', [])
                # BLOCK履歴を記録
                if pid_str not in block_history:
                    block_history[pid_str] = {'count': 0, 'first_seen': datetime.now().isoformat(), 'reasons': []}
                block_history[pid_str]['count'] += 1
                block_history[pid_str]['last_seen'] = datetime.now().isoformat()
                block_history[pid_str]['reasons'] = reasons[:3]
                block_history[pid_str]['content_hash'] = content_hash

                if block_history[pid_str]['count'] >= MAX_BLOCK_COUNT:
                    _archive_draft(pid, reasons)
                    block_history.pop(pid_str, None)
                    archived += 1
                else:
                    print(f"  draft {pid} BLOCK ({block_history[pid_str]['count']}/{MAX_BLOCK_COUNT}): {reasons[:2]}")
                    rew += 1
        except Exception:
            err += 1

    _save_block_history(block_history)
    print(f"[{datetime.now().isoformat()}] draft={len(all_drafts)} publish={pub} block={rew} archived={archived} err={err}")

if __name__ == '__main__':
    main()
