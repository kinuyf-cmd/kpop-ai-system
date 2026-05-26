#!/usr/bin/env python3
"""X投稿ラッパー: google_metrics/post_to_x.py (~/.x_credentials) を直接利用

スパム防止3層防御:
  1. レート制限: 1時間あたり MAX_POSTS_PER_HOUR 投稿まで
  2. 類似テキスト検知: 直近投稿と類似度が高い場合はキュー送り
  3. フック+リプライ方式: URLはリプライで挿入、ハッシュタグでユニーク化
"""
import sys, os, json, re
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, '/home/aiuser/kpop-ai-system/google_metrics')
sys.path.insert(0, '/home/aiuser/kpop-ai-system')

BASE = Path('/home/aiuser/kpop-ai-system')
LOG = str(BASE / 'logs' / 'x_posts.jsonl')
RETRY_QUEUE = BASE / 'config' / 'x_retry_queue.json'

MAX_POSTS_PER_HOUR = 10
MAX_POSTS_PER_DAY = 40  # 日次上限: KCON等イベント時の大量公開に対応 (15→40)
SIMILARITY_THRESHOLD = 0.6  # 60%以上類似ならキュー送り（ワード分割Jaccard）
MIN_INTERVAL_SEC = 15  # 連続投稿間隔: 最低15秒空ける（バースト防止）

# 既存モジュールをimport
_validate = None
_post = None
try:
    from post_to_x import validate_credentials as _validate, post_tweet as _post
except BaseException as e:
    # SystemExit も捕捉(2026-05-23 移植): sys.path 上の post_to_x が
    # __main__ガード無しの CLI(google_metrics/post_to_x.py)に解決されると
    # import 時 top-level の sys.exit() で SystemExit が飛ぶ。except Exception は
    # SystemExit(BaseException) を捕捉しないため x_poster import がクラッシュしていた。
    # _validate/_post は None のまま → 下流(L157/L350)で graceful skip される。
    print(f"post_to_x import warning: {type(e).__name__}: {e}", file=sys.stderr)
    _validate = None
    _post = None


def _recent_posts(hours: int = 1) -> list[dict]:
    """直近N時間の投稿ログを取得"""
    if not os.path.exists(LOG):
        return []
    cutoff = datetime.now() - timedelta(hours=hours)
    recent = []
    try:
        with open(LOG, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry.get('ts', '2000-01-01'))
                    if ts >= cutoff and entry.get('status') == 'ok':
                        recent.append(entry)
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        pass
    return recent


def _text_similarity(a: str, b: str) -> float:
    """テキスト類似度（ワード分割Jaccard係数）
    文字集合だとK-POP記事は共通文字が多く誤検知するため、
    ハッシュタグ・URL除去+ワード分割で比較する。
    """
    import re
    if not a or not b:
        return 0.0
    # ハッシュタグ・URL・絵文字を除去して本文のみ比較
    def _clean(t):
        t = re.sub(r'#\S+', '', t)
        t = re.sub(r'https?://\S+', '', t)
        t = re.sub(r'[\U00010000-\U0010ffff]', '', t)  # 絵文字除去
        return t.strip()
    ca, cb = _clean(a), _clean(b)
    # 2-gram + ワード分割のハイブリッド
    def _tokens(t):
        words = set(re.split(r'[\s、。！？!?\n]+', t))
        words.discard('')
        # 2文字gramも追加（短文対応）
        for i in range(len(t) - 1):
            words.add(t[i:i+2])
        return words
    set_a = _tokens(ca[:150])
    set_b = _tokens(cb[:150])
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def _extract_artist_from_title(title: str) -> str:
    """タイトルからアーティスト名を推定"""
    # 【速報】以降の最初の固有名詞を抽出
    title = re.sub(r'^【[^】]*】\s*', '', title)
    # 英字アーティスト名 (BTS, BLACKPINK, LE SSERAFIM etc.)
    m = re.match(r'([A-Z][A-Za-z0-9\s\.\-]{1,25}?)(?:が|の|は|、|「)', title)
    if m:
        return m.group(1).strip()
    # カタカナ名
    m = re.match(r'([ァ-ヶー]{2,15})(?:が|の|は|、)', title)
    if m:
        return m.group(1)
    return ''


