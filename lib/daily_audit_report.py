#!/usr/bin/env python3
"""daily_audit_report.py — 毎日21:30（全社会議後）に自動監査レポートをDiscord送信。

機能:
  1. 品質スコア70点未満の記事をリライトキューに追加
  2. KPI目標との乖離を自動検出（PV・CTR・投稿数）
  3. Discordに監査サマリーを送信

Usage:
  python3 lib/daily_audit_report.py
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
CONFIG = BASE / "config"

# KPI目標
KPI_TARGETS = {
    "daily_posts": 5,          # 1日の目標投稿数
    "min_ctr_pct": 2.0,        # 最低CTR (%)
    "min_avg_score": 70,       # 品質スコア下限
}


def load_discord_webhook():
    """Discord webhook URLを取得"""
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
    # フォールバック
    fallback = Path.home() / ".kpop_discord_webhook"
    if fallback.exists():
        return fallback.read_text().strip()
    return os.environ.get("DISCORD_WEBHOOK", "")


def get_today_posts():
    """今日の投稿記事をkpi_posts.jsonlから取得"""
    today = datetime.now().strftime("%Y-%m-%d")
    posts = []
    kpi_file = LOGS / "kpi_posts.jsonl"
    if not kpi_file.exists():
        return posts
    for line in kpi_file.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
            if d.get("date", "")[:10] == today:
                posts.append(d)
        except Exception:
            continue
    return posts


def get_today_errors():
    """今日のエラーをkpi_errors.jsonlから取得"""
    today = datetime.now().strftime("%Y-%m-%d")
    errors = []
    err_file = LOGS / "kpi_errors.jsonl"
    if not err_file.exists():
        return errors
    for line in err_file.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
            if d.get("date", "")[:10] == today:
                errors.append(d)
        except Exception:
            continue
    return errors


def get_gardevoir_scores():
    """直近のgardevoir品質スコアを取得"""
    scores = []
    hook_file = LOGS / "gardevoir_hook.jsonl"
    if not hook_file.exists():
        return scores
    for line in hook_file.read_text(errors="replace").splitlines()[-50:]:
        try:
            d = json.loads(line)
            score = d.get("score", 0)
            if isinstance(score, (int, float)):
                scores.append({
                    "score": score,
                    "verdict": d.get("verdict", ""),
                    "title": d.get("title", "")[:40],
                    "post_id": d.get("post_id", ""),
                })
        except Exception:
            continue
    return scores


def get_gsc_metrics():
    """GSCメトリクス（昨日分）を取得"""
    metrics_file = BASE / "google_metrics" / "metrics_yesterday.json"
    if not metrics_file.exists():
        return None
    try:
        return json.loads(metrics_file.read_text())
    except Exception:
        return None


def add_to_rewrite_queue(post_id: int, reason: str):
    """リライトキューに追加（重複チェック付き）"""
    queue_file = LOGS / "rewrite_queue.jsonl"
    existing = set()
    if queue_file.exists():
        for line in queue_file.read_text(errors="replace").splitlines():
            try:
                existing.add(json.loads(line).get("post_id"))
            except Exception:
                pass
    if post_id in existing:
        return False
    with open(queue_file, "a") as f:
        f.write(json.dumps({
            "post_id": post_id,
            "reason": reason,
            "queued_at": datetime.now().isoformat(),
            "status": "pending",
        }, ensure_ascii=False) + "\n")
    return True


def send_discord(webhook: str, message: str):
    """Discord webhook送信"""
    if not webhook:
        print("Discord webhook未設定 — スキップ")
        return
    payload = json.dumps({"content": message[:1900]}).encode()
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "KPJ-AuditBot/1.0"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print("Discord監査レポート送信完了")
    except Exception as e:
        print(f"Discord送信失敗: {e}")


def get_quality_scores_for_posts(post_ids: list) -> list:
    """各記事のquality_scoreを取得"""
    import subprocess
    results = []
    for pid in post_ids:
        try:
            out = subprocess.check_output(
                ["python3", str(BASE / "lib" / "audit_helpers.py"), "quality_score", str(pid)],
                timeout=15, text=True, stderr=subprocess.DEVNULL,
                cwd=str(BASE),
            )
            score = None
            rank = None
            for line in out.strip().splitlines():
                if line.startswith("SCORE:"):
                    score = int(line.split(":")[1])
                elif line.startswith("RANK:"):
                    rank = line.split(":")[1]
            if score is not None:
                results.append({"post_id": pid, "score": score, "rank": rank or "?"})
        except Exception:
            pass
    return results


def get_yesterday_quality_avg() -> float | None:
    """前日の品質スコア平均をログから取得"""
    audit_log = LOGS / "daily_audit.jsonl"
    if not audit_log.exists():
        return None
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    for line in reversed(audit_log.read_text(errors="replace").splitlines()):
        try:
            d = json.loads(line)
            if d.get("date") == yesterday:
                return d.get("avg_quality_score")
        except Exception:
            continue
    return None


def main():
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    print(f"=== 日次監査レポート {today} ===")

    posts = get_today_posts()
    errors = get_today_errors()
    gardevoir_scores = get_gardevoir_scores()
    gsc = get_gsc_metrics()

    report_lines = []
    alerts = []
    rewrite_count = 0

    # ── 1. 投稿数チェック ──
    post_count = len(posts)
    target_posts = KPI_TARGETS["daily_posts"]
    if post_count < target_posts:
        alerts.append(f"投稿数不足: {post_count}/{target_posts}件")
    report_lines.append(f"📊 投稿数: {post_count}/{target_posts}件")

    # ── 2. エラー数 ──
    err_count = len(errors)
    recoverable = sum(1 for e in errors if e.get("recoverable", True))
    unrecoverable = err_count - recoverable
    report_lines.append(f"⚠️ エラー: {err_count}件（致命的: {unrecoverable}件 / 回復可能: {recoverable}件）")
    if unrecoverable >= 3:
        alerts.append(f"致命的エラー{unrecoverable}件")

    # ── 3. 品質スコアチェック ──
    low_score_articles = []
    for s in gardevoir_scores:
        if s["score"] < KPI_TARGETS["min_avg_score"] and s.get("post_id"):
            low_score_articles.append(s)
            if add_to_rewrite_queue(s["post_id"], f"quality_score_{s['score']}"):
                rewrite_count += 1

    if gardevoir_scores:
        avg_score = sum(s["score"] for s in gardevoir_scores) / len(gardevoir_scores)
        hard_fail_count = sum(1 for s in gardevoir_scores if s["verdict"] == "HARD_FAIL")
        report_lines.append(f"🎯 品質スコア: 平均{avg_score:.0f}点 / HARD_FAIL: {hard_fail_count}件")
        if avg_score < KPI_TARGETS["min_avg_score"]:
            alerts.append(f"品質スコア平均{avg_score:.0f}点（目標: {KPI_TARGETS['min_avg_score']}点）")
    else:
        report_lines.append("🎯 品質スコア: データなし")

    if rewrite_count > 0:
        report_lines.append(f"📝 リライトキュー追加: {rewrite_count}件")

    # ── 4. GSCメトリクス ──
    if gsc:
        total_clicks = gsc.get("total_clicks", 0)
        total_impressions = gsc.get("total_impressions", 0)
        avg_ctr = gsc.get("avg_ctr", 0) * 100 if gsc.get("avg_ctr", 0) < 1 else gsc.get("avg_ctr", 0)
        avg_pos = gsc.get("avg_position", 0)
        report_lines.append(f"🔍 GSC: クリック{total_clicks} / IMP{total_impressions} / CTR{avg_ctr:.1f}% / 平均順位{avg_pos:.1f}")
        if avg_ctr < KPI_TARGETS["min_ctr_pct"]:
            alerts.append(f"CTR{avg_ctr:.1f}%（目標: {KPI_TARGETS['min_ctr_pct']}%）")
    else:
        report_lines.append("🔍 GSC: データなし")

    # ── 4.5 品質スコアサマリー ──
    post_ids = [p.get("post_id") for p in posts if p.get("post_id")]
    quality_results = get_quality_scores_for_posts(post_ids) if post_ids else []
    quality_rewrite_count = 0

    if quality_results:
        rank_dist = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
        for qr in quality_results:
            r = qr.get("rank", "?")
            if r in rank_dist:
                rank_dist[r] += 1

        avg_q = sum(qr["score"] for qr in quality_results) / len(quality_results)
        dist_str = " / ".join(f"{k}:{v}" for k, v in rank_dist.items() if v > 0)
        report_lines.append(f"📋 品質スコア(新): 平均{avg_q:.0f}点 [{dist_str}]")

        # Bスコア以下をリライトキューに追加
        b_below = [qr for qr in quality_results if qr["score"] < 75]
        for qr in b_below:
            if add_to_rewrite_queue(qr["post_id"], f"quality_rank_{qr['rank']}_score_{qr['score']}"):
                quality_rewrite_count += 1

        if b_below:
            report_lines.append(f"  ⚠️ B以下: {len(b_below)}件")
            for qr in b_below[:5]:
                report_lines.append(f"    #{qr['post_id']} → {qr['rank']}({qr['score']}点)")
            alerts.append(f"品質B以下{len(b_below)}件 → リライトキュー追加")

        # 前日比
        yesterday_avg = get_yesterday_quality_avg()
        if yesterday_avg is not None:
            diff = avg_q - yesterday_avg
            arrow = "📈" if diff > 0 else ("📉" if diff < 0 else "➡️")
            report_lines.append(f"  {arrow} 前日比: {diff:+.1f}点")
    else:
        report_lines.append("📋 品質スコア(新): 本日投稿なし")

    if quality_rewrite_count > 0:
        rewrite_count += quality_rewrite_count

    # ── 5. X投稿ステータス ──
    sns_cfg_file = CONFIG / "sns_config.json"
    x_suspended = False
    if sns_cfg_file.exists():
        try:
            sns_cfg = json.loads(sns_cfg_file.read_text())
            tw = sns_cfg.get("twitter", {})
            if not tw.get("enabled", True):
                x_suspended = True
                x_reason = tw.get("reason", "disabled")
                report_lines.append(f"🐦 X投稿: ⏸️ 停止中（{x_reason}）")
        except Exception:
            pass
    if not x_suspended:
        x_cred_exists = os.path.exists(os.path.expanduser("~/.x_credentials"))
        if not x_cred_exists:
            report_lines.append("🐦 X投稿: ⏸️ PENDING（credentials設定待ち）")
        else:
            report_lines.append("🐦 X投稿: ✅ credentials設定済み")

    # ── 監査レポート構築 ──
    status_icon = "🚨" if alerts else "✅"
    header = f"{status_icon} **日次監査レポート** {today}"
    body = "\n".join(report_lines)

    alert_section = ""
    if alerts:
        alert_section = "\n\n🚨 **アラート:**\n" + "\n".join(f"• {a}" for a in alerts)

    message = f"{header}\n\n{body}{alert_section}"

    print(message)

    # ── Discord送信 ──
    webhook = load_discord_webhook()
    send_discord(webhook, message)

    # ── ログ保存 ──
    audit_log = LOGS / "daily_audit.jsonl"
    with open(audit_log, "a") as f:
        f.write(json.dumps({
            "date": today,
            "ts": now.isoformat(),
            "post_count": post_count,
            "error_count": err_count,
            "unrecoverable_errors": unrecoverable,
            "avg_quality_score": round(avg_q, 1) if quality_results else (round(avg_score, 1) if gardevoir_scores else None),
            "rewrite_queued": rewrite_count,
            "alerts": alerts,
            "x_credentials": x_cred_exists,
        }, ensure_ascii=False) + "\n")

    print(f"\n=== 監査完了: アラート{len(alerts)}件 / リライトキュー{rewrite_count}件追加 ===")


if __name__ == "__main__":
    main()
