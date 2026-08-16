#!/usr/bin/env python3
"""X投稿スケジューラー — キューベースの時間分散投稿

設計思想:
  記事公開時にXへ即時投稿せず、x_post_queue.json にキューイング。
  本スクリプトがcronで定期実行され、ピーク時間帯に合わせて投稿する。

投稿タイミング設計:
  - 07:00-08:00 (通勤): 3件まで
  - 12:00-13:00 (昼休み): 3件まで
  - 17:00-18:00 (退勤): 2件まで
  - 19:00-21:00 (ゴールデン): 5件まで (最重要)
  - 上記以外: 1件/時 (フィラー)

投稿間隔: 最低5分（同一時間帯内で分散）

Usage:
  python3 -m pipeline.x_scheduled_poster           # キューから投稿実行
  python3 -m pipeline.x_scheduled_poster --status  # キュー状態確認

cron: */15 7-21 * * * (15分おきに確認・投稿)
"""
import json
import os
import sys
import time
import base64
import argparse
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, '/home/aiuser/kpop-ai-system')
from dotenv import load_dotenv
load_dotenv('/home/aiuser/kpop-ai-system/.env')

BASE = Path('/home/aiuser/kpop-ai-system')
QUEUE_FILE = BASE / 'config' / 'x_post_queue.json'
POSTS_LOG = BASE / 'logs' / 'x_posts.jsonl'
SCHEDULE_LOG = BASE / 'logs' / 'x_scheduled.log'

# 2026-06-22: シャドウバン(アカウント単位の可視性フィルタ)対処で日次上限を
#   10→6に削減。本人では見えるが第三者アカウントで「このポストは表示でき
#   ません」になる状態を確認(shadowban_x_20260622.md)。
#   真因=投稿量過多(1記事=hook+要点+URLリプライ=3ツイート×日10件で raw 18-24
#   tweet/日)+外部リンク比率57%+超低imp57% の bot シグネチャ。
#   ※同日: 認証アカウント(Premium)へアップグレード済 → アルゴ4xboost+リンク
#   ペナルティ緩和。よって量を絞りすぎず6件に。当面は評判回復を優先し、
#   回復確認後に段階的に増やす(まず量と間隔で bot シグネチャを除去)。
# 旧設定(参考): DAILY_POST_CAP=10 / SLOTS 7:2,8,12,13,17,18,19,20,21 各1
# 2026-08-12 Phase1(シャドウバン解除後の段階再開): 5週間全停止→診断3点セット健全を
#   確認して再開。真因「量×外部リンク×無反応」のうちリンクを完全に断つため、
#   会話型text-onlyのみ・cap=3 で運用。imp回復確認後に Phase2(記事誘導は
#   URLリプライでなくプロフィール誘導化)へ。可視性悪化時は x_auto_repause_guard が自動停止。
# Phase1前の設定(参考): DAILY_POST_CAP=6 / SLOTS 8,12,17(記事)+19,21(会話) 各1
# 2026-08-16 Phase2移行: tools/x_phase2_report.py が GO 判定(n=8 / 平均imp 84.4 /
#   中央値 69.5 / GATE=平均8・中央値6)。バン期の崩壊水準6.0を10倍超で上回り、
#   可視性は回復と判断。ただし再発トリガーだった外部リンクは戻さない:
#   記事誘導は「URLゼロ・本文フックのみ(プロフィール誘導)」で復活させる
#   (POST_ARTICLE_URL=False)。cap は 3→4 の +1 のみ、記事帯も 12時の1枠のみ。
#   一気に旧設定(cap6/記事3枠)へ戻すと量×リンクの bot シグネチャが再構成される。
DAILY_POST_CAP = 4            # 1日の総投稿上限(Phase2: 会話3 + 記事1)
# 時間帯ごとの最大投稿数。合計=4。昼に記事帯、夜ゴールデン2枠は会話を維持。
SLOTS = {
    12: 1,   # 12:xx 昼(記事・URLなし)
    17: 1,   # 17:xx 夕(会話)
    19: 1,   # 19:xx ゴールデン(会話)
    21: 1,   # 21:xx ゴールデン(会話)
}
DEFAULT_SLOT_SIZE = 0  # 上記以外の時間帯は投稿しない(上限厳守)
MIN_INTERVAL_MIN = 5   # 同一時間帯内の最低間隔(分)
PRIORITY_GENRES = {'news', 'breaking', 'comeback', 'chart'}  # 優先ジャンル