def _add_to_retry_queue(text: str, url: str, post_id: int = None):
    """レート制限超過時にリトライキューに追加"""
    queue_data = {'created': datetime.now().strftime('%Y-%m-%d'), 'reason': 'rate_limit', 'queue': []}
    if RETRY_QUEUE.exists():
        try:
            queue_data = json.loads(RETRY_QUEUE.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass

    if not isinstance(queue_data.get('queue'), list):
        queue_data['queue'] = []

    entry = {'text': text[:200], 'url': url, 'added_at': datetime.now().isoformat()}
    if post_id:
        entry['post_id'] = post_id
    queue_data['queue'].append(entry)
    RETRY_QUEUE.write_text(json.dumps(queue_data, ensure_ascii=False, indent=2), encoding='utf-8')


def post_tweet(text: str, url: str = None, post_id: int = None,
               genre: str = "", artist: str = "",
               schedule: bool = True) -> dict:
    """X投稿 (unified_publisher等から呼ばれる)

    デフォルト動作: スケジューラーキューに追加し、ピーク時間帯に分散投稿。
    schedule=False で即時投稿（リトライプロセッサー用）。

    Args:
        text: タイトル/本文
        url: 記事URL (メイン投稿に含める)
        post_id: WordPress記事ID（監査のログ照合用）
        genre: ジャンル (breaking/news/comeback等) — ハッシュタグ・CTA選択に使用
        artist: アーティスト名 — ハッシュタグ生成に使用
        schedule: True=キュー経由で分散投稿 / False=即時投稿

    Returns:
        {'success': bool, 'tweet_id': str|None, 'error': str|None, 'queued': bool}
    """
    # --- スケジューラーキュー投入モード ---
    if schedule and url:
        try:
            from pipeline.x_scheduled_poster import enqueue
            priority = 'high' if genre in ('breaking', 'news', 'comeback') else 'normal'
            enqueued = enqueue(text, url, post_id=post_id, genre=genre,
                              artist=artist, priority=priority)
            if enqueued:
                return {'success': False, 'queued': True,
                        'error': 'スケジューラーキューに追加（ピーク時間帯に投稿）'}
            # 既にキューにある場合は即時投稿にフォールバック
        except Exception as _e:
            print(f"[x_poster] scheduler queue fallback: {_e}", file=sys.stderr)

    if _validate is None or _post is None:
        return {'success': False, 'error': 'post_to_x module import失敗'}

    # --- 空テキストガード ---
    if not text or len(text.strip()) < 5:
        return {'success': False, 'error': 'テキストが空または短すぎる', 'queued': False}

    # --- WP記事status再検証 (2026-05-07: trash記事へのX投稿事故防止) ---
    if post_id:
        try:
            import urllib.request as _ur, base64 as _b64, json as _json
            _AUTH = _b64.b64encode(b'kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh').decode()
            _u = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}?_fields=id,status,featured_media&status=any'
            _req = _ur.Request(_u, headers={'Authorization': f'Basic {_AUTH}'})
            with _ur.urlopen(_req, timeout=10) as _r:
                _wp = _json.loads(_r.read())
            if _wp.get('status') != 'publish':
                return {'success': False,
                        'error': f'WP記事 {post_id} status={_wp.get("status")} (publish以外) — X投稿スキップ',
                        'queued': False}
            if _wp.get('featured_media', 0) == 0:
                return {'success': False,
                        'error': f'WP記事 {post_id} featured_media未設定 — サムネ不一致防止のためX投稿スキップ',
                        'queued': False}
        except Exception as _e:
            print(f"[x_poster] WP status check err: {_e}", file=sys.stderr)

    # --- OGP事前検証 (2026-05-07更新: og-default も block) ---
    # ユーザー指示「サムネイルは投稿記事と必ず同じものを使用」厳守のため、
    # og-default 検出時は X 投稿しない (記事サムネ無し → Twitter Card不一致直結)
    if url:
        try:
            from lib.x_post_url_validator import validate_url
            url_check = validate_url(url)
            if not url_check.get('ok'):
                reason = url_check.get('reason', '')
                ogp_issue = url_check.get('ogp_issue', {})
                warn_entry = {
                    'ts': datetime.now().isoformat(),
                    'url': url,
                    'status': 'ogp_warn',
                    'reason': reason,
                    'og_image': ogp_issue.get('og_image', ''),
                }
                if post_id:
                    warn_entry['post_id'] = post_id
                _log(warn_entry)
                # soft-404 / og-default / OGP問題はすべて block (サムネ一致原則)
                if any(kw in reason for kw in ('soft-404', 'og-default', 'OGP問題')):
                    return {'success': False, 'error': f'URL検証NG: {reason}', 'queued': False}
                print(f"  [x_poster] OGP warn (続行): {reason}")
        except Exception:
            pass

    # --- バースト防止: 直前投稿からMIN_INTERVAL_SEC秒空ける ---
    recent = _recent_posts(hours=1)
    if recent:
        from datetime import datetime as _dt
        last_ts = max(r.get('ts', '') for r in recent)
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(last_ts)).total_seconds()
            if elapsed < MIN_INTERVAL_SEC:
                import time as _time
                wait = MIN_INTERVAL_SEC - elapsed
                _time.sleep(wait)
        except (ValueError, TypeError):
            pass

    # --- レート制限チェック ---
    if len(recent) >= MAX_POSTS_PER_HOUR:
        _add_to_retry_queue(text, url, post_id)
        return {
            'success': False, 'queued': True,
            'error': f'レート制限: 直近1時間に{len(recent)}件投稿済み (上限{MAX_POSTS_PER_HOUR}件)。キューに追加'
        }

    # --- 日次レート制限チェック ---
    daily = _recent_posts(hours=24)
    if len(daily) >= MAX_POSTS_PER_DAY:
        return {
            'success': False, 'queued': False,
            'error': f'日次上限: 直近24時間に{len(daily)}件投稿済み (上限{MAX_POSTS_PER_DAY}件)。翌日まで停止'
        }

    # --- 類似テキスト検知 ---
    for r in recent:
        if _text_similarity(text, r.get('text', '')) > SIMILARITY_THRESHOLD:
            _add_to_retry_queue(text, url, post_id)
            return {
                'success': False, 'queued': True,
                'error': '類似テキスト検知: 直近投稿と類似度が高いためキューに追加'
            }

    # --- credential検証 ---
    creds, errors = _validate()
    if errors or creds is None:
        return {'success': False, 'error': '; '.join(errors[:2]) if errors else 'credential invalid'}

    # --- テキスト構築: generate_tweet() でフック+感情行+CTA+ハッシュタグ生成 ---
    full_text = ''
    try:
        from lib.x_post_templates import generate_tweet, CATEGORY_TO_GENRE
        _genre = genre or 'default'
        # カテゴリID→ジャンル変換（unified_publisherからkind=category名が来る場合）
        if _genre not in ('news', 'analysis', 'beauty', 'travel',
                          'breaking', 'comeback', 'controversy', 'live',
                          'chart', 'fashion', 'default'):
            _genre = CATEGORY_TO_GENRE.get(_genre, 'default')
        full_text = generate_tweet(text, url or '', _genre, include_url=bool(url))
    except Exception as _e:
        print(f"[x_poster] generate_tweet fallback: {_e}", file=sys.stderr)

    # フォールバック: テンプレート生成失敗時は従来方式
    if not full_text:
        hashtags = '#KPOPJOURNAL #KPOP'
        try:
            from lib.x_post_templates import build_hashtags
            _artist = artist or _extract_artist_from_title(text)
            hashtags = build_hashtags(_artist, genre or 'default')
        except Exception:
            pass
        url_reserve = 24 if url else 0
        hashtag_reserve = len(hashtags) + 2
        max_title = 280 - url_reserve - hashtag_reserve - 4
        hook_text = text[:max_title].rstrip()
        parts = [hook_text, f'\n\n{hashtags}']
        if url:
            parts.append(f'\n{url}')
        full_text = ''.join(parts)[:280]

    # --- 投稿前セルフ検証 (2026-05-06追加: ハッシュタグ0件事故の再発防止) ---
    _hashtag_count = full_text.count('#')
    if _hashtag_count < 2:
        import sys as _sys
        print(f"[x_poster] WARN: hashtag {_hashtag_count}個 (<2)。テンプレート関数の問題を調査",
              file=_sys.stderr)
        # フォールバック: 最低限のハッシュタグを強制追加
        if '#KPOPJOURNAL' not in full_text:
            _fallback_tags = '\n#KPOPJOURNAL #KPOP'
            full_text = full_text[:280 - len(_fallback_tags)] + _fallback_tags

    try:
        tweet_id, attempts = _post(full_text, '', creds)
        entry = {
            'ts': datetime.now().isoformat(),
            'tweet_id': tweet_id,
            'text': full_text[:120],
            'url': url,
            'attempts': attempts,
            'status': 'ok',
            'hashtag_count': _hashtag_count,
        }
        if post_id:
            entry['post_id'] = post_id

        _log(entry)
        return {'success': True, 'tweet_id': tweet_id}
    except Exception as e:
        err = str(e)[:200]
        entry = {
            'ts': datetime.now().isoformat(),
            'text': full_text[:120],
            'url': url,
            'status': 'error',
            'error': err,
        }
        if post_id:
            entry['post_id'] = post_id
        _log(entry)
        # API失敗時もリトライキューに追加（永久エラー以外）
        if url and '401' not in err:
            _add_to_retry_queue(text, url, post_id)
        return {'success': False, 'error': err, 'queued': bool(url and '401' not in err)}


