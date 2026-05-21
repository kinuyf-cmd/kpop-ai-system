"""
テンプレートオプティマイザー (template_optimizer.py)

カテゴリ別TOP5勝ちパターンを抽出し、次回投稿のテンプレートを推奨する。

対象カテゴリ:
  breaking / chart / profile / guide / review / rumor / live / comeback

評価軸:
  - number + contrast + emotion + proper_noun の組み合わせ頻度
  - thumbnail_score + x_hook_score の合計

入力:
  logs/winning_patterns.jsonl

出力:
  logs/template_recommendations.json
"""
import json
import os
from datetime import datetime, timezone
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
LOGS_DIR = os.path.join(BASE_DIR, "logs")

PATTERNS_FILE = os.path.join(LOGS_DIR, "winning_patterns.jsonl")
TEMPLATE_OUT = os.path.join(LOGS_DIR, "template_recommendations.json")

CATEGORIES = [
    "breaking", "chart", "profile", "guide",
    "review", "rumor", "live", "comeback",
]

ELEMENT_KEYS = ["has_number", "has_proper_noun", "has_emotion_word", "has_contrast"]


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


def element_combo(pattern):
    """要素の組み合わせをfrozensetで返す"""
    return frozenset(k for k in ELEMENT_KEYS if pattern.get(k))


def combo_label(combo):
    labels = {
        "has_number": "数字",
        "has_proper_noun": "固有名詞",
        "has_emotion_word": "感情語",
        "has_contrast": "対比",
    }
    return "+".join(labels.get(k, k) for k in sorted(combo))


def analyze_category(patterns, category):
    """カテゴリ内のWINパターンを分析してTOP5を返す"""
    wins = [p for p in patterns if p.get("category") == category and p.get("rank") == "WIN"]

    if not wins:
        return {
            "category": category,
            "win_count": 0,
            "top5": [],
            "best_combo": None,
            "best_combo_label": None,
            "avg_thumb_score": 0,
            "avg_x_score": 0,
        }

    # 要素組み合わせ頻度集計
    combo_counts = defaultdict(int)
    combo_scores = defaultdict(list)

    for p in wins:
        combo = element_combo(p)
        combo_counts[combo] += 1
        total_score = (p.get("thumbnail_score", 0) or 0) + (p.get("x_hook_score", 0) or 0)
        combo_scores[combo].append(total_score)

    # 最頻出組み合わせ
    best_combo = max(combo_counts, key=lambda c: (combo_counts[c], sum(combo_scores[c]) / len(combo_scores[c])))

    # TOP5: thumb+xスコア合計でソート
    wins_scored = sorted(
        wins,
        key=lambda p: (p.get("thumbnail_score", 0) or 0) + (p.get("x_hook_score", 0) or 0),
        reverse=True
    )
    top5 = []
    for p in wins_scored[:5]:
        top5.append({
            "post_id": p.get("post_id"),
            "title": p.get("title", "")[:40],
            "thumbnail_score": p.get("thumbnail_score", 0),
            "x_hook_score": p.get("x_hook_score", 0),
            "publish_hour": p.get("publish_hour"),
            "elements": combo_label(element_combo(p)),
        })

    avg_thumb = sum(p.get("thumbnail_score", 0) or 0 for p in wins) / len(wins)
    avg_x = sum(p.get("x_hook_score", 0) or 0 for p in wins) / len(wins)

    return {
        "category": category,
        "win_count": len(wins),
        "top5": top5,
        "best_combo": list(best_combo),
        "best_combo_label": combo_label(best_combo),
        "best_combo_count": combo_counts[best_combo],
        "avg_thumb_score": round(avg_thumb, 1),
        "avg_x_score": round(avg_x, 1),
    }


def run():
    patterns = load_jsonl(PATTERNS_FILE)

    if not patterns:
        result = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": "winning_patterns.jsonlが空またはなし",
            "categories": {},
        }
        with open(TEMPLATE_OUT, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("winning_patterns.jsonlが空のためスキップ")
        return result

    categories_result = {}
    for cat in CATEGORIES:
        categories_result[cat] = analyze_category(patterns, cat)

    # 全カテゴリ横断TOP10
    all_wins = [p for p in patterns if p.get("rank") == "WIN"]
    all_wins_sorted = sorted(
        all_wins,
        key=lambda p: (p.get("thumbnail_score", 0) or 0) + (p.get("x_hook_score", 0) or 0),
        reverse=True
    )
    global_top10 = []
    for p in all_wins_sorted[:10]:
        global_top10.append({
            "post_id": p.get("post_id"),
            "title": p.get("title", "")[:40],
            "category": p.get("category"),
            "thumbnail_score": p.get("thumbnail_score", 0),
            "x_hook_score": p.get("x_hook_score", 0),
            "elements": combo_label(element_combo(p)),
        })

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_win_patterns": len(all_wins),
        "global_top10": global_top10,
        "categories": categories_result,
    }

    with open(TEMPLATE_OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"テンプレート推奨生成完了: {len(CATEGORIES)}カテゴリ / WIN合計{len(all_wins)}件")
    return result


if __name__ == "__main__":
    run()