AB_LOG = "/home/aiuser/kpop-ai-system/logs/x_ab_log.jsonl"


def _next_ab_variant() -> str:
    """M10 AB の variant を「これまでの実投稿件数が少ない方」に割り当てる。
    旧実装(post_id%2)は breaking 記事IDが偶奇に偏るため A:B が崩れた(実測16:36)。
    AB_LOG の実件数を読み、少ない方を返す(同数なら A)。これで自動的に均衡する。
    """
    import json as _j
    a = b = 0
    try:
        with open(AB_LOG, encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line:
                    continue
                _v = _j.loads(_line).get("variant")
                if _v == "A":
                    a += 1
                elif _v == "B":
                    b += 1
    except FileNotFoundError:
        pass
    except Exception:
        # ログ破損時は偏らせないよう A/B いずれかに寄せきらない=Aで継続
        return "A"
    return "A" if a <= b else "B"

# 2026-05-26(施策2): 時間帯の役割分担。最新Xアルゴは「会話/返信」が最強(返信13.5,
# 著者返信+75)で、ゴールデン帯(19-21時)は会話起点 text-only が伸びる。一方 通勤/昼/夕は
# 記事誘導(リンククリック+11)で流入を稼ぐ。混在帯は記事を主にしつつ時々会話。
#   'conversation' = 会話起点 text-only を投げる(x_conversation_starter)
#   'article'      = queue から記事誘導(post_hook_and_reply / thread)
#   'mix'          = 記事主。本回が mix なら記事、ただし会話cron(7/17/21)が別途会話を担う
# 2026-06-22: SLOTS削減に合わせて役割時間帯も {8,12,17}=記事 / {19,21}=会話 に整合。
# 2026-08-12 Phase1: 全スロット会話型・記事帯ゼロ(URL投稿を完全停止)。
#   Phase2移行時は ARTICLE_HOURS を復活させること(Phase1前: {8,12,17})。
# 2026-08-16 Phase2: 記事帯を 12時の1枠だけ復活(Phase1前の{8,12,17}のうち1つ)。
#   会話は 17/19/21 の3枠。POST_ARTICLE_URL=False によりこの記事帯も URL を
#   一切含まない(本文フックのみ+プロフィール誘導)ため、リンク比率は 0% のまま。
CONVERSATION_HOURS = {17, 19, 21}   # Phase2: 夕+ゴールデン2枠は会話
ARTICLE_HOURS = {12}                # Phase2: 昼1枠のみ記事誘導(URLなし)

# 2026-08-16: Phase2 の記事誘導は URL を投げない。True に戻すと本文リンク/URL
# リプライが復活するが、それがシャドウバン再発の主トリガーだった
# (x-shadowban-state-and-history)。戻すのは Phase3 で、再度 imp 実測を確認してから。
POST_ARTICLE_URL = False
def slot_role(hour: int) -> str:
    if hour in CONVERSATION_HOURS:
        return 'conversation'
    if hour in ARTICLE_HOURS:
        return 'article'
    return 'mix'


def load_queue() -> list:
    if not QUEUE_FILE.exists():
        return []
    try:
        data = json.loads(QUEUE_FILE.read_text(encoding='utf-8'))
        return data.get('queue', [])
    except (json.JSONDecodeError, OSError):
        return []


def _writeback_tweet_id(post_id: int, tweet_id: str):
    """tweet_idをWordPressメタ+ローカルTSVに書き戻し"""
    try:
        import urllib.request
        url = f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}"
        import base64
        WP_USER = os.environ.get('WP_USER', 'kpop-bot')
        WP_PASS = os.environ.get('WP_PASS', '')
        auth = f"Basic {base64.b64encode(f'{WP_USER}:{WP_PASS}'.encode()).decode()}"
        payload = json.dumps({"meta": {"_x_tweet_id": str(tweet_id)}}).encode()
        req = urllib.request.Request(url, data=payload, headers={
            "Authorization": auth, "Content-Type": "application/json",
        }, method="POST")
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass
    # ローカルTSV
    tsv_path = BASE / 'logs' / 'tweet_id_db.tsv'
    try:
        with open(tsv_path, 'a', encoding='utf-8') as f:
            f.write(f"{post_id}\t{tweet_id}\t\t{datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")
    except Exception:
        pass


