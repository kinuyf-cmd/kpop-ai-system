#!/usr/bin/env python3
"""weekly_quality_report.py — 週次品質レポート（月曜9時JST実行）

過去7日間の記事品質スコア分布・B以下一覧・改善提案をDiscordに送信。

Usage:
  python3 lib/weekly_quality_report.py
"""

import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"


def load_discord_webhook() -> str:
    wh_file = CONFIG / "discord_webhooks.json"
    if wh_file.exists():
        try:
            data = json.loads(wh_file.read_text())
            for key in ("daily_ceo_report", "alert_summary", "urgent_errors"):
                urls = data.get(key, [])
                if urls:
                    return urls[0] if isinstance(urls, list) else urls
        except Exception:
            pass
    fallback = Path.home() / ".kpop_discord_webhook"
    if fallback.exists():
        return fallback.read_text().strip()
    return os.environ.get("DISCORD_WEBHOOK", "")


def send_discord(webhook: str, message: str):
    if not webhook:
        print("Discord webhook未設定 — スキップ")
        return
    payload = json.dumps({"content": message[:1900]}).encode()
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "KPJ-QualityBot/1.0"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print("Discord送信完了")
    except Exception as e:
        print(f"Discord送信失敗: {e}")


def get_week_post_ids() -> list[int]:
    """過去7日間に投稿された記事IDをkpi_posts.jsonlから取得"""
    kpi_file = LOGS / "kpi_posts.jsonl"
    if not kpi_file.exists():
        return []
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    ids = []
    for line in kpi_file.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
            if d.get("date", "")[:10] >= week_ago and d.get("post_id"):
                ids.append(d["post_id"])
        except Exception:
            continue
    return ids


def score_post(post_id: int) -> dict | None:
    """audit_helpers.py quality_score を呼び出し"""
    try:
        out = subprocess.check_output(
            ["python3", str(BASE / "lib" / "audit_helpers.py"), "quality_score", str(post_id)],
            timeout=15, text=True, stderr=subprocess.DEVNULL,
            cwd=str(BASE),
        )
        result = {"post_id": post_id}
        for line in out.strip().splitlines():
            if line.startswith("SCORE:"):
                result["score"] = int(line.split(":")[1])
            elif line.startswith("RANK:"):
                result["rank"] = line.split(":")[1]
            elif line.startswith("BREAKDOWN:"):
                result["breakdown"] = json.loads(line.split(":", 1)[1])
        return result if "score" in result else None
    except Exception:
        return None


def get_daily_audit_history() -> list[dict]:
    """daily_audit.jsonlから過去7日分を取得"""
    audit_log = LOGS / "daily_audit.jsonl"
    if not audit_log.exists():
        return []
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    entries = []
    for line in audit_log.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
            if d.get("date", "") >= week_ago:
                entries.append(d)
        except Exception:
            continue
    return entries


def generate_improvement_suggestions(results: list[dict]) -> list[str]:
    """品質スコア内訳から改善提案を生成"""
    suggestions = []

    # 各カテゴリの平均を算出
    categories = ["char_count", "h2_structure", "title_quality", "seo", "eeat", "user_value", "cta_links"]
    max_scores = {"char_count": 15, "h2_structure": 10, "title_quality": 15, "seo": 15, "eeat": 15, "user_value": 15, "cta_links": 15}
    cat_labels = {
        "char_count": "文字数", "h2_structure": "見出し構造", "title_quality": "タイトル品質",
        "seo": "SEO", "eeat": "E-E-A-T", "user_value": "ユーザー価値", "cta_links": "CTA・内部リンク",
    }

    totals = {c: 0 for c in categories}
    count = 0
    for r in results:
        bd = r.get("breakdown", {})
        if bd:
            count += 1
            for c in categories:
                totals[c] += bd.get(c, 0)

    if count == 0:
        return ["データ不足のため提案生成不可"]

    # 平均達成率でソート（低い順）
    rates = []
    for c in categories:
        avg = totals[c] / count
        rate = avg / max_scores[c] * 100
        rates.append((c, avg, rate))

    rates.sort(key=lambda x: x[2])

    # 下位3項目に対する提案
    improvement_map = {
        "char_count": "記事の文字数を2500字以上に。深掘りセクションやFAQの追加を検討",
        "h2_structure": "H2見出しを4〜6個に調整。論理的な構成で読者の離脱を防止",
        "title_quality": "タイトルに感情ワード（衝撃/最新/完全等）or 具体的数字を追加",
        "seo": "メタディスクリプション120〜160字化 + slugの英語化 + キーワード配置強化",
        "eeat": "著者情報（編集部名）の追記 + 情報源の明示 + 日付の明記を徹底",
        "user_value": "「なぜ」「どうやって」「いくら」への回答を意識。具体的数字を増やす",
        "cta_links": "内部リンク3本以上 + アフィリエイトCTA挿入 + 関連記事セクション追加",
    }

    for c, avg, rate in rates[:3]:
        if rate < 80:
            label = cat_labels.get(c, c)
            suggestion = improvement_map.get(c, "改善検討")
            suggestions.append(f"**{label}** (達成率{rate:.0f}%): {suggestion}")

    return suggestions


