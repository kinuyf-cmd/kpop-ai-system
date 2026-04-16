"""
初心者ガイド記事（カテゴリ113）再監査エージェント

機能:
1. beginner_guide_review.jsonl から next_review_due が今日以前の記事を抽出
2. WordPressから現在の本文を取得
3. チェックルールを実行（invert=Trueは「パターンが見つからない場合に問題」）
4. 問題があればDiscordに通知してstatusをneeds_reviewに更新
5. 問題なければlast_factchecked_atとnext_review_dueを更新

Usage:
  python3 lib/beginner_guide_reviewer.py --dry-run
  python3 lib/beginner_guide_reviewer.py --all          # 期限に関係なく全件チェック
  python3 lib/beginner_guide_reviewer.py                # 期限到来分のみ
  python3 lib/beginner_guide_reviewer.py --post-id 2432 # 単記事チェック
"""

import argparse
import json
import os
import re
import urllib.request
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

BASE = Path("/home/aiuser/kpop-ai-system")
LEDGER = BASE / "logs" / "beginner_guide_review.jsonl"
LOG_PATH = BASE / "logs" / "beginner_guide_review.log"
WP_API = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"

# ── リスクに応じた次回監査間隔 ──────────────────────────────
REVIEW_INTERVALS = {
    "beginner_guide": 30,
}
DEFAULT_INTERVAL = 30

# ── 自動チェックルール ────────────────────────────────────────
# invert=True のルールは「パターンが見つからない場合に問題」として扱う
CHECK_RULES = [
    {
        "id": "old_abema_price",
        "pattern": r"960円",
        "severity": "critical",
        "message": "旧ABEMAプレミアム料金(960円)が残存。正: 月1,180円",
    },
    {
        "id": "old_lemino_price",
        "pattern": r"990円",
        "severity": "critical",
        "message": "旧Leminoプレミアム料金(990円)が残存。正: Web登録月1,540円",
    },
    {
        "id": "missing_hub_link",
        "pattern": r"kpop-hub-link|kpop-beginner-hub-2026|初心者.*ハブ|ハブ.*初心者",
        "severity": "high",
        "message": "113ハブへの導線が見当たらない（kpop-hub-linkクラス不在）",
        "invert": True,  # パターンが存在しない場合に問題
    },
    {
        "id": "missing_view_guide_link",
        "pattern": r"kpop-view-guide|kpop-streaming-guide-2026|視聴方法.*まとめ",
        "severity": "high",
        "message": "111ハブへの導線が見当たらない（kpop-view-guideクラス不在）",
        "invert": True,
    },
    {
        "id": "ive_weverse_error",
        "pattern": r"^(?=.*\bIVE\b)(?=.*Weverse)(?!.*非対応)(?!.*対応していません).*$",
        "severity": "critical",
        "message": "IVEをWeverse対応と記述している行が存在。IVEはKakao系でWeverse非対応",
    },
    {
        "id": "unconfirmed_broadcast",
        "pattern": r"配信予定です(?!.*要確認)(?!.*公式)",
        "severity": "high",
        "message": "未確認情報への断定「配信予定です」が残存",
    },
    {
        "id": "born_again_wrong_tourname",
        "pattern": r"BORN AGAIN",
        "severity": "critical",
        "message": "誤BTSツアー名「BORN AGAIN」残存。正: BTS WORLD TOUR 'ARIRANG'",
    },
    {
        "id": "wrong_member_herin",
        "pattern": r"ヘリン(?!.*ハリン)",
        "severity": "high",
        "message": "誤メンバー名「ヘリン」残存。正: ハリン(Haerin)",
    },
]


def _log(msg: str):
    """コンソール出力とログファイルへの両方に書き出す"""
    print(msg)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def _wp_auth_header() -> str:
    wp_auth_path = os.path.expanduser("~/.wp_auth")
    if os.path.exists(wp_auth_path):
        with open(wp_auth_path) as f:
            for line in f:
                m = re.match(r'header\s*=\s*"Authorization:\s*Basic\s+([^"]+)"', line.strip())
                if m:
                    return m.group(1).strip()
    return ""


def fetch_post_content(post_id: int) -> dict:
    """WordPressから記事の生HTML本文とタイトルを取得"""
    url = f"{WP_API}/{post_id}?context=edit"
    auth_token = _wp_auth_header()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth_token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read())
            return {
                "title": d.get("title", {}).get("rendered", ""),
                "content": d.get("content", {}).get("raw", "") or d.get("content", {}).get("rendered", ""),
                "link": d.get("link", ""),
                "modified": d.get("modified", ""),
            }
    except Exception as e:
        return {"error": str(e)}


HUB_POST_ID = 2442  # 113ハブ記事はinvertルール(欠如チェック)の対象外