def save_queue(queue: list):
    data = {
        'updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'count': len(queue),
        'queue': queue,
    }
    QUEUE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def enqueue(title: str, url: str, post_id: int = None, genre: str = '',
            artist: str = '', priority: str = 'normal'):
    """投稿をキューに追加（x_poster.pyから呼ばれる）"""
    queue = load_queue()

    # 重複チェック
    if any(e.get('url') == url for e in queue):
        return False

    entry = {
        'title': title[:120],
        'url': url,
        'post_id': post_id,
        'genre': genre,
        'artist': artist,
        'priority': priority,
        'queued_at': datetime.now().isoformat(),
    }
    queue.append(entry)
    save_queue(queue)
    return True


def _posts_this_hour() -> int:
    """現在の時間帯に投稿済みの件数。
    1記事 = hook + url_reply の2エントリだが、SLOT制限は記事数基準のため
    mode='hook'のみカウントする (2026-05-07: スロット2倍消化バグ修正)
    """
    if not POSTS_LOG.exists():
        return 0
    now = datetime.now()
    hour_start = now.replace(minute=0, second=0, microsecond=0)
    count = 0
    for line in open(POSTS_LOG, encoding='utf-8'):
        try:
            e = json.loads(line.strip())
            if e.get('status') != 'ok':
                continue
            # hookのみカウント (url_replyは同一記事のフォローアップ)
            if e.get('mode') and e.get('mode') != 'hook':
                continue
            ts = datetime.fromisoformat(e.get('ts', '2000-01-01'))
            if ts >= hour_start:
                count += 1
        except (json.JSONDecodeError, ValueError):
            continue
    return count


def _posts_today() -> int:
    """本日(0時以降)に投稿した件数。hookのみカウント(会話・記事とも1件=1hook)。
    DAILY_POST_CAP の判定に使う。"""
    if not POSTS_LOG.exists():
        return 0
    day_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    count = 0
    for line in open(POSTS_LOG, encoding='utf-8'):
        try:
            e = json.loads(line.strip())
            if e.get('status') != 'ok':
                continue
            if e.get('mode') and e.get('mode') != 'hook':
                continue
            ts = datetime.fromisoformat(e.get('ts', '2000-01-01'))
            if ts >= day_start:
                count += 1
        except (json.JSONDecodeError, ValueError):
            continue
    return count


def _last_post_time() -> datetime:
    """最後に投稿した時刻"""
    if not POSTS_LOG.exists():
        return datetime.min
    last = datetime.min
    for line in open(POSTS_LOG, encoding='utf-8'):
        try:
            e = json.loads(line.strip())
            if e.get('status') == 'ok':
                ts = datetime.fromisoformat(e.get('ts', '2000-01-01'))
                if ts > last:
                    last = ts
        except (json.JSONDecodeError, ValueError):
            continue
    return last


def _current_slot_limit() -> int:
    """現在時刻のスロット上限"""
    hour = datetime.now().hour
    return SLOTS.get(hour, DEFAULT_SLOT_SIZE)


QUEUE_MAX_AGE_HOURS = 48  # 48h超のqueue itemsは古ニュース扱いでdrop


def _drop_stale(queue: list) -> list:
    """48h超のqueue itemsを除外 (古いニュースは投稿価値が低い)"""
    cutoff = datetime.now() - timedelta(hours=QUEUE_MAX_AGE_HOURS)
    fresh = []
    for e in queue:
        qa = e.get('queued_at', '')
        try:
            qt = datetime.fromisoformat(qa)
            if qt >= cutoff:
                fresh.append(e)
        except (ValueError, TypeError):
            fresh.append(e)  # 日時不明はとりあえず残す
    if len(fresh) < len(queue):
        print(f"[scheduler] {len(queue) - len(fresh)}件を48h超でdrop")
    return fresh