def _log(d):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(d, ensure_ascii=False) + '\n')


def post_hook_and_reply(text: str, url: str, post_id: int = None,
                        genre: str = "", artist: str = "") -> dict:
    """2段投稿: フック(URLなし)→URLリプライ (IMP最大化ハック)

    1) generate_tweet(include_url=False) でフック投稿（URLペナルティ回避）
    2) tweet_idに対してURLリプライを投稿（OGPカード表示）

    Returns:
        {'success': bool, 'tweet_id': str, 'reply_id': str|None, 'error': str|None}
    """
    import time as _time

    if _validate is None or _post is None:
        return {'success': False, 'error': 'post_to_x module import失敗'}

    if not text or len(text.strip()) < 5:
        return {'success': False, 'error': 'テキストが空または短すぎる'}

    # --- WP記事status再検証 (2026-05-07: 投稿後trash化されたbroken linkをXに送る事故防止) ---
    if post_id:
        try:
            import urllib.request as _ur, urllib.error as _ue, base64 as _b64, json as _json
            _AUTH = _b64.b64encode(b'kpop-bot:vl1H 1brV m4Pq Z1sm F8lZ 3nzh').decode()
            _u = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}?_fields=id,status,featured_media,link&status=any'
            _req = _ur.Request(_u, headers={'Authorization': f'Basic {_AUTH}'})
            with _ur.urlopen(_req, timeout=10) as _r:
                _wp = _json.loads(_r.read())
            if _wp.get('status') != 'publish':
                return {'success': False,
                        'error': f'WP記事 {post_id} status={_wp.get("status")} (publish以外) — X投稿スキップ'}
            # featured_media が無い記事は og-default になりサムネ不一致 → スキップ
            if _wp.get('featured_media', 0) == 0:
                return {'success': False,
                        'error': f'WP記事 {post_id} featured_media未設定 — X投稿スキップ'}
        except Exception as _e:
            print(f"[x_poster] WP status check err: {_e}", file=sys.stderr)

    # --- URL事前検証 (soft-404 + OGP og-default 検出) ---
    if url:
        try:
            from lib.x_post_url_validator import validate_url
            url_check = validate_url(url)
            if not url_check.get('ok'):
                _reason = url_check.get('reason', '')
                # soft-404 / OGP問題 (og-default.png) いずれもサムネ不一致直結のためスキップ
                if 'soft-404' in _reason or 'og-default' in _reason or 'OGP問題' in _reason:
                    return {'success': False, 'error': f'URL検証NG: {_reason}'}
        except Exception:
            pass

    # --- レート制限チェック ---
    recent = _recent_posts(hours=1)
    if len(recent) >= MAX_POSTS_PER_HOUR:
        _add_to_retry_queue(text, url, post_id)
        return {'success': False, 'queued': True, 'error': 'レート制限'}

    # --- バースト防止 ---
    if recent:
        last_ts = max(r.get('ts', '') for r in recent)
        try:
            elapsed = (datetime.now() - datetime.fromisoformat(last_ts)).total_seconds()
            if elapsed < MIN_INTERVAL_SEC:
                _time.sleep(MIN_INTERVAL_SEC - elapsed)
        except (ValueError, TypeError):
            pass

    # --- credential検証 ---
    creds, errors = _validate()
    if errors or creds is None:
        return {'success': False, 'error': '; '.join(errors[:2]) if errors else 'credential invalid'}

    # --- Step 1: フック投稿（URLなし） ---
    try:
        from lib.x_post_templates import generate_tweet, generate_tweet_llm, CATEGORY_TO_GENRE
        _genre = genre or 'default'
        if _genre not in ('news', 'analysis', 'beauty', 'travel',
                          'breaking', 'comeback', 'controversy', 'live',
                          'chart', 'fashion', 'default'):
            _genre = CATEGORY_TO_GENRE.get(_genre, 'default')
        # 2026-05-26: X_PERSONA_LLM=1 で「等身大ライターのつぶやき」フックを生成
        # (テンプレ/タイトル丸写しの AI 臭を根治)。X_TWEET_LLM=1 は faceless 事実型の
        # 旧 Phase2。どちらも本文(source)を読むため、有効なら WP から本文を取得する。
        _persona_enabled = os.getenv('X_PERSONA_LLM', '0') == '1'
        _llm_enabled = os.getenv('X_TWEET_LLM', '0') == '1'
        _source_text = ''
        if (_persona_enabled or _llm_enabled) and post_id:
            try:
                import urllib.request as _ur
                import json as _json
                _u = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}?_fields=content'
                _r = _ur.urlopen(_u, timeout=10)
                _wp = _json.loads(_r.read())
                _raw = _wp.get('content', {}).get('rendered', '') or ''
                _source_text = re.sub(r'<[^>]+>', '', _raw)[:1500]
            except Exception:
                _source_text = ''
        hook_text = ''
        if _persona_enabled:
            try:
                from lib.x_persona_voice import generate_persona_post
                _p = generate_persona_post(
                    {'title': text, 'source_text': _source_text, 'artist': artist},
                    kind='article', genre=_genre, include_url=False,
                )
                if _p.get('used_llm') and _p.get('text'):
                    hook_text = _p['text']
            except Exception:
                hook_text = ''
        if not hook_text:
            if _llm_enabled and _source_text:
                hook_text = generate_tweet_llm(text, '', _source_text, _genre, include_url=False)
            else:
                hook_text = generate_tweet(text, '', _genre, include_url=False)
    except Exception as _e:
        # フォールバック
        hook_text = text[:200] + '\n\n#KPOPJOURNAL #KPOP'

    if not hook_text:
        hook_text = text[:200] + '\n\n#KPOPJOURNAL #KPOP'

    try:
        tweet_id, attempts = _post(hook_text, '', creds)
    except Exception as e:
        err = str(e)[:200]
        _log({'ts': datetime.now().isoformat(), 'text': hook_text[:120],
              'url': url, 'status': 'error', 'error': err, 'post_id': post_id})
        return {'success': False, 'error': err}

    _log({
        'ts': datetime.now().isoformat(), 'tweet_id': tweet_id,
        'text': hook_text[:120], 'url': url, 'attempts': attempts,
        'status': 'ok', 'mode': 'hook', 'post_id': post_id,
    })

    # --- Step 2: URLリプライ（3秒後） ---
    reply_id = None
    if url and tweet_id:
        _time.sleep(3)
        try:
            from lib.x_post_templates import generate_url_reply
            reply_text = generate_url_reply(url)
        except Exception:
            reply_text = f"📖 記事はこちら👇\n{url}"

        try:
            from google_metrics.post_to_x import post_tweet as _raw_post
            reply_id, _ = _raw_post(reply_text, tweet_id, creds)
            _log({
                'ts': datetime.now().isoformat(), 'tweet_id': reply_id,
                'text': reply_text[:120], 'url': url,
                'status': 'ok', 'mode': 'url_reply',
                'reply_to': tweet_id, 'post_id': post_id,
            })
        except Exception as e:
            # リプライ失敗はフック投稿自体は成功なので致命的ではない
            _log({
                'ts': datetime.now().isoformat(), 'url': url,
                'status': 'reply_error', 'error': str(e)[:100],
                'reply_to': tweet_id, 'post_id': post_id,
            })

    return {'success': True, 'tweet_id': tweet_id, 'reply_id': reply_id}


