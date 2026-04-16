"""
公開後評価モジュール (post_publish_evaluator.py)

公開後 24h / 48h / 72h の時点でランク評価を行う。
ランク: WIN / HOLD / IMPROVE / REWRITE_NOW

入力:
  logs/kpi_posts.jsonl       - 投稿ログ (post_id, timestamp, title, url, categories)
  logs/gsc_tracking.json     - GSCインデックス/クリック数
  logs/x_post_results.jsonl  - X投稿結果 (post_id, status, hook_score)

出力:
  logs/post_publish_evaluations.jsonl  - 評価結果追記
"""
import json
import os
import sys
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
LOGS_DIR = os.path.join(BASE_DIR, "logs")

KPI_POSTS = os.path.join(LOGS_DIR, "kpi_posts.jsonl")
GSC_TRACKING = os.path.join(LOGS_DIR, "gsc_tracking.json")
X_RESULTS = os.path.join(LOGS_DIR, "x_post_results.jsonl")
EVAL_OUT     = os.path.join(LOGS_DIR, "post_publish_evaluations.jsonl")
ACTIONS_FILE = os.path.join(LOGS_DIR, "rewrite_actions.jsonl")


def load_jsonl(path):
    records = []
    if not os.path.exists(path):
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    return records


def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}


def load_existing_evals():
    """既存評価をpost_id -> list[eval]で返す"""
    evals = {}
    records = load_jsonl(EVAL_OUT)
    for r in records:
        pid = str(r.get("post_id", ""))
        if pid:
            evals.setdefault(pid, []).append(r)
    return evals


def hours_since(ts_str):
    """ISO8601文字列から現在までの経過時間(時間)を返す"""
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - ts
        return delta.total_seconds() / 3600
    except Exception:
        return None


def rank_post(post, gsc_data, x_data):
    """
    評価ロジック:
    WIN:         インデックス済み AND (クリック>=5 OR X投稿成功)
    HOLD:        インデックス済み AND クリック<5
    IMPROVE:     未インデックス AND 48h未満 (まだ猶予あり)
    REWRITE_NOW: 未インデックス AND 48h以上 OR クリック0が72h継続
    """
    post_id = str(post.get("post_id", ""))
    ts = post.get("timestamp", "")
    hours = hours_since(ts) if ts else None

    # GSCデータ
    gsc = gsc_data.get(post_id, {})
    indexed = gsc.get("indexed", False)
    clicks = gsc.get("clicks_7d", 0) or 0
    impressions = gsc.get("impressions_7d", 0) or 0

    # X投稿データ
    x_info = x_data.get(post_id, {})
    x_success = x_info.get("status", "") == "posted"
    x_hook_score = x_info.get("hook_score", 0) or 0

    # ランク判定
    if indexed and (clicks >= 5 or x_success):
        rank = "WIN"
    elif indexed and clicks < 5:
        rank = "HOLD"
    elif not indexed and hours is not None and hours < 48:
        rank = "IMPROVE"
    else:
        rank = "REWRITE_NOW"

    # リライト後フラグ
    rewrite_actions = []
    actions_path = ACTIONS_FILE
    if os.path.exists(actions_path):
        with open(actions_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    a = json.loads(line)
                    if str(a.get("post_id", "")) == post_id:
                        rewrite_actions.append(a)
                except Exception:
                    pass

    is_post_rewrite = len(rewrite_actions) > 0
    rewrite_count   = len(rewrite_actions)

    # before/after スコア (impressions_7d を簡易スコアとして利用)
    before_score = None
    after_score  = None
    improvement_delta = None
    if rewrite_actions:
        # 最初のリライト前後でimpressionsを比較
        first_action_ts = rewrite_actions[0].get("executed_at", "")
        # before: first_action_ts以前の評価のclicks
        before_evals = [e for e in load_jsonl(EVAL_OUT)
                        if str(e.get("post_id","")) == post_id
                        and e.get("eval_ts","") < first_action_ts]
        if before_evals:
            before_score = before_evals[-1].get("clicks_7d", 0) or 0
        after_score = clicks
        if before_score is not None:
            improvement_delta = after_score - before_score

    return {
        "post_id": post_id,
        "title": post.get("title", ""),
        "url": post.get("url", ""),
        "publish_ts": ts,
        "eval_ts": datetime.now(timezone.utc).isoformat(),
        "hours_since_publish": round(hours, 1) if hours is not None else None,
        "indexed": indexed,
        "clicks_7d": clicks,
        "impressions_7d": impressions,
        "x_success": x_success,
        "x_hook_score": x_hook_score,
        "rank": rank,
        "is_post_rewrite": is_post_rewrite,
        "rewrite_count": rewrite_count,
        "before_score": before_score,
        "after_score": after_score,
        "improvement_delta": improvement_delta,
    }


def should_evaluate(post, existing_evals):
    """24h/48h/72hのチェックポイントで未評価なら評価対象とする"""
    post_id = str(post.get("post_id", ""))
    ts = post.get("timestamp", "")
    hours = hours_since(ts) if ts else None
    if hours is None:
        return False

    # 24h未満は対象外
    if hours < 23:
        return False

    # 168h(7日)超は古すぎてスキップ
    if hours > 168:
        return False

    prev = existing_evals.get(post_id, [])

    # 評価チェックポイント: 24h / 48h / 72h
    checkpoints = [24, 48, 72]
    prev_hours = [e.get("hours_since_publish", 0) or 0 for e in prev]

    for cp in checkpoints:
        if hours >= cp:
            # このチェックポイント近辺(cp±6h)の評価がなければ評価
            already = any(abs(ph - cp) <= 6 for ph in prev_hours)
            if not already:
                return True

    return False


def run(post_id_filter=None):
    posts = load_jsonl(KPI_POSTS)
    gsc_raw = load_json(GSC_TRACKING)
    x_records = load_jsonl(X_RESULTS)
    existing_evals = load_existing_evals()

    # X結果をpost_idでインデックス
    x_data = {}
    for r in x_records:
        pid = str(r.get("post_id", ""))
        if pid:
            x_data[pid] = r

    evaluated = []
    for post in posts:
        post_id = str(post.get("post_id", ""))
        if post_id_filter and post_id != str(post_id_filter):
            continue
        if not should_evaluate(post, existing_evals):
            continue

        result = rank_post(post, gsc_raw, x_data)
        evaluated.append(result)

        with open(EVAL_OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

    return evaluated


if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else None
    results = run(pid)
    print(f"評価完了: {len(results)}件")
    for r in results:
        print(f"  [{r['rank']}] post_id={r['post_id']} {r['title'][:30]} ({r['hours_since_publish']}h)")