def _genre_engagement_map() -> dict:
    """施策3の実測 initial_performance.jsonl から genre 別の平均 score_per_impression を作る。
    記事の genre は queue 側にしか無いため、ここでは「実測がある=効いている系統」を
    緩く反映する代理として、全体平均 spi を返す(genre 紐付けが無い場合のフォールバック)。
    実測が無ければ空(=engagement項は0)。"""
    perf = BASE / 'logs' / 'initial_performance.jsonl'
    if not perf.exists():
        return {}
    spis = []
    for line in perf.read_text(encoding='utf-8', errors='replace').splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get('source') == 'x_engagement':
            spis.append(float(r.get('x_score_per_impression', 0) or 0))
    return {'_avg_spi': (sum(spis) / len(spis)) if spis else 0.0}


def _score_queue(queue: list) -> list:
    """10件選定スコアで降順ソート(2026-05-26 オーナー指示)。
    最新Xアルゴ(時間減衰・優先度)+ 施策3実測 + 多様性(連投回避)で並べる。

    score = priority(0-40) + freshness(0-30) + engagement(0-15) - diversity_penalty
      priority: high/優先ジャンル=40, 通常=20, travel/popup/default=10
      freshness: queued からの経過で減衰(0h=30, 24hで約半分, 48hで0)。アルゴの時間減衰に対応
      engagement: 実測 spi があれば最大15(効いている系統を後押し)
      diversity: 同一アーティストが上位に既出なら -15(連投回避=スキル§10)
    """
    eng = _genre_engagement_map()
    avg_spi = eng.get('_avg_spi', 0.0)
    now_ts = datetime.now().timestamp()
    scored = []
    for e in queue:
        # priority
        if e.get('priority') == 'high' or e.get('genre') in PRIORITY_GENRES:
            pscore = 40.0
        elif e.get('genre') in ('travel', 'popup', 'default', ''):
            pscore = 10.0
        else:
            pscore = 20.0
        # freshness: 24hで半減する指数減衰
        age_h = max(0.0, (now_ts - _ts_to_int(e.get('queued_at', ''))) / 3600.0)
        fscore = 30.0 * (0.5 ** (age_h / 24.0))
        # engagement: 実測 spi を 0.5 で頭打ち→15点満点に正規化
        escore = min(15.0, (avg_spi / 0.5) * 15.0) if avg_spi > 0 else 0.0
        scored.append((pscore + fscore + escore, e))
    # スコア降順。多様性ペナルティは選定段で適用するためここでは素点で並べる
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored]


def _select_with_diversity(sorted_queue: list, n: int) -> list:
    """スコア順から n 件選ぶ際、同一アーティストの連投を避ける。
    既に選んだアーティストの2件目以降は後回し(同点なら別アーティスト優先)。"""
    picked, seen_artists, deferred = [], set(), []
    for e in sorted_queue:
        if len(picked) >= n:
            break
        a = (e.get('artist') or '').strip()
        if a and a in seen_artists:
            deferred.append(e)
            continue
        picked.append(e)
        if a:
            seen_artists.add(a)
    # 枠が余れば deferred(同一アーティスト2件目以降)で埋める
    for e in deferred:
        if len(picked) >= n:
            break
        picked.append(e)
    return picked


def _sort_queue(queue: list) -> list:
    """選定スコアで並べる(後方互換の名前を維持。中身は _score_queue に委譲)。"""
    return _score_queue(queue)


def _ts_to_int(ts: str) -> int:
    try:
        return int(datetime.fromisoformat(ts).timestamp())
    except (ValueError, TypeError):
        return 0