def post_thread(text: str, url: str, post_id: int = None,
                genre: str = "", artist: str = "") -> dict:
    """3段スレッド投稿(施策4): フック(text-only)→要点(text-only)→URL(OGPカード)。

    スレッドは単発比 +40-60% imp(最新Xアルゴ)。本文URLは最終段のみ=非Premium
    ペナルティ回避。post_hook_and_reply を土台に、間に「要点」ツイートを1枚挟む。
    要点生成に失敗したら自動的に従来の2段(post_hook_and_reply)へフォールバック。
    """
    import time as _time

    if _validate is None or _post is None:
        return {'success': False, 'error': 'post_to_x module import失敗'}

    # 要点テキストを記事本文から生成(LLM)。失敗・無効なら2段にフォールバック。
    point_text = ""
    try:
        creds, cerr = _validate()
        if not creds:
            return {'success': False, 'error': f'認証NG: {cerr}'}
        _genre = genre or 'default'
        _source_text = ""
        if post_id:
            try:
                import urllib.request as _ur, json as _json
                _u = f'https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}?_fields=content'
                with _ur.urlopen(_u, timeout=10) as _r:
                    _wp = _json.loads(_r.read())
                _raw = _wp.get('content', {}).get('rendered', '') or ''
                _source_text = re.sub(r'<[^>]+>', '', _raw)[:1500]
            except Exception:
                _source_text = ''
        if _source_text:
            from lib.x_post_templates import generate_tweet_llm
            # 要点: フックとは別角度の「数値/固有名詞を含む1文」をURLなしで
            point_text = generate_tweet_llm(text, '', _source_text, _genre, include_url=False)
    except Exception:
        point_text = ""

    # 要点が作れない/フックと酷似なら 2段にフォールバック(スレッドにする意味が無い)
    if not point_text or point_text.strip()[:40] == text.strip()[:40]:
        return post_hook_and_reply(text, url, post_id=post_id, genre=genre, artist=artist)

    # hook → 要点(reply) → url(reply) の順で3段を直接組む。
    _genre = genre or 'default'
    hook_text = ''
    # 2026-05-26: X_PERSONA_LLM=1 ならフックを等身大ライターのつぶやき化(要点は
    # 従来の事実型 generate_tweet_llm のまま=人間の声+客観要点の二段構え)。
    if os.getenv('X_PERSONA_LLM', '0') == '1':
        try:
            from lib.x_persona_voice import generate_persona_post
            _p = generate_persona_post(
                {'title': text, 'source_text': _source_text, 'artist': artist},
                kind='article', genre=_genre, include_url=False,
            )
            if _p.get('used_llm') and _p.get('text'):
                hook_text = _p['text']
        except Exception:
            hook_text = ''
    try:
        from lib.x_post_templates import generate_tweet, generate_tweet_llm, generate_url_reply
        if not hook_text:
            hook_text = generate_tweet(text, '', _genre, include_url=False)
    except Exception:
        hook_text = hook_text or (text[:200] + '\n\n#KPOPJOURNAL #KPOP')
    if not hook_text:
        hook_text = text[:200] + '\n\n#KPOPJOURNAL #KPOP'

    try:
        t1, _ = _post(hook_text, '', creds)
    except Exception as e:
        return {'success': False, 'error': f'hook投稿失敗: {str(e)[:120]}'}
    _log({'ts': datetime.now().isoformat(), 'tweet_id': t1, 'text': hook_text[:120],
          'url': url, 'status': 'ok', 'mode': 'hook', 'post_id': post_id})

    from google_metrics.post_to_x import post_tweet as _raw_post
    # Step 2: 要点(URLなし、t1への返信)
    t2 = None
    _time.sleep(3)
    try:
        t2, _ = _raw_post(point_text, t1, creds)
        _log({'ts': datetime.now().isoformat(), 'tweet_id': t2, 'text': point_text[:120],
              'status': 'ok', 'mode': 'thread_point', 'reply_to': t1, 'post_id': post_id})
    except Exception as e:
        _log({'ts': datetime.now().isoformat(), 'status': 'thread_point_error',
              'error': str(e)[:100], 'reply_to': t1, 'post_id': post_id})

    # Step 3: URL(t2 があれば t2、無ければ t1 への返信)
    reply_to = t2 or t1
    reply_id = None
    if url:
        _time.sleep(3)
        try:
            reply_text = generate_url_reply(url)
        except Exception:
            reply_text = f"📖 記事はこちら👇\n{url}"
        try:
            reply_id, _ = _raw_post(reply_text, reply_to, creds)
            _log({'ts': datetime.now().isoformat(), 'tweet_id': reply_id, 'text': reply_text[:120],
                  'url': url, 'status': 'ok', 'mode': 'url_reply', 'reply_to': reply_to, 'post_id': post_id})
        except Exception as e:
            _log({'ts': datetime.now().isoformat(), 'url': url, 'status': 'reply_error',
                  'error': str(e)[:100], 'reply_to': reply_to, 'post_id': post_id})

    return {'success': True, 'tweet_id': t1, 'point_id': t2, 'reply_id': reply_id, 'mode': 'thread'}


if __name__ == '__main__':
    t = sys.argv[1] if len(sys.argv) > 1 else 'X連携テスト'
    u = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(post_tweet(t, u), ensure_ascii=False, indent=2))
