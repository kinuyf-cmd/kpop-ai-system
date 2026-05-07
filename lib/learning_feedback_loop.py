#!/usr/bin/env python3
"""
learning_feedback_loop.py — 強化学習フィードバックループ v1.0

improvement_engine.sh から呼ばれる3つの学習ステップ:
  1. learn-titles  : CTR上位タイトルのパターン分析 → eevee/metamon プロンプト注入
  2. learn-typos   : 誤字パターン収集 → error_patterns.json 自動追加
  3. learn-quality  : S/Cランク記事の共通特徴抽出 → 品質ゲート自動フィードバック

Usage:
  python3 lib/learning_feedback_loop.py learn-titles
  python3 lib/learning_feedback_loop.py learn-typos
  python3 lib/learning_feedback_loop.py learn-quality
  python3 lib/learning_feedback_loop.py dashboard-data   # ダッシュボード用JSON出力
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"
AGENTS = BASE / "agents"

ERROR_PATTERNS_FILE = CONFIG / "error_patterns.json"
AUTO_DIRECTIVES_FILE = CONFIG / "auto_directives.json"
LEARNING_LOG_FILE = LOGS / "learning_feedback.jsonl"
QUALITY_WEEKLY_FILE = LOGS / "quality_weekly.jsonl"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ユーティリティ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _log_learning(category: str, action: str, details: dict) -> None:
    """学習結果をJSONLに記録"""
    LOGS.mkdir(exist_ok=True)
    record = {
        "ts": datetime.now().isoformat(),
        "category": category,
        "action": action,
        **details,
    }
    with open(LEARNING_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _load_jsonl(path: Path, max_lines: int = 500) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(errors="replace").splitlines()[-max_lines:]:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 9: タイトル品質学習
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def learn_titles() -> None:
    """直近7日間のCTR上位タイトルからパターンを抽出し、eevee/metamonに注入"""
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    # GSCメトリクスからCTR上位を取得
    metrics_file = BASE / "google_metrics" / "metrics_yesterday.json"
    metrics = _load_json(metrics_file)

    # winning_patterns.jsonl からも取得
    wp_records = _load_jsonl(LOGS / "winning_patterns.jsonl")
    recent_wp = [r for r in wp_records if r.get("recorded_at", "")[:10] >= week_ago]

    # title_performance.jsonl からwin記事を取得
    tp_records = _load_jsonl(LOGS / "title_performance.jsonl")
    win_titles = [r.get("title", "") for r in tp_records
                  if r.get("result") == "win" and r.get("ts", r.get("date", ""))[:10] >= week_ago]

    # KPI posts からも取得
    kpi_records = _load_jsonl(LOGS / "kpi_posts.jsonl")
    recent_kpi = [r for r in kpi_records if r.get("date", "")[:10] >= week_ago]

    # パターン分析
    hook_words = Counter()
    title_patterns = Counter()
    all_titles = win_titles[:]

    # winning_patterns の高スコア記事
    for r in recent_wp:
        title = r.get("title", "")
        if title:
            all_titles.append(title)

    if not all_titles:
        print("タイトル学習: 直近7日間の対象タイトルなし")
        return

    # フックワード頻度分析
    HOOK_WORDS = [
        "なぜ", "ついに", "衝撃", "完全", "最新", "速報", "判明", "解禁",
        "決定", "炎上", "話題", "注目", "始動", "復活", "伝説", "異常",
        "全部", "本当", "実は", "まさか", "神", "レベチ", "電撃", "暴露",
        "緊急", "独占", "初公開", "驚愕", "覚醒", "圧巻",
    ]

    for title in all_titles:
        for hw in HOOK_WORDS:
            if hw in title:
                hook_words[hw] += 1

        # 構造パターン検出
        if re.search(r"\d+", title):
            title_patterns["数字入り"] += 1
        if re.search(r"なぜ|どうして|いつ", title):
            title_patterns["疑問形"] += 1
        if re.search(r"[？?]", title):
            title_patterns["疑問符"] += 1
        if "——" in title or "―" in title or "—" in title:
            title_patterns["ダッシュ区切り"] += 1
        if re.search(r"「.+」", title):
            title_patterns["カギ括弧引用"] += 1
        if re.search(r"異常|衝撃|伝説|覚醒|圧巻|レベチ|神", title):
            title_patterns["感情爆発ワード"] += 1
        if len(title) <= 35:
            title_patterns["35字以内"] += 1
        elif len(title) <= 45:
            title_patterns["36-45字"] += 1

    # 上位パターンを抽出
    top_hooks = [w for w, _ in hook_words.most_common(10)]
    top_patterns = [p for p, _ in title_patterns.most_common(5)]

    # auto_directives.json に注入
    directives = _load_json(AUTO_DIRECTIVES_FILE)
    if not directives:
        directives = {"updated_at": "", "agent_directives": {}, "winning_words": []}

    # winning_words 更新
    existing_words = set(directives.get("winning_words", []))
    new_words = [w for w in top_hooks if w not in existing_words][:5]
    directives["winning_words"] = list(existing_words | set(new_words))[:15]

    # eevee/metamon への学習指示注入
    pattern_desc = "、".join(top_patterns[:3])
    hook_desc = "、".join(top_hooks[:5])

    for agent in ("eevee", "metamon"):
        agent_dir = directives.setdefault("agent_directives", {})
        existing = agent_dir.get(agent, {})
        learned_patterns = existing.get("learned_title_patterns", "")
        new_pattern_str = f"【CTR学習({datetime.now().strftime('%m/%d')})】勝ちパターン: {pattern_desc} / フック語: {hook_desc}"

        if new_pattern_str != learned_patterns:
            agent_dir.setdefault(agent, {})
            agent_dir[agent]["learned_title_patterns"] = new_pattern_str
            agent_dir[agent]["title_learning_date"] = datetime.now().strftime("%Y-%m-%d")

    directives["updated_at"] = datetime.now().isoformat()
    AUTO_DIRECTIVES_FILE.write_text(json.dumps(directives, ensure_ascii=False, indent=2) + "\n")

    _log_learning("title_quality", "pattern_extracted", {
        "title_count": len(all_titles),
        "top_hooks": top_hooks[:5],
        "top_patterns": top_patterns[:3],
        "new_words_added": new_words,
    })

    print(f"タイトル学習完了: {len(all_titles)}本分析")
    print(f"  フック語TOP5: {hook_desc}")
    print(f"  勝ちパターン: {pattern_desc}")
    if new_words:
        print(f"  新規勝ちワード: {', '.join(new_words)}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 10: 誤字学習
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def learn_typos() -> None:
    """直近7日間の誤字パターンを収集し、error_patterns.json に追加"""
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    # audit_feedback.jsonl から誤字関連を抽出
    feedback_records = _load_jsonl(LOGS / "audit_feedback.jsonl", max_lines=200)
    recent_feedback = [r for r in feedback_records if r.get("ts", "")[:10] >= week_ago]

    # post_audit.log からも誤字検出を拾う
    audit_log = LOGS / "post_audit.log"
    typo_from_log = []
    if audit_log.exists():
        for line in audit_log.read_text(errors="replace").splitlines():
            if line[:10] >= week_ago:
                if any(kw in line for kw in ["誤字", "脱字", "typo", "文字化け", "誤記", "スペルミス", "表記ゆれ"]):
                    typo_from_log.append(line.strip()[:120])

    # 誤字パターンを収集
    typo_patterns = Counter()
    typo_examples = {}

    TYPO_KEYWORDS = ["誤字", "脱字", "typo", "文字化け", "誤記", "スペルミス", "表記ゆれ",
                     "変換ミス", "全角半角", "カタカナ", "ローマ字"]
    # 正常報告やセクションヘッダーは誤字パターンではないのでスキップ
    FALSE_POSITIVE_RE = re.compile(r"(なし|OK|正常|✅|問題なし|検出なし|---.*チェック|AUDIT.*---)")

    for record in recent_feedback:
        for issue in record.get("issues", []):
            if FALSE_POSITIVE_RE.search(issue):
                continue
            for kw in TYPO_KEYWORDS:
                if kw in issue:
                    key = re.sub(r"[#\d]+", "N", issue[:20]).strip()
                    typo_patterns[key] += 1
                    typo_examples[key] = issue[:100]
                    break

    for log_line in typo_from_log:
        if FALSE_POSITIVE_RE.search(log_line):
            continue
        for kw in TYPO_KEYWORDS:
            if kw in log_line:
                key = re.sub(r"[#\d]+", "N", log_line[:20]).strip()
                typo_patterns[key] += 1
                typo_examples[key] = log_line[:100]
                break

    if not typo_patterns:
        print("誤字学習: 直近7日間の誤字パターンなし")
        _log_learning("typo", "no_patterns", {"period": week_ago})
        return

    # error_patterns.json に追加
    error_data = _load_json(ERROR_PATTERNS_FILE)
    if not error_data:
        error_data = {"updated_at": "", "patterns": {}, "recurring_errors": []}

    patterns = error_data.setdefault("patterns", {})
    added = 0

    for key, count in typo_patterns.most_common(10):
        pattern_key = f"typo_{abs(hash(key)) % 100000}"
        # 既存パターンとの重複チェック
        existing = None
        for pk, pv in patterns.items():
            if pv.get("example", "")[:20] == typo_examples.get(key, "")[:20]:
                existing = pk
                break

        if existing:
            patterns[existing]["count"] = patterns[existing].get("count", 0) + count
            patterns[existing]["last_seen"] = datetime.now().strftime("%Y-%m-%d")
        else:
            patterns[pattern_key] = {
                "count": count,
                "last_seen": datetime.now().strftime("%Y-%m-%d"),
                "example": typo_examples.get(key, ""),
                "fix": "生成時に誤字チェックリストで照合すること。同一パターンの再発防止",
                "agent": "deoxys",
                "category": "typo",
            }
            added += 1

    # recurring_errors 更新（3回以上のパターン）
    error_data["recurring_errors"] = [
        {"key": k, **v} for k, v in patterns.items()
        if v.get("count", 0) >= 3
    ]

    error_data["updated_at"] = datetime.now().isoformat()
    ERROR_PATTERNS_FILE.write_text(json.dumps(error_data, ensure_ascii=False, indent=2) + "\n")

    _log_learning("typo", "patterns_collected", {
        "patterns_found": len(typo_patterns),
        "new_added": added,
        "top_patterns": dict(typo_patterns.most_common(3)),
    })

    print(f"誤字学習完了: {len(typo_patterns)}パターン検出, {added}件新規追加")
    for key, count in typo_patterns.most_common(3):
        print(f"  [{count}回] {typo_examples.get(key, key)[:60]}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STEP 11: 品質スコア学習
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def learn_quality() -> None:
    """S/Cランク記事の共通特徴を抽出し、品質ゲートにフィードバック"""
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    # quality_weekly.jsonl から週次データ取得
    weekly_records = _load_jsonl(QUALITY_WEEKLY_FILE)

    # kpi_posts.jsonl から直近記事を取得
    kpi_records = _load_jsonl(LOGS / "kpi_posts.jsonl")
    recent_posts = [r for r in kpi_records if r.get("date", "")[:10] >= week_ago]

    # winning_patterns.jsonl からランク情報取得
    wp_records = _load_jsonl(LOGS / "winning_patterns.jsonl")
    recent_wp = [r for r in wp_records if r.get("recorded_at", "")[:10] >= week_ago]

    # audit_feedback.jsonl から品質問題を取得
    feedback_records = _load_jsonl(LOGS / "audit_feedback.jsonl", max_lines=200)
    recent_feedback = [r for r in feedback_records if r.get("ts", "")[:10] >= week_ago]

    # S/Aランク記事の共通特徴
    s_features = Counter()
    c_problems = Counter()

    for r in recent_wp:
        has_number = r.get("has_number", False)
        has_proper_noun = r.get("has_proper_noun", False)
        has_emotion = r.get("has_emotion_word", False)
        has_contrast = r.get("has_contrast", False)
        has_thumb = r.get("has_thumbnail", False)
        title_len = r.get("title_length", 0)
        thumb_score = r.get("thumbnail_score", 0) or 0

        feature_count = sum([has_number, has_proper_noun, has_emotion, has_contrast])

        # 高スコア記事の特徴（thumb_score >= 70 or 4要素中3以上）
        if thumb_score >= 70 or feature_count >= 3:
            if has_number:
                s_features["数字入り"] += 1
            if has_proper_noun:
                s_features["固有名詞"] += 1
            if has_emotion:
                s_features["感情ワード"] += 1
            if has_contrast:
                s_features["対比構造"] += 1
            if has_thumb:
                s_features["サムネあり"] += 1
            if 24 <= title_len <= 38:
                s_features["最適文字数(24-38)"] += 1

        # 低スコア記事の問題
        if thumb_score < 50 and thumb_score > 0:
            if not has_number:
                c_problems["数字なし"] += 1
            if not has_proper_noun:
                c_problems["固有名詞なし"] += 1
            if not has_emotion:
                c_problems["感情ワードなし"] += 1
            if title_len > 50:
                c_problems["タイトル長すぎ(50字超)"] += 1
            if title_len < 20:
                c_problems["タイトル短すぎ(20字未満)"] += 1

    # audit_feedback から頻出問題パターン
    issue_counter = Counter()
    for record in recent_feedback:
        for issue in record.get("issues", []):
            # カテゴリ分類
            if any(kw in issue for kw in ["文字数", "短い", "薄い"]):
                issue_counter["文字数不足"] += 1
            elif any(kw in issue for kw in ["SEO", "キーワード", "メタ"]):
                issue_counter["SEO不備"] += 1
            elif any(kw in issue for kw in ["CTA", "リンク", "導線"]):
                issue_counter["CTA/導線不足"] += 1
            elif any(kw in issue for kw in ["タイトル", "CTR"]):
                issue_counter["タイトル品質低"] += 1
            elif any(kw in issue for kw in ["ファクト", "事実", "誤り", "架空"]):
                issue_counter["ファクト問題"] += 1

    # 品質ゲートへのフィードバック
    directives = _load_json(AUTO_DIRECTIVES_FILE)
    if not directives:
        directives = {"updated_at": "", "agent_directives": {}}

    # arceus への品質学習注入
    arceus_dir = directives.setdefault("agent_directives", {}).setdefault("arceus", {})
    if s_features:
        top_s = "、".join(f for f, _ in s_features.most_common(3))
        arceus_dir["learned_s_features"] = f"S/A記事共通特徴: {top_s}"
    if c_problems:
        top_c = "、".join(f for f, _ in c_problems.most_common(3))
        arceus_dir["learned_c_problems"] = f"C/D記事共通問題: {top_c}"
    arceus_dir["quality_learning_date"] = datetime.now().strftime("%Y-%m-%d")

    # 繰り返し問題の検出（3回以上同じカテゴリ）
    recurring_issues = [issue for issue, cnt in issue_counter.items() if cnt >= 3]
    if recurring_issues:
        arceus_dir["recurring_quality_issues"] = "、".join(recurring_issues)

    # safety_config への動的フィードバック
    safety_file = CONFIG / "safety_config.json"
    if safety_file.exists():
        safety = _load_json(safety_file)
        gates = safety.setdefault("quality_gates", {})

        # Sランク記事が多い場合 → ゲート維持/強化、C多い場合 → チェック項目追加
        s_count = sum(1 for r in recent_wp
                      if (r.get("thumbnail_score", 0) or 0) >= 70)
        c_count = sum(1 for r in recent_wp
                      if 0 < (r.get("thumbnail_score", 0) or 0) < 50)

        if c_count > s_count and c_count >= 3:
            # C記事が多すぎる場合、チェック強化の記録
            gates["quality_feedback_note"] = (
                f"C記事{c_count}件>S記事{s_count}件 ({datetime.now().strftime('%m/%d')}): "
                f"問題={', '.join(c for c, _ in c_problems.most_common(2))}"
            )
            safety["updated_at"] = datetime.now().isoformat()
            safety_file.write_text(json.dumps(safety, ensure_ascii=False, indent=2) + "\n")

    directives["updated_at"] = datetime.now().isoformat()
    AUTO_DIRECTIVES_FILE.write_text(json.dumps(directives, ensure_ascii=False, indent=2) + "\n")

    _log_learning("quality_score", "feedback_generated", {
        "s_features": dict(s_features.most_common(5)),
        "c_problems": dict(c_problems.most_common(5)),
        "recurring_issues": recurring_issues,
        "s_count": s_count if 's_count' in dir() else 0,
        "c_count": c_count if 'c_count' in dir() else 0,
    })

    print(f"品質スコア学習完了:")
    if s_features:
        print(f"  S/A記事特徴: {', '.join(f'{f}({c})' for f, c in s_features.most_common(3))}")
    if c_problems:
        print(f"  C/D記事問題: {', '.join(f'{f}({c})' for f, c in c_problems.most_common(3))}")
    if recurring_issues:
        print(f"  繰り返し問題(3回+): {', '.join(recurring_issues)}")
    if issue_counter:
        print(f"  頻出問題: {', '.join(f'{i}({c})' for i, c in issue_counter.most_common(5))}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ダッシュボード用データ出力
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def dashboard_data() -> dict:
    """ダッシュボード表示用の学習データを返す"""
    now = datetime.now()
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    result = {
        "generated_at": now.isoformat(),
        "learning_count_week": 0,
        "applied_count_week": 0,
        "recurring_errors_top5": [],
        "quality_trend": [],
    }

    # 今週の学習件数
    learning_records = _load_jsonl(LEARNING_LOG_FILE)
    week_learnings = [r for r in learning_records if r.get("ts", "")[:10] >= week_ago]
    result["learning_count_week"] = len(week_learnings)

    # 適用された改善件数
    directives = _load_json(AUTO_DIRECTIVES_FILE)
    agent_dirs = directives.get("agent_directives", {})
    applied = 0
    for agent, info in agent_dirs.items():
        if isinstance(info, dict):
            set_at = info.get("set_at", info.get("title_learning_date", ""))
            if set_at and set_at >= week_ago:
                applied += 1
    result["applied_count_week"] = applied

    # 繰り返しエラーTOP5
    error_data = _load_json(ERROR_PATTERNS_FILE)
    patterns = error_data.get("patterns", {})
    sorted_patterns = sorted(
        patterns.items(),
        key=lambda x: x[1].get("count", 0),
        reverse=True,
    )
    for key, info in sorted_patterns[:5]:
        result["recurring_errors_top5"].append({
            "key": key,
            "count": info.get("count", 0),
            "example": info.get("example", "")[:60],
            "agent": info.get("agent", "unknown"),
            "last_seen": info.get("last_seen", ""),
            "resolved": bool(info.get("resolved_at")),
        })

    # 品質スコア週次トレンド
    weekly_records = _load_jsonl(QUALITY_WEEKLY_FILE)
    for r in weekly_records[-8:]:
        result["quality_trend"].append({
            "date": r.get("date", r.get("week_start", "")),
            "avg_score": r.get("avg_score", 0),
            "article_count": r.get("article_count", 0),
            "rank_dist": r.get("rank_distribution", {}),
        })

    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    parser = argparse.ArgumentParser(description="学習フィードバックループ")
    parser.add_argument("command", choices=[
        "learn-titles", "learn-typos", "learn-quality", "dashboard-data",
    ])
    args = parser.parse_args()

    if args.command == "learn-titles":
        learn_titles()
    elif args.command == "learn-typos":
        learn_typos()
    elif args.command == "learn-quality":
        learn_quality()
    elif args.command == "dashboard-data":
        data = dashboard_data()
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