def run_checks(content: str, post_id: int) -> list:
    """チェックルールを実行し、問題リストを返す"""
    findings = []
    for rule in CHECK_RULES:
        invert = rule.get("invert", False)
        # ハブ記事(2442)自身はハブリンク欠如チェックの対象外
        if invert and post_id == HUB_POST_ID:
            continue
        # ive_weverse_error は行単位マッチ（MULTILINE）、他はDOTALL
        flags = re.MULTILINE if rule["id"] == "ive_weverse_error" else re.DOTALL
        matches = re.findall(rule["pattern"], content, flags)

        if invert:
            # invert=True: パターンが「見つからない」場合に問題
            if not matches:
                findings.append({
                    "rule_id": rule["id"],
                    "severity": rule["severity"],
                    "message": rule["message"],
                    "match_count": 0,
                })
        else:
            # 通常: パターンが「見つかった」場合に問題
            if matches:
                findings.append({
                    "rule_id": rule["id"],
                    "severity": rule["severity"],
                    "message": rule["message"],
                    "match_count": len(matches),
                })
    return findings


def load_ledger() -> list:
    if not LEDGER.exists():
        return []
    records = []
    with open(LEDGER) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def save_ledger(records: list):
    with open(LEDGER, "w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def send_discord(webhook_url: str, message: str):
    if not webhook_url:
        return
    payload = json.dumps({"content": message}).encode()
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def review(dry_run=False, all_records=False, target_post_id=None):
    today = date.today()
    records = load_ledger()

    # 対象フィルタ
    if target_post_id:
        targets = [r for r in records if r["post_id"] == target_post_id]
    elif all_records:
        targets = records
    else:
        targets = [r for r in records if date.fromisoformat(r["next_review_due"]) <= today]

    if not targets:
        _log(f"[beginner_guide_reviewer] 期限到来記事なし (today={today})")
        return

    _log(f"[beginner_guide_reviewer] 監査対象: {len(targets)}件")

    # Discordウェブフック
    discord_webhook = os.environ.get("DISCORD_WEBHOOK", "")
    env_path = BASE / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                if line.startswith("DISCORD_WEBHOOK="):
                    discord_webhook = line.strip().split("=", 1)[1].strip('"\'')

    results = []
    for rec in targets:
        pid = rec["post_id"]
        title = rec["title"]
        _log(f"\n  チェック中: [{pid}] {title[:50]}")

        post = fetch_post_content(pid)
        if "error" in post:
            _log(f"    ❌ 取得エラー: {post['error']}")
            continue

        content = post["content"]
        findings = run_checks(content, pid)

        if findings:
            critical = [f for f in findings if f["severity"] == "critical"]
            high = [f for f in findings if f["severity"] == "high"]
            medium = [f for f in findings if f["severity"] == "medium"]
            _log(f"    ⚠️  問題検出: critical={len(critical)} high={len(high)} medium={len(medium)}")
            for fi in findings:
                _log(f"      [{fi['severity'].upper()}] {fi['message']}")

            if not dry_run:
                rec["status"] = "needs_review"
                severity_icon = "🚨" if critical else "⚠️"
                msg = (
                    f"{severity_icon} **初心者ガイド記事 再監査アラート**\n"
                    f"[{pid}] {title}\n"
                    f"問題数: critical={len(critical)} / high={len(high)} / medium={len(medium)}\n"
                    f"最優先: {findings[0]['message']}\n"
                    f"URL: {post.get('link', '')}"
                )
                send_discord(discord_webhook, msg)
        else:
            _log(f"    ✅ 問題なし")
            if not dry_run:
                interval = REVIEW_INTERVALS.get(rec.get("article_type", "beginner_guide"), DEFAULT_INTERVAL)
                rec["last_factchecked_at"] = today.isoformat()
                rec["next_review_due"] = (today + timedelta(days=interval)).isoformat()
                rec["status"] = "published_verified"

        results.append({"post_id": pid, "findings": findings})

    if not dry_run:
        reviewed_ids = {r["post_id"] for r in targets}
        updated = []
        target_map = {r["post_id"]: r for r in targets}
        for rec in records:
            if rec["post_id"] in reviewed_ids:
                updated.append(target_map[rec["post_id"]])
            else:
                updated.append(rec)
        save_ledger(updated)
        _log(f"\n✅ 台帳更新完了: {LEDGER}")

    # サマリー
    total_issues = sum(len(r["findings"]) for r in results)
    _log(f"\n=== 監査サマリー ===")
    _log(f"  対象: {len(results)}件 / 問題あり: {sum(1 for r in results if r['findings'])}件")
    _log(f"  総問題数: {total_issues}")
    if dry_run:
        _log("  (dry-run: 台帳未更新)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="初心者ガイド記事 再監査スクリプト")
    parser.add_argument("--dry-run", action="store_true", help="台帳を更新せず結果のみ表示")
    parser.add_argument("--all", action="store_true", help="期限に関係なく全件チェック")
    parser.add_argument("--post-id", type=int, help="単記事チェック")
    args = parser.parse_args()
    review(dry_run=args.dry_run, all_records=args.all, target_post_id=args.post_id)
