"""
視聴導線記事（カテゴリ111）再監査エージェント

機能:
1. streaming_guide_review.jsonl から next_review_due が今日以前の記事を抽出
2. WordPressから現在の本文を取得
3. 以下をチェック:
   - 旧料金（960円/990円）の残存
   - 「配信予定です/配信されます」等の未確認断定
   - IVEのWeverse誤導線
   - メンバー名の誤記（既知パターン）
   - 見出しと本文の矛盾（「未確認」と「断言」の共存）
4. 問題があればDiscordに通知してstatusをneeds_reviewに更新
5. 問題なければlast_factchecked_atとnext_review_dueを更新

Usage:
  python3 lib/streaming_guide_reviewer.py --dry-run
  python3 lib/streaming_guide_reviewer.py --all          # 期限に関係なく全件チェック
  python3 lib/streaming_guide_reviewer.py                # 期限到来分のみ
  python3 lib/streaming_guide_reviewer.py --post-id 2339 # 単記事チェック
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
LEDGER = BASE / "logs" / "streaming_guide_review.jsonl"
WP_API = "https://www.kpopjournal.tokyo/wp-json/wp/v2/posts"

# ── リスクに応じた次回監査間隔 ──────────────────────────────
REVIEW_INTERVALS = {
    "comprehensive_guide":    30,
    "single_show_guide":      60,
    "event_guide":            14,
    "artist_streaming_guide": 14,
}

# ── 自動チェックルール ────────────────────────────────────────
CHECK_RULES = [
    {
        "id": "old_abema_price",
        "pattern": r"960円",
        "severity": "critical",
        "message": "旧ABEMAプレミアム料金(960円)が残存。正: 月1,180円（2026年4月改定済み）",
    },
    {
        "id": "old_lemino_price",
        "pattern": r"990円",
        "severity": "critical",
        "message": "旧Leminoプレミアム料金(990円)が残存。正: Web登録月1,540円（2026年2月改定済み）",
    },
    {
        "id": "unconfirmed_broadcast",
        "pattern": r"配信予定です(?!.*要確認)(?!.*公式)",
        "severity": "high",
        "message": "未確認情報への断定「配信予定です」が残存",
    },
    {
        "id": "unconfirmed_streaming",
        "pattern": r"配信されます(?!.*要確認)(?!.*公式)",
        "severity": "high",
        "message": "未確認情報への断定「配信されます」が残存",
    },
    {
        "id": "ive_weverse_error",
        # 同一行内でIVEとWeverseが共存、かつ「非対応」「対応していません」が含まれない行
        "pattern": r"^(?=.*\bIVE\b)(?=.*Weverse)(?!.*非対応)(?!.*対応していません).*$",
        "severity": "critical",
        "message": "IVEをWeverse対応と記述している行が存在。IVEはKakao系でWeverse非対応",
    },
    {
        "id": "wrong_member_herin",
        "pattern": r"ヘリン(?!.*ハリン)",
        "severity": "high",
        "message": "誤メンバー名「ヘリン」残存。正: ハリン(Haerin)",
    },
    {
        "id": "wrong_member_hewoon",
        "pattern": r"ヘウン",
        "severity": "critical",
        "message": "存在しないメンバー名「ヘウン」残存",
    },
    {
        "id": "contradiction_unconfirmed_assert",
        "pattern": r"公式確認できていません.{0,500}?配信されます|未確認.{0,500}?視聴できます",
        "severity": "high",
        "message": "「未確認」と断言の矛盾が同記事内に存在する可能性",
    },
    {
        "id": "born_again_wrong_tourname",
        "pattern": r"BORN AGAIN",
        "severity": "critical",
        "message": "誤BTSツアー名「BORN AGAIN」残存。正: BTS WORLD TOUR 'ARIRANG'",
    },
    {
        "id": "price_without_disclaimer",
        "pattern": r"(月\d{1,3},?\d{3}円|月額\d{1,3},?\d{3}円)(?!.*公式サイト)",
        "severity": "medium",
        "message": "料金記載箇所に「公式サイトで確認」の併記が不足している可能性",
    },
]

# ── YouTube「全て無料視聴可能」禁止パターン ──
YOUTUBE_OVERASSERT = re.compile(r"YouTube.{0,50}?(全て|すべて).{0,20}?無料視聴可能")


def _wp_auth_header() -> str:
    wp_auth_path = os.path.expanduser("~/.wp_auth")
    if os.path.exists(wp_auth_path):
        with open(wp_auth_path) as f:
            for line in f:
                # 形式: header = "Authorization: Basic xxxx"
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


def run_checks(content: str, post_id: int) -> list[dict]:
    """チェックルールを実行し、問題リストを返す"""
    findings = []
    for rule in CHECK_RULES:
        # ive_weverse_error は行単位マッチ（MULTILINE）、他はDOTALL
        flags = re.MULTILINE if rule["id"] == "ive_weverse_error" else re.DOTALL
        matches = re.findall(rule["pattern"], content, flags)
        if matches:
            findings.append({
                "rule_id": rule["id"],
                "severity": rule["severity"],
                "message": rule["message"],
                "match_count": len(matches),
            })
    # YouTube過断言チェック
    if YOUTUBE_OVERASSERT.search(content):
        findings.append({
            "rule_id": "youtube_overassert",
            "severity": "medium",
            "message": "YouTubeの「全て無料視聴可能」表現。正: 「無料公開動画あり」",
            "match_count": 1,
        })
    return findings


def load_ledger() -> list[dict]:
    if not LEDGER.exists():
        return []
    records = []
    with open(LEDGER) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def save_ledger(records: list[dict]):
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


def append_to_ledger(record: dict):
    """新規記事を台帳に追記（重複チェックあり）"""
    records = load_ledger()
    existing_ids = {r["post_id"] for r in records}
    if record["post_id"] in existing_ids:
        # 更新
        records = [record if r["post_id"] == record["post_id"] else r for r in records]
    else:
        records.append(record)
    save_ledger(records)


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
        print(f"[streaming_guide_reviewer] 期限到来記事なし (today={today})")
        return

    print(f"[streaming_guide_reviewer] 監査対象: {len(targets)}件")

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
        print(f"\n  チェック中: [{pid}] {title[:50]}")

        post = fetch_post_content(pid)
        if "error" in post:
            print(f"    ❌ 取得エラー: {post['error']}")
            continue

        content = post["content"]
        findings = run_checks(content, pid)

        if findings:
            critical = [f for f in findings if f["severity"] == "critical"]
            high = [f for f in findings if f["severity"] == "high"]
            medium = [f for f in findings if f["severity"] == "medium"]
            print(f"    ⚠️  問題検出: critical={len(critical)} high={len(high)} medium={len(medium)}")
            for f in findings:
                print(f"      [{f['severity'].upper()}] {f['message']}")

            if not dry_run:
                rec["status"] = "needs_review"
                # Discordに通知
                severity_icon = "🚨" if critical else "⚠️"
                msg = (
                    f"{severity_icon} **視聴導線記事 再監査アラート**\n"
                    f"[{pid}] {title}\n"
                    f"問題数: critical={len(critical)} / high={len(high)} / medium={len(medium)}\n"
                    f"最優先: {findings[0]['message']}\n"
                    f"URL: {post.get('link', '')}"
                )
                send_discord(discord_webhook, msg)
        else:
            print(f"    ✅ 問題なし")
            if not dry_run:
                interval = REVIEW_INTERVALS.get(rec.get("article_type", ""), 30)
                rec["last_factchecked_at"] = today.isoformat()
                rec["next_review_due"] = (today + timedelta(days=interval)).isoformat()
                rec["status"] = "published_verified"

        results.append({"post_id": pid, "findings": findings})

    if not dry_run:
        # 台帳更新（審査済みレコードを反映）
        reviewed_ids = {r["post_id"] for r in targets}
        updated = []
        target_map = {r["post_id"]: r for r in targets}
        for rec in records:
            if rec["post_id"] in reviewed_ids:
                updated.append(target_map[rec["post_id"]])
            else:
                updated.append(rec)
        save_ledger(updated)
        print(f"\n✅ 台帳更新完了: {LEDGER}")

    # サマリー
    total_issues = sum(len(r["findings"]) for r in results)
    print(f"\n=== 監査サマリー ===")
    print(f"  対象: {len(results)}件 / 問題あり: {sum(1 for r in results if r['findings'])}件")
    print(f"  総問題数: {total_issues}")
    if dry_run:
        print("  (dry-run: 台帳未更新)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="視聴導線記事 再監査スクリプト")
    parser.add_argument("--dry-run", action="store_true", help="台帳を更新せず結果のみ表示")
    parser.add_argument("--all", action="store_true", help="期限に関係なく全件チェック")
    parser.add_argument("--post-id", type=int, help="単記事チェック")
    args = parser.parse_args()
    review(dry_run=args.dry_run, all_records=args.all, target_post_id=args.post_id)
