#!/usr/bin/env python3
"""
Post Guard - 二重投稿防止 + 投稿履歴管理 + BLOCK条件チェック
監査本部（アブソル）管轄

【最重要】
- final_post.md のみを投稿対象とする
- 審査レポート（3_arceus.md等）の投稿を構造的に不可能にする
- 質問文・審査文の混入を検出してBLOCK
"""
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime
from difflib import SequenceMatcher

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
CONFIG_DIR = os.path.join(BASE_DIR, "config")
POST_LOG_FILE = os.path.join(LOGS_DIR, "post_log.json")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
FINAL_POST_PATH = os.path.join(REPORTS_DIR, "final_post.md")


def load_safety_config():
    config_file = os.path.join(CONFIG_DIR, "safety_config.json")
    if os.path.exists(config_file):
        with open(config_file, encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_post_log():
    """投稿履歴の読み込み"""
    if os.path.exists(POST_LOG_FILE):
        with open(POST_LOG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"posts": [], "daily_counts": {}}


def save_post_log(log):
    """投稿履歴の保存"""
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(POST_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def record_post(post_id, title, slug, url, article_type="flow", categories=None):
    """投稿をログに記録"""
    log = load_post_log()
    today = date.today().isoformat()

    entry = {
        "post_id": post_id,
        "title": title,
        "slug": slug,
        "url": url,
        "article_type": article_type,
        "categories": categories or [],
        "published_at": datetime.now().isoformat(),
        "date": today,
        "title_hash": hashlib.md5(title.encode()).hexdigest(),
        "slug_hash": hashlib.md5(slug.encode()).hexdigest(),
    }

    log["posts"].append(entry)

    # 日別カウント更新
    if today not in log["daily_counts"]:
        log["daily_counts"][today] = {"total": 0, "flow": 0, "asset": 0, "revenue": 0}
    log["daily_counts"][today]["total"] += 1
    log["daily_counts"][today][article_type] = log["daily_counts"][today].get(article_type, 0) + 1

    save_post_log(log)
    return entry


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 二重投稿チェック
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_duplicate_title(title, days=2):
    """同一タイトルの二重投稿チェック"""
    log = load_post_log()
    title_hash = hashlib.md5(title.encode()).hexdigest()
    cutoff = date.today().isoformat()

    for post in reversed(log["posts"]):
        post_date = post.get("date", "")
        if post_date < cutoff and days > 0:
            from datetime import timedelta
            cutoff_date = (date.today() - timedelta(days=days)).isoformat()
            if post_date < cutoff_date:
                continue

        # 完全一致
        if post.get("title_hash") == title_hash:
            return {"duplicate": True, "reason": "exact_title_match", "existing_post": post}

        # 類似度チェック（85%以上）
        similarity = SequenceMatcher(None, title, post.get("title", "")).ratio()
        if similarity >= 0.85:
            return {"duplicate": True, "reason": f"similar_title ({similarity:.0%})", "existing_post": post}

    return {"duplicate": False}


def check_duplicate_slug(slug):
    """同一slugの二重投稿チェック"""
    log = load_post_log()
    slug_hash = hashlib.md5(slug.encode()).hexdigest()

    for post in log["posts"]:
        if post.get("slug_hash") == slug_hash:
            return {"duplicate": True, "reason": "slug_exists", "existing_post": post}

    return {"duplicate": False}


def check_daily_limit(article_type="flow"):
    """同日投稿上限チェック"""
    config = load_safety_config()
    limits = config.get("daily_post_limits", {"max_total": 20})

    log = load_post_log()
    today = date.today().isoformat()
    counts = log.get("daily_counts", {}).get(today, {"total": 0})

    total = counts.get("total", 0)
    type_count = counts.get(article_type, 0)

    max_total = limits.get("max_total", 20)
    max_type = limits.get(f"max_{article_type}", max_total)

    if total >= max_total:
        return {"allowed": False, "reason": f"daily_total_limit ({total}/{max_total})"}
    if type_count >= max_type:
        return {"allowed": False, "reason": f"daily_{article_type}_limit ({type_count}/{max_type})"}

    return {"allowed": True, "remaining_total": max_total - total, "remaining_type": max_type - type_count}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BLOCK条件チェック（投稿前最終ゲート）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def validate_final_post(file_path=None, article_type="flow"):
    """
    final_post.md の投稿前バリデーション
    BLOCKされた場合は投稿を絶対に実行しない
    """
    if file_path is None:
        file_path = FINAL_POST_PATH

    errors = []
    warnings = []

    # ── ファイル存在チェック ──
    if not os.path.exists(file_path):
        return {"status": "BLOCK", "errors": ["final_post.md does not exist"], "warnings": []}

    # ── ファイルパスチェック（審査レポート誤投稿防止） ──
    basename = os.path.basename(file_path)
    if basename != "final_post.md":
        return {"status": "BLOCK", "errors": [f"Wrong file: {basename} (only final_post.md allowed)"], "warnings": []}

    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    lines = content.strip().split("\n")

    # ── タイトルチェック ──
    if not lines:
        return {"status": "BLOCK", "errors": ["File is empty"], "warnings": []}

    title = lines[0].strip()

    if not title:
        errors.append("no_title: 1行目が空")
    elif title.startswith("#"):
        errors.append("markdown_title: タイトルに#が含まれている")
    elif len(title) < 10:
        errors.append(f"title_too_short: {len(title)}文字")
    elif len(title) > 80:
        warnings.append(f"title_long: {len(title)}文字")

    # ── 本文チェック ──
    body = "\n".join(lines[1:]).strip()

    if not body:
        errors.append("no_body: 本文が空")
        return {"status": "BLOCK", "errors": errors, "warnings": warnings}

    # HTML除去して純テキスト
    plain = re.sub(r'<[^>]+>', '', body).strip()
    plain = re.sub(r'\s+', ' ', plain)
    char_count = len(plain)

    # ── 審査レポート混入チェック（最重要） ──
    review_signals = [
        "エージェント別採点", "最終記事品質評価", "投稿承認", "投稿却下",
        "採点表", "スコア:", "点数:", "/50点", "/10点",
        "デオキシス:", "メタモン:", "ジラーチ:", "アルセウス:",
        "修正箇所：", "修正サマリー", "チェック項目：", "【修正内容】",
        "review_log", "3_arceus",
    ]
    for signal in review_signals:
        if signal in content:
            errors.append(f"review_report_detected: '{signal}' found in content")
            break

    # ── 質問文チェック ──
    question_signals = [
        "質問があります", "確認させてください", "お手伝いできますか",
        "申し訳ありません", "承知しました", "以下に示します",
        "AIとして", "言語モデル", "お答えできません",
        "いかがでしょうか", "ご確認ください",
    ]
    for signal in question_signals:
        if signal in content:
            errors.append(f"question_detected: '{signal}' found")
            break

    # ── HTML構造チェック ──
    h2_count = len(re.findall(r'<h2', body, re.IGNORECASE))
    if h2_count < 2:
        errors.append(f"insufficient_h2: {h2_count} (min 2)")

    if not re.search(r'<(h2|h3|p|div|ul|ol)', body, re.IGNORECASE):
        errors.append("no_html: HTML tags not found")

    # ── 文字数チェック（記事タイプ別） ──
    min_chars = {"flow": 1500, "asset": 2500, "revenue": 2500, "analysis": 4000, "comparison": 5000}
    required = min_chars.get(article_type, 1500)

    if char_count < required:
        errors.append(f"char_count_low: {char_count} (min {required} for {article_type})")
    elif char_count < required * 0.8:
        errors.append(f"char_count_critical: {char_count}")

    # ── コードブロック混入チェック ──
    if "```" in body:
        errors.append("codeblock_detected: markdown code block in content")

    # ── 警告（BLOCKしないが改善推奨） ──
    if not any(w in body for w in ['情報元', '出典', '参照', '引用']):
        warnings.append("no_source: 情報元の記載なし")

    if 'revenue-cta' not in body and article_type != "flow":
        warnings.append("no_cta: CTA block not found")

    if not re.search(r'<a\s+href=.*?>', body):
        warnings.append("no_internal_links: 内部リンクなし")

    # ── 判定 ──
    if errors:
        status = "BLOCK"
    elif warnings:
        status = "PASS_WITH_WARNING"
    else:
        status = "PASS"

    return {
        "status": status,
        "title": title if lines else "",
        "char_count": char_count,
        "h2_count": h2_count,
        "article_type": article_type,
        "errors": errors,
        "warnings": warnings,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 統合ガード（投稿前に全チェックを実行）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def full_pre_publish_check(title, slug, article_type="flow", file_path=None):
    """
    投稿前の全チェックを実行
    1つでもBLOCKがあれば投稿しない
    """
    results = {}

    # 1. final_post.md バリデーション
    validation = validate_final_post(file_path, article_type)
    results["validation"] = validation
    if validation["status"] == "BLOCK":
        return {"allowed": False, "reason": "validation_block", "details": results}

    # 2. 二重投稿チェック（タイトル）
    dup_title = check_duplicate_title(title)
    results["duplicate_title"] = dup_title
    if dup_title["duplicate"]:
        return {"allowed": False, "reason": "duplicate_title", "details": results}

    # 3. 二重投稿チェック（slug）
    dup_slug = check_duplicate_slug(slug)
    results["duplicate_slug"] = dup_slug
    if dup_slug["duplicate"]:
        return {"allowed": False, "reason": "duplicate_slug", "details": results}

    # 4. 日次上限チェック
    limit = check_daily_limit(article_type)
    results["daily_limit"] = limit
    if not limit["allowed"]:
        return {"allowed": False, "reason": "daily_limit", "details": results}

    # 5. 手動承認チェック
    approval = check_manual_approval_needed(title, article_type)
    results["manual_approval"] = approval

    return {
        "allowed": True,
        "needs_approval": approval.get("needs_approval", False),
        "warnings": validation.get("warnings", []),
        "details": results,
    }


def check_manual_approval_needed(title, article_type):
    """手動承認が必要かチェック"""
    config = load_safety_config()
    triggers = config.get("manual_approval_triggers", {})

    reasons = []

    # ゴシップ・炎上系
    if triggers.get("gossip_category", False):
        controversy_kw = triggers.get("controversy_keywords", [])
        if any(kw in title for kw in controversy_kw):
            reasons.append(f"controversy_keyword_in_title")

    # 新カテゴリ初投稿
    if triggers.get("new_category_first_post", False):
        # TODO: カテゴリ別投稿履歴から判定
        pass

    return {"needs_approval": len(reasons) > 0, "reasons": reasons}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 異常検知
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_anomalies():
    """異常検知チェック"""
    config = load_safety_config()
    anomaly_config = config.get("anomaly_detection", {})
    alerts = []

    log = load_post_log()
    today = date.today().isoformat()
    today_count = log.get("daily_counts", {}).get(today, {}).get("total", 0)

    # 投稿数ゼロアラート
    zero_hour = anomaly_config.get("zero_post_alert_hour", 12)
    from datetime import datetime as dt
    if dt.now().hour >= zero_hour and today_count == 0:
        alerts.append({"type": "zero_posts", "message": f"No posts by {zero_hour}:00", "severity": "warning"})

    # 異常投稿数
    max_daily = anomaly_config.get("abnormal_post_count_daily", 25)
    if today_count > max_daily:
        alerts.append({"type": "abnormal_count", "message": f"{today_count} posts today (max {max_daily})", "severity": "critical"})

    return alerts


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 強制停止チェック
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_emergency_stop():
    """強制停止条件のチェック"""
    config = load_safety_config()
    stop_config = config.get("emergency_stop", {})
    stop_file = os.path.join(BASE_DIR, "EMERGENCY_STOP")

    # 手動停止ファイル
    if os.path.exists(stop_file):
        return {"stop": True, "reason": "EMERGENCY_STOP file exists"}

    # 連続失敗チェック
    error_log = os.path.join(LOGS_DIR, "kpi_errors.jsonl")
    if os.path.exists(error_log):
        recent_errors = []
        with open(error_log, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    if entry.get("date") == date.today().isoformat():
                        recent_errors.append(entry)
                except (json.JSONDecodeError, KeyError):
                    continue

        max_errors = stop_config.get("daily_error_threshold", 5)
        if len(recent_errors) >= max_errors:
            return {"stop": True, "reason": f"Daily error threshold ({len(recent_errors)}/{max_errors})"}

        # 連続失敗
        consecutive = stop_config.get("consecutive_failures", 3)
        if len(recent_errors) >= consecutive:
            last_n = recent_errors[-consecutive:]
            if all(not e.get("recoverable", True) for e in last_n):
                return {"stop": True, "reason": f"{consecutive} consecutive unrecoverable failures"}

    return {"stop": False}


# ── CLI ──

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: post_guard.py <validate|check_dup|check_limit|full_check|anomalies|emergency>")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "validate":
        path = sys.argv[2] if len(sys.argv) > 2 else None
        atype = sys.argv[3] if len(sys.argv) > 3 else "flow"
        result = validate_final_post(path, atype)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "check_dup":
        title = sys.argv[2] if len(sys.argv) > 2 else ""
        result = check_duplicate_title(title)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "check_limit":
        atype = sys.argv[2] if len(sys.argv) > 2 else "flow"
        result = check_daily_limit(atype)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "full_check":
        title = sys.argv[2] if len(sys.argv) > 2 else ""
        slug = sys.argv[3] if len(sys.argv) > 3 else ""
        atype = sys.argv[4] if len(sys.argv) > 4 else "flow"
        result = full_pre_publish_check(title, slug, atype)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "record":
        data = json.loads(sys.argv[2])
        result = record_post(**data)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "anomalies":
        result = check_anomalies()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "emergency":
        result = check_emergency_stop()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