def main():
    now = datetime.now()
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")

    print(f"=== 週次品質レポート {week_start} 〜 {today} ===")

    # 過去7日の記事IDを取得
    post_ids = get_week_post_ids()
    print(f"対象記事: {len(post_ids)}件")

    if not post_ids:
        print("投稿記事なし — スキップ")
        return

    # 品質スコア算出
    results = []
    for pid in post_ids:
        r = score_post(pid)
        if r:
            results.append(r)
            print(f"  #{pid}: {r.get('rank', '?')}({r.get('score', 0)}点)")

    if not results:
        print("スコア算出結果なし — スキップ")
        return

    # 統計
    scores = [r["score"] for r in results]
    avg_score = sum(scores) / len(scores)
    min_score = min(scores)
    max_score = max(scores)

    rank_dist = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
    for r in results:
        rank = r.get("rank", "?")
        if rank in rank_dist:
            rank_dist[rank] += 1

    b_below = [r for r in results if r["score"] < 75]

    # 日別品質推移
    daily_history = get_daily_audit_history()

    # 改善提案
    suggestions = generate_improvement_suggestions(results)

    # ── レポート構築 ──
    lines = [
        f"📊 **週次品質レポート** ({week_start} 〜 {today})",
        "",
        f"**対象記事:** {len(results)}件",
        f"**平均スコア:** {avg_score:.1f}点 (最高{max_score} / 最低{min_score})",
        "",
        "**ランク分布:**",
    ]

    dist_lines = []
    for rank in ["S", "A", "B", "C", "D"]:
        count = rank_dist[rank]
        if count > 0:
            bar = "█" * count
            dist_lines.append(f"  {rank}: {bar} ({count}件)")
    lines.extend(dist_lines)

    # B以下一覧
    if b_below:
        lines.append("")
        lines.append(f"⚠️ **B以下の記事 ({len(b_below)}件):**")
        for r in sorted(b_below, key=lambda x: x["score"]):
            lines.append(f"  #{r['post_id']}: {r['rank']}({r['score']}点)")

    # 日別推移
    if daily_history:
        lines.append("")
        lines.append("**日別品質推移:**")
        for entry in daily_history[-7:]:
            qs = entry.get("avg_quality_score")
            date_str = entry.get("date", "?")
            pc = entry.get("post_count", 0)
            if qs is not None:
                lines.append(f"  {date_str}: {qs:.0f}点 ({pc}件投稿)")

    # 改善提案
    if suggestions:
        lines.append("")
        lines.append("💡 **今週の改善提案:**")
        for i, s in enumerate(suggestions, 1):
            lines.append(f"  {i}. {s}")

    # ── 品質トレンド分析（週次で改善しているか） ──
    past_weeks = []
    log_file = LOGS / "quality_weekly.jsonl"
    if log_file.exists():
        for line in log_file.read_text(errors="replace").splitlines():
            try:
                past_weeks.append(json.loads(line))
            except Exception:
                continue

    if len(past_weeks) >= 2:
        lines.append("")
        lines.append("📈 **品質トレンド（直近4週）:**")
        for pw in past_weeks[-4:]:
            pw_date = pw.get("date", pw.get("week_start", "?"))
            pw_avg = pw.get("avg_score", 0)
            pw_cnt = pw.get("article_count", 0)
            lines.append(f"  {pw_date}: {pw_avg:.1f}点 ({pw_cnt}件)")

        prev_avg = past_weeks[-2].get("avg_score", 0)
        curr_avg = avg_score
        delta = curr_avg - prev_avg
        if delta > 0:
            lines.append(f"  → 前週比 **+{delta:.1f}点** 改善 ✅")
        elif delta < 0:
            lines.append(f"  → 前週比 **{delta:.1f}点** 低下 ⚠️")
        else:
            lines.append(f"  → 前週比 横ばい")

    # ── 繰り返しエラー検出（3回以上は根本修正を提案） ──
    error_patterns_file = CONFIG / "error_patterns.json"
    if error_patterns_file.exists():
        try:
            ep_data = json.loads(error_patterns_file.read_text())
            recurring = [
                (k, v) for k, v in ep_data.get("patterns", {}).items()
                if v.get("count", 0) >= 3 and not v.get("resolved_at")
            ]
            recurring.sort(key=lambda x: x[1].get("count", 0), reverse=True)

            if recurring:
                lines.append("")
                lines.append(f"🔄 **繰り返しエラー（3回以上・未解決）: {len(recurring)}件**")
                for key, info in recurring[:5]:
                    cnt = info.get("count", 0)
                    agent = info.get("agent", "?")
                    example = info.get("example", "")[:50]
                    fix = info.get("fix", "")[:60]
                    lines.append(f"  ❗ [{cnt}回] {key} ({agent})")
                    lines.append(f"    例: {example}")
                    lines.append(f"    → 根本修正提案: {fix}")
        except Exception:
            pass

    # ── 学習適用確認（improvement_engineが学習結果を実際に適用しているか） ──
    learning_log = LOGS / "learning_feedback.jsonl"
    if learning_log.exists():
        learn_records = []
        for line in learning_log.read_text(errors="replace").splitlines():
            try:
                learn_records.append(json.loads(line))
            except Exception:
                continue
        week_learnings = [r for r in learn_records if r.get("ts", "")[:10] >= week_start]

        if week_learnings:
            categories = {}
            for lr in week_learnings:
                cat = lr.get("category", "unknown")
                categories[cat] = categories.get(cat, 0) + 1

            lines.append("")
            lines.append(f"🧠 **学習適用状況（今週）: {len(week_learnings)}件**")
            for cat, cnt in sorted(categories.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"  {cat}: {cnt}件")

            # auto_directives への反映確認
            directives_file = CONFIG / "auto_directives.json"
            if directives_file.exists():
                try:
                    dirs = json.loads(directives_file.read_text())
                    updated_at = dirs.get("updated_at", "")
                    if updated_at and updated_at[:10] >= week_start:
                        ad_count = len(dirs.get("agent_directives", {}))
                        ww_count = len(dirs.get("winning_words", []))
                        lines.append(f"  → auto_directives反映済: エージェント指示{ad_count}件, 勝ちワード{ww_count}個")
                    else:
                        lines.append(f"  ⚠️ auto_directivesが今週未更新 → 学習が反映されていない可能性")
                except Exception:
                    pass
        else:
            lines.append("")
            lines.append("⚠️ **今週の学習記録なし** → learning_feedback_loop.py が実行されているか確認")

    message = "\n".join(lines)
    print(message)

    # Discord送信
    webhook = load_discord_webhook()
    send_discord(webhook, message)

    # ログ保存
    log_file = LOGS / "quality_weekly.jsonl"
    LOGS.mkdir(exist_ok=True)
    with open(log_file, "a") as f:
        f.write(json.dumps({
            "date": today,
            "week_start": week_start,
            "article_count": len(results),
            "avg_score": round(avg_score, 1),
            "min_score": min_score,
            "max_score": max_score,
            "rank_distribution": rank_dist,
            "b_below_count": len(b_below),
            "suggestions": suggestions,
        }, ensure_ascii=False) + "\n")

    print(f"\n=== 週次レポート完了: {len(results)}件分析 / 平均{avg_score:.1f}点 ===")


if __name__ == "__main__":
    main()
