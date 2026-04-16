"""
再生成キュービルダー (regeneration_queue_builder.py)

REWRITE_NOW / IMPROVE ランクの投稿に対して、
勝ちパターンを参考にタイトル/サムネ/Xフック候補を3案生成する。

優先度:
  P0: rank=REWRITE_NOW AND hours>=72
  P1: rank=REWRITE_NOW AND hours<72
  P2: rank=IMPROVE

入力:
  logs/post_publish_evaluations.jsonl
  logs/winning_patterns.jsonl
  logs/rewrite_targets.json  (CTRスコア低い投稿)

出力:
  logs/regeneration_queue.jsonl
"""
import json
import os
import sys
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
LOGS_DIR = os.path.join(BASE_DIR, "logs")

EVAL_FILE = os.path.join(LOGS_DIR, "post_publish_evaluations.jsonl")
PATTERNS_FILE = os.path.join(LOGS_DIR, "winning_patterns.jsonl")
REWRITE_FILE = os.path.join(LOGS_DIR, "rewrite_targets.json")
QUEUE_OUT = os.path.join(LOGS_DIR, "regeneration_queue.jsonl")


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


def load_existing_queue():
    records = load_jsonl(QUEUE_OUT)
    return {str(r.get("post_id", "")): r for r in records}


def get_latest_eval(evals_by_post):
    """各post_idの最新評価を返す"""
    latest = {}
    for r in load_jsonl(EVAL_FILE):
        pid = str(r.get("post_id", ""))
        if pid not in latest or (r.get("hours_since_publish", 0) or 0) > (latest[pid].get("hours_since_publish", 0) or 0):
            latest[pid] = r
    return latest


def get_winning_template(category, patterns):
    """カテゴリ一致する勝ちパターンのうち最もスコアが高いものを返す"""
    matches = [p for p in patterns if p.get("category") == category and p.get("rank") == "WIN"]
    if not matches:
        matches = [p for p in patterns if p.get("rank") == "WIN"]
    if not matches:
        return None
    # thumb_score + x_hook_scoreの合計でソート
    matches.sort(key=lambda p: (p.get("thumbnail_score", 0) or 0) + (p.get("x_hook_score", 0) or 0), reverse=True)
    return matches[0]


def generate_candidates(post_eval, template):
    """タイトル/サムネ/Xフック候補を3案生成"""
    title = post_eval.get("title", "")
    category = post_eval.get("category", "")

    candidates = []

    # 案1: 数字強調型
    cand1 = {
        "pattern": "数字強調型",
        "title_hint": f"【数字】+ {title[:20]} の衝撃",
        "thumbnail_line1": "【速報】",
        "thumbnail_line2": f"{title[:10]}の真相",
        "x_hook_hint": f"数字+固有名詞+感情語+対比で120-150文字構成",
        "thumb_elements": ["number", "emotion", "contrast"],
    }
    candidates.append(cand1)

    # 案2: 固有名詞×感情型
    cand2 = {
        "pattern": "固有名詞×感情型",
        "title_hint": f"アーティスト名 + {title[:15]} が判明",
        "thumbnail_line1": "アーティスト名",
        "thumbnail_line2": "ついに判明",
        "x_hook_hint": f"固有名詞+感情語+対比構造で構成",
        "thumb_elements": ["proper_noun", "emotion"],
    }
    candidates.append(cand2)

    # 案3: 対比構造型 (テンプレートから)
    if template:
        cand3 = {
            "pattern": "対比構造型(勝ちパターン参照)",
            "title_hint": f"復帰/空白/急騰 + {title[:15]}",
            "thumbnail_line1": "急騰",
            "thumbnail_line2": f"{title[:10]}",
            "x_hook_hint": "対比構造+数字+固有名詞で構成",
            "thumb_elements": ["contrast", "number", "proper_noun"],
            "template_ref": {
                "category": template.get("category"),
                "thumb_score": template.get("thumbnail_score"),
                "x_score": template.get("x_hook_score"),
            }
        }
    else:
        cand3 = {
            "pattern": "対比構造型",
            "title_hint": f"電撃 + {title[:15]}",
            "thumbnail_line1": "電撃発表",
            "thumbnail_line2": f"{title[:10]}",
            "x_hook_hint": "電撃+対比+感情語構成",
            "thumb_elements": ["contrast", "emotion"],
        }
    candidates.append(cand3)

    return candidates


def assign_priority(rank, hours):
    if rank == "REWRITE_NOW" and (hours or 0) >= 72:
        return "P0"
    elif rank == "REWRITE_NOW":
        return "P1"
    else:
        return "P2"


def run():
    latest_evals = get_latest_eval({})
    patterns = load_jsonl(PATTERNS_FILE)
    rewrite_targets = load_json(REWRITE_FILE)
    existing_queue = load_existing_queue()

    # rewrite_targetsのpost_idも対象に加える
    rewrite_ids = set()
    if isinstance(rewrite_targets, list):
        for r in rewrite_targets:
            rewrite_ids.add(str(r.get("post_id", "")))
    elif isinstance(rewrite_targets, dict):
        rewrite_ids.update(str(k) for k in rewrite_targets.keys())

    queued = []

    for pid, ev in latest_evals.items():
        rank = ev.get("rank", "")
        hours = ev.get("hours_since_publish", 0) or 0

        # 対象: REWRITE_NOW / IMPROVE / rewrite_targets
        if rank not in ("REWRITE_NOW", "IMPROVE") and pid not in rewrite_ids:
            continue

        # 既にキューにある場合はスキップ
        if pid in existing_queue:
            continue

        category = ev.get("category", "")
        template = get_winning_template(category, patterns)
        candidates = generate_candidates(ev, template)
        priority = assign_priority(rank, hours)

        record = {
            "post_id": pid,
            "title": ev.get("title", ""),
            "url": ev.get("url", ""),
            "rank": rank,
            "priority": priority,
            "hours_since_publish": hours,
            "category": category,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "candidates": candidates,
        }
        queued.append(record)

        with open(QUEUE_OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return queued


if __name__ == "__main__":
    results = run()
    print(f"再生成キュー追加: {len(results)}件")
    for r in results:
        print(f"  [{r['priority']}] {r['rank']} post_id={r['post_id']} {r['title'][:30]}")