def _post_conversation(dry_run: bool = False) -> dict:
    """会話起点 text-only 投稿(施策2/1)。x_conversation_starter で生成し、
    URLなしで投稿。成功したら engagement watch を登録(施策1 が +10/30/60分で返信収集)。"""
    try:
        from lib.x_conversation_starter import generate, validate, register_watch
    except ImportError as e:
        print(f"  [conversation] import失敗: {e}")
        return {'success': False, 'error': str(e)}
    post = generate(None, None)        # ランダムテンプレ×アーティスト(directives重み付けは生成側)
    issues = validate(post)
    if issues:
        print(f"  [conversation] バリデーションNG: {issues}")
        return {'success': False, 'error': str(issues)}
    if dry_run:
        print(f"  [conversation] DRY: {post['text'][:50]}...")
        return {'success': True, 'dry_run': True}
    from google_metrics.post_to_x import post_tweet, validate_credentials
    creds, errors = validate_credentials()
    if creds is None:
        return {'success': False, 'error': '; '.join(errors)}
    tid, err = post_tweet(post['text'], creds=creds)
    if not tid:
        print(f"  [conversation] 投稿失敗: {err}")
        return {'success': False, 'error': err}
    print(f"  [conversation] ✓ {tid}: {post['text'][:40]}")
    # x_posts.jsonl に記録(レート制限カウント用、mode=hook 扱い)。
    # tweet_id は x_auto_repause_guard の可視性実測が要るため必須(2026-08-12)。
    try:
        with POSTS_LOG.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'ts': datetime.now().isoformat(), 'mode': 'hook',
                                'status': 'ok', 'tweet_id': str(tid),
                                'text': post['text'],
                                'kind': 'conversation'}, ensure_ascii=False) + '\n')
    except OSError:
        pass
    # engagement watch 登録(施策1 が消化)。register_watch が無くても致命でない。
    try:
        register_watch(tid, post['text'])
    except Exception as e:  # noqa: BLE001
        print(f"  [conversation] watch登録skip: {e}")
    return {'success': True, 'tweet_id': tid}


def process_queue(dry_run: bool = False) -> dict:
    """キューからピーク時間帯に合わせて投稿（フック+URLリプライ方式）"""

    raw_queue = load_queue()
    queue = _drop_stale(raw_queue)
    if len(queue) < len(raw_queue):
        save_queue(queue)  # stale drop を永続化
    # 2026-08-16 修理: 会話起点(text-only)はキューを使わないため、キューが空でも
    # 投稿できなければならない。従来はここで無条件 return しており、キューが空に
    # なった瞬間に会話帯の投稿ごと死んでいた(8/16 12:17 の会話投稿が実際に消失。
    # Phase1中はキューに残骸が数件あったため偶然生き延びていただけ)。
    # 会話帯かどうかは時刻で決まるので、判定前に return してはいけない。
    if not queue and slot_role(datetime.now().hour) != 'conversation':
        print("[scheduler] キュー空")
        return {'processed': 0, 'remaining': 0}

    now = datetime.now()
    hour = now.hour

    # 営業時間外は投稿しない
    if hour < 7 or hour > 21:
        print(f"[scheduler] 営業時間外 ({hour}時) — スキップ")
        return {'processed': 0, 'remaining': len(queue)}

    # 2026-05-26: 日次上限(会話+記事の合計)を厳守
    posted_today = _posts_today()
    if posted_today >= DAILY_POST_CAP:
        print(f"[scheduler] 日次上限到達 ({posted_today}/{DAILY_POST_CAP}) — スキップ")
        return {'processed': 0, 'remaining': len(queue)}

    # 今時間帯の残りスロット(日次残予算でも頭打ち)
    slot_limit = _current_slot_limit()
    already_posted = _posts_this_hour()
    daily_budget = max(0, DAILY_POST_CAP - posted_today)
    remaining_slots = min(max(0, slot_limit - already_posted), daily_budget)

    if remaining_slots <= 0:
        print(f"[scheduler] {hour}時台スロット消化({already_posted}/{slot_limit}) or 日次残{daily_budget}")
        return {'processed': 0, 'remaining': len(queue)}

    # 最低間隔チェック
    last_post = _last_post_time()
    elapsed_min = (now - last_post).total_seconds() / 60
    if elapsed_min < MIN_INTERVAL_MIN:
        wait = MIN_INTERVAL_MIN - elapsed_min
        print(f"[scheduler] 前回投稿から{elapsed_min:.0f}分 — {wait:.0f}分待機")
        return {'processed': 0, 'remaining': len(queue)}

    # 2026-05-26(施策2): 時間帯の役割で会話/記事を出し分け。
    # conversation 帯はまず会話起点を1件(text-only)。残スロットがあれば記事も。
    # mix 帯は記事主。article 帯は記事のみ。
    role = slot_role(hour)
    if role == 'conversation':
        conv = _post_conversation(dry_run=dry_run)
        if conv.get('success'):
            # 会話を1枠消費。残スロットで記事も出す(ゴールデンは枠が広い)
            remaining_slots = max(0, remaining_slots - 1)
            if remaining_slots <= 0:
                save_queue(queue)
                print(f"[scheduler] 会話1件投稿(ゴールデン)/ 残キュー: {len(queue)}件")
                return {'processed': 1, 'remaining': len(queue)}
            # 会話投稿後は間隔を空けるため、本回は記事を出さず次回に回す
            print(f"[scheduler] 会話1件投稿 / 記事は次回(間隔確保)/ 残キュー: {len(queue)}件")
            return {'processed': 1, 'remaining': len(queue)}

    # 選定スコアで並べ、同一アーティスト連投を避けて選ぶ
    queue = _sort_queue(queue)
    to_post = min(remaining_slots, 2)  # 1回の実行で最大2件
    selected = _select_with_diversity(queue, to_post)
    processed = 0
    new_queue = list(queue)

    for entry in selected:
        title = entry.get('title', '')
        url = entry.get('url', '')
        post_id = entry.get('post_id')
        genre = entry.get('genre', '')
        artist = entry.get('artist', '')

        print(f"  posting: {title[:50]}...")

        # 2026-05-08: WP status verify (draft/trash の即時投稿事故防止 — 18765事案)
        # unauthenticated REST APIは publish のみ200を返す。401/404は draft/trash として扱う
        if post_id:
            try:
                import urllib.request, urllib.error, json as _json
                _req = urllib.request.Request(
                    f"https://www.kpopjournal.tokyo/wp-json/wp/v2/posts/{post_id}?_fields=id,status",
                    headers={'User-Agent': 'kpopjournal-scheduler/1.0'})
                _is_publish = False
                try:
                    with urllib.request.urlopen(_req, timeout=10) as _r:
                        _wp = _json.loads(_r.read().decode())
                    _is_publish = (_wp.get('status') == 'publish')
                except urllib.error.HTTPError as _he:
                    if _he.code in (401, 403, 404):
                        _is_publish = False  # draft/trash/deleted
                    else:
                        raise
                if not _is_publish:
                    print(f"    ✗ WP not-publish — skip & remove from queue (pid={post_id})")
                    new_queue.remove(entry)
                    processed += 1
                    continue
            except Exception as _e:
                print(f"    [warn] WP status check failed ({_e}) — proceeding")

        if dry_run:
            processed += 1
            new_queue.remove(entry)
            continue

        # 2026-05-26(施策4): high priority 記事はスレッド(フック→要点→URL、単発比+40-60%imp)、
        # その他は従来の2段。post_thread は要点生成不可なら自動で2段にフォールバック。
        # M10 AB (2026-05-28 / 偏り修正 2026-06-05): variant を「実投稿件数が少ない方」へ
        # 割当(A=ペルソナ/B=PopCrave)。旧 post_id%2 は記事IDの偶奇偏りで A:B=16:36 に崩れた。
        variant = _next_ab_variant()
        # 2026-08-16 Phase2: POST_ARTICLE_URL=False の間は URL を渡さない。
        # post_hook_and_reply は url='' なら Step2 の URL リプライを打たず、
        # フック単発(URLゼロ)で終わる。post_thread は末尾に URL を出す設計のため
        # Phase2 では high priority でも使わず、単発に統一する。
        if not POST_ARTICLE_URL:
            from lib.x_poster import post_hook_and_reply
            result = post_hook_and_reply(title, '', post_id=post_id, genre=genre,
                                         artist=artist, variant=variant)
        elif entry.get('priority') == 'high' or genre in PRIORITY_GENRES:
            from lib.x_poster import post_thread
            result = post_thread(title, url, post_id=post_id, genre=genre, artist=artist, variant=variant)
        else:
            from lib.x_poster import post_hook_and_reply
            result = post_hook_and_reply(title, url, post_id=post_id, genre=genre, artist=artist, variant=variant)
        if result.get('success'):
            tid = result.get('tweet_id', '')
            rid = result.get('reply_id', '')
            actual_variant = result.get('variant', variant)
            print(f"    ✓ hook={tid} reply={rid} variant={actual_variant}")
            # M10 AB log: tweet_id, variant, post_id, title を記録(72h後に集計)
            try:
                import json as _j, os as _o
                from datetime import datetime as _dt
                _o.makedirs(_o.path.dirname(AB_LOG), exist_ok=True)
                with open(AB_LOG, "a", encoding="utf-8") as _f:
                    _f.write(_j.dumps({
                        "ts": _dt.now().isoformat(),
                        "tweet_id": tid, "reply_id": rid,
                        "variant": actual_variant, "post_id": post_id,
                        "title": title[:120], "genre": genre,
                        "mode": result.get('mode', 'hook_reply'),
                    }, ensure_ascii=False) + "\n")
            except Exception as _e:
                print(f"    [warn] AB log write failed: {_e}")
            processed += 1
            new_queue.remove(entry)
            # tweet_idをWPに書き戻し（kpop_pipeline.sh互換）
            if tid and post_id:
                _writeback_tweet_id(post_id, tid)
        elif result.get('queued'):
            # レート制限 → 次回に回す
            print(f"    → rate limited, retry later")
            break
        else:
            # 永久エラー → キューから除外
            print(f"    ✗ {result.get('error', '')[:60]}")
            new_queue.remove(entry)
            processed += 1

        time.sleep(15)  # 投稿間隔

    save_queue(new_queue)

    result = {'processed': processed, 'remaining': len(new_queue)}
    print(f"[scheduler] 投稿: {processed}件 / 残キュー: {len(new_queue)}件")

    # 2026-05-07: silent rot 検知用 alert
    # ガード厳格化により全rejectされ続けた場合の早期警告
    # cond: queue>=10あるのに 連続3回以上 processed=0 ならalert
    _alert_silent_rot(processed, len(new_queue))

    return result


def _alert_silent_rot(processed: int, remaining: int):
    """0件alert: queue 残あるのに連続skipが続いたら警告"""
    alert_log = BASE / 'logs' / 'x_scheduler_silent_rot.jsonl'
    alert_log.parent.mkdir(exist_ok=True)
    # 直近5回の processed history を読む
    history = []
    if alert_log.exists():
        try:
            for line in alert_log.read_text(errors='replace').splitlines()[-5:]:
                d = json.loads(line)
                history.append(d.get('processed', 0))
        except Exception:
            history = []
    # 直近の processed をlogに append
    entry = {
        'ts': datetime.now().isoformat(),
        'processed': processed,
        'remaining': remaining,
    }
    with alert_log.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    # alert: 直近(本回含む)4回連続 processed=0 かつ queue 残>=10
    history.append(processed)
    if remaining >= 10 and len(history) >= 4 and all(h == 0 for h in history[-4:]):
        msg = (f"[ALERT] x_scheduled_poster: 連続4回 0投稿 / queue残 {remaining}件 — "
               f"全guard rejected (trash/og-default疑い) もしくは外部要因。要調査")
        print(msg)
        # logs/alerts.jsonl に追加 (運用alert集約)
        alerts_path = BASE / 'logs' / 'alerts.jsonl'
        with alerts_path.open('a', encoding='utf-8') as f:
            f.write(json.dumps({
                'ts': datetime.now().isoformat(),
                'severity': 'high',
                'source': 'x_scheduled_poster',
                'msg': msg,
                'history': history[-4:],
                'remaining': remaining,
            }, ensure_ascii=False) + '\n')


def show_status():
    """キュー状態表示"""
    queue = load_queue()
    print(f"キュー: {len(queue)}件")
    hour = datetime.now().hour
    print(f"現在: {hour}時台 スロット上限={SLOTS.get(hour, DEFAULT_SLOT_SIZE)}")
    print(f"今時間帯の投稿済み: {_posts_this_hour()}件")
    print(f"最終投稿: {_last_post_time().strftime('%H:%M:%S')}")
    print()
    for i, e in enumerate(queue[:10], 1):
        genre = e.get('genre', '-')
        title = e.get('title', '')[:40]
        queued = e.get('queued_at', '')[:16]
        print(f"  {i}. [{genre}] {title} ({queued})")
    if len(queue) > 10:
        print(f"  ... +{len(queue)-10}件")


def main():
    parser = argparse.ArgumentParser(description="X投稿スケジューラー")
    parser.add_argument("--status", action="store_true", help="キュー状態確認")
    parser.add_argument("--dry-run", action="store_true", help="チェックのみ")
    args = parser.parse_args()

    if args.status:
        show_status()
    else:
        print(f"=== x_scheduled_poster: {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
        process_queue(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
